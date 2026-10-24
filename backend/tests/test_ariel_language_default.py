"""
Ariel defaults to the user's interface language.

A tester on the Hebrew UI got Ariel's first questions in English and then a
switch to Hebrew mid-conversation: the persona only said "reply in the
user's language", and an upload or a short first message gave her nothing to
go on.
"""
from backend.api.routes import chat
from backend.repositories import profile_repository


def _locale(monkeypatch, value):
    monkeypatch.setattr(profile_repository, "get_locales", lambda user_id: {"ui_locale": value, "cv_locale": None})


def test_hebrew_ui_defaults_to_hebrew(monkeypatch):
    _locale(monkeypatch, "he")
    note = chat._ariel_language_note("00000000-0000-0000-0000-000000000001")
    assert "interface language is Hebrew" in note and "first turn" in note


def test_unset_or_unreadable_adds_nothing(monkeypatch):
    _locale(monkeypatch, None)
    assert chat._ariel_language_note("00000000-0000-0000-0000-000000000001") == ""

    def _boom(user_id):
        raise profile_repository.LocalesUnavailable("down")
    monkeypatch.setattr(profile_repository, "get_locales", _boom)
    assert chat._ariel_language_note("00000000-0000-0000-0000-000000000001") == ""


def test_note_is_part_of_the_system_prompt(monkeypatch):
    _locale(monkeypatch, "he")
    monkeypatch.setattr(chat, "get_profile", lambda user_id: {})
    system = chat._build_ariel_system([], "00000000-0000-0000-0000-000000000001")
    assert "<LanguageDefault>" in system and "Hebrew" in system


def test_the_ui_language_sent_by_the_client_wins(monkeypatch):
    _locale(monkeypatch, None)   # nothing stored — most users never toggled
    note = chat._ariel_language_note("00000000-0000-0000-0000-000000000001", "he")
    assert "interface language is Hebrew" in note


def test_an_unknown_client_value_falls_back_to_the_stored_one(monkeypatch):
    _locale(monkeypatch, "en")
    note = chat._ariel_language_note("00000000-0000-0000-0000-000000000001", "xx")
    assert "interface language is English" in note
