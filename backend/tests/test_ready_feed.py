"""
The feed's "ready" gate runs in SQL and picks exactly the rows the old
Python gate did.

GET /api/jobs/feed used to read the user's whole feed — every match, with
full JD text, structured JD and the tailored CV document — and drop
incomplete rows in Python, on every page view. Together with the enrichment
sweep doing the same every two minutes, that exhausted the Supabase free
plan's egress quota and the project was suspended (no one could sign in).
"""
from __future__ import annotations

import json

from sqlalchemy import text

from backend.tests.test_analytics_service import _QA_USER_A, _cleanup, _make_job, _uid


def _python_gate(j, min_score=0.0):
    return (
        bool((j.jd_structured or "").strip())
        and j.score_is_proxy is False
        and (j.match_score or 0.0) > 0
        and bool((j.company or "").strip())
        and bool((j.title or "").strip())
        and bool((j.fit_brief or "").strip())
        and not (min_score > 0 and (j.match_score or 0.0) < min_score)
    )


def test_sql_gate_matches_the_python_gate(db_available):
    from backend.core.postgres import PG_ENGINE
    from backend.repositories import job_repository as job_store

    tag = _uid()[:8]
    cases = {
        "ready_hi":   dict(score=91.0, structured=True,  brief="Strong fit", proxy=False),
        "ready_lo":   dict(score=55.0, structured=True,  brief="Partial fit", proxy=False),
        "no_struct":  dict(score=80.0, structured=False, brief="x",           proxy=False),
        "no_brief":   dict(score=80.0, structured=True,  brief="  ",          proxy=False),
        "proxy":      dict(score=80.0, structured=True,  brief="x",           proxy=True),
        "zero_score": dict(score=0.0,  structured=True,  brief="x",           proxy=False),
    }
    ids = {k: f"ready-{k}-{tag}" for k in cases}
    for key, c in cases.items():
        job = _make_job(ids[key], _QA_USER_A, match_score=c["score"])
        job.fit_brief = c["brief"]
        job.score_is_proxy = c["proxy"]
        job.jd_structured = json.dumps({"summary": "s"}) if c["structured"] else None
        job_store.save_with_source_priority(job)
    try:
        # save may not persist every column on insert; set them explicitly.
        with PG_ENGINE.begin() as conn:
            for key, c in cases.items():
                conn.execute(text(
                    "UPDATE public.user_job_matches SET fit_brief = :b, score_is_proxy = :p, match_score = :s "
                    "WHERE job_id = :j AND user_id = CAST(:u AS uuid)"
                ), {"b": c["brief"], "p": c["proxy"], "s": c["score"], "j": ids[key], "u": _QA_USER_A})
                conn.execute(text(
                    "UPDATE public.job_postings SET jd_structured = CAST(:js AS jsonb) WHERE id = "
                    "(SELECT job_posting_id FROM public.user_job_matches WHERE job_id = :j AND user_id = CAST(:u AS uuid))"
                ), {"js": json.dumps({"summary": "s"}) if c["structured"] else None, "j": ids[key], "u": _QA_USER_A})

        mine = set(ids.values())
        expected = [j.job_id for j in job_store.get_feed(_QA_USER_A) if j.job_id in mine and _python_gate(j)]
        got = [j.job_id for j in job_store.get_ready_feed(_QA_USER_A, limit=200) if j.job_id in mine]
        assert got == expected == [ids["ready_hi"], ids["ready_lo"]]

        above_60 = [j.job_id for j in job_store.get_ready_feed(_QA_USER_A, min_score=60, limit=200) if j.job_id in mine]
        assert above_60 == [ids["ready_hi"]]
    finally:
        _cleanup(list(ids.values()))


def test_limit_is_applied_in_sql(db_available):
    from backend.repositories import job_repository as job_store
    assert len(job_store.get_ready_feed(_QA_USER_A, limit=1)) <= 1


def test_has_tailored_cv_without_reading_the_cv(db_available):
    from backend.core.postgres import PG_ENGINE
    from backend.repositories import job_repository as job_store

    jid = f"tcv-{_uid()[:8]}"
    job_store.save_with_source_priority(_make_job(jid, _QA_USER_A, match_score=70.0))
    try:
        assert job_store.get_by_id(jid, _QA_USER_A).has_tailored_cv is False
        with PG_ENGINE.begin() as conn:
            conn.execute(text(
                "UPDATE public.user_job_matches SET tailored_cv = CAST(:cv AS jsonb) "
                "WHERE job_id = :j AND user_id = CAST(:u AS uuid)"
            ), {"cv": json.dumps({"name": "x"}), "j": jid, "u": _QA_USER_A})
        assert job_store.get_by_id(jid, _QA_USER_A).has_tailored_cv is True
    finally:
        _cleanup([jid])


def test_feed_ships_a_jd_preview_not_the_whole_text(db_available):
    from backend.core.postgres import PG_ENGINE
    from backend.repositories import job_repository as job_store

    jid = f"prev-{_uid()[:8]}"
    job = _make_job(jid, _QA_USER_A, match_score=77.0)
    job_store.save_with_source_priority(job)
    try:
        with PG_ENGINE.begin() as conn:
            conn.execute(text(
                "UPDATE public.user_job_matches SET fit_brief = 'Strong fit', score_is_proxy = false "
                "WHERE job_id = :j AND user_id = CAST(:u AS uuid)"
            ), {"j": jid, "u": _QA_USER_A})
            conn.execute(text(
                "UPDATE public.job_postings SET jd_text = :jd, jd_structured = CAST(:js AS jsonb) WHERE id = "
                "(SELECT job_posting_id FROM public.user_job_matches WHERE job_id = :j AND user_id = CAST(:u AS uuid))"
            ), {"jd": "x" * 5000, "js": json.dumps({"summary": "s"}), "j": jid, "u": _QA_USER_A})

        listed = next(j for j in job_store.get_ready_feed(_QA_USER_A, limit=200) if j.job_id == jid)
        assert len(listed.jd_text) == 400 and listed.jd_structured
        assert len(job_store.get_by_id(jid, _QA_USER_A).jd_text) == 5000   # full text on demand
    finally:
        _cleanup([jid])


def test_contains_url_is_a_cheap_existence_check(db_available):
    from backend.repositories import job_repository as job_store

    jid = f"url-{_uid()[:8]}"
    url = f"https://example.com/{jid}"
    assert job_store.contains_url(url, _QA_USER_A) is False
    job_store.save_with_source_priority(_make_job(jid, _QA_USER_A, match_score=10.0, apply_url=url))
    try:
        assert job_store.contains_url(url, _QA_USER_A) is True
        assert job_store.contains_url(url, "00000000-0000-0000-0000-000000000000") is False
    finally:
        _cleanup([jid])
