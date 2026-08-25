"""
Regression tests for the daily Ariel chat message cap (2026-08-21).

Same two-layer split as test_cv_generation_cap.py: the repository's counting
logic against real Postgres, and the FastAPI dependency's 429 boundary
against a mocked repository call (no DB needed for that half).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from sqlalchemy import text

from backend.core.database import ENGINE
from backend.models import application, ariel, chat_message_log, cv_generation, kv, matching, profile  # noqa: F401
from backend.repositories import chat_message_log_repository as repo

_TEST_USER = "e2472fa3-db25-4e53-9d0b-2aed67bcfe0e"   # real profiles row from conftest's QA seeding


@pytest.fixture()
def clean_messages(db_available):
    with ENGINE.begin() as c:
        c.execute(text("DELETE FROM public.chat_messages_log WHERE user_id = :u"), {"u": _TEST_USER})
    yield
    with ENGINE.begin() as c:
        c.execute(text("DELETE FROM public.chat_messages_log WHERE user_id = :u"), {"u": _TEST_USER})


def test_count_today_is_zero_with_no_rows(clean_messages):
    assert repo.count_today(_TEST_USER) == 0


def test_record_then_count_reflects_it_across_both_endpoints(clean_messages):
    repo.record(_TEST_USER, endpoint="stream")
    assert repo.count_today(_TEST_USER) == 1
    repo.record(_TEST_USER, endpoint="ariel_private")
    assert repo.count_today(_TEST_USER) == 2, "both chat surfaces must count against the same daily total"


def test_count_today_excludes_yesterdays_rows(clean_messages):
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S")
    with ENGINE.begin() as c:
        c.execute(text(
            "INSERT INTO public.chat_messages_log (id, user_id, endpoint, created_at) "
            "VALUES (:id, :u, :e, :t)"
        ), {"id": uuid.uuid4().hex, "u": _TEST_USER, "e": "stream", "t": yesterday})

    assert repo.count_today(_TEST_USER) == 0, "a row from yesterday must not count toward today's cap"

    repo.record(_TEST_USER, endpoint="stream")
    assert repo.count_today(_TEST_USER) == 1


def test_count_today_is_scoped_per_user(clean_messages):
    other_user = "2631c93b-93bb-4313-a2c2-79dbb786d199"
    with ENGINE.begin() as c:
        c.execute(text("DELETE FROM public.chat_messages_log WHERE user_id = :u"), {"u": other_user})
    try:
        repo.record(other_user, endpoint="stream")
        assert repo.count_today(_TEST_USER) == 0, "another user's messages must not count against this user's cap"
    finally:
        with ENGINE.begin() as c:
            c.execute(text("DELETE FROM public.chat_messages_log WHERE user_id = :u"), {"u": other_user})


# ── Dependency boundary — no DB needed, count_today() is mocked ─────────────

class _FakeUser:
    def __init__(self, user_id):
        self.user_id = user_id


@pytest.mark.asyncio
async def test_dependency_allows_when_under_cap():
    from backend.api.deps import daily_chat_limit, DAILY_CHAT_MESSAGE_CAP

    with patch("backend.repositories.chat_message_log_repository.count_today", return_value=DAILY_CHAT_MESSAGE_CAP - 1):
        await daily_chat_limit(user=_FakeUser("any-user"))  # must not raise


@pytest.mark.asyncio
async def test_dependency_blocks_at_cap_with_429():
    from backend.api.deps import daily_chat_limit, DAILY_CHAT_MESSAGE_CAP

    with patch("backend.repositories.chat_message_log_repository.count_today", return_value=DAILY_CHAT_MESSAGE_CAP):
        with pytest.raises(HTTPException) as exc_info:
            await daily_chat_limit(user=_FakeUser("any-user"))
    assert exc_info.value.status_code == 429
    assert str(DAILY_CHAT_MESSAGE_CAP) in exc_info.value.detail


@pytest.mark.asyncio
async def test_dependency_blocks_over_cap_too():
    from backend.api.deps import daily_chat_limit, DAILY_CHAT_MESSAGE_CAP

    with patch("backend.repositories.chat_message_log_repository.count_today", return_value=DAILY_CHAT_MESSAGE_CAP + 5):
        with pytest.raises(HTTPException) as exc_info:
            await daily_chat_limit(user=_FakeUser("any-user"))
    assert exc_info.value.status_code == 429
