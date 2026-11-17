# Reading multi-column CV uploads: before and after (2026-11-13)

**What changed:** `_extract_pdf` in `backend/services/cv_aggregator_service.py` is the extractor for uploaded CVs, reached from `backend/api/routes/profile.py` and `backend/api/routes/chat.py`. It now finds the columns on each page and reads one column at a time. The logic lives in `backend/services/pdf_columns.py`; the tests are in `backend/tests/test_cv_pdf_columns.py`.

**Why:** the parsing test in `docs/research/06-cv-generation.md`, section 49, showed the problem. On every two-column Canva CV, the sidebar and the main column came out on the same lines, and in Hebrew a role lost its dates. 77% of Canva's templates have more than one column, and so do almost all of its Hebrew ones.

## How it works

1. pdfplumber's words are joined into **segments**: runs of words on one line. A gap wider than about one letter height starts a new segment, so two columns on the same line become two segments.
2. A **gutter** is an x position that few segments cross. It counts only if both sides look like real columns side by side:
   - each side has at least 3 segments and at least 10% of the characters;
   - the two sides overlap vertically;
   - few lines cross between them;
   - most lines on each side sit directly above or below another line on the same side.

   These checks reject the one-column trap: the dates at the right margin of a one-column CV also leave a clean vertical gap.
3. Lines that cross the gutter, such as a centred name or a full-width heading, act as **separators**. Between two separators, the columns are read one after the other: left first, or right first on a Hebrew page. A header that sits above the second column is read first.
4. Each column is searched once more, for three-column pages.
5. **One-column pages take the old path unchanged:** `extract_text(layout=True)` plus the right-to-left fix. If column detection raises an error, the page also falls back to that path.
6. The PyMuPDF fallback, used when pdfplumber finds no text, uses the same regions. On left-to-right pages each region is sorted by position. Hebrew pages keep the default order inside each region, because sorting reverses Hebrew word order on Chromium PDFs (stage 2).
7. The OCR step for scanned PDFs (`ocr_pdf`) is not touched.

## The 8 Canva PDFs from the parsing test, before and after

| PDF | Columns detected | Result |
|---|---|---|
| EN plain (one column) | none | **Byte-identical** to before |
| HE one column | none | **Byte-identical** to before |
| EN corporate sidebar | yes | Sections whole; each role sits on one line with its dates |
| EN creative | yes | Experience, then contact, then About Me and Skills; no mixed lines |
| EN boxed (2 pages) | yes | The contact box no longer runs into the job bullets |
| HE two-column with photo | yes | Profile, skills and contact, then experience; role and dates on one line |
| HE B&W two-column | yes | Profile, education and skills, then contact, then experience; each job's dates stay inside that job |
| EN dark tech | yes | Paragraphs whole; the rotated "RESUME" (formerly "EMUSER") is gone. **Weaker:** see below |

**EN corporate.** Before, one extracted line held both columns:

    Executive  Snapshot  Work  Experience
    Innovative and disciplined leader with 2019 - Present SENIOR OPERATIONS MANAGER
    a proven record of enhancing  Company Name / City

After, the columns are read one at a time:

    Executive Snapshot
    Innovative and disciplined leader with
    a proven record of enhancing
    ...
    Work Experience
    2019 - Present SENIOR OPERATIONS MANAGER
    Company Name / City
    Directed strategic operations, ...

**HE two-column.** Before, the profile text and the experience shared every line:

    מנהלת שיווק ודיגיטל בעלת ניסיון של 6 • - 2022 היום | מנהלת שיווק ודיגיטל
    שנים בבניית אסטרטגיות שיווק, ניהול • בניית והוצאה לפועל של תוכניות שיווק שנתיות

After:

    פרופיל מקצועי
    מנהלת שיווק ודיגיטל בעלת ניסיון של 6
    שנים בבניית אסטרטגיות שיווק, ניהול
    ...
    ניסיון תעסוקתי
    • - 2022 היום | מנהלת שיווק ודיגיטל
    • בניית והוצאה לפועל של תוכניות שיווק שנתיות

## Known limits

- **Label columns:** some templates put each section heading in a narrow column of its own, beside the section. EN dark tech is one; it sets "PROFIL" and "PENGALAMAN" to the left of their text. These headings now come out together as a list before the content. The content itself stays in order.
- **Rotated words are left out on multi-column pages.** On design-tool CVs they are decoration. One-column pages still include them, as before.
- **Date runs in Hebrew** still come out as `- 2022 היום` and `2022 - 2019` (reversed). This comes from the existing right-to-left fix, which this change does not touch, and it happens on one-column pages too.
- A one-column CV whose right margin carries a block of text running several lines could in principle pass the gutter checks. The tests cover the common forms: dates at the margin, with short and with long bullets.
