"""
"Ariel's analysis" on a job card is written in the user's interface language.

fit_brief and the gap list are shown verbatim on the card. The scoring
prompt never named a language, so Hebrew users got English — read by testers
as "switching to Hebrew doesn't translate everything".
"""
from backend.repositories import profile_repository
from backend.services import match_score_service as svc


def _locale(monkeypatch, value):
    monkeypatch.setattr(profile_repository, "get_locales", lambda user_id: {"ui_locale": value, "cv_locale": None})


def test_hebrew_ui_asks_for_hebrew_values(monkeypatch):
    _locale(monkeypatch, "he")
    note = svc._output_language_note("00000000-0000-0000-0000-000000000001")
    assert "Hebrew" in note and "Keys stay English" in note


def test_english_or_unset_ui_adds_nothing(monkeypatch):
    _locale(monkeypatch, "en")
    assert svc._output_language_note("00000000-0000-0000-0000-000000000001") == ""
    _locale(monkeypatch, None)
    assert svc._output_language_note("00000000-0000-0000-0000-000000000001") == ""


def test_unreadable_preference_falls_back_to_english(monkeypatch):
    def _boom(user_id):
        raise profile_repository.LocalesUnavailable("db down")
    monkeypatch.setattr(profile_repository, "get_locales", _boom)
    assert svc._output_language_note("00000000-0000-0000-0000-000000000001") == ""


def test_template_renders_with_the_note():
    out = svc._LLM_SCORER_TEMPLATE.format(
        output_language_note="\nOUTPUT LANGUAGE: Hebrew\n", job_title="PM", company_name="Acme",
        jd_excerpt="jd", cv_summary="s", cv_skills="k", cv_experience="e", company_legacy_note="",
    )
    assert "OUTPUT LANGUAGE: Hebrew" in out and '"fit_brief"' in out
