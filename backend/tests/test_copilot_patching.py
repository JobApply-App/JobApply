"""
CopilotAgent's patch-based edit path (backend/agents/copilot.py).

Exercises the agent's response handling end to end with a stubbed LLM, so the
three branches that matter are covered without spending a real call:

  1. the model returns a patch (the contract),
  2. the model ignores the contract and returns a full document (fallback),
  3. the model returns a patch that cannot be applied (recovery).

The stub replaces call_llm, so these are deterministic and run in CI.
"""
from __future__ import annotations

import copy
import json
from types import SimpleNamespace

import pytest

import backend.agents.copilot as copilot_mod
from backend.agents.copilot import CopilotAgent


def _cv() -> dict:
    return {
        "header": {"full_name": "Ron", "target_title": "Product Manager",
                   "email": "r@example.com", "phone": "050", "location": "TLV",
                   "linkedin": "linkedin.com/in/ron"},
        "summary": "Managed a 40-account portfolio.",
        "experience": [
            {"company": "Acme", "role": "CSM", "dates": "2020 - 2023",
             "bullets": ["Cut churn by 12%.", "Onboarded 20 partners."]},
        ],
        "education": [],
        "military_service": None,
        "skills": {"categories": [{"label": "Tools", "items": ["Salesforce"]}]},
        "languages": [],
        "volunteering": "",
    }


@pytest.fixture(autouse=True)
def _no_api_key_required(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")


def _stub_llm(monkeypatch, payload: dict):
    """Make call_llm return `payload` as the model's JSON response."""
    async def fake_call_llm(*a, **k):
        return SimpleNamespace(text=json.dumps(payload))
    monkeypatch.setattr(copilot_mod, "call_llm", fake_call_llm)


# Static-section re-injection reads the DB; stub it so these stay pure.
@pytest.fixture(autouse=True)
def _no_db(monkeypatch):
    monkeypatch.setattr(copilot_mod, "_enforce_limits", lambda d: d)
    monkeypatch.setattr(copilot_mod, "_sanitize_ai_tells", lambda d: d)


@pytest.mark.asyncio
async def test_patch_response_applies_surgically(monkeypatch):
    _stub_llm(monkeypatch, {
        "status": "success",
        "message": None,
        "changes_summary": "Updated bullet 2 of Acme.",
        "patch": [{"op": "replace", "path": "/experience/0/bullets/1",
                   "value": "Onboarded 25 partners."}],
    })
    before = _cv()
    frozen = copy.deepcopy(before)

    out = await CopilotAgent().edit(cv_data=before, user_prompt="tweak bullet 2",
                                    master_profile={}, chat_history=[])

    assert out["status"] == "success"
    assert out["cv_data"]["experience"][0]["bullets"][1] == "Onboarded 25 partners."
    # untouched content is genuinely untouched
    assert out["cv_data"]["experience"][0]["bullets"][0] == frozen["experience"][0]["bullets"][0]
    assert out["cv_data"]["summary"] == frozen["summary"]
    # and the client gets ops to replay
    assert any(o["path"] == "/experience/0/bullets/1" for o in out["patch"])


@pytest.mark.asyncio
async def test_full_document_response_is_accepted_and_diffed(monkeypatch):
    """
    A model that ignores the patch instruction should still produce a usable
    edit — and the client must still receive ops, so the frontend has one code
    path regardless of which mode the model used.
    """
    mutated = _cv()
    mutated["summary"] = "Rewritten summary."
    _stub_llm(monkeypatch, {
        "status": "success", "message": None,
        "changes_summary": "Rewrote the summary.",
        "cv_data": mutated,
    })

    out = await CopilotAgent().edit(cv_data=_cv(), user_prompt="rewrite summary",
                                    master_profile={}, chat_history=[])

    assert out["status"] == "success"
    assert out["cv_data"]["summary"] == "Rewritten summary."
    assert any(o["op"] == "replace" and o["path"] == "/summary" for o in out["patch"])


@pytest.mark.asyncio
async def test_broken_patch_path_rejects_without_touching_the_cv(monkeypatch):
    _stub_llm(monkeypatch, {
        "status": "success", "message": None, "changes_summary": "Edited bullet 9.",
        "patch": [{"op": "replace", "path": "/experience/0/bullets/9", "value": "nope"}],
    })
    before = _cv()
    frozen = copy.deepcopy(before)

    out = await CopilotAgent().edit(cv_data=before, user_prompt="edit bullet 9",
                                    master_profile={}, chat_history=[])

    assert out["status"] == "rejected"
    assert out["cv_data"] == frozen
    assert out["patch"] == []
    assert out.get("patch_error")


@pytest.mark.asyncio
async def test_patch_targeting_contact_details_is_refused(monkeypatch):
    """The zero-hallucination boundary must hold through the agent, not just
    the patch service."""
    _stub_llm(monkeypatch, {
        "status": "success", "message": None, "changes_summary": "Updated email.",
        "patch": [{"op": "replace", "path": "/header/email", "value": "attacker@evil.com"}],
    })
    before = _cv()

    out = await CopilotAgent().edit(cv_data=before, user_prompt="change my email",
                                    master_profile={}, chat_history=[])

    assert out["status"] == "rejected"
    assert out["cv_data"]["header"]["email"] == "r@example.com"


@pytest.mark.asyncio
async def test_response_with_neither_patch_nor_cv_data_is_rejected(monkeypatch):
    _stub_llm(monkeypatch, {
        "status": "success", "message": None, "changes_summary": "Did something.",
    })
    before = _cv()
    out = await CopilotAgent().edit(cv_data=before, user_prompt="do a thing",
                                    master_profile={}, chat_history=[])
    assert out["status"] == "rejected"
    assert out["cv_data"] == before


@pytest.mark.asyncio
async def test_warning_status_leaves_the_cv_alone(monkeypatch):
    _stub_llm(monkeypatch, {
        "status": "warning",
        "message": "That would delete your most recent role. Confirm?",
        "changes_summary": None, "patch": [],
    })
    before = _cv()
    out = await CopilotAgent().edit(cv_data=before, user_prompt="remove everything",
                                    master_profile={}, chat_history=[])
    assert out["status"] == "warning"
    assert out["cv_data"] == before
