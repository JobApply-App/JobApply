"""Eliya, the support assistant: what her prompt contains, and how her
conversations are saved, kept private and carried over on sign-in."""
import uuid

import pytest
from sqlalchemy.orm import Session

from backend.api import deps
from backend.api.routes import chat

_QA_A = "2631c93b-93bb-4313-a2c2-79dbb786d199"   # seeded in CI by ci-seed-qa-users.sql


# ── Prompt ────────────────────────────────────────────────────────────────────

def test_prompt_carries_the_knowledge_file_and_live_limits():
    prompt = chat._eliya_system_prompt(signed_in=False)
    assert "## Getting started" in prompt                      # from knowledge/eliya_product.md
    assert f"AI match analyses: {deps.DAILY_ANALYSIS_CAP} a day" in prompt
    assert f"Tailored CVs: {deps.DAILY_CV_GENERATION_CAP} a day" in prompt
    assert f"Messages with Ariel: {deps.DAILY_CHAT_MESSAGE_CAP} a day" in prompt


def test_prompt_keeps_answers_short_and_on_jobapply():
    prompt = chat._eliya_system_prompt(signed_in=False)
    assert "one to three short sentences" in prompt
    assert "you only help with JobApply" in prompt


def test_career_requests_route_by_sign_in_state():
    assert "open Ariel with the round button" in chat._eliya_system_prompt(signed_in=True)
    assert "Ariel comes with an account" in chat._eliya_system_prompt(signed_in=False)


# ── Storage ───────────────────────────────────────────────────────────────────

@pytest.fixture()
def repo(db_available):
    from backend.core.database import ENGINE
    from backend.models.support_message import SupportMessageRow
    from backend.repositories import support_message_repository

    sessions: list[str] = []

    def new_session() -> str:
        sid = str(uuid.uuid4())
        sessions.append(sid)
        return sid

    yield support_message_repository, new_session
    with Session(ENGINE) as s:
        s.query(SupportMessageRow).filter(SupportMessageRow.session_id.in_(sessions)).delete(synchronize_session=False)
        s.commit()


def test_anonymous_conversation_is_saved_in_order(repo):
    r, new_session = repo
    sid = new_session()
    r.add(sid, None, "user", "How do I sign up?")
    r.add(sid, None, "assistant", "Go to /signup.")
    assert r.recent(sid, None, 10) == [
        {"role": "user", "content": "How do I sign up?"},
        {"role": "assistant", "content": "Go to /signup."},
    ]


def test_another_browser_session_sees_nothing(repo):
    r, new_session = repo
    r.add(new_session(), None, "user", "private question")
    assert r.recent(new_session(), None, 10) == []


def test_signing_in_takes_the_conversation_along(repo):
    r, new_session = repo
    sid = new_session()
    r.add(sid, None, "user", "before sign-in")
    r.claim_session(sid, _QA_A)
    r.add(sid, _QA_A, "user", "after sign-in")

    # Signed in, from any browser: the whole conversation.
    contents = [m["content"] for m in r.recent(new_session(), _QA_A, 50)]
    assert contents[-2:] == ["before sign-in", "after sign-in"]
    # Signed out on that browser again: the user's rows are no longer readable.
    assert r.recent(sid, None, 10) == []


def test_clear_deletes_only_the_callers_conversation(repo):
    r, new_session = repo
    mine, theirs = new_session(), new_session()
    r.add(mine, None, "user", "mine")
    r.add(theirs, None, "user", "theirs")
    r.clear(mine, None)
    assert r.recent(mine, None, 10) == []
    assert r.recent(theirs, None, 10) == [{"role": "user", "content": "theirs"}]


def test_ariel_knows_the_same_live_limits(monkeypatch):
    # Both of Ariel's prompts (private chat and job-context chat) carry the
    # limits from deps.py, the same text Eliya gets.
    from backend.repositories import profile_repository
    monkeypatch.setattr(chat, "get_profile", lambda user_id: {})
    monkeypatch.setattr(profile_repository, "get_locales", lambda user_id: {"ui_locale": None, "cv_locale": None})
    uid = "00000000-0000-0000-0000-000000000001"
    limits = chat._daily_limits_note()
    for prompt in (chat._build_ariel_system([], uid), chat._build_system_prompt(None, uid)):
        assert limits in prompt
        assert f"AI match analyses: {deps.DAILY_ANALYSIS_CAP} a day" in prompt
        assert f"Messages with Ariel: {deps.DAILY_CHAT_MESSAGE_CAP} a day" in prompt
