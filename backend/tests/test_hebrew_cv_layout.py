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


PROFILE_EDU = [{"degree": "B.A. Business Administration & Digital Innovation",
                "institution": "Reichman University", "dates": "2020 - 2023", "honors": "", "coursework": ""}]


def test_hebrew_cv_keeps_the_models_hebrew_education_wording():
    from backend.agents.tailor import _localized_education
    gen = [{"degree": "תואר ראשון במנהל עסקים וחדשנות דיגיטלית", "institution": "אוניברסיטת רייכמן",
            "dates": "2019 - 2024"}]
    out = _localized_education(PROFILE_EDU, gen)
    assert out[0]["degree"].startswith("תואר ראשון") and out[0]["institution"] == "אוניברסיטת רייכמן"
    assert out[0]["dates"] == "2020 - 2023", "dates always come from the profile"


def test_english_or_mismatched_education_keeps_the_profile():
    from backend.agents.tailor import _localized_education
    english = [{"degree": "BA in Business", "institution": "Reichman", "dates": "2020 - 2023"}]
    assert _localized_education(PROFILE_EDU, english) == PROFILE_EDU
    extra = [{"degree": "תואר ראשון", "institution": "רייכמן"}, {"degree": "תואר שני", "institution": "הרווארד"}]
    assert _localized_education(PROFILE_EDU, extra) == PROFILE_EDU, "an invented extra degree is never used"


def test_hebrew_directive_covers_education():
    from backend.agents.tailor import _output_language_directive
    assert "EDUCATION" in _output_language_directive("he")


def test_hebrew_pages_embed_one_hebrew_font_and_no_italics():
    html = render_html(HE_CV, "t2_modern", user_id="u")
    assert "font-family: 'Heebo'" in html and "data:font/woff2;base64," in html
    assert "font-style: normal !important" in html
    assert "Heebo" not in render_html(EN_CV, "t2_modern", user_id="u"), "English CVs keep their template fonts"


NATIONAL = {**HE_CV, "military_service": {"role_title": "רכזת קליטה בשירות לאומי", "unit_type": "בית חולים שערי צדק",
                                         "dates": "2018 - 2020", "key_responsibilities": ["ליוויתי 40 מתנדבות חדשות."]}}


@pytest.mark.parametrize("template_id", TEMPLATES)
def test_hebrew_summary_heading_is_takzir(template_id):
    html = render_html(HE_CV, template_id, user_id="u")
    assert "תקציר" in html and "תמצית" not in html


DETAILED = {**HE_CV, "military_service": {**HE_CV["military_service"],
                                          "key_responsibilities": ["ניהול חמ״ל של 40 חיילים."]}}


def _order(html, *marks):
    body = html[html.index("<body"):]
    return [body.index(m) for m in marks]


@pytest.mark.parametrize("template_id", TEMPLATES)
def test_service_with_lines_of_its_own_follows_experience(template_id):
    """Founder decision 2026-11-12: service that needs text sits right after
    Experience; how much text it gets is the tailoring model's call per person."""
    html = render_html(DETAILED, template_id, user_id="u")
    exp, mil, edu = _order(html, "ניסיון תעסוקתי", "שירות צבאי", ">השכלה<")
    assert exp < mil < edu
    assert html.count("שירות צבאי") == 1 and "ניהול חמ״ל" in html


@pytest.mark.parametrize("template_id", TEMPLATES)
def test_one_line_service_follows_education(template_id):
    html = render_html(HE_CV, template_id, user_id="u")
    edu, mil = _order(html, ">השכלה<", "שירות צבאי")
    assert edu < mil
    assert html.count("שירות צבאי") == 1 and "קצין מבצעים" in html


@pytest.mark.parametrize("template_id", TEMPLATES)
def test_english_follows_the_same_rule(template_id):
    short = render_html(EN_CV, template_id, user_id="u")
    edu, mil = _order(short, "Education", "Military Service")
    assert edu < mil and short.count("Military Service") == 1
    detailed = render_html({**EN_CV, "military_service": DETAILED["military_service"]}, template_id, user_id="u")
    exp, mil, edu = _order(detailed, "Experience", "Military Service", "Education")
    assert exp < mil < edu


@pytest.mark.parametrize("template_id", TEMPLATES)
def test_national_service_gets_its_own_heading(template_id):
    html = render_html(NATIONAL, template_id, user_id="u")
    assert "שירות לאומי" in html
    assert ">שירות צבאי<" not in html


def test_english_national_service_heading():
    cv = {**EN_CV, "military_service": {"role_title": "National Service volunteer", "unit_type": "Shaare Zedek",
                                         "dates": "2018 - 2020", "key_responsibilities": []}}
    html = render_html(cv, "t1", user_id="u")
    assert "National Service" in html and ">Military Service<" not in html
