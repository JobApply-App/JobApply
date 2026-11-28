"""
"Ariel's analysis" (fit_brief) translated into the interface language and
stored beside the original, never over it.

Unit tests mock the repository and the LLM; the SQL tests run the repository
queries against the local Postgres (user_job_matches has a hard FK to
auth.users, so they seed the shared QA account, as test_analytics_service.py
does).
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
    svc._locales.clear()
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
    asked = []

    def _list(user_id, lang, limit):
        asked.append(lang)
        return rows[:limit]

    def _save(job_id, user_id, src, lang, new):
        saved[job_id] = (src, lang, new)
        return True
    monkeypatch.setattr(job_repository, "list_briefs_to_translate", _list)
    monkeypatch.setattr(job_repository, "save_fit_brief_translation", _save)
    return saved, asked


async def test_translates_english_briefs_into_hebrew_beside_the_original(monkeypatch):
    saved, asked = _fake_repo(monkeypatch, [("j1", "Strong B2B fit."), ("j2", "Lacks SQL.")])
    calls = _fake_llm(monkeypatch, lambda src: json.dumps(["התאמה חזקה ל-B2B.", "חסר SQL."], ensure_ascii=False))
    assert await svc.translate_batch(_USER, "he") == 2
    assert saved == {"j1": ("Strong B2B fit.", "he", "התאמה חזקה ל-B2B."),
                     "j2": ("Lacks SQL.", "he", "חסר SQL.")}
    assert asked == ["he"] and len(calls) == 1
    assert "English to Hebrew" in calls[0]["system"]


async def test_translates_hebrew_briefs_into_english(monkeypatch):
    # Ron, 2026-11-28: an English interface showed Hebrew analyses.
    saved, asked = _fake_repo(monkeypatch, [("j1", "חוזק: ניסיון B2B עמוק.")])
    calls = _fake_llm(monkeypatch, lambda src: json.dumps(["Strength: deep B2B experience."]))
    assert await svc.translate_batch(_USER, "en") == 1
    assert saved == {"j1": ("חוזק: ניסיון B2B עמוק.", "en", "Strength: deep B2B experience.")}
    assert asked == ["en"]
    assert "Hebrew to English" in calls[0]["system"]


async def test_empty_backlog_stops_querying(monkeypatch):
    queries = []
    monkeypatch.setattr(job_repository, "list_briefs_to_translate",
                        lambda user_id, lang, limit: queries.append(1) or [])
    await svc.translate_batch(_USER, "en")
    await svc.translate_batch(_USER, "en")
    assert len(queries) == 1


async def test_reply_in_the_wrong_language_is_skipped_not_retried(monkeypatch):
    saved, _ = _fake_repo(monkeypatch, [("j1", "Strong fit."), ("j2", "Weak fit.")])
    _fake_llm(monkeypatch, lambda src: json.dumps(["Strong fit.", "התאמה חלשה."], ensure_ascii=False))
    assert await svc.translate_batch(_USER, "he") == 1
    assert list(saved) == ["j2"]
    assert svc._skipped[(_USER, "he")] == {"j1"}


async def test_hebrew_left_in_an_english_reply_is_skipped(monkeypatch):
    saved, _ = _fake_repo(monkeypatch, [("j1", "התאמה חזקה.")])
    _fake_llm(monkeypatch, lambda src: json.dumps(["התאמה חזקה."], ensure_ascii=False))
    assert await svc.translate_batch(_USER, "en") == 0
    assert saved == {}


async def test_wrong_length_reply_saves_nothing(monkeypatch):
    saved, _ = _fake_repo(monkeypatch, [("j1", "a"), ("j2", "b")])
    _fake_llm(monkeypatch, lambda src: json.dumps(["רק אחד"], ensure_ascii=False))
    assert await svc.translate_batch(_USER, "he") == 0
    assert saved == {}


async def test_spent_daily_cap_skips_the_llm(monkeypatch):
    monkeypatch.setattr(svc, "_consume_daily", lambda user_id: False)
    _fake_repo(monkeypatch, [("j1", "Strong fit.")])
    calls = _fake_llm(monkeypatch, lambda src: "[]")
    assert await svc.translate_batch(_USER, "he") == 0
    assert calls == []


async def test_llm_failure_does_not_raise(monkeypatch):
    _fake_repo(monkeypatch, [("j1", "Strong fit.")])

    async def _boom(**kw):
        raise RuntimeError("provider down")
    monkeypatch.setattr("backend.services.llm_client.call_llm", _boom)
    assert await svc.translate_batch(_USER, "he") == 0


async def test_translate_all_uses_each_users_language(monkeypatch):
    monkeypatch.setattr(profile_repository, "list_ui_locales", lambda: {_USER: "he", "u2": "en"})
    seen = []

    async def _batch(user_id, lang):
        seen.append((user_id, lang))
        return 1
    monkeypatch.setattr(svc, "translate_batch", _batch)
    assert await svc.translate_all() == 2
    assert seen == [(_USER, "he"), ("u2", "en")]


async def test_user_who_switches_language_is_checked_again(monkeypatch):
    locales = {_USER: "he"}
    monkeypatch.setattr(profile_repository, "list_ui_locales", lambda: dict(locales))
    seen = []

    async def _batch(user_id, lang):
        seen.append((user_id, lang))
        svc._done.add((user_id, lang))      # backlog finished
        return 0
    monkeypatch.setattr(svc, "translate_batch", _batch)
    svc._done.add((_USER, "en"))            # e.g. finished in English earlier in the process

    await svc.translate_all()
    await svc.translate_all()               # done: not asked again
    assert seen == [(_USER, "he")]

    locales[_USER] = "en"                   # switches the interface to English
    await svc.translate_all()
    assert seen == [(_USER, "he"), (_USER, "en")]


async def test_does_not_touch_the_scoring_budget(monkeypatch):
    from backend.services import llm_budget

    def _forbidden(*a, **k):
        raise AssertionError("translation must not spend the scoring budget")
    monkeypatch.setattr(llm_budget, "consume", _forbidden)
    monkeypatch.setattr(llm_budget, "background_llm_allowed", _forbidden)
    _fake_repo(monkeypatch, [("j1", "Strong fit.")])
    _fake_llm(monkeypatch, lambda src: json.dumps(["התאמה חזקה."], ensure_ascii=False))
    assert await svc.translate_batch(_USER, "he") == 1


def test_daily_cap_counts_in_kv(monkeypatch):
    from backend.repositories import kv_repository
    store = {}
    monkeypatch.setattr(kv_repository, "get",
                        lambda k: SimpleNamespace(value=store[k]) if k in store else None)
    monkeypatch.setattr(kv_repository, "upsert", lambda k, v: store.__setitem__(k, v))
    monkeypatch.setattr(svc, "_DAILY_BATCHES", 2)
    assert [_REAL_CONSUME_DAILY(_USER) for _ in range(3)] == [True, True, False]


def test_served_translations_only_while_the_original_is_current():
    i18n = {"src": "Strong fit.", "he": "התאמה חזקה.", "en": ""}
    assert job_repository.brief_translations("Strong fit.", i18n) == {"he": "התאמה חזקה."}
    # Re-scored since: the old translation no longer describes this brief.
    assert job_repository.brief_translations("Weak fit.", i18n) is None
    assert job_repository.brief_translations("Strong fit.", None) is None
    assert job_repository.brief_translations(None, i18n) is None


# ── SQL against the local Postgres ───────────────────────────────────────────

def _seed(job_id: str, fit_brief: str):
    from backend.schemas.job import DetailedAnalysis, JobMatch
    job_repository.save_with_source_priority(JobMatch(
        job_id=job_id, title="Translation test", company=f"Acme {job_id}", location="Remote",  # distinct posting per seed
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


def _stored(job_id: str):
    from backend.core.postgres import PG_ENGINE
    with PG_ENGINE.connect() as conn:
        return conn.execute(text(
            "SELECT fit_brief, fit_brief_i18n FROM public.user_job_matches WHERE job_id = :j"), {"j": job_id}).one()


def test_sql_lists_ui_locales(db_available):
    from backend.core.postgres import PG_ENGINE
    with PG_ENGINE.begin() as conn:
        conn.execute(text(
            "INSERT INTO public.user_preferences (user_id, ui_locale) VALUES (CAST(:u AS uuid), 'he') "
            "ON CONFLICT (user_id) DO UPDATE SET ui_locale = 'he'"), {"u": _QA_USER_A})
    assert profile_repository.list_ui_locales().get(_QA_USER_A) == "he"


def test_sql_translation_is_stored_beside_the_original(db_available):
    en, he = f"tr-en-{uuid.uuid4()}", f"tr-he-{uuid.uuid4()}"
    _seed(en, "Strong B2B fit.")
    _seed(he, "התאמה חזקה ל-B2B.")
    try:
        assert {j for j, _ in job_repository.list_briefs_to_translate(_QA_USER_A, "he", 500)} >= {en}
        assert he not in {j for j, _ in job_repository.list_briefs_to_translate(_QA_USER_A, "he", 500)}
        assert he in {j for j, _ in job_repository.list_briefs_to_translate(_QA_USER_A, "en", 500)}

        # A re-score that changed the brief meanwhile wins.
        assert not job_repository.save_fit_brief_translation(en, _QA_USER_A, "something else", "he", "תרגום")
        assert job_repository.save_fit_brief_translation(en, _QA_USER_A, "Strong B2B fit.", "he", "התאמה חזקה.")
        brief, i18n = _stored(en)
        assert brief == "Strong B2B fit."                       # the original is untouched
        assert i18n == {"src": "Strong B2B fit.", "he": "התאמה חזקה."}
        assert en not in {j for j, _ in job_repository.list_briefs_to_translate(_QA_USER_A, "he", 500)}

        assert job_repository.save_fit_brief_translation(he, _QA_USER_A, "התאמה חזקה ל-B2B.", "en", "Strong B2B fit.")
        assert he not in {j for j, _ in job_repository.list_briefs_to_translate(_QA_USER_A, "en", 500)}
    finally:
        _cleanup([en, he])
