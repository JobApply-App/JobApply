"""
Domain dimension: the candidate's domains (from the CV upload and from Ariel,
in profile_entities) reach the score, and the scorer judges the job's
industry against them. Before this, cv_data["domains"] was never set, so the
dimension was 50 for every job.

Pure tests: no database, and the model call is faked.
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

from backend.services import match_score_service as svc
from backend.services.llm_client import LLMResult
from backend.services.match_dimensions import LEGACY_FLOOR, score_domain_context
from backend.services.profile_baseline_service import build_cv_data


def test_judged_domain_fit_sets_the_dimension():
    assert score_domain_context("", "Acme", ["Payments"], [], "same")[0] == 100.0
    assert score_domain_context("", "Acme", ["Payments"], [], "adjacent")[0] == 75.0


def test_a_different_field_is_neutral_not_a_penalty():
    different = score_domain_context("", "Acme", ["Payments"], [], "different")[0]
    no_signal = score_domain_context("", "Acme", [], [], None)[0]
    unjudged_miss = score_domain_context("we sell shoes", "Acme", ["Payments"], [], None)[0]
    assert different == no_signal == unjudged_miss == 50.0


def test_prior_employer_floor_still_wins():
    exp = [{"company": "Harborline Payments"}]
    score, legacy, _ = score_domain_context("", "Harborline Payments", [], exp, "different")
    assert (score, legacy) == (LEGACY_FLOOR, "Harborline Payments")


def test_without_a_judgement_the_names_are_still_looked_for():
    score, _, _ = score_domain_context("payments infrastructure for logistics", "Acme",
                                       ["Payments", "Logistics"], [], None)
    assert score > 50.0


def test_scoring_cv_carries_role_dates(monkeypatch):
    monkeypatch.setattr("backend.services.user_profile.build_full_text", lambda _uid: "")
    profile = {"experience": [
        {"company": "A", "role": "Lead", "period": "2022 - present", "details": "x"},
        {"company": "B", "role": "Dev", "start": "2016", "end": "2019"},
        {"company": "C", "role": "", "roles": [{"title": "PM", "period": "2010 - 2012"}, {"title": "APM"}],
         "period": "2008 - 2012"},
    ]}
    dates = [e["dates"] for e in build_cv_data(profile, user_id="u")["experience"]]
    assert dates == ["2022 - present", "2016 - 2019", "2010 - 2012", "2008 - 2012"]


def _reply(payload) -> LLMResult:
    return LLMResult(text=json.dumps(payload), model="test-model", input_tokens=None,
                     output_tokens=None, latency_ms=0.0, attempts=1, raw=None)


async def test_scorer_sees_the_domains_and_returns_the_judgement(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    fake = AsyncMock(return_value=_reply({
        "semantic_score": 80, "management_score": 70, "fit_brief": "ok",
        "missing_critical_capabilities": [], "domain_fit": "Same", "requirements": [],
    }))
    with patch.object(svc, "call_llm", new=fake):
        *_, domain_fit = await svc._llm_dual_score(
            {"experience": []}, "jd " * 200, "PM", domains=["Payments", "Logistics"])
    assert "Payments, Logistics" in fake.call_args.kwargs["messages"][0]["content"]
    assert domain_fit == "same"


async def test_unknown_domain_answer_is_no_judgement(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    fake = AsyncMock(return_value=_reply({
        "semantic_score": 80, "management_score": 70, "fit_brief": "ok",
        "missing_critical_capabilities": [], "domain_fit": "very close",
    }))
    with patch.object(svc, "call_llm", new=fake):
        *_, domain_fit = await svc._llm_dual_score({"experience": []}, "jd " * 200, "PM")
    assert domain_fit is None
