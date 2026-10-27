"""
One-time Hebrew backfill of fit_brief for jobs scored before #81.

Unit tests mock the repository and the LLM; the SQL tests run the two
repository queries against the local Postgres (user_job_matches has a hard
FK to auth.users, so they seed the shared QA account, as
test_analytics_service.py does).
"""
from __future__ import annotations

import json
import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from backend.repositories import job_repository, profile_repository
from backend.services import fit_brief_translation as svc

_USER = "00000000-0000-0000-0000-000000000001"
_QA_USER_A = "2631c93b-93bb-4313-a2c2-79dbb786d199"
_REAL_CONSUME_DAILY = svc._consume_daily   # the autouse fixture stubs it


@pytest.fixture(autouse=True)
def _fresh_state(monkeypatch):
    svc._done.clear()
    svc._skipped.clear()
    monkeypatch.setattr(profile_repository, "get_locales", lambda user_id: {"ui_locale": "he", "cv_locale": None})
    monkeypatch.setattr(svc, "_consume_daily", lambda user_id: True)
    monkeypatch.setattr("backend.services.llm_client.providers_unavailable", lambda: False)


def _fake_llm(monkeypatch, reply):
    calls = []

    async def _call(**kw):
        calls.append(kw)
        return SimpleNamespace(text=reply(json.loads(kw["messages"][0]["content"])))
    monkeypatch.setattr("backend.services.llm_client.call_llm", _call)
    return calls


def _fake_repo(monkeypatch, rows):
    saved = {}
    monkeypatch.setattr(job_repository, "list_untranslated_fit_briefs", lambda user_id, limit: rows[:limit])
    monkeypatch.setattr(job_repository, "replace_fit_brief",
                        lambda job_id, user_id, old, new: saved.setdefault(job_id, new) is not None)
    return saved


async def test_translates_and_saves_hebrew(monkeypatch):
    saved = _fake_repo(monkeypatch, [("j1", "Strong B2B fit."), ("j2", "Lacks SQL.")])
    calls = _fake_llm(monkeypatch, lambda src: json.dumps(["התאמה חזקה ל-B2B.", "חסר SQL."], ensure_ascii=False))
    assert await svc.translate_batch(_USER) == 2
    assert saved == {"j1": "התאמה חזקה ל-B2B.", "j2": "חסר SQL."}
    assert len(calls) == 1


async def test_english_user_is_never_touched(monkeypatch):
    monkeypatch.setattr(profile_repository, "get_locales", lambda user_id: {"ui_locale": "en", "cv_locale": None})
    _fake_repo(monkeypatch, [("j1", "Strong fit.")])
    calls = _fake_llm(monkeypatch, lambda src: "[]")
    assert await svc.translate_batch(_USER) == 0
    assert calls == []


async def test_empty_backlog_stops_querying(monkeypatch):
    queries = []
    monkeypatch.setattr(job_repository, "list_untranslated_fit_briefs",
                        lambda user_id, limit: queries.append(1) or [])
    await svc.translate_batch(_USER)
    await svc.translate_batch(_USER)
    assert len(queries) == 1


async def test_non_hebrew_reply_is_skipped_not_retried(monkeypatch):
    saved = _fake_repo(monkeypatch, [("j1", "Strong fit."), ("j2", "Weak fit.")])
    _fake_llm(monkeypatch, lambda src: json.dumps(["Strong fit.", "התאמה חלשה."], ensure_ascii=False))
    assert await svc.translate_batch(_USER) == 1
    assert saved == {"j2": "התאמה חלשה."}
    assert svc._skipped[_USER] == {"j1"}


async def test_wrong_length_reply_saves_nothing(monkeypatch):
    saved = _fake_repo(monkeypatch, [("j1", "a"), ("j2", "b")])
    _fake_llm(monkeypatch, lambda src: json.dumps(["רק אחד"], ensure_ascii=False))
    assert await svc.translate_batch(_USER) == 0
    assert saved == {}


async def test_spent_daily_cap_skips_the_llm(monkeypatch):
    monkeypatch.setattr(svc, "_consume_daily", lambda user_id: False)
    _fake_repo(monkeypatch, [("j1", "Strong fit.")])
    calls = _fake_llm(monkeypatch, lambda src: "[]")
    assert await svc.translate_batch(_USER) == 0
    assert calls == []


async def test_llm_failure_does_not_raise(monkeypatch):
    _fake_repo(monkeypatch, [("j1", "Strong fit.")])

    async def _boom(**kw):
        raise RuntimeError("provider down")
    monkeypatch.setattr("backend.services.llm_client.call_llm", _boom)
    assert await svc.translate_batch(_USER) == 0


async def test_translate_all_covers_users_outside_the_pipeline(monkeypatch):
    monkeypatch.setattr(svc, "_users", None)
    monkeypatch.setattr(profile_repository, "list_hebrew_ui_user_ids", lambda: [_USER, "u2"])
    seen = []

    async def _batch(user_id):
        seen.append(user_id)
        return 1
    monkeypatch.setattr(svc, "translate_batch", _batch)
    assert await svc.translate_all() == 2
    assert seen == [_USER, "u2"]


async def test_does_not_touch_the_scoring_budget(monkeypatch):
    from backend.services import llm_budget

    def _forbidden(*a, **k):
        raise AssertionError("translation must not spend the scoring budget")
    monkeypatch.setattr(llm_budget, "consume", _forbidden)
    monkeypatch.setattr(llm_budget, "background_llm_allowed", _forbidden)
    _fake_repo(monkeypatch, [("j1", "Strong fit.")])
    _fake_llm(monkeypatch, lambda src: json.dumps(["התאמה חזקה."], ensure_ascii=False))
    assert await svc.translate_batch(_USER) == 1


def test_daily_cap_counts_in_kv(monkeypatch):
    from backend.repositories import kv_repository
    store = {}
    monkeypatch.setattr(kv_repository, "get",
                        lambda k: SimpleNamespace(value=store[k]) if k in store else None)
    monkeypatch.setattr(kv_repository, "upsert", lambda k, v: store.__setitem__(k, v))
    monkeypatch.setattr(svc, "_DAILY_BATCHES", 2)
    assert [_REAL_CONSUME_DAILY(_USER) for _ in range(3)] == [True, True, False]


# ── SQL against the local Postgres ───────────────────────────────────────────

def _seed(job_id: str, fit_brief: str):
    from backend.schemas.job import DetailedAnalysis, JobMatch
    job_repository.save_with_source_priority(JobMatch(
        job_id=job_id, title="Translation test", company="Acme", location="Remote",
        score=80.0, confidence_score=50, culture_fit_score=50,
        trajectory_alignment="", company_dna_inference="",
        detailed_analysis=DetailedAnalysis(strengths=[], critical_gaps=[], strategic_advice=[]),
        investigation_points=[], reasons=[], user_id=_QA_USER_A, match_score=99.9, status="new",
        is_new=True, posted_at="", source="automatic", is_open=True, source_type="other",
        score_is_proxy=False, created_at="2026-10-27T00:00:00+00:00",
        apply_url=f"https://example.com/{job_id}", fit_brief=fit_brief,
    ))


def _cleanup(job_ids):
    from backend.core.postgres import PG_ENGINE
    with PG_ENGINE.begin() as conn:
        postings = conn.execute(text(
            "SELECT job_posting_id FROM public.user_job_matches WHERE job_id = ANY(:ids)"), {"ids": job_ids}).fetchall()
        conn.execute(text("DELETE FROM public.user_job_matches WHERE job_id = ANY(:ids)"), {"ids": job_ids})
        for (pid,) in postings:
            conn.execute(text("DELETE FROM public.job_postings WHERE id = :pid"), {"pid": pid})


def test_sql_lists_hebrew_ui_users(db_available):
    from backend.core.postgres import PG_ENGINE
    with PG_ENGINE.begin() as conn:
        conn.execute(text(
            "INSERT INTO public.user_preferences (user_id, ui_locale) VALUES (CAST(:u AS uuid), 'he') "
            "ON CONFLICT (user_id) DO UPDATE SET ui_locale = 'he'"), {"u": _QA_USER_A})
    assert _QA_USER_A in profile_repository.list_hebrew_ui_user_ids()


def test_sql_lists_only_english_and_replace_is_conditional(db_available):
    en, he = f"tr-en-{uuid.uuid4()}", f"tr-he-{uuid.uuid4()}"
    _seed(en, "Strong B2B fit.")
    _seed(he, "התאמה חזקה ל-B2B.")
    try:
        ids = {j for j, _ in job_repository.list_untranslated_fit_briefs(_QA_USER_A, 500)}
        assert en in ids and he not in ids
        # A re-score that changed the brief meanwhile wins.
        assert not job_repository.replace_fit_brief(en, _QA_USER_A, "something else", "תרגום")
        assert job_repository.replace_fit_brief(en, _QA_USER_A, "Strong B2B fit.", "התאמה חזקה.")
        ids = {j for j, _ in job_repository.list_untranslated_fit_briefs(_QA_USER_A, 500)}
        assert en not in ids
    finally:
        _cleanup([en, he])
