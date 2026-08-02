"""
Multi-tenant isolation tests for the Phase 2 job_postings/user_job_matches
schema (docs/db-redesign-proposal.md).

Deliberately a SEPARATE file from test_tenant_isolation.py: that file's
autouse _patch_engine fixture force-points every module under test at an
isolated in-memory SQLite engine, but job_postings/user_job_matches only
exist on Postgres, and user_job_matches.user_id has a hard FK to
auth.users(id) — arbitrary test strings aren't valid there, only real,
already-existing Supabase auth accounts are. Every test here uses the
`db_available` fixture (backend/tests/conftest.py) to skip gracefully
rather than fail when Postgres isn't reachable (e.g. CI without secrets).

Running
-------
    backend/.venv/bin/pytest backend/tests/test_job_postings_isolation.py -v
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import text

# Two stable, pre-existing Supabase QA accounts in this project, reused as
# the "two tenants" below.
_QA_USER_A = "2631c93b-93bb-4313-a2c2-79dbb786d199"   # qa.test2.jobapply.claude@gmail.com
_QA_USER_B = "b0dbf35a-929c-4db3-a04a-24fbe3a3d59d"   # qa-test-linkedin-tab@example.com


def _uid() -> str:
    return str(uuid.uuid4())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _cleanup(job_ids: list[str]) -> None:
    from backend.core.postgres import PG_ENGINE
    with PG_ENGINE.begin() as conn:
        postings = conn.execute(text(
            "SELECT job_posting_id FROM public.user_job_matches WHERE job_id = ANY(:ids)"
        ), {"ids": job_ids}).fetchall()
        conn.execute(text("DELETE FROM public.user_job_matches WHERE job_id = ANY(:ids)"), {"ids": job_ids})
        for (pid,) in postings:
            conn.execute(text("DELETE FROM public.job_postings WHERE id = :pid"), {"pid": pid})


def _make_job(job_id: str, user_id: str, match_score: float, status: str = "new"):
    from backend.schemas.job import DetailedAnalysis, JobMatch
    return JobMatch(
        job_id=job_id, title=f"PM {_uid()}", company="Acme", location="Remote",
        score=80.0, confidence_score=50, culture_fit_score=50,
        trajectory_alignment="", company_dna_inference="",
        detailed_analysis=DetailedAnalysis(strengths=[], critical_gaps=[], strategic_advice=[]),
        investigation_points=[], reasons=[],
        user_id=user_id, match_score=match_score, status=status,
        is_new=True, posted_at="", source="automatic", is_open=True,
        source_type="other", score_is_proxy=False, created_at=_now(),
    )


def _make_job_match(
    *, job_id: str, user_id: str, apply_url: str, source_type: str,
    title: Optional[str] = None, company: str = "Acme", location: str = "Remote",
    match_score: float = 0.0, fit_brief: Optional[str] = None,
):
    from backend.schemas.job import DetailedAnalysis, JobMatch

    # title defaults to something unique per call — save_with_source_priority
    # matches globally by (title, company, location) via job_postings, so a
    # fixed default would collide with rows other test runs create.
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
        fit_brief=fit_brief,
    )


class TestUserJobMatchesIsolation:
    def test_get_all_only_returns_the_calling_users_jobs(self, db_available):
        from backend.repositories import job_repository as job_store

        jid_a, jid_b1, jid_b2 = f"job-a-1-{_uid()}", f"job-b-1-{_uid()}", f"job-b-2-{_uid()}"
        job_store.save_with_source_priority(_make_job(jid_a, _QA_USER_A, match_score=91.5))
        job_store.save_with_source_priority(_make_job(jid_b1, _QA_USER_B, match_score=12.0))
        job_store.save_with_source_priority(_make_job(jid_b2, _QA_USER_B, match_score=45.5))
        try:
            jobs_a = job_store.get_all(_QA_USER_A)
            jobs_b = job_store.get_all(_QA_USER_B)

            ids_a = {j.job_id for j in jobs_a}
            ids_b = {j.job_id for j in jobs_b}
            assert jid_a in ids_a and jid_a not in ids_b
            assert {jid_b1, jid_b2} <= ids_b
            assert jid_b1 not in ids_a and jid_b2 not in ids_a
            # No cross-contamination of match scores between accounts.
            assert next(j for j in jobs_a if j.job_id == jid_a).match_score == 91.5
        finally:
            _cleanup([jid_a, jid_b1, jid_b2])

    def test_get_feed_status_filter_stays_scoped_per_user(self, db_available):
        from backend.repositories import job_repository as job_store

        jid_a, jid_b = f"job-a-saved-{_uid()}", f"job-b-saved-{_uid()}"
        job_store.save_with_source_priority(_make_job(jid_a, _QA_USER_A, match_score=70.0, status="saved"))
        job_store.save_with_source_priority(_make_job(jid_b, _QA_USER_B, match_score=70.0, status="saved"))
        try:
            feed_a = job_store.get_feed(_QA_USER_A, status_filter="saved")
            ids_a = {j.job_id for j in feed_a}
            assert jid_a in ids_a
            assert jid_b not in ids_a
        finally:
            _cleanup([jid_a, jid_b])


class TestJobPostingsSourcePriorityIsolation:
    """
    Phase 2 jobs cutover replaced the old single-table jobs model (where
    JOB-92 made save_with_source_priority() clone a private row per tenant,
    because global posting facts and private match state illegally shared
    one row) with job_postings (global, shared) + user_job_matches (strictly
    per-user). The invariant these tests guard is the NEW correct one:
    job_postings legitimately gets shared/upgraded across tenants (that's
    the point of a normalized global catalog); user_job_matches — the
    private score/status/fit_brief a tenant never wants another tenant to see
    or overwrite — never is.
    """

    def test_cross_tenant_apply_url_match_shares_the_posting_not_the_match(self, db_available):
        from backend.repositories import job_repository as job_store

        url = f"https://boards.example.com/job-{_uid()}"
        title = f"Senior PM {_uid()}"
        jid_a, jid_b = f"job-a-{_uid()}", f"job-b-{_uid()}"

        job_a = _make_job_match(
            job_id=jid_a, user_id=_QA_USER_A, apply_url=url, title=title,
            source_type="linkedin", match_score=91.5, fit_brief="A's private brief",
        )
        assert job_store.save_with_source_priority(job_a) is True

        # User B discovers the SAME posting from a higher-priority source.
        job_b = _make_job_match(
            job_id=jid_b, user_id=_QA_USER_B, apply_url=url, title=title,
            source_type="company_site", match_score=10.0,
        )
        try:
            assert job_store.save_with_source_priority(job_b) is True

            fetched_a = job_store.get_by_id(jid_a, _QA_USER_A)
            fetched_b = job_store.get_by_id(jid_b, _QA_USER_B)

            # Both users have their own match row, each only visible to its owner.
            assert fetched_a is not None and fetched_b is not None
            assert job_store.get_by_id(jid_a, _QA_USER_B) is None
            assert job_store.get_by_id(jid_b, _QA_USER_A) is None

            # A's PRIVATE match state is untouched by B's higher-priority save.
            assert fetched_a.match_score == 91.5
            assert fetched_a.fit_brief == "A's private brief"

            # The SHARED posting legitimately picked up B's higher-priority
            # source — that's the point of job_postings being global.
            assert fetched_a.source_type == "company_site"
            assert fetched_b.source_type == "company_site"

            # Feed isolation still holds.
            assert jid_a in {j.job_id for j in job_store.get_all(_QA_USER_A)}
            assert jid_b in {j.job_id for j in job_store.get_all(_QA_USER_B)}
            assert jid_b not in {j.job_id for j in job_store.get_all(_QA_USER_A)}
        finally:
            _cleanup([jid_a, jid_b])

    def test_cross_tenant_dedup_key_match_shares_the_posting_not_the_match(self, db_available):
        """Same real job cross-posted under different URLs — postings merge, matches stay isolated."""
        from backend.repositories import job_repository as job_store

        title, company, location = f"Staff Engineer {_uid()}", "Acme Corp", "Tel Aviv"
        jid_a, jid_b = f"job-a-{_uid()}", f"job-b-{_uid()}"

        job_a = _make_job_match(
            job_id=jid_a, user_id=_QA_USER_A,
            apply_url=f"https://drushim.co.il/job-{_uid()}", source_type="other",
            title=title, company=company, location=location, match_score=77.0,
        )
        assert job_store.save_with_source_priority(job_a) is True

        job_b = _make_job_match(
            job_id=jid_b, user_id=_QA_USER_B,
            apply_url=f"https://alljobs.co.il/job-{_uid()}", source_type="linkedin",
            title=title, company=company, location=location, match_score=5.0,
        )
        try:
            assert job_store.save_with_source_priority(job_b) is True

            fetched_a = job_store.get_by_id(jid_a, _QA_USER_A)
            fetched_b = job_store.get_by_id(jid_b, _QA_USER_B)
            assert fetched_a.match_score == 77.0
            assert fetched_b.match_score == 5.0
        finally:
            _cleanup([jid_a, jid_b])

    def test_never_reassigns_a_match_to_another_tenant(self, db_available):
        """
        Regression guard: no branch of save_with_source_priority may create or
        modify a user_job_matches row belonging to a different user_id — a's
        match must stay exactly a's, no matter how many higher-priority saves
        other users make against the same posting afterward.
        """
        from backend.repositories import job_repository as job_store

        url = f"https://boards.example.com/job-{_uid()}"
        jid_a = f"job-a-{_uid()}"
        all_job_ids = [jid_a]

        job_a = _make_job_match(job_id=jid_a, user_id=_QA_USER_A, apply_url=url, source_type="other")
        job_store.save_with_source_priority(job_a)

        try:
            for source_type in ("linkedin", "company_site"):
                jid_b = f"job-b-{source_type}-{_uid()}"
                all_job_ids.append(jid_b)
                job_b = _make_job_match(
                    job_id=jid_b, user_id=_QA_USER_B, apply_url=url, source_type=source_type,
                )
                job_store.save_with_source_priority(job_b)

                # A's match row still exists, still owned by A, untouched.
                still_a = job_store.get_by_id(jid_a, _QA_USER_A)
                assert still_a is not None
                assert job_store.get_by_id(jid_a, _QA_USER_B) is None
        finally:
            _cleanup(all_job_ids)
