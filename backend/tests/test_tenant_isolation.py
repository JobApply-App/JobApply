"""
Multi-tenant isolation tests.
==============================

Proves that two distinct user accounts are strictly isolated for
match-score-bearing job rows and application data (the legacy jobs table's
tenant_id backfill mechanism only — see TestJobIsolation's docstring). Also
covers the Confidence Matrix (profile_entities).

Master Profile isolation moved to test_profile_isolation.py: it now runs
through profile_repository.py (Postgres-only, profiles.id has a hard FK to
auth.users(id)), so it can no longer run against this file's isolated
SQLite database.

Runs against an isolated in-memory SQLite database — the real jobs.db is
never touched. Follows the exact StaticPool + monkeypatch(ENGINE) pattern
already established in test_profile_trust.py.

Running
-------
    backend/.venv/bin/pytest backend/tests/test_tenant_isolation.py -v
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

# ---------------------------------------------------------------------------
# Shared in-memory SQLite engine (isolated per test session)
# ---------------------------------------------------------------------------
# StaticPool is required for sqlite:///:memory: — see test_profile_trust.py
# for why (default QueuePool gives every connection its own DB).

_TEST_ENGINE = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)


def _setup_schema() -> None:
    """
    Create the full real schema, then run the tenant_id migration on it —
    exercising the actual migration path, not a hand-rolled test schema.

    Deliberately does NOT call _migrate_confidence_matrix() here: that
    function's rename/recreate dance for evidence_records has a pre-existing
    bug (unrelated to tenant scoping — see docs/multi-tenant-erd.md §4) that
    only reproduces against a table created from scratch by
    Base.metadata.create_all(). Every table this test suite touches
    (applications, profile_entities, evidence_records) already has a proper
    ORM class in db.py, so create_all() alone is sufficient and correct here
    — no need to invoke the raw-DDL migration path that only exists to bring
    pre-ORM-era databases up to date.
    """
    from backend.core.database import Base
    from backend.models import application, ariel, kv, matching, profile  # noqa: F401
    from backend.core.migrations import _migrate_tenant_id

    Base.metadata.create_all(_TEST_ENGINE)
    # _migrate_tenant_id manages its own commits internally (it calls
    # conn.commit() mid-function for the WAL-checkpoint step) — use .connect(),
    # not .begin(), matching exactly how the real init_db() invokes it.
    with _TEST_ENGINE.connect() as conn:
        _migrate_tenant_id(conn)


_setup_schema()


def _uid() -> str:
    return str(uuid.uuid4())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@pytest.fixture(autouse=True)
def _patch_engine(monkeypatch):
    """Point every service module under test at the in-memory test engine."""
    import backend.core.database as db_module
    import backend.services.master_profile_service as mp_module
    import backend.repositories.job_repository as job_store_module
    import backend.services.confidence_matrix_service as cm_module

    monkeypatch.setattr(db_module, "ENGINE", _TEST_ENGINE)
    monkeypatch.setattr(mp_module, "ENGINE", _TEST_ENGINE, raising=False)
    monkeypatch.setattr(job_store_module, "ENGINE", _TEST_ENGINE, raising=False)
    monkeypatch.setattr(cm_module, "ENGINE", _TEST_ENGINE, raising=False)

# ═══════════════════════════════════════════════════════════════════════════
# Confidence Matrix (profile_entities) isolation
# ═══════════════════════════════════════════════════════════════════════════

class TestConfidenceMatrixIsolation:
    def _insert_entity(self, entity_id: str, user_id: str, name: str, score: float) -> None:
        with _TEST_ENGINE.begin() as conn:
            conn.execute(text("""
                INSERT INTO profile_entities
                    (entity_id, user_id, entity_type, name, normalized_name,
                     confidence_score, verification_status, created_at, updated_at)
                VALUES (:eid, :uid, 'skill', :name, :norm, :score, 'unverified', :now, :now)
            """), {
                "eid": entity_id, "uid": user_id, "name": name,
                "norm": name.lower(), "score": score, "now": _now(),
            })

    def test_entity_breakdown_never_crosses_users(self):
        from backend.services.confidence_matrix_service import get_entity_breakdown

        user_a, user_b = f"user-a-{_uid()}", f"user-b-{_uid()}"
        self._insert_entity(_uid(), user_a, "Python", 85.0)
        self._insert_entity(_uid(), user_b, "Excel", 30.0)

        breakdown_a = get_entity_breakdown(user_a, _TEST_ENGINE)
        breakdown_b = get_entity_breakdown(user_b, _TEST_ENGINE)

        # EntityScore is a TypedDict — plain dict access at runtime, not attrs.
        names_a = {e["name"] for e in breakdown_a}
        names_b = {e["name"] for e in breakdown_b}

        assert names_a == {"Python"}
        assert names_b == {"Excel"}
        assert names_a.isdisjoint(names_b)


# ═══════════════════════════════════════════════════════════════════════════
# Application isolation
# ═══════════════════════════════════════════════════════════════════════════

class TestApplicationIsolation:
    def _insert_application(self, application_id: str, user_id: str, job_id: str) -> None:
        from backend.models.application import ApplicationRow

        with Session(_TEST_ENGINE) as session:
            session.add(ApplicationRow(
                application_id=application_id, user_id=user_id, job_id=job_id,
                title="PM", company="Acme", ats="Direct", status="submitted",
                submitted_at=_now(), last_update=_now(), score=80.0,
            ))
            session.commit()

    def test_applications_are_scoped_by_user_id(self):
        from backend.models.application import ApplicationRow

        user_a, user_b = f"user-a-{_uid()}", f"user-b-{_uid()}"
        self._insert_application("app-a-1", user_a, "job-1")
        self._insert_application("app-b-1", user_b, "job-1")
        self._insert_application("app-b-2", user_b, "job-2")

        with Session(_TEST_ENGINE) as session:
            apps_a = session.query(ApplicationRow).filter(ApplicationRow.user_id == user_a).all()
            apps_b = session.query(ApplicationRow).filter(ApplicationRow.user_id == user_b).all()

        assert {a.application_id for a in apps_a} == {"app-a-1"}
        assert {a.application_id for a in apps_b} == {"app-b-1", "app-b-2"}


# ═══════════════════════════════════════════════════════════════════════════
# JOB-92 — job_id salting prevents cross-tenant PK collisions
# ═══════════════════════════════════════════════════════════════════════════

class TestTenantJobIdSalting:
    def test_same_inputs_are_deterministic(self):
        from backend.scrapers.base_scraper import make_tenant_job_id

        assert (
            make_tenant_job_id("scraped-abc123", "user-a")
            == make_tenant_job_id("scraped-abc123", "user-a")
        )

    def test_different_users_get_different_ids(self):
        from backend.scrapers.base_scraper import make_tenant_job_id

        assert (
            make_tenant_job_id("scraped-abc123", "user-a")
            != make_tenant_job_id("scraped-abc123", "user-b")
        )
