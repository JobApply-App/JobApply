"""
How Ariel addresses the user in Hebrew, and how she changes it.

The form (cv_hebrew_gender: m / f / n) is saved at signup from the gender
answer, or later by Ariel's set_addressing_form tool; the same value sets the
wording of Hebrew CVs. These tests stub the answer store, so they need no DB.
"""

from backend.agents import ariel_tools
from backend.api.routes import chat
from backend.repositories import profile_repository


def _stub_answers(monkeypatch, answers: dict) -> dict:
    monkeypatch.setattr(profile_repository, "get_answer", lambda uid, key: answers.get(key))
    monkeypatch.setattr(profile_repository, "set_answer", lambda uid, key, value: answers.__setitem__(key, value))
    return answers


def test_no_form_saved_means_no_block(monkeypatch):
    _stub_answers(monkeypatch, {})
    assert chat._ariel_addressing_note("u1") == ""


def test_feminine_form_is_followed(monkeypatch):
    _stub_answers(monkeypatch, {"cv_hebrew_gender": "f", "gender": "female"})
    note = chat._ariel_addressing_note("u1")
    assert note.startswith("<AddressingForm>")
    assert "feminine" in note
    assert "default" not in note


def test_unspecified_gender_is_marked_as_a_default(monkeypatch):
    _stub_answers(monkeypatch, {"cv_hebrew_gender": "m", "gender": "unspecified"})
    note = chat._ariel_addressing_note("u1")
    assert "masculine" in note
    assert "default" in note


def test_neutral_form_addresses_in_plural(monkeypatch):
    _stub_answers(monkeypatch, {"cv_hebrew_gender": "n"})
    assert "plural" in chat._ariel_addressing_note("u1")


def test_tool_saves_the_form_cvs_read(monkeypatch):
    answers = _stub_answers(monkeypatch, {"cv_hebrew_gender": "m"})
    result = ariel_tools.execute_tool("set_addressing_form", {"form": "n"}, "u1", session=None)
    assert answers["cv_hebrew_gender"] == "n"
    assert "saved" in result


def test_tool_rejects_an_unknown_form(monkeypatch):
    answers = _stub_answers(monkeypatch, {"cv_hebrew_gender": "m"})
    result = ariel_tools.execute_tool("set_addressing_form", {"form": "x"}, "u1", session=None)
    assert result.startswith("error")
    assert answers["cv_hebrew_gender"] == "m"


def test_tool_is_offered_to_the_model():
    assert "set_addressing_form" in {t["name"] for t in ariel_tools.ARIEL_TOOLS}
