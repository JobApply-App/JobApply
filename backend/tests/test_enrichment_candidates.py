"""
The enrichment sweep picks the same jobs, in the same order, from narrow rows
as it did from full rows.

It used to read every match with its full JD text and structured JD just to
choose up to three jobs to score — the main source of the database egress
that got the Supabase project suspended. The choice now comes from
get_enrichment_candidates() (scores, flags, JD length); this pins that the
narrow path and the old full-row path agree.
"""
from __future__ import annotations

import json

from sqlalchemy import text

from backend.services import feed_service
from backend.tests.test_analytics_service import _QA_USER_A, _cleanup, _make_job, _uid


def _old_choice(user_id):
    rows = [j for j in feed_service.job_store.get_feed(user_id) if feed_service._needs_enrichment(j)]
    rows.sort(key=lambda j: (j.match_score or j.score or 0.0, j.posted_at or ""), reverse=True)
    return [j.job_id for j in rows]


def _new_choice(user_id):
    rows = [
        c for c in feed_service.job_store.get_enrichment_candidates(user_id, feed_service._JD_MIN_CHARS)
        if feed_service._needs_enrichment_fields(
            enrichment_failures=c.enrichment_failures, apply_url=c.apply_url, jd_thin=c.jd_thin,
            fit_brief_missing=c.fit_brief_missing, score_is_proxy=c.score_is_proxy,
        )
    ]
    rows.sort(key=lambda j: (j.match_score or j.score or 0.0, j.posted_at or ""), reverse=True)
    return [c.job_id for c in rows]


def test_narrow_and_full_paths_choose_the_same_jobs(db_available):
    from backend.core.postgres import PG_ENGINE
    from backend.repositories import job_repository as job_store

    tag = _uid()[:8]
    long_jd = "Responsibilities and requirements. " * 20
    cases = {
        # key: (score, jd_text, fit_brief, proxy, failures, url)
        "rich_unscored":  (70.0, long_jd, None,       True,  0, None),
        "thin":           (65.0, "short",  None,       True,  0, None),
        "thin_ws":        (60.0, "  \n " + "x" * 240 + " \t", "brief", False, 0, None),
        "sentinel":       (55.0, "__hydrate_failed__", None, True, 0, None),
        "done":           (90.0, long_jd, "A real brief of the fit, long enough.", False, 0, None),
        "retired":        (80.0, long_jd, None,       True,  3, None),
        "linkedin_thin":  (75.0, "short",  None,       True,  0, "https://www.linkedin.com/jobs/view/1"),
        "linkedin_rich":  (50.0, long_jd, None,       True,  0, "https://www.linkedin.com/jobs/view/2"),
    }
    ids = {k: f"cand-{k}-{tag}" for k in cases}
    for key, (score, *_rest) in cases.items():
        url = cases[key][5] or f"https://example.com/{ids[key]}"
        job_store.save_with_source_priority(_make_job(ids[key], _QA_USER_A, match_score=score, apply_url=url))
    try:
        with PG_ENGINE.begin() as conn:
            for key, (score, jd, brief, proxy, fails, _url) in cases.items():
                conn.execute(text(
                    "UPDATE public.user_job_matches SET fit_brief = :b, score_is_proxy = :p, "
                    "enrichment_failures = :f, match_score = :s WHERE job_id = :j AND user_id = CAST(:u AS uuid)"
                ), {"b": brief, "p": proxy, "f": fails, "s": score, "j": ids[key], "u": _QA_USER_A})
                conn.execute(text(
                    "UPDATE public.job_postings SET jd_text = :jd WHERE id = (SELECT job_posting_id "
                    "FROM public.user_job_matches WHERE job_id = :j AND user_id = CAST(:u AS uuid))"
                ), {"jd": jd, "j": ids[key], "u": _QA_USER_A})

        mine = set(ids.values())
        old = [j for j in _old_choice(_QA_USER_A) if j in mine]
        new = [j for j in _new_choice(_QA_USER_A) if j in mine]
        assert new == old
        # Sanity: the cases that should be chosen are, in score order.
        # "sentinel": JD fetch failed for good, but it has no brief yet — still scored.
        assert new == [ids["rich_unscored"], ids["thin"], ids["thin_ws"], ids["sentinel"], ids["linkedin_rich"]]
    finally:
        _cleanup(list(ids.values()))
