"""
Finishing onboarding must admit the user to the matching pipeline.

The background loop that fills a user's Matches feed fans out only over
profiles.onboarding_status = 'complete' (tenant_registry.list_pipeline_user_ids).
For as long as this test did not exist, nothing the onboarding wizard did ever
set that status: it wrote `profile_completed` into Supabase auth metadata, a
different flag in a different system, and the only writer of the real one was
an Ariel tool that fires when a user tells the chat "that's everything".

So in production zero users had the status — including one who had used the
product for months — and the loop ran every 30 minutes over an empty list. It
never failed, which is why nobody noticed: a loop that does nothing on purpose
and a loop that does nothing by accident look identical in the logs.

These tests pin the behaviour that was missing, and the last one asserts on the
pipeline's own gate rather than on the column, because the column being set was
never the point — being matched was.

Postgres-backed; CI drops the profiles -> auth.users FK so a synthetic UUID
user needs no Supabase account.
"""
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from backend.core.database import ENGINE
from backend.repositories import profile_repository
from backend.services import tenant_registry


def _status(uid: str):
    with ENGINE.connect() as c:
        return c.execute(
            text("SELECT onboarding_status FROM public.profiles WHERE id = CAST(:u AS uuid)"),
            {"u": uid},
        ).scalar()


def _set_incomplete_row(uid: str) -> None:
    with ENGINE.begin() as c:
        c.execute(
            text("INSERT INTO public.profiles (id, onboarding_status) VALUES (CAST(:u AS uuid), 'incomplete') "
                 "ON CONFLICT (id) DO UPDATE SET onboarding_status = 'incomplete'"),
            {"u": uid},
        )


@pytest.fixture()
def uid(db_available):
    u = str(uuid.uuid4())
    yield u
    with ENGINE.begin() as c:
        c.execute(text("DELETE FROM public.profiles WHERE id = CAST(:u AS uuid)"), {"u": u})


def test_marks_existing_incomplete_row_complete(uid):
    _set_incomplete_row(uid)
    assert profile_repository.mark_onboarding_complete(uid) is True
    assert _status(uid) == "complete"


def test_creates_row_when_none_exists(uid):
    assert _status(uid) is None
    assert profile_repository.mark_onboarding_complete(uid) is True
    assert _status(uid) == "complete"


def test_is_idempotent(uid):
    """A double-submitted wizard or a retried request must be harmless."""
    assert profile_repository.mark_onboarding_complete(uid) is True
    assert profile_repository.mark_onboarding_complete(uid) is False
    assert _status(uid) == "complete"


def test_does_not_touch_another_user(uid):
    other = str(uuid.uuid4())
    try:
        _set_incomplete_row(other)
        profile_repository.mark_onboarding_complete(uid)
        assert _status(other) == "incomplete"
    finally:
        with ENGINE.begin() as c:
            c.execute(text("DELETE FROM public.profiles WHERE id = CAST(:u AS uuid)"), {"u": other})


def test_endpoint_marks_only_the_caller(uid):
    from backend.main import app
    from backend.api.deps import get_current_user, CurrentUser

    _set_incomplete_row(uid)
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(user_id=uid, email="t@example.com")
    try:
        client = TestClient(app)
        first = client.post("/api/profile/onboarding/complete")
        second = client.post("/api/profile/onboarding/complete")
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert first.status_code == 200 and first.json()["changed"] is True
    assert second.status_code == 200 and second.json()["changed"] is False
    assert _status(uid) == "complete"


def test_user_enters_the_matching_pipeline_after_onboarding(uid):
    """
    The regression this file exists for. Asserted on the pipeline's own gate,
    not the column: before the fix the column could only be set by an LLM tool
    call, so this list was empty for every real user.
    """
    _set_incomplete_row(uid)
    assert uid not in tenant_registry.list_pipeline_user_ids()

    profile_repository.mark_onboarding_complete(uid)

    assert uid in tenant_registry.list_pipeline_user_ids()
