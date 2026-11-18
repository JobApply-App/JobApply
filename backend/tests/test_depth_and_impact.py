"""
Depth and impact dimensions.

Depth: the literal match finds a skill name inside a requirement line, so a
line written as an ability ("owning a product area with an engineering
squad") matched nothing and depth sat on its floor of 15. It now takes the scorer's verdict credits, as hard skills does.
A skill's own years are measured against at most _ESTABLISHED_SKILL_YEARS,
not the JD's headline years ("8+ years of backend" is not 8 years of Kafka).

Impact: was a count of $ / % / "N users" in the CV, the same for every job,
and 0 for CVs whose results are not numbers. The scorer now judges it for
the job; the count is the fallback.

Pure tests: no database, and the model call is faked.
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

from backend.services import match_score_service as svc
from backend.services.llm_client import LLMResult
from backend.services.match_dimensions import (
    TRANSFERABLE_DEPTH_FLOOR,
    compute_dimensions,
    score_depth_breadth,
)

_MUST = ["Owning a product area with an engineering squad",
         "Product analytics, including funnels, cohorts, and A/B tests"]
_SKILLS = ["roadmapping", "a/b testing"]


def test_verdict_credits_cover_sentence_requirements():
    literal, _ = score_depth_breadth(_MUST, _SKILLS, {})
    judged, _ = score_depth_breadth(_MUST, _SKILLS, {},
                                    credits={_MUST[0]: 1.0, _MUST[1]: 1.0})
    assert literal == TRANSFERABLE_DEPTH_FLOOR
    assert judged > 80.0


def test_partial_verdicts_earn_part_of_the_breadth():
    full, _ = score_depth_breadth(_MUST, _SKILLS, {}, credits={_MUST[0]: 1.0, _MUST[1]: 1.0})
    half, _ = score_depth_breadth(_MUST, _SKILLS, {}, credits={_MUST[0]: 1.0, _MUST[1]: 0.5})
    none, _ = score_depth_breadth(_MUST, _SKILLS, {}, credits={_MUST[0]: 0.0, _MUST[1]: 0.0})
    assert full > half > none == TRANSFERABLE_DEPTH_FLOOR


def test_one_verdict_flipping_does_not_jump_depth():
    """One "partly" among six lines was ~50 against a floor of 15; repeats flip it."""
    must = [f"Ability number {i} worded as a sentence" for i in range(6)]
    none, _ = score_depth_breadth(must, _SKILLS, {}, credits={})
    one, _ = score_depth_breadth(must, _SKILLS, {}, credits={must[0]: 0.5})
    assert none == TRANSFERABLE_DEPTH_FLOOR
    assert one - none < 10.0


def test_headline_years_are_not_asked_of_each_skill():
    """Three years of Kafka is established Kafka, whatever the JD's headline years."""
    must = ["kafka"]
    three, _ = score_depth_breadth(must, must, {"kafka": {"years": 3.0}}, required_years=8.0)
    eight, _ = score_depth_breadth(must, must, {"kafka": {"years": 8.0}}, required_years=8.0)
    one, _ = score_depth_breadth(must, must, {"kafka": {"years": 1.0}}, required_years=8.0)
    assert three == eight
    assert one < three


def test_a_short_requirement_is_still_the_bar():
    must = ["python"]
    two, _ = score_depth_breadth(must, must, {"python": {"years": 2.0}}, required_years=2.0)
    one, _ = score_depth_breadth(must, must, {"python": {"years": 1.0}}, required_years=2.0)
    assert one < two


def _dims(**kw):
    base = dict(must_haves=["python"], nice_haves=[], profile_skills=["python"], skill_depth={},
                profile_domains=[], experience=[], jd_text="", target_company="Acme", impact=0.0)
    return compute_dimensions(**{**base, **kw})


def test_judged_impact_replaces_the_number_count():
    assert _dims(impact_fit="strong").impact == 100.0
    assert _dims(impact_fit="some").impact == 70.0
    assert _dims(impact_fit="little").impact == 40.0
    assert _dims(impact=22.0).impact == 22.0          # scorer failed → the count, as before
    assert _dims(impact=22.0, impact_fit="huge").impact == 22.0
    assert _dims(impact_fit="strong").structural > _dims(impact_fit="little").structural


def _reply(payload) -> LLMResult:
    return LLMResult(text=json.dumps(payload), model="test-model", input_tokens=None,
                     output_tokens=None, latency_ms=0.0, attempts=1, raw=None)


async def test_scorer_returns_impact_fit_and_sees_the_result(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    fake = AsyncMock(return_value=_reply({
        "semantic_score": 80, "management_score": 70, "fit_brief": "ok",
        "missing_critical_capabilities": [], "impact_fit": "Strong", "requirements": [],
    }))
    bullet = ("Owns the visual language of 3 snack brands sold in major supermarket chains, "
              "designing 40 new packages, 2 seasonal ranges, and in-store campaign materials.")
    cv = {"experience": [{"role": "Designer", "company": "Snacks", "dates": "2020 - present",
                          "bullets": [bullet]}]}
    with patch.object(svc, "call_llm", new=fake):
        *_, impact_fit = await svc._llm_dual_score(cv, "jd " * 200, "Designer")
    assert "designing 40 new packages" in fake.call_args.kwargs["messages"][0]["content"]
    assert impact_fit == "strong"


async def test_unknown_impact_answer_is_no_judgement(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    fake = AsyncMock(return_value=_reply({
        "semantic_score": 80, "management_score": 70, "fit_brief": "ok",
        "missing_critical_capabilities": [], "impact_fit": "very high",
    }))
    with patch.object(svc, "call_llm", new=fake):
        *_, impact_fit = await svc._llm_dual_score({"experience": []}, "jd " * 200, "PM")
    assert impact_fit is None
