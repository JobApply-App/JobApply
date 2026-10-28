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
    assert _gap_ids(uid) == ["core_linkedin"]          # optional, asked once

    # Skipping an optional question is remembered (and saves no fake value).
    assert up.save_user_personal_field(uid, "linkedin", up.SKIP_ANSWER)
    assert _gap_ids(uid) == []
    assert up.get_profile(uid)["personal"]["linkedin"] == ""
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


# ── Gap answers (the LLM's missing_data questions) ───────────────────────────

def test_gap_answers_are_kept_per_user_and_reach_the_next_cv(uid, monkeypatch):
    """
    Answers to tailoring's gap questions went to supplemental_store — one
    process-wide file mixing every user's answers, never read back — so each
    answer served one CV and was lost. They are now stored on the user's
    profile and included in build_full_text(), the profile the agent sees.
    """
    from backend.services import master_profile_service as mps
    from backend.services import supplemental_store

    def _no_global(*_a, **_k):
        raise AssertionError("wrote to the process-wide supplemental store")
    monkeypatch.setattr(supplemental_store, "save", _no_global)

    other = str(uuid.uuid4())
    try:
        mps.merge_answers({"zendesk_experience": "Yes — two years of Zendesk at Acme"}, uid)
        assert "zendesk_experience: Yes — two years of Zendesk at Acme" in up.build_full_text(uid)
        assert "zendesk_experience" not in up.build_full_text(other)
    finally:
        from backend.core.database import ENGINE
        with ENGINE.begin() as c:
            c.execute(text("DELETE FROM public.profiles WHERE id = CAST(:u AS uuid)"), {"u": other})


def test_phone_typed_at_sign_up_reaches_the_profile(uid, monkeypatch):
    """
    Sign-up requires a phone number. It was dropped before reaching Supabase,
    and nothing copied auth metadata into the profile, so tailoring asked for
    the phone again. get_profile now reads the sign-up metadata.
    """
    import json
    from backend.core.database import ENGINE
    monkeypatch.setattr(up, "_metrics_doc_personal", lambda user_id: {})
    with ENGINE.begin() as c:
        c.execute(text(
            "INSERT INTO auth.users (id, raw_user_meta_data) VALUES (CAST(:u AS uuid), CAST(:m AS jsonb)) "
            "ON CONFLICT (id) DO UPDATE SET raw_user_meta_data = EXCLUDED.raw_user_meta_data"
        ), {"u": uid, "m": json.dumps({"full_name": "Ben Cohen", "phone": "+972501234567"})})
    try:
        personal = up.get_profile(uid)["personal"]
        assert personal["phone"] == "+972501234567" and personal["name"] == "Ben Cohen"
        assert "core_phone" not in _gap_ids(uid)
        up.save_user_personal_field(uid, "phone", "052-0000000")   # typed later wins
        assert up.get_profile(uid)["personal"]["phone"] == "052-0000000"
    finally:
        with ENGINE.begin() as c:
            c.execute(text("DELETE FROM auth.users WHERE id = CAST(:u AS uuid)"), {"u": uid})
