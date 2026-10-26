"""
Contact details typed during CV tailoring are saved to that user's profile.

Tailoring asks for a missing phone/location before generating. The answer
was saved by save_personal_field() — a process-wide file and the legacy
single-user USER_PROFILE — so the user's own profile never changed and the
next tailoring asked the same question again, every time. A missing name
was never asked at all, so CVs could go out with no name.
"""
import uuid

import pytest
from sqlalchemy import text

from backend.agents import tailor
from backend.services import user_profile as up


@pytest.fixture()
def uid(db_available):
    from backend.core.database import ENGINE
    u = str(uuid.uuid4())
    yield u
    with ENGINE.begin() as c:
        c.execute(text("DELETE FROM public.profiles WHERE id = CAST(:u AS uuid)"), {"u": u})


def _gap_ids(user_id):
    return [g["id"] for g in tailor._core_profile_gaps(user_id)]


def test_answers_are_saved_per_user_and_not_asked_again(uid, monkeypatch):
    monkeypatch.setattr(up, "_metrics_doc_personal", lambda user_id: {})
    assert set(_gap_ids(uid)) >= {"core_name", "core_phone", "core_location"}

    assert up.save_user_personal_field(uid, "phone", "050-1234567")
    assert up.save_user_personal_field(uid, "location", "Haifa")
    assert up.save_user_personal_field(uid, "name", "Sahar Levi")

    assert _gap_ids(uid) == []
    personal = up.get_profile(uid)["personal"]
    assert (personal["phone"], personal["location"], personal["name"]) == ("050-1234567", "Haifa", "Sahar Levi")


def test_another_users_answer_does_not_leak(uid, monkeypatch):
    monkeypatch.setattr(up, "_metrics_doc_personal", lambda user_id: {})
    other = str(uuid.uuid4())
    up.save_user_personal_field(uid, "phone", "050-1234567")
    assert "core_phone" in _gap_ids(other)
    from backend.core.database import ENGINE
    with ENGINE.begin() as c:
        c.execute(text("DELETE FROM public.profiles WHERE id = CAST(:u AS uuid)"), {"u": other})


def test_unknown_or_blank_fields_are_ignored(uid):
    assert up.save_user_personal_field(uid, "salary", "1") is False
    assert up.save_user_personal_field(uid, "phone", "   ") is False
