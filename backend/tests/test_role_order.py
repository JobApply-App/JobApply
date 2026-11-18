"""
CLAUDE.md principle 1: the scorer reads the roles newest first. Callers pass
them that way; the old code reversed them, so the prompt showed the oldest
role first under the heading "most recent first".
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

from backend.services import match_score_service as svc
from backend.services.llm_client import LLMResult
from backend.services.profile_baseline_service import build_cv_data


def _roles(*dates):
    return [{"role": f"R{i}", "company": "C", "dates": d} for i, d in enumerate(dates)]


def test_newest_first_input_stays_newest_first():
    roles = _roles("2022 - present", "2016 - 2019", "2012 - 2015")
    assert svc._most_recent_first(roles) == roles


def test_dated_roles_are_sorted_newest_first_whatever_the_input_order():
    roles = _roles("2012 - 2015", "2022 - present", "2016 - 2019")
    assert [r["role"] for r in svc._most_recent_first(roles)] == ["R1", "R2", "R0"]


def test_any_undated_role_keeps_the_given_order():
    roles = _roles("2012 - 2015", "", "2022 - present")
    assert svc._most_recent_first(roles) == roles


async def test_prompt_shows_the_profiles_latest_role_first(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.setattr("backend.services.user_profile.build_full_text", lambda _uid: "")
    cv = build_cv_data({"experience": [
        {"company": "Corvina Pay", "role": "Team Lead", "period": "2022 - present"},
        {"company": "Mamram", "role": "Developer", "period": "2012 - 2015"},
    ]}, user_id="u")
    reply = LLMResult(text=json.dumps({"semantic_score": 80, "management_score": 70, "fit_brief": "ok"}),
                      model="m", input_tokens=None, output_tokens=None, latency_ms=0.0, attempts=1, raw=None)
    fake = AsyncMock(return_value=reply)
    with patch.object(svc, "call_llm", new=fake):
        await svc._llm_dual_score(cv, "jd " * 200, "Lead")
    prompt = fake.call_args.kwargs["messages"][0]["content"]
    assert prompt.index("[1] Team Lead @ Corvina Pay") < prompt.index("[2] Developer @ Mamram")
