"""
A Hebrew CV rendered in the English layout: left-to-right, "PROFESSIONAL
SUMMARY" / "EXPERIENCE" headings over Hebrew text, and every line's
punctuation on the wrong side (founder's export, 2026-10-29). The page now
takes lang/dir and its headings from the CV's language, detected from the
CV's own prose.
"""
import pytest

import backend.services.pdf_builder as pb
from backend.services.pdf_builder import TEMPLATE_REGISTRY, detect_cv_locale, render_html

CONTACT = {"name": "רון מורים", "email": "ron@example.com", "phone": "054-0000000",
           "linkedin": "https://www.linkedin.com/in/ron-morim/", "location": "תל אביב"}

HE_CV = {
    "header": {"target_title": "מנהל הצלחת לקוחות"},
    "summary": "מנהל Customer Success עם רקע מוכח בניהול תיקי לקוחות של מעל 1,000 חשבונות B2B SaaS.",
    "experience": [{"role": "ראש צוות הצלחת לקוחות", "company": "GO-OUT", "dates": "2023 - 2026",
                    "bullets": ["הובלתי צוות של 12 עובדים בפריסה בינלאומית.",
                                "ניהלתי ממשק API עם צוותי הפיתוח."]}],
    "education": [{"degree": "B.A. Business Administration", "institution": "Reichman University", "dates": "2020 - 2023"}],
    "skills": {"categories": [{"label": "כישורי ליבה", "items": ["ניהול לקוחות", "Jira"]}]},
    "languages": [{"language": "Hebrew", "level": "Native"}, {"language": "English", "level": "Fluent"}],
    "military_service": {"role_title": "קצין מבצעים", "unit_type": "חיל הקשר", "dates": "2017 - 2020",
                         "key_responsibilities": []},
}
EN_CV = {**HE_CV, "summary": "Customer Success manager with 1,000+ B2B SaaS accounts.",
         "experience": [{"role": "Team Lead", "company": "GO-OUT", "dates": "2023 - 2026",
                         "bullets": ["Led a team of 12 across three countries."]}]}

TEMPLATES = [t["id"] for t in TEMPLATE_REGISTRY] + [None]   # None = the legacy fallback


@pytest.fixture(autouse=True)
def _contact(monkeypatch):
    monkeypatch.setattr(pb, "_load_contact", lambda uid: dict(CONTACT))


def test_language_is_read_from_the_cvs_own_prose():
    assert detect_cv_locale(HE_CV) == "he"
    assert detect_cv_locale(EN_CV) == "en"


@pytest.mark.parametrize("template_id", TEMPLATES)
def test_hebrew_cv_renders_right_to_left_with_hebrew_headings(template_id):
    html = render_html(HE_CV, template_id, user_id="u")
    assert 'lang="he" dir="rtl"' in html
    for heading in ("ניסיון תעסוקתי", "השכלה", "כישורים", "שפות", "שירות צבאי"):
        assert heading in html, heading
    for english in (">Experience<", ">Education<", ">Skills<", ">Military Service<", ">Languages<"):
        assert english not in html, english
    assert "שפת אם" in html and "עברית" in html     # fixed vocabulary translated


@pytest.mark.parametrize("template_id", TEMPLATES)
def test_english_cv_is_unchanged(template_id):
    html = render_html(EN_CV, template_id, user_id="u")
    assert 'lang="en" dir="ltr"' in html
    assert "Experience" in html and "Education" in html
    assert "{{" not in html


def test_an_explicit_locale_wins_over_detection():
    assert 'dir="rtl"' in render_html(EN_CV, "t2_modern", user_id="u", cv_locale="he")


def test_hebrew_directive_translates_titles_and_keeps_proper_nouns():
    from backend.agents.tailor import _output_language_directive
    d = _output_language_directive("he")
    assert "every role title" in d and "skill category label" in d
    assert "Jira" in d and "company" in d          # proper nouns stay as they are
    assert _output_language_directive("en") == ""
