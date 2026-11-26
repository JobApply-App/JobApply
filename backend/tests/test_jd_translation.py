"""
Hebrew job summaries (job_postings.jd_structured_he) and Hebrew locations.

Unit tests mock the repository and the LLM; the SQL tests run against the
local Postgres and seed the shared QA account, like test_fit_brief_translation.
"""
from __future__ import annotations

import json
import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from backend.repositories import job_repository
from backend.services import jd_translation as svc
from backend.services.israel_cities import hebrew_location

_QA_USER_A = "2631c93b-93bb-4313-a2c2-79dbb786d199"

_EN = {
    "company_name": "Log-On Software",
    "company_details": "",
    "role_overview": "Manage enterprise clients.",
    "responsibilities": ["Lead QBRs.", "Ensure SLA compliance."],
    "requirements": ["3+ years in Customer Success."],
    "advantages": [],
    "additional_info": "",
}
_HE = {
    "company_name": "שם מתורגם בטעות",
    "company_details": "",
    "role_overview": "ניהול לקוחות אנטרפרייז.",
    "responsibilities": ["הובלת QBRs.", "עמידה ב-SLA."],
    "requirements": ["3+ שנים ב-Customer Success."],
    "advantages": [],
    "additional_info": "",
}


@pytest.fixture(autouse=True)
def _fresh_state(monkeypatch):
    svc._skipped.clear()
    monkeypatch.setattr(svc, "_consume_daily", lambda: True)
    monkeypatch.setattr("backend.services.llm_client.providers_unavailable", lambda: False)


def _fake_llm(monkeypatch, reply):
    calls = []

    async def _call(**kw):
        calls.append(kw)
        return SimpleNamespace(text=reply(json.loads(kw["messages"][0]["content"])))
    monkeypatch.setattr("backend.services.llm_client.call_llm", _call)
    return calls


def _fake_repo(monkeypatch, rows):
    saved = []
    monkeypatch.setattr(job_repository, "list_untranslated_jd_for_hebrew_users", lambda limit: rows[:limit])

    def _save(pid, src, he):
        saved.append((pid, he))
        return True
    monkeypatch.setattr(job_repository, "save_jd_structured_he", _save)
    return saved


# ── Shape checks ─────────────────────────────────────────────────────────────

def test_usable_keeps_company_name_from_source():
    out = svc._usable(_EN, _HE)
    assert out is not None
    assert out["company_name"] == "Log-On Software"     # never translated
    assert out["responsibilities"] == ["הובלת QBRs.", "עמידה ב-SLA."]


def test_usable_rejects_changed_list_length_or_english():
    assert svc._usable(_EN, {**_HE, "responsibilities": ["רק אחת."]}) is None
    english = {**_EN}
    assert svc._usable(_EN, english) is None            # came back untranslated
    assert svc._usable(_EN, {**_HE, "role_overview": ""}) is None   # dropped a filled field


# ── The sweep ────────────────────────────────────────────────────────────────

async def test_translates_and_saves(monkeypatch):
    saved = _fake_repo(monkeypatch, [("p1", _EN)])
    calls = _fake_llm(monkeypatch, lambda src: json.dumps([_HE], ensure_ascii=False))
    assert await svc.translate_next() == 1
    assert saved[0][0] == "p1" and saved[0][1]["role_overview"] == "ניהול לקוחות אנטרפרייז."
    assert calls[0]["purpose"] == "jd_translation"


async def test_unusable_item_is_skipped_not_retried(monkeypatch):
    saved = _fake_repo(monkeypatch, [("p1", _EN), ("p2", _EN)])
    _fake_llm(monkeypatch, lambda src: json.dumps([_HE, _EN], ensure_ascii=False))
    assert await svc.translate_next() == 1
    assert [pid for pid, _ in saved] == ["p1"]
    assert svc._skipped == {"p2"}


async def test_nothing_pending_makes_no_call(monkeypatch):
    _fake_repo(monkeypatch, [])
    calls = _fake_llm(monkeypatch, lambda src: "[]")
    assert await svc.translate_next() == 0
    assert calls == []


async def test_daily_cap_stops_the_call(monkeypatch):
    _fake_repo(monkeypatch, [("p1", _EN)])
    monkeypatch.setattr(svc, "_consume_daily", lambda: False)
    calls = _fake_llm(monkeypatch, lambda src: "[]")
    assert await svc.translate_next() == 0
    assert calls == []


async def test_llm_failure_never_raises(monkeypatch):
    _fake_repo(monkeypatch, [("p1", _EN)])

    async def _boom(**kw):
        raise RuntimeError("provider down")
    monkeypatch.setattr("backend.services.llm_client.call_llm", _boom)
    assert await svc.translate_next() == 0


# ── Locations ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("location,expected", [
    ("Petah Tikva, Center District, Israel", "פתח תקווה, מחוז המרכז, ישראל"),
    ("Tel Aviv-Yafo, Tel Aviv District, Israel", "תל אביב, מחוז תל אביב, ישראל"),
    ("Center District, Israel", "מחוז המרכז, ישראל"),
    ("Israel", "ישראל"),
    ("Acre, Brazil", None),                 # another country: left alone
    ("Remote", None),
    ("", None),
])
def test_hebrew_location(location, expected):
    assert hebrew_location(location) == expected


# ── SQL against the local Postgres ───────────────────────────────────────────

def _seed(job_id: str, structured: dict):
    from backend.schemas.job import DetailedAnalysis, JobMatch
    job_repository.save_with_source_priority(JobMatch(
        job_id=job_id, title=f"JD translation test {job_id}", company="Acme", location="Herzliya",
        score=80.0, confidence_score=50, culture_fit_score=50,
        trajectory_alignment="", company_dna_inference="",
        detailed_analysis=DetailedAnalysis(strengths=[], critical_gaps=[], strategic_advice=[]),
        investigation_points=[], reasons=[], user_id=_QA_USER_A, match_score=99.9, status="new",
        is_new=True, posted_at="", source="automatic", is_open=True, source_type="other",
        score_is_proxy=False, created_at="2026-11-26T00:00:00+00:00",
        apply_url=f"https://example.com/{job_id}", jd_structured=json.dumps(structured),
    ))


def _cleanup(job_ids):
    from backend.core.postgres import PG_ENGINE
    with PG_ENGINE.begin() as conn:
        postings = conn.execute(text(
            "SELECT job_posting_id FROM public.user_job_matches WHERE job_id = ANY(:ids)"), {"ids": job_ids}).fetchall()
        conn.execute(text("DELETE FROM public.user_job_matches WHERE job_id = ANY(:ids)"), {"ids": job_ids})
        for (pid,) in postings:
            conn.execute(text("DELETE FROM public.job_postings WHERE id = :pid"), {"pid": pid})


def _set_ui(locale):
    from backend.core.postgres import PG_ENGINE
    with PG_ENGINE.begin() as conn:
        conn.execute(text(
            "INSERT INTO public.user_preferences (user_id, ui_locale) VALUES (CAST(:u AS uuid), :l) "
            "ON CONFLICT (user_id) DO UPDATE SET ui_locale = :l"), {"u": _QA_USER_A, "l": locale})


def test_sql_lists_saves_and_serves_hebrew_only_to_hebrew_users(db_available):
    job = f"jdtr-{uuid.uuid4()}"
    _seed(job, _EN)
    try:
        _set_ui("he")
        rows = dict(job_repository.list_untranslated_jd_for_hebrew_users(500))
        posting = next(pid for pid, jd in rows.items() if jd == _EN)
        # The English structure changed meanwhile: the stale translation is refused.
        assert not job_repository.save_jd_structured_he(posting, {**_EN, "role_overview": "x"}, _HE)
        assert job_repository.save_jd_structured_he(posting, _EN, _HE)
        assert posting not in dict(job_repository.list_untranslated_jd_for_hebrew_users(500))

        served = job_repository.get_by_id(job, _QA_USER_A)
        assert json.loads(served.jd_structured)["role_overview"] == _EN["role_overview"]   # scorer's copy untouched
        assert json.loads(served.jd_structured_he)["role_overview"] == _HE["role_overview"]
        assert served.location_he == "הרצליה"

        _set_ui("en")
        served = job_repository.get_by_id(job, _QA_USER_A)
        assert served.jd_structured_he is None and served.location_he is None

        # Re-structuring the English summary clears the translation.
        job_repository.update_jd_structured(job, json.dumps({**_EN, "role_overview": "New."}))
        _set_ui("he")
        assert posting in dict(job_repository.list_untranslated_jd_for_hebrew_users(500))
    finally:
        _set_ui("he")
        _cleanup([job])
