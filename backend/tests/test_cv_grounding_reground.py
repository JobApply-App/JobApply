"""
Regression tests for the CV grounding repair path (2026-08-21).

Covers reground_bullets() (the LLM repair call, mocked — no real DB/LLM
needed) and GroundingGate.reground_and_filter() (the orchestration: check,
repair, re-verify, and only remove as the last resort).
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from backend.services.cv_grounding import GroundingGate, reground_bullets
from backend.services.llm_client import LLMResult


def _llm_result(text: str) -> LLMResult:
    return LLMResult(text=text, model="test-model", input_tokens=None,
                      output_tokens=None, latency_ms=0.0, attempts=1, raw=None)


# ── reground_bullets() ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_reground_bullets_returns_empty_for_no_input():
    assert await reground_bullets([], profile_text="anything", model="m", user_id="u", purpose="test") == {}


@pytest.mark.asyncio
async def test_reground_bullets_maps_original_to_rewrite():
    raw = '{"rewrites": [{"i": 1, "text": "Managed a growing engineering team"}]}'
    with patch("backend.services.llm_client.call_llm", new=AsyncMock(return_value=_llm_result(raw))):
        out = await reground_bullets(
            ["Managed a team of 47 engineers at Initech"],
            profile_text="Worked as an engineering manager.",
            model="m", user_id="u", purpose="test",
        )
    assert out == {"Managed a team of 47 engineers at Initech": "Managed a growing engineering team"}


@pytest.mark.asyncio
async def test_reground_bullets_omits_index_the_model_declined():
    # Two bullets sent, model only returns a rewrite for #2 — #1 must be absent.
    raw = '{"rewrites": [{"i": 2, "text": "Delivered the project on schedule"}]}'
    with patch("backend.services.llm_client.call_llm", new=AsyncMock(return_value=_llm_result(raw))):
        out = await reground_bullets(
            ["Grew revenue by 300%", "Delivered the project 3 weeks early"],
            profile_text="Delivered projects on schedule.",
            model="m", user_id="u", purpose="test",
        )
    assert "Grew revenue by 300%" not in out
    assert out["Delivered the project 3 weeks early"] == "Delivered the project on schedule"


@pytest.mark.asyncio
async def test_reground_bullets_returns_empty_on_unparseable_json():
    with patch("backend.services.llm_client.call_llm", new=AsyncMock(return_value=_llm_result("not json at all"))):
        out = await reground_bullets(["some bullet"], profile_text="x", model="m", user_id="u", purpose="test")
    assert out == {}


# ── GroundingGate.reground_and_filter() ─────────────────────────────────────

def _cv(bullets: list[str]) -> dict:
    return {"experience": [{"role": "Engineer", "company": "Acme", "bullets": bullets}]}


@pytest.mark.asyncio
async def test_reground_and_filter_leaves_clean_cv_untouched():
    gate = GroundingGate({"acme", "47"}, context="test")
    cv_data = _cv(["Worked at Acme managing 47 people"])
    out, report = await gate.reground_and_filter(cv_data, user_id="u", model="m")
    assert out["experience"][0]["bullets"] == ["Worked at Acme managing 47 people"]
    assert report.flagged_count == 0
    assert report.rewritten == 0
    assert report.removed == 0


@pytest.mark.asyncio
async def test_reground_and_filter_rewrites_a_flagged_bullet():
    # Corpus supports "acme" but not "999" — the bullet should get repaired,
    # not deleted, since the rewrite below re-verifies clean against the corpus.
    gate = GroundingGate({"acme"}, context="test")
    cv_data = _cv(["Grew Acme's revenue by 999%"])

    raw = '{"rewrites": [{"i": 1, "text": "Grew Acme'"'"'s revenue significantly"}]}'
    with patch("backend.services.llm_client.call_llm", new=AsyncMock(return_value=_llm_result(raw))), \
         patch("backend.services.user_profile.build_full_text", return_value="Worked at Acme."):
        out, report = await gate.reground_and_filter(cv_data, user_id="u", model="m")

    assert out["experience"][0]["bullets"] == ["Grew Acme's revenue significantly"]
    assert report.flagged_count == 1
    assert report.rewritten == 1
    assert report.removed == 0


@pytest.mark.asyncio
async def test_reground_and_filter_removes_when_rewrite_still_fails_verification():
    # The "repaired" bullet the model returns still contains an unverifiable
    # number — the invariant (never ship a fabrication) means this must be
    # removed, not shipped just because a rewrite was attempted.
    gate = GroundingGate({"acme"}, context="test")
    cv_data = _cv(["Grew Acme's revenue by 999%"])

    raw = '{"rewrites": [{"i": 1, "text": "Grew Acme'"'"'s revenue by 999% still"}]}'
    with patch("backend.services.llm_client.call_llm", new=AsyncMock(return_value=_llm_result(raw))), \
         patch("backend.services.user_profile.build_full_text", return_value="Worked at Acme."):
        out, report = await gate.reground_and_filter(cv_data, user_id="u", model="m")

    assert out["experience"][0]["bullets"] == []
    assert report.rewritten == 0
    assert report.removed == 1
    assert "999" in report.user_notice() or "removed" in report.user_notice()


@pytest.mark.asyncio
async def test_reground_and_filter_removes_when_repair_call_raises():
    # A hard failure in the repair path (network error, etc.) must fall back
    # to removal — the safe side — never leave the unverified bullet in place.
    gate = GroundingGate({"acme"}, context="test")
    cv_data = _cv(["Grew Acme's revenue by 999%"])

    with patch("backend.services.llm_client.call_llm", new=AsyncMock(side_effect=RuntimeError("boom"))), \
         patch("backend.services.user_profile.build_full_text", return_value="Worked at Acme."):
        out, report = await gate.reground_and_filter(cv_data, user_id="u", model="m")

    assert out["experience"][0]["bullets"] == []
    assert report.removed == 1


@pytest.mark.asyncio
async def test_reground_and_filter_removes_when_profile_text_unavailable():
    gate = GroundingGate({"acme"}, context="test")
    cv_data = _cv(["Grew Acme's revenue by 999%"])

    with patch("backend.services.user_profile.build_full_text", side_effect=RuntimeError("no profile")):
        out, report = await gate.reground_and_filter(cv_data, user_id="u", model="m")

    assert out["experience"][0]["bullets"] == []
    assert report.removed == 1


@pytest.mark.asyncio
async def test_reground_and_filter_empty_corpus_skips_entirely():
    gate = GroundingGate(set(), context="test")
    cv_data = _cv(["Grew Acme's revenue by 999%"])
    out, report = await gate.reground_and_filter(cv_data, user_id="u", model="m")
    assert out["experience"][0]["bullets"] == ["Grew Acme's revenue by 999%"]
    assert report.checked == 0
