"""
Uploaded CVs with a sidebar were read across the page, line by line, so the
sidebar and the main column shared every line (docs/research/06-cv-generation.md,
section 49, "Parsing test": "Innovative and disciplined leader with 2019 -
Present SENIOR OPERATIONS MANAGER" was one extracted line, and in Hebrew a
role lost its dates). `_extract_pdf` now finds the columns and reads each one
top to bottom; a one-column page goes through the old path unchanged.

The PDFs are rendered by Chromium, as design-tool exports and our own
templates are, with the bundled Heebo font so Hebrew renders in CI too.
"""
from __future__ import annotations

import io
from pathlib import Path

import fitz
import pdfplumber
import pytest

from backend.services import cv_aggregator_service as agg
from backend.services import pdf_columns

_FONTS = Path(__file__).resolve().parent.parent / "templates" / "fonts" / "heebo"


# ── Fixtures: small CVs rendered by Chromium ─────────────────────────────────

def _html(lang: str, body: str, extra_css: str = "") -> str:
    d = "rtl" if lang == "he" else "ltr"
    return f"""<!doctype html><html lang="{lang}" dir="{d}"><head><meta charset="utf-8"><style>
@font-face {{ font-family: H; src: url({(_FONTS / 'heebo-hebrew-400-normal.woff2').as_uri()}); }}
@font-face {{ font-family: H; src: url({(_FONTS / 'heebo-latin-400-normal.woff2').as_uri()}); }}
body {{ font-family: H; font-size: 10pt; margin: 0; }}
.hdr {{ text-align: center; padding: 20px; }}
.grid {{ display: grid; grid-template-columns: 32% 1fr; gap: 28px; padding: 0 36px; }}
.side {{ background: #eef; }}
.one {{ padding: 0 48px; }}
h2 {{ font-size: 12pt; margin: 12px 0 4px; }}
p {{ margin: 0 0 4px; }}
.row {{ display: flex; justify-content: space-between; }}
{extra_css}
</style></head><body>{body}</body></html>"""


EN_SIDE = (
    "<h2>PROFILE</h2><p>Innovative and disciplined leader with ten years of experience "
    "running operations teams across three countries.</p>"
    "<h2>SKILLS</h2><p>Budgeting</p><p>Vendor management</p><p>Lean process design</p>"
    "<h2>LANGUAGES</h2><p>English, Hebrew</p>"
)
EN_MAIN = (
    "<h2>WORK EXPERIENCE</h2>"
    "<div class='row'><b>SENIOR OPERATIONS MANAGER</b><span>2019 - Present</span></div><p>Acme Logistics</p>"
    "<p>• Cut fulfilment time by 30% by redesigning the pick and pack flow across two sites.</p>"
    "<p>• Led a team of 40 staff through a warehouse system migration.</p>"
    "<div class='row'><b>OPERATIONS ANALYST</b><span>2015 - 2019</span></div><p>Beta Retail</p>"
    "<p>• Built the weekly capacity model used by every regional manager.</p>"
    "<h2>EDUCATION</h2><div class='row'><b>B.A. Economics</b><span>2011 - 2015</span></div>"
    "<p>Tel Aviv University</p>"
)
EN_HEADER = "<div class='hdr'><b>DANA LEVI</b><br>Operations Manager | dana@example.com</div>"

HE_SIDE = (
    "<h2>פרופיל</h2><p>מנהלת שיווק ודיגיטל בעלת ניסיון של שש שנים בהובלת קמפיינים לחברות טכנולוגיה.</p>"
    "<h2>כישורים</h2><p>ניהול תקציב</p><p>Google Ads</p><p>כתיבה שיווקית</p>"
    "<h2>שפות</h2><p>עברית, אנגלית</p>"
)
HE_MAIN = (
    "<h2>ניסיון תעסוקתי</h2>"
    "<div class='row'><b>מנהלת שיווק ודיגיטל</b><span>2022 - היום</span></div><p>חברת אלפא</p>"
    "<p>• הובלתי צוות של חמישה עובדים בהשקת מוצר חדש בשלוש מדינות.</p>"
    "<p>• הגדלתי את מספר הלידים בתוך שנה.</p>"
    "<div class='row'><b>רכזת תוכן</b><span>2019 - 2022</span></div><p>חברת בטא</p>"
    "<p>• כתבתי את כל תוכן האתר והניוזלטר החודשי.</p>"
    "<h2>השכלה</h2><div class='row'><b>תואר ראשון בתקשורת</b><span>2015 - 2019</span></div>"
    "<p>אוניברסיטת רייכמן</p>"
)
HE_HEADER = "<div class='hdr'><b>מרינה זלוצין</b><br>מנהלת שיווק | marina@example.com</div>"

# One column with dates at the right margin and short lines throughout: the
# dates leave a clean vertical gap, which must not be taken for a gutter.
EN_ONE_COLUMN = EN_HEADER + "<div class='one'>" + EN_SIDE + EN_MAIN.replace(
    "redesigning the pick and pack flow across two sites", "a new pick flow"
).replace("through a warehouse system migration", "") + "</div>"
HE_ONE_COLUMN = HE_HEADER + "<div class='one'>" + HE_SIDE + HE_MAIN + "</div>"

DOCS = {
    "en_two_column": _html("en", EN_HEADER + f"<div class='grid'><div class='side'>{EN_SIDE}</div><div>{EN_MAIN}</div></div>"),
    "he_two_column": _html("he", HE_HEADER + f"<div class='grid'><div class='side'>{HE_SIDE}</div><div>{HE_MAIN}</div></div>"),
    # Sidebar on the right, header inside the main column: the name must still come first.
    "en_right_sidebar": _html("en", f"<div class='grid' style='grid-template-columns:1fr 30%'>"
                                    f"<div>{EN_HEADER}{EN_MAIN}</div><div class='side'>{EN_SIDE}</div></div>"),
    "en_one_column": _html("en", EN_ONE_COLUMN),
    "he_one_column": _html("he", HE_ONE_COLUMN),
}


@pytest.fixture(scope="module")
def pdfs() -> dict[str, bytes]:
    sync_api = pytest.importorskip("playwright.sync_api")
    out = {}
    try:
        with sync_api.sync_playwright() as pw:
            if not Path(pw.chromium.executable_path).exists():
                pytest.skip("Chromium is not installed (python -m playwright install chromium)")
            browser = pw.chromium.launch()
            page = browser.new_page()
            for name, html in DOCS.items():
                page.set_content(html)
                page.evaluate("document.fonts.ready")
                out[name] = page.pdf(format="A4", print_background=True)
            browser.close()
    except sync_api.Error as exc:            # binary present but cannot launch
        pytest.skip(f"Chromium could not start: {exc}")
    return out


# ── Helpers ──────────────────────────────────────────────────────────────────

def _lines(text: str) -> list[str]:
    return [" ".join(l.split()) for l in text.split("\n") if l.strip()]


def _pos(text: str, needle: str) -> int:
    i = text.find(needle)
    assert i >= 0, f"{needle!r} missing from extracted text:\n{text}"
    return i


def _assert_in_order(text: str, *needles: str) -> None:
    """Each needle appears after the previous one (a phrase may also occur earlier)."""
    text = "\n".join(_lines(text))          # layout=True pads with extra spaces
    at = 0
    for n in needles:
        _pos(text, n)
        i = text.find(n, at)
        assert i >= 0, f"{n!r} is not after {needles[:needles.index(n)]}:\n{text}"
        at = i + len(n)


def _assert_no_mixed_line(text: str, side: list[str], main: list[str]) -> None:
    for line in _lines(text):
        s = [w for w in side if w in line]
        m = [w for w in main if w in line]
        assert not (s and m), f"line mixes the columns ({s} + {m}): {line!r}"


def _old_path(pdf_bytes: bytes) -> str:
    """What _extract_pdf returned before column detection existed."""
    pages = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            t = page.extract_text(layout=True)
            if t:
                pages.append("\n".join(agg._fix_rtl_visual(l) for l in t.split("\n")))
    return "\n".join(pages).strip()


def _page_regions(pdf_bytes: bytes):
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        page = pdf.pages[0]
        words = page.extract_words()
        segs = pdf_columns.build_segments((w["x0"], w["top"], w["x1"], w["bottom"], w["text"], None) for w in words)
        return pdf_columns.reading_regions(segs, pdf_columns.page_is_rtl("".join(w["text"] for w in words)))


EN_SIDE_WORDS = ["Innovative", "disciplined", "Budgeting", "Vendor management", "Lean process", "LANGUAGES", "SKILLS"]
EN_MAIN_WORDS = ["SENIOR OPERATIONS", "2019 - Present", "Acme", "fulfilment", "warehouse", "OPERATIONS ANALYST",
                 "Beta Retail", "capacity", "EDUCATION", "Economics", "Tel Aviv University"]
HE_SIDE_WORDS = ["פרופיל", "קמפיינים", "כישורים", "ניהול תקציב", "Google Ads", "כתיבה שיווקית", "שפות"]
HE_MAIN_WORDS = ["ניסיון תעסוקתי", "חברת אלפא", "חמישה עובדים", "הלידים", "רכזת תוכן", "חברת בטא",
                 "הניוזלטר", "השכלה", "בתקשורת", "רייכמן"]


# ── Two columns ──────────────────────────────────────────────────────────────

def test_english_two_column_is_read_column_by_column(pdfs):
    text = agg._extract_pdf(pdfs["en_two_column"])
    _assert_no_mixed_line(text, EN_SIDE_WORDS, EN_MAIN_WORDS)
    _assert_in_order(text, "DANA LEVI", "PROFILE", "Innovative", "SKILLS", "Budgeting", "LANGUAGES",
                     "WORK EXPERIENCE", "SENIOR OPERATIONS MANAGER", "Acme Logistics", "fulfilment",
                     "warehouse", "OPERATIONS ANALYST", "capacity", "EDUCATION", "Tel Aviv University")
    # A role keeps its dates on its own line.
    lines = _lines(text)
    assert any("SENIOR OPERATIONS MANAGER" in l and "2019 - Present" in l for l in lines), text
    assert any("OPERATIONS ANALYST" in l and "2015 - 2019" in l for l in lines), text


def test_the_old_path_did_mix_these_columns(pdfs):
    """Guards the fixture: if it stopped reproducing the bug, the test above would prove nothing."""
    with pytest.raises(AssertionError, match="mixes the columns"):
        _assert_no_mixed_line(_old_path(pdfs["en_two_column"]), EN_SIDE_WORDS, EN_MAIN_WORDS)
    with pytest.raises(AssertionError, match="mixes the columns"):
        _assert_no_mixed_line(_old_path(pdfs["he_two_column"]), HE_SIDE_WORDS, HE_MAIN_WORDS)


def test_hebrew_two_column_reads_the_right_column_first(pdfs):
    text = agg._extract_pdf(pdfs["he_two_column"])
    _assert_no_mixed_line(text, HE_SIDE_WORDS, HE_MAIN_WORDS)
    # In RTL the sidebar (first grid column) is on the right and is read first.
    _assert_in_order(text, "מרינה זלוצין", "פרופיל", "קמפיינים", "כישורים", "שפות",
                     "ניסיון תעסוקתי", "מנהלת שיווק ודיגיטל", "חברת אלפא", "חמישה עובדים",
                     "רכזת תוכן", "חברת בטא", "הניוזלטר", "השכלה", "רייכמן")
    lines = _lines(text)
    # The role and its dates stay on one line.
    role = [l for l in lines if "רכזת תוכן" in l]
    assert role and "2019" in role[0] and "2022" in role[0], text
    # Letters come out in reading order (the existing RTL fix still applies).
    assert "ניהול תקציב" in text and "Google Ads" in text


def test_header_over_the_second_column_is_read_first(pdfs):
    text = agg._extract_pdf(pdfs["en_right_sidebar"])
    _assert_no_mixed_line(text, EN_SIDE_WORDS, EN_MAIN_WORDS)
    _assert_in_order(text, "DANA LEVI", "WORK EXPERIENCE", "EDUCATION", "Tel Aviv University", "PROFILE", "LANGUAGES")


# ── One column: unchanged ────────────────────────────────────────────────────

@pytest.mark.parametrize("name", ["en_one_column", "he_one_column"])
def test_one_column_output_is_unchanged(pdfs, name):
    assert _page_regions(pdfs[name]) is None, "one-column page was taken for columns"
    assert agg._extract_pdf(pdfs[name]) == _old_path(pdfs[name])


def test_one_column_role_keeps_its_right_aligned_date(pdfs):
    lines = _lines(agg._extract_pdf(pdfs["en_one_column"]))
    assert any("SENIOR OPERATIONS MANAGER" in l and "2019 - Present" in l for l in lines)


def test_single_line_pdf_still_extracts():
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "Senior FP&A Analyst at Acme")
    assert "FP&A Analyst" in agg._extract_pdf(doc.tobytes())


# ── PyMuPDF fallback ─────────────────────────────────────────────────────────

def test_pymupdf_fallback_also_reads_columns(pdfs, monkeypatch):
    class _Broken:
        def __enter__(self):
            raise RuntimeError("unsupported font")

        def __exit__(self, *a):
            return False

    monkeypatch.setattr("pdfplumber.open", lambda *a, **k: _Broken())
    text = agg._extract_pdf(pdfs["en_two_column"])
    _assert_no_mixed_line(text, EN_SIDE_WORDS, EN_MAIN_WORDS)
    _assert_in_order(text, "PROFILE", "SKILLS", "LANGUAGES", "WORK EXPERIENCE",
                     "SENIOR OPERATIONS MANAGER", "fulfilment", "OPERATIONS ANALYST", "EDUCATION")


# ── The column finder on its own (no Chromium needed) ────────────────────────

def _w(x0, top, x1, text, h=10.0):
    return (x0, top, x1, top + h, text, None)


def test_dates_at_the_right_margin_are_not_a_column():
    words = []
    y = 50
    for role in range(4):
        words.append(_w(50, y, 200, f"Role{role} Title"))
        words.append(_w(480, y, 545, "2019 - 2023"))
        for b in range(3):
            y += 14
            words.append(_w(60, y, 330, f"bullet {role}.{b} short line of text"))
        y += 24
    segs = pdf_columns.build_segments(words)
    assert pdf_columns.reading_regions(segs, rtl=False) is None


def test_three_columns_are_read_left_to_right():
    words = []
    for col, x in enumerate((40, 230, 420)):
        for line in range(8):
            words.append(_w(x, 60 + line * 13, x + 150, f"c{col} line {line} text text"))
    regions = pdf_columns.reading_regions(pdf_columns.build_segments(words), rtl=False)
    assert regions is not None
    assert [r[0].text.split()[0] for r in regions] == ["c0", "c1", "c2"]
    regions = pdf_columns.reading_regions(pdf_columns.build_segments(words), rtl=True)
    assert [r[0].text.split()[0] for r in regions] == ["c2", "c1", "c0"]
