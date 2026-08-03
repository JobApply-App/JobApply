"""
Unit tests — backend.services.analytics_service.compute_overview()

Confirms the fix for the three-sequential-queries pattern: jobs_scanned_today,
actions_taken_today, and average_match_score used to each cost their own
round trip to Postgres. Now computed via one conditional-aggregation query.
Semantics (date boundary, null handling on zero matching rows) must be
identical — verified against real seeded rows on a real QA Supabase account,
same pattern as test_job_postings_isolation.py (user_job_matches has a hard
FK to auth.users, so it can't be faked against an in-memory SQLite engine).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import event, text

_QA_USER_A = "2631c93b-93bb-4313-a2c2-79dbb786d199"


def _uid() -> str:
    return str(uuid.uuid4())


def _now_iso() -> str:
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


def _make_job(
    job_id: str, user_id: str, match_score: float, *,
    applied: bool = False, apply_url: Optional[str] = None,
):
    from backend.schemas.job import DetailedAnalysis, JobMatch
    return JobMatch(
        job_id=job_id, title=f"KPI test {_uid()}", company="Acme", location="Remote",
        score=80.0, confidence_score=50, culture_fit_score=50,
        trajectory_alignment="", company_dna_inference="",
        detailed_analysis=DetailedAnalysis(strengths=[], critical_gaps=[], strategic_advice=[]),
        investigation_points=[], reasons=[],
        user_id=user_id, match_score=match_score, status="applied" if applied else "new",
        is_new=True, posted_at="", source="automatic", is_open=True,
        source_type="other", score_is_proxy=False, created_at=_now_iso(),
        apply_url=apply_url or f"https://example.com/{job_id}",
    )


def test_kpis_match_manually_seeded_rows(db_available):
    """
    user_job_matches.user_id has a hard FK to auth.users(id), so this must
    insert against a real QA account (_QA_USER_A) rather than an arbitrary
    UUID — same constraint test_job_postings_isolation.py works around.
    That account may already have other rows, so this asserts the DELTA the
    3 newly-seeded rows produce, not an absolute value.
    """
    from backend.repositories import job_repository as job_store
    from backend.services.analytics_service import compute_overview

    jid_scored, jid_zero, jid_applied = f"kpi-a-{_uid()}", f"kpi-b-{_uid()}", f"kpi-c-{_uid()}"

    before = compute_overview(_QA_USER_A)

    job_store.save_with_source_priority(_make_job(jid_scored, _QA_USER_A, match_score=88.0))
    job_store.save_with_source_priority(_make_job(jid_zero, _QA_USER_A, match_score=0.0))
    job_store.save_with_source_priority(_make_job(jid_applied, _QA_USER_A, match_score=60.0, applied=True))

    try:
        from backend.core.postgres import PG_ENGINE
        with PG_ENGINE.begin() as conn:
            conn.execute(text(
                "UPDATE public.user_job_matches SET applied = true, applied_at = now() "
                "WHERE job_id = :jid AND user_id = CAST(:uid AS uuid)"
            ), {"jid": jid_applied, "uid": _QA_USER_A})

        after = compute_overview(_QA_USER_A)

        # All 3 new jobs were created "today" (just now).
        assert after["jobs_scanned_today"] - before["jobs_scanned_today"] == 3
        # Only 1 of the 3 has applied=true AND applied_at set to today.
        assert after["actions_taken_today"] - before["actions_taken_today"] == 1
    finally:
        _cleanup([jid_scored, jid_zero, jid_applied])


def test_kpis_zero_for_user_with_no_rows(db_available):
    from backend.services.analytics_service import compute_overview

    user_id = _uid()
    result = compute_overview(user_id)

    assert result == {
        "jobs_scanned_today": 0,
        "actions_taken_today": 0,
        "average_match_score": 0.0,
    }


def test_jobs_created_before_midnight_excluded(db_available):
    """Date-boundary semantics preserved: only jobs created today count."""
    from backend.repositories import job_repository as job_store
    from backend.services.analytics_service import compute_overview

    jid_old = f"kpi-old-job-{_uid()}"
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()

    before = compute_overview(_QA_USER_A)

    job_store.save_with_source_priority(_make_job(jid_old, _QA_USER_A, match_score=50.0))
    try:
        from backend.core.postgres import PG_ENGINE
        with PG_ENGINE.begin() as conn:
            conn.execute(text(
                "UPDATE public.user_job_matches SET created_at = :ts "
                "WHERE job_id = :jid AND user_id = CAST(:uid AS uuid)"
            ), {"ts": yesterday, "jid": jid_old, "uid": _QA_USER_A})

        after = compute_overview(_QA_USER_A)
        # created_at was backdated to yesterday — must NOT count toward today's total.
        assert after["jobs_scanned_today"] == before["jobs_scanned_today"]
    finally:
        _cleanup([jid_old])


def test_compute_overview_issues_exactly_one_query(db_available):
    """The whole point of the fix: 3 sequential queries collapsed into 1."""
    from backend.core.database import ENGINE
    from backend.services.analytics_service import compute_overview

    query_count = 0

    def _count(*a, **kw):
        nonlocal query_count
        query_count += 1

    event.listen(ENGINE, "before_cursor_execute", _count)
    try:
        compute_overview(_uid())
    finally:
        event.remove(ENGINE, "before_cursor_execute", _count)

    assert query_count == 1, f"expected 1 query, got {query_count}"
