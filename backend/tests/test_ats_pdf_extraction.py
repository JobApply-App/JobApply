"""
Does the generated PDF survive the only reading that matters — a machine's?

An applicant tracking system does not look at the CV. It extracts the text and
searches it. A resume that is beautiful and unparseable scores zero, and the
candidate never learns why. Since ATS-optimisation is this product's whole
claim, these are contract tests, not cosmetic ones.

The specific defect they lock down: `letter-spacing` above roughly 0.145 x
font-size makes Chromium place glyphs far enough apart that extractors emit
"E X P E R I E N C E" instead of "EXPERIENCE". Four of the five templates
shipped that way, including the default — every section heading in the PDF was
invisible to a keyword search. CLAUDE.md had recorded the symptom
("M I L I T A R Y  S E R V I C E") as a grep footgun without anyone connecting
it to the resumes users were sending to employers.

It survived because the existing PDF test (test_export_pdf_route.py) mocks
build_pdf entirely: it proves the route returns whatever bytes it is handed,
and nothing about what is in them. These tests render for real.
"""
import asyncio
import pytest

pytest.importorskip("playwright", reason="playwright not installed")
fitz = pytest.importorskip("fitz", reason="pymupdf not installed")

from backend.services.pdf_builder import build_pdf, TEMPLATE_REGISTRY  # noqa: E402
import backend.services.pdf_builder as pdf_builder  # noqa: E402


TEMPLATE_IDS = [t["id"] for t in TEMPLATE_REGISTRY]

CONTACT = {
    "name": "Test Candidate", "email": "candidate@example.com",
    "phone": "+972-50-000-0000", "linkedin": "linkedin.com/in/example",
    "location": "Tel Aviv, Israel",
}

CV = {
    "header": {"full_name": "Test Candidate", "target_title": "Customer Success Manager"},
    "summary": "Customer Success professional managing portfolios of 300+ B2B accounts.",
    "experience": [
        {"company": "Northwind Trading", "role": "Customer Success Team Lead",
         "dates": "2023-01 - 2026-02",
         "bullets": ["Led onboarding for 1,000+ B2B client accounts.",
                     "Prevented churn by re-engaging at-risk enterprise accounts."]},
        {"company": "Contoso Insurance", "role": "Financial Referent",
         "dates": "2020-01 - 2023-01",
         "bullets": ["Managed compliance documentation for 800+ client accounts."]},
    ],
    "education": [{"degree": "B.A. Business Administration", "institution": "Reichman University",
                   "dates": "2020-10 - 2023-07", "honors": "Dean's List", "coursework": "SQL, Python"}],
    "military_service": {"role_title": "Clerk to Lieutenant Colonel",
                         "unit_type": "IDF Signal Corps", "dates": "2018-03 - 2020-03",
                         "key_responsibilities": []},
    "skills": {"categories": [
        {"label": "Customer Success", "items": ["Onboarding", "Churn Prevention"]},
        {"label": "Tools", "items": ["Salesforce", "Jira", "SQL"]}]},
    "languages": [{"language": "Hebrew", "level": "Native"},
                  {"language": "English", "level": "Professional"}],
    "volunteering": "",
}


@pytest.fixture(autouse=True)
def _stub_contact(monkeypatch):
    """
    Contact details are read from the user's stored profile, not from cv_data,
    so without this the tests would need a seeded database and would fail for
    a reason that has nothing to do with the PDF.
    """
    monkeypatch.setattr(pdf_builder, "_load_contact", lambda user_id: dict(CONTACT))


def _extract(template_id: str) -> str:
    pdf = asyncio.run(build_pdf(CV, template_id=template_id, user_id="test-user"))
    doc = fitz.open(stream=pdf, filetype="pdf")
    try:
        return "\n".join(page.get_text() for page in doc)
    finally:
        doc.close()


@pytest.mark.parametrize("template_id", TEMPLATE_IDS)
def test_pdf_contains_extractable_text(template_id):
    """A PDF of rendered images extracts nothing and is unreadable to an ATS."""
    text = _extract(template_id)
    assert len(text.strip()) > 200, (
        f"{template_id}: only {len(text.strip())} chars extracted — the PDF may be "
        f"rasterised rather than real text."
    )


@pytest.mark.parametrize("template_id", TEMPLATE_IDS)
def test_section_headings_are_not_letter_spaced(template_id):
    """
    The regression this file exists for.

    Headings are matched as whole words. Asserting on the raw text is the point:
    a heading that extracts as "E X P E R I E N C E" passes any check that
    strips whitespace first, and fails the only one that matters.
    """
    text = _extract(template_id).upper()
    missing = [h for h in ("EXPERIENCE", "EDUCATION", "SKILLS") if h not in text]
    assert not missing, (
        f"{template_id}: section heading(s) {missing} not found in extracted text. "
        f"Most likely letter-spacing exceeds ~0.145 x font-size, so the glyphs "
        f"extract spaced out. Extracted:\n{text[:400]}"
    )


@pytest.mark.parametrize("template_id", TEMPLATE_IDS)
def test_content_keywords_survive_extraction(template_id):
    """Employers, skills and institutions are what a keyword search actually hits."""
    text = _extract(template_id)
    for kw in ("Northwind Trading", "Contoso Insurance", "Salesforce", "Reichman"):
        assert kw in text, f"{template_id}: {kw!r} missing from extracted text"


@pytest.mark.parametrize("template_id", TEMPLATE_IDS)
def test_contact_details_survive_extraction(template_id):
    """
    An unreachable candidate is worse than a low-scoring one. Contact details
    are also the most common casualty of putting them in a PDF header/footer,
    which some extractors drop.
    """
    text = _extract(template_id)
    for field in ("candidate@example.com", "Test Candidate"):
        assert field in text, f"{template_id}: contact detail {field!r} missing"
