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
    (jobs, applications, master_profiles, profile_entities, evidence_records)
    already has a proper ORM class in db.py, so create_all() alone is
    sufficient and correct here — no need to invoke the raw-DDL migration
    path that only exists to bring pre-ORM-era databases up to date.
    """
    from backend.core.database import Base
    from backend.models import application, ariel, job, kv, matching, profile  # noqa: F401
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
# Job / match-score isolation
# ═══════════════════════════════════════════════════════════════════════════

class TestJobIsolation:
    """
    Note: this class covers the legacy jobs table's tenant_id backfill
    migration only (SQLite, isolated _TEST_ENGINE) — get_all()/get_feed()
    scoping against the NEW job_postings/user_job_matches tables is covered
    separately in test_job_postings_isolation.py, which needs real Dev
    Postgres (those tables don't exist on SQLite, and user_job_matches has a
    hard FK to auth.users) and so can't share this file's autouse
    ENGINE-patching fixture.
    """

    def _insert_job(self, job_id: str, user_id: str, match_score: float, status: str = "new") -> None:
        from backend.models.job import JobRow

        with Session(_TEST_ENGINE) as session:
            session.add(JobRow(
                job_id=job_id, title="PM", company="Acme", location="Remote",
                score=80.0, confidence_score=50, culture_fit_score=50,
                trajectory_alignment="", company_dna_inference="",
                investigation_points=[], detailed_analysis={}, reasons=[],
                user_id=user_id, match_score=match_score, status=status,
                is_new=True, posted_at="", source="automatic", is_open=True,
                source_type="other", score_is_proxy=False, created_at=_now(),
            ))
            session.commit()

    def test_tenant_id_backfilled_correctly_per_user(self):
        """
        Simulates the realistic legacy-data scenario the migration brief asks
        for: rows that predate the tenant_id column (inserted here via raw SQL
        with no tenant_id, exactly like every pre-migration row in the real
        jobs.db) must be backfilled to their OWN user_id — never a shared
        sentinel that would blur tenants together (see
        docs/multi-tenant-erd.md §5). _migrate_tenant_id is safe to re-run
        (idempotent, only touches NULL rows), which is exactly what this test
        exercises a second time against fresh "legacy" rows.
        """
        from backend.core.migrations import _migrate_tenant_id

        user_a, user_b = f"user-a-{_uid()}", f"user-b-{_uid()}"
        # Insert through the ORM helper (sets every required column correctly,
        # including tenant_id since the model default runs), then null out
        # tenant_id via raw SQL to simulate a genuinely pre-migration legacy
        # row — the exact shape every row in the real jobs.db had before this
        # migration ran.
        self._insert_job("job-legacy-a", user_a, match_score=1.0)
        self._insert_job("job-legacy-b", user_b, match_score=1.0)
        with _TEST_ENGINE.begin() as conn:
            conn.execute(text(
                "UPDATE jobs SET tenant_id = NULL WHERE job_id IN ('job-legacy-a', 'job-legacy-b')"
            ))

        with _TEST_ENGINE.connect() as conn:
            _migrate_tenant_id(conn)

        with _TEST_ENGINE.connect() as conn:
            row_a = conn.execute(text(
                "SELECT user_id, tenant_id FROM jobs WHERE job_id = 'job-legacy-a'"
            )).fetchone()
            row_b = conn.execute(text(
                "SELECT user_id, tenant_id FROM jobs WHERE job_id = 'job-legacy-b'"
            )).fetchone()

        assert row_a.tenant_id == row_a.user_id == user_a
        assert row_b.tenant_id == row_b.user_id == user_b
        assert row_a.tenant_id != row_b.tenant_id


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
