"""
Per-requirement verdicts: the scorer judges each JD requirement line, and code
turns the verdicts into coverage. For a years line the scorer names the roles
that count and code sums their dates, so "4 years as partnerships manager and
4 as customer success manager" is 8 years in the field.

Pure tests: no database, and the model call is faked.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from backend.services import match_score_service as svc
from backend.services.llm_client import LLMResult
from backend.services.match_dimensions import (
    compute_dimensions,
    requirement_credits,
    role_span,
    years_in_roles,
)

NOW = datetime(2026, 11, 17, tzinfo=timezone.utc)


def test_role_dates_are_read_in_the_common_forms():
    assert role_span("2016 - 2019", NOW) == (2016, 2019)
    assert role_span("03/2019 – 2021", NOW) == (2019 + 2 / 12, 2021)
    assert role_span("2022 - present", NOW) == (2022, 2026 + 10 / 12)
    assert role_span("2021-04 - היום", NOW)[0] == 2021 + 3 / 12
    assert role_span("", NOW) is None


def test_years_add_up_across_roles_in_the_field():
    experience = [{"dates": "2018 - 2022"}, {"dates": "2014 - 2018"}, {"dates": "2010 - 2014"}]
    assert years_in_roles(experience, [0, 1], NOW) == 8.0


def test_overlapping_roles_count_once():
    experience = [{"dates": "2018 - 2022"}, {"dates": "2020 - 2022"}]
    assert years_in_roles(experience, [0, 1], NOW) == 4.0


def test_unreadable_dates_are_unknown_not_zero():
    assert years_in_roles([{"dates": "a while"}], [0], NOW) is None


_EXP = [{"dates": "2018 - 2022"}, {"dates": "2014 - 2018"}, {"dates": "2012 - 2014"}]
_REQS = ["8+ years in partnerships or customer success", "Salesforce", "SQL", "Hebrew and English"]


def test_years_line_is_judged_on_summed_years_and_more_is_never_less():
    credits = requirement_credits(
        [{"n": 1, "verdict": "met", "evidence": "[1] [2]", "years_required": 8, "roles": [1, 2]}],
        _REQS, _EXP, NOW,
    )
    assert credits[_REQS[0]] == 1.0
    more = requirement_credits(
        [{"n": 1, "verdict": "met", "evidence": "x", "years_required": 5, "roles": [1, 2, 3]}],
        _REQS, _EXP, NOW,
    )
    assert more[_REQS[0]] == 1.0          # 10 years for 5 asked: full, not more, not less


def test_fewer_years_than_asked_earn_their_share():
    credits = requirement_credits(
        [{"n": 1, "verdict": "partial", "evidence": "[1]", "years_required": 8, "roles": [1]}],
        _REQS, _EXP, NOW,
    )
    assert credits[_REQS[0]] == 0.5        # 4 of 8


def test_verdict_words_and_unsupported_claims():
    credits = requirement_credits(
        [
            {"n": 2, "verdict": "met", "evidence": "[1] Salesforce admin"},
            {"n": 3, "verdict": "met", "evidence": ""},        # claimed with nothing to point to
            {"n": 4, "verdict": "not_met", "evidence": ""},
            {"n": 9, "verdict": "met", "evidence": "out of range"},
            {"verdict": "met"},
        ],
        _REQS, _EXP, NOW,
    )
    assert credits == {_REQS[1]: 1.0, _REQS[2]: 0.5, _REQS[3]: 0.0}


def _dims(credits):
    return compute_dimensions(
        must_haves=_REQS, nice_haves=[], profile_skills=["Salesforce"], skill_depth={},
        profile_domains=[], experience=[], jd_text="", target_company="", credits=credits,
    )


def test_without_verdicts_the_literal_match_is_used_as_before():
    dims = _dims(None)
    assert _REQS[0] not in dims.missing_must_haves          # years line left out
    assert dims.hard_skills == round(100 / 3, 1)            # Salesforce of 3 skill lines


def test_verdicts_raise_coverage_and_keep_the_years_line():
    dims = _dims({_REQS[0]: 1.0, _REQS[2]: 0.5, _REQS[3]: 1.0})
    assert dims.hard_skills == 87.5                         # (1 + 1 + 0.5 + 1) / 4
    assert _REQS[0] in dims.matched_must_haves


def test_a_wrong_not_met_cannot_undo_a_skill_the_profile_names():
    dims = _dims({_REQS[1]: 0.0})
    assert _REQS[1] in dims.matched_must_haves


def test_reply_cut_off_inside_the_verdicts_keeps_scores_and_brief():
    raw = ('{"semantic_score": 80, "management_score": 70, "fit_brief": "ok", '
           '"missing_critical_capabilities": [], "requirements": [{"n": 1, "verdict": "met", '
           '"evidence": "x"}, {"n": 2, "verd')
    payload = svc._parse_json_robust(raw)
    assert payload["fit_brief"] == "ok" and payload["requirements"] == [
        {"n": 1, "verdict": "met", "evidence": "x"}]


def _reply(payload) -> LLMResult:
    return LLMResult(text=json.dumps(payload), model="test-model", input_tokens=None,
                     output_tokens=None, latency_ms=0.0, attempts=1, raw=None)


async def test_scorer_returns_credits_and_sees_numbered_dated_roles(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    cv = {"experience": [{"role": "CSM", "company": "B", "dates": "2014 - 2018"},
                         {"role": "Partnerships Manager", "company": "A", "dates": "2018 - 2022"}]}
    fake = AsyncMock(return_value=_reply({
        "semantic_score": 80, "management_score": 70, "fit_brief": "ok",
        "missing_critical_capabilities": [],
        "requirements": [{"n": 1, "verdict": "met", "evidence": "[1] [2]",
                          "years_required": 8, "roles": [1, 2]}],
    }))
    with patch.object(svc, "call_llm", new=fake):
        sem, mgmt, brief, gaps, credits = await svc._llm_dual_score(
            cv, "jd " * 200, "Head of Partnerships", requirements=[_REQS[0]])
    prompt = fake.call_args.kwargs["messages"][0]["content"]
    assert "[1] Partnerships Manager @ A (2018 - 2022)" in prompt   # most recent first
    assert f"1. {_REQS[0]}" in prompt
    assert (sem, mgmt, brief) == (80, 70, "ok")
    assert credits == {_REQS[0]: 1.0}


async def test_malformed_verdicts_never_cost_the_scores(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    fake = AsyncMock(return_value=_reply({
        "semantic_score": 80, "management_score": 70, "fit_brief": "ok",
        "missing_critical_capabilities": [], "requirements": "not a list",
    }))
    with patch.object(svc, "call_llm", new=fake):
        sem, mgmt, brief, _, credits = await svc._llm_dual_score(
            {"experience": []}, "jd " * 200, "PM", requirements=["SQL"])
    assert (sem, mgmt, brief, credits) == (80, 70, "ok", {})
