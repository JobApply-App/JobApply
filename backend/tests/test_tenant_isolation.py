"""
Multi-tenant isolation tests.
==============================

Proves that two distinct user accounts are strictly isolated for the three
data classes the Infra & Multi-Tenant migration brief called out by name:
Master Profile, match-score-bearing job rows, and application data. Also
covers the Confidence Matrix (profile_entities), since it's the other
half of "Master Profile data cannot be shared, leaked, or overwritten."

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
# Master Profile isolation — the ticket's explicit constraint #4
# ═══════════════════════════════════════════════════════════════════════════

class TestMasterProfileIsolation:
    def test_two_users_cannot_read_each_others_profile(self):
        """User B's load() must never return User A's saved data, and vice versa."""
        from backend.services import master_profile_service as mp

        user_a, user_b = f"user-a-{_uid()}", f"user-b-{_uid()}"

        profile_a = {"version": 1, "professional_summary": "A's secret summary"}
        profile_b = {"version": 1, "professional_summary": "B's secret summary"}

        mp.save(profile_a, user_id=user_a)
        mp.save(profile_b, user_id=user_b)

        loaded_a = mp.load(user_a)
        loaded_b = mp.load(user_b)

        assert loaded_a["professional_summary"] == "A's secret summary"
        assert loaded_b["professional_summary"] == "B's secret summary"
        # The actual isolation assertion: neither leaked into the other.
        assert loaded_a["professional_summary"] != loaded_b["professional_summary"]

    def test_save_for_user_a_does_not_overwrite_user_b_row(self):
        """Writing A's profile after B's must leave B's row untouched (no
        shared-row / last-writer-wins collapse across accounts)."""
        from backend.services import master_profile_service as mp

        user_a, user_b = f"user-a-{_uid()}", f"user-b-{_uid()}"

        mp.save({"version": 1, "professional_summary": "B original"}, user_id=user_b)
        mp.save({"version": 1, "professional_summary": "A original"}, user_id=user_a)
        # A second write to A must not disturb B.
        mp.save({"version": 1, "professional_summary": "A updated"}, user_id=user_a)

        assert mp.load(user_b)["professional_summary"] == "B original"
        assert mp.load(user_a)["professional_summary"] == "A updated"

    def test_master_profiles_row_count_matches_distinct_users(self):
        """Structural check: master_profiles.user_id is the primary key, so N
        distinct users must produce exactly N rows — never fewer (collapsed)."""
        from backend.services import master_profile_service as mp

        users = [f"user-{_uid()}" for _ in range(5)]
        for u in users:
            mp.save({"version": 1, "professional_summary": f"summary for {u}"}, user_id=u)

        with Session(_TEST_ENGINE) as session:
            from backend.models.profile import MasterProfileRow
            count = session.query(MasterProfileRow).filter(
                MasterProfileRow.user_id.in_(users)
            ).count()
        assert count == len(users)


# ═══════════════════════════════════════════════════════════════════════════
# Job / match-score isolation
# ═══════════════════════════════════════════════════════════════════════════

class TestJobIsolation:
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

    def test_get_all_only_returns_the_calling_users_jobs(self):
        from backend.repositories import job_repository as job_store

        user_a, user_b = f"user-a-{_uid()}", f"user-b-{_uid()}"
        self._insert_job("job-a-1", user_a, match_score=91.5)
        self._insert_job("job-b-1", user_b, match_score=12.0)
        self._insert_job("job-b-2", user_b, match_score=45.5)

        jobs_a = job_store.get_all(user_a)
        jobs_b = job_store.get_all(user_b)

        assert {j.job_id for j in jobs_a} == {"job-a-1"}
        assert {j.job_id for j in jobs_b} == {"job-b-1", "job-b-2"}
        # No cross-contamination of match scores between accounts.
        assert jobs_a[0].match_score == 91.5
        assert all(j.match_score != 91.5 for j in jobs_b)

    def test_get_feed_status_filter_stays_scoped_per_user(self):
        from backend.repositories import job_repository as job_store

        user_a, user_b = f"user-a-{_uid()}", f"user-b-{_uid()}"
        self._insert_job("job-a-saved", user_a, match_score=70.0, status="saved")
        self._insert_job("job-b-saved", user_b, match_score=70.0, status="saved")

        feed_a = job_store.get_feed(user_a, status_filter="saved")
        assert {j.job_id for j in feed_a} == {"job-a-saved"}

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
# JOB-92 — save_with_source_priority() must never reassign a row's user_id
# ═══════════════════════════════════════════════════════════════════════════

def _make_job_match(
    *, job_id: str, user_id: str, apply_url: str, source_type: str,
    title: Optional[str] = None, company: str = "Acme", location: str = "Remote",
    match_score: float = 0.0, why_ron: Optional[str] = None,
):
    from backend.schemas.job import DetailedAnalysis, JobMatch

    # title defaults to something unique per call — save_with_source_priority
    # matches across the WHOLE persistent test engine by (title, company,
    # location), so a fixed default would collide with rows other test
    # methods insert in the same module-level in-memory DB.
    if title is None:
        title = f"Senior PM {_uid()}"

    return JobMatch(
        job_id=job_id, title=title, company=company, location=location,
        score=80.0, confidence_score=50, culture_fit_score=50,
        trajectory_alignment="", company_dna_inference="",
        detailed_analysis=DetailedAnalysis(strengths=[], critical_gaps=[], strategic_advice=[]),
        investigation_points=[], reasons=[],
        apply_url=apply_url, is_new=True, posted_at="", source="automatic",
        is_open=True, user_id=user_id, source_type=source_type,
        match_score=match_score, score_is_proxy=False, created_at=_now(),
        why_ron=why_ron,
    )


class TestJobSourcePriorityIsolation:
    """JOB-92: cross-tenant matches must clone a private row, never hijack an existing one."""

    def test_cross_tenant_apply_url_match_does_not_reassign_owner(self):
        from backend.repositories import job_repository as job_store
        from backend.models.job import JobRow

        user_a, user_b = f"user-a-{_uid()}", f"user-b-{_uid()}"
        url = f"https://boards.example.com/job-{_uid()}"
        title = f"Senior PM {_uid()}"

        job_a = _make_job_match(
            job_id=f"job-a-{_uid()}", user_id=user_a, apply_url=url, title=title,
            source_type="linkedin", match_score=91.5, why_ron="A's private brief",
        )
        assert job_store.save_with_source_priority(job_a) is True

        # User B discovers the SAME posting from a higher-priority source.
        job_b = _make_job_match(
            job_id=f"job-b-{_uid()}", user_id=user_b, apply_url=url, title=title,
            source_type="company_site", match_score=10.0,
        )
        assert job_store.save_with_source_priority(job_b) is True

        with Session(_TEST_ENGINE) as session:
            rows = session.query(JobRow).filter(JobRow.apply_url == url).all()
        by_user = {r.user_id: r for r in rows}

        # Both users now have their own row for the same posting.
        assert set(by_user) == {user_a, user_b}
        # A's row is untouched: same owner, same private analysis.
        assert by_user[user_a].user_id == user_a
        assert by_user[user_a].match_score == 91.5
        assert by_user[user_a].why_ron == "A's private brief"
        # B's row is its own, separate row (distinct job_id from A's).
        assert by_user[user_b].job_id != by_user[user_a].job_id
        assert by_user[user_b].source_type == "company_site"

        # Feed isolation still holds.
        assert {j.job_id for j in job_store.get_all(user_a)} == {by_user[user_a].job_id}
        assert {j.job_id for j in job_store.get_all(user_b)} == {by_user[user_b].job_id}

    def test_cross_tenant_dedup_key_match_does_not_reassign_owner(self):
        """Same real job cross-posted under different URLs — must still isolate by user."""
        from backend.repositories import job_repository as job_store
        from backend.models.job import JobRow

        user_a, user_b = f"user-a-{_uid()}", f"user-b-{_uid()}"
        title, company, location = f"Staff Engineer {_uid()}", "Acme Corp", "Tel Aviv"

        job_a = _make_job_match(
            job_id=f"job-a-{_uid()}", user_id=user_a,
            apply_url=f"https://drushim.co.il/job-{_uid()}", source_type="other",
            title=title, company=company, location=location, match_score=77.0,
        )
        assert job_store.save_with_source_priority(job_a) is True

        job_b = _make_job_match(
            job_id=f"job-b-{_uid()}", user_id=user_b,
            apply_url=f"https://alljobs.co.il/job-{_uid()}", source_type="linkedin",
            title=title, company=company, location=location, match_score=5.0,
        )
        assert job_store.save_with_source_priority(job_b) is True

        with Session(_TEST_ENGINE) as session:
            rows = session.query(JobRow).filter(JobRow.title == title).all()
        by_user = {r.user_id: r for r in rows}

        assert set(by_user) == {user_a, user_b}
        assert by_user[user_a].match_score == 77.0
        assert by_user[user_b].match_score == 5.0

    def test_never_reassigns_row_user_id(self):
        """
        Regression guard: no branch of save_with_source_priority may change an
        existing row's user_id — it must always stay with its original owner,
        no matter how many higher-priority saves other users make afterward.
        """
        from backend.repositories import job_repository as job_store
        from backend.models.job import JobRow

        user_a, user_b = f"user-a-{_uid()}", f"user-b-{_uid()}"
        url = f"https://boards.example.com/job-{_uid()}"

        job_a = _make_job_match(job_id=f"job-a-{_uid()}", user_id=user_a, apply_url=url, source_type="other")
        job_store.save_with_source_priority(job_a)

        with Session(_TEST_ENGINE) as session:
            original_job_id = session.query(JobRow).filter(JobRow.apply_url == url).one().job_id

        for source_type in ("linkedin", "company_site"):
            job_b = _make_job_match(
                job_id=f"job-b-{_uid()}", user_id=user_b, apply_url=url, source_type=source_type,
            )
            job_store.save_with_source_priority(job_b)

            with Session(_TEST_ENGINE) as session:
                a_row = session.get(JobRow, original_job_id)
                assert a_row is not None
                assert a_row.user_id == user_a


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
