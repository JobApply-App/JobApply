"""
Regression tests for the daily CV-generation cap (2026-08-21).

Covers both layers: the repository's counting logic (real Postgres —
count_today() needs a real date-range query, not something worth mocking),
and the FastAPI dependency's 429 boundary (mocked repository call, so this
half runs without any DB at all).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from sqlalchemy import text

from backend.core.database import ENGINE
from backend.models import application, ariel, cv_generation, kv, matching, profile  # noqa: F401
from backend.repositories import cv_generation_repository as repo

_TEST_USER = "e2472fa3-db25-4e53-9d0b-2aed67bcfe0e"   # real profiles row from conftest's QA seeding


@pytest.fixture()
def clean_generations(db_available):
    with ENGINE.begin() as c:
        c.execute(text("DELETE FROM public.cv_generations WHERE user_id = :u"), {"u": _TEST_USER})
    yield
    with ENGINE.begin() as c:
        c.execute(text("DELETE FROM public.cv_generations WHERE user_id = :u"), {"u": _TEST_USER})


def test_count_today_is_zero_with_no_rows(clean_generations):
    assert repo.count_today(_TEST_USER) == 0


def test_record_then_count_reflects_it(clean_generations):
    repo.record(_TEST_USER, job_id="job-1")
    assert repo.count_today(_TEST_USER) == 1
    repo.record(_TEST_USER, job_id="job-2")
    assert repo.count_today(_TEST_USER) == 2


def test_count_today_excludes_yesterdays_rows(clean_generations):
    # Insert a row timestamped yesterday directly — record() always stamps
    # "now", so this is the one case that has to go around it.
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S")
    with ENGINE.begin() as c:
        c.execute(text(
            "INSERT INTO public.cv_generations (id, user_id, job_id, created_at) "
            "VALUES (:id, :u, :j, :t)"
        ), {"id": uuid.uuid4().hex, "u": _TEST_USER, "j": "job-old", "t": yesterday})

    assert repo.count_today(_TEST_USER) == 0, "a row from yesterday must not count toward today's cap"

    repo.record(_TEST_USER, job_id="job-today")
    assert repo.count_today(_TEST_USER) == 1, "yesterday's row still must not count, even alongside a real one"


def test_count_today_is_scoped_per_user(clean_generations):
    other_user = "2631c93b-93bb-4313-a2c2-79dbb786d199"
    with ENGINE.begin() as c:
        c.execute(text("DELETE FROM public.cv_generations WHERE user_id = :u"), {"u": other_user})
    try:
        repo.record(other_user, job_id="job-other-user")
        assert repo.count_today(_TEST_USER) == 0, "another user's generation must not count against this user's cap"
    finally:
        with ENGINE.begin() as c:
            c.execute(text("DELETE FROM public.cv_generations WHERE user_id = :u"), {"u": other_user})


# ── Dependency boundary — no DB needed, count_today() is mocked ─────────────

class _FakeUser:
    def __init__(self, user_id):
        self.user_id = user_id


@pytest.mark.asyncio
async def test_dependency_allows_when_under_cap():
    from backend.api.deps import daily_generation_limit, DAILY_CV_GENERATION_CAP

    with patch("backend.repositories.cv_generation_repository.count_today", return_value=DAILY_CV_GENERATION_CAP - 1):
        await daily_generation_limit(user=_FakeUser("any-user"))  # must not raise


@pytest.mark.asyncio
async def test_dependency_blocks_at_cap_with_429():
    from backend.api.deps import daily_generation_limit, DAILY_CV_GENERATION_CAP

    with patch("backend.repositories.cv_generation_repository.count_today", return_value=DAILY_CV_GENERATION_CAP):
        with pytest.raises(HTTPException) as exc_info:
            await daily_generation_limit(user=_FakeUser("any-user"))
    assert exc_info.value.status_code == 429
    assert str(DAILY_CV_GENERATION_CAP) in exc_info.value.detail


@pytest.mark.asyncio
async def test_dependency_blocks_over_cap_too():
    """Not just ==: a race (two requests in flight) could push the count past
    the cap between checks, and the very next request must still be blocked,
    not slip through because it isn't an exact match."""
    from backend.api.deps import daily_generation_limit, DAILY_CV_GENERATION_CAP

    with patch("backend.repositories.cv_generation_repository.count_today", return_value=DAILY_CV_GENERATION_CAP + 3):
        with pytest.raises(HTTPException) as exc_info:
            await daily_generation_limit(user=_FakeUser("any-user"))
    assert exc_info.value.status_code == 429
