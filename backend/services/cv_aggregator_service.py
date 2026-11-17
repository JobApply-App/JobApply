"""
CV Aggregation Service — multi-file text extraction + LLM deduplication.

Public API
----------
    extract_text(content: bytes, filename: str) -> str
    aggregate_cv_claims(texts: list[str], user_id: str) -> dict

The aggregator accepts raw file bytes (PDF or DOCX), extracts plain text,
then passes all combined text through a single LLM call that produces a
structured ``cv_claims`` object:

    {
      "skills":      ["Python", "Product Management", ...],
      "experiences": [
        {
          "company":   "Acme Corp",
          "role":      "Senior PM",
          "start":     "2021",
          "end":       "2024",
          "summary":   "Led a cross-functional team..."
        },
        ...
      ],
      "education":   [
        {
          "degree":      "BA Business Administration",
          "institution": "Reichman University",
          "years":       "2015–2018"
        }
      ],
      "summary":     "Concise professional background paragraph"
    }

The result is intentionally labelled as *claims* — unverified text scraped
from uploaded CVs.  Jonathan uses this as a basis for gap-analysis probing,
not as established fact.
"""
from __future__ import annotations

import io
import json
import logging
import re
from datetime import date
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

from backend.services.llm_client import call_llm

load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=True)
logger = logging.getLogger(__name__)

_MODEL      = "claude-haiku-4-5"
_MAX_TOKENS = 4000   # raised from 2000 — deep multi-role CVs need headroom for full skill arrays

# ── Text extraction ───────────────────────────────────────────────────────────

def extract_text(content: bytes, filename: str) -> str:
    """
    Extract plain text from a PDF or DOCX file given raw bytes.
    Returns an empty string if extraction fails.
    """
    fname = (filename or "").lower()
    if fname.endswith(".pdf"):
        return _extract_pdf(content)
    if fname.endswith(".docx"):
        return _extract_docx(content)
    if fname.endswith(".doc"):
        logger.warning("[cv_aggregator] .doc format is not supported — skip %s", filename)
        return ""
    # Attempt PDF first, fallback to DOCX
    text = _extract_pdf(content)
    if not text.strip():
        text = _extract_docx(content)
    return text


_RTL_RE = re.compile(r'[\u0590-\u05FF\u0600-\u06FF]')
# LTR runs (words, numbers, symbols) separated by spaces
_LTR_RUN_RE = re.compile(
    r'[A-Za-z0-9@#.$%^&*()[\]{}<>\-_|+]+(?:[\s]+[A-Za-z0-9@#.$%^&*()[\]{}<>\-_|+]+)*'
)


def _fix_rtl_visual(text: str) -> str:
    """
    pdfplumber returns Hebrew in visual order (letters reversed). Reverse the
    line, then put the LTR runs inside it (English, numbers, dates) back.
    """
    if not text or not _RTL_RE.search(text):
        return text
    return _LTR_RUN_RE.sub(lambda m: m.group(0)[::-1], text[::-1])


def _char_key(c: dict) -> tuple:
    return (round(c["x0"], 2), round(c["top"], 2), c["text"])


def _center_in(c: dict, boxes) -> bool:
    x = (c["x0"] + c["x1"]) / 2
    y = (c["top"] + c["bottom"]) / 2
    return any(b[0] <= x <= b[2] and b[1] <= y <= b[3] for b in boxes)


def _plumber_page_text(page) -> str:
    """
    One page through pdfplumber. A one-column page goes through the original
    `extract_text(layout=True)` path untouched. A multi-column page (see
    backend/services/pdf_columns.py) is read region by region, each region
    being one column of one band, so a sidebar never shares a line with the
    main column.
    """
    from backend.services import pdf_columns

    regions = None
    try:
        words = page.extract_words(return_chars=True)
        # Rotated words (a sideways "RESUME" down the margin) are decoration
        # on design-tool CVs, and their tall boxes would straddle the columns.
        segments = pdf_columns.build_segments(
            (w["x0"], w["top"], w["x1"], w["bottom"], w["text"], w) for w in words if w.get("upright", True)
        )
        rtl = pdf_columns.page_is_rtl("".join(w["text"] for w in words))
        regions = pdf_columns.reading_regions(segments, rtl)
    except Exception as exc:
        # Column detection is an improvement over the old path, never a
        # reason to lose the page: fall back to reading it as one column.
        logger.warning("[cv_aggregator] column detection failed (%s): %s", type(exc).__name__, exc)

    if not regions:
        text = page.extract_text(layout=True)
        if not text:
            return ""
        return "\n".join(_fix_rtl_visual(line) for line in text.split("\n"))

    chunks = []
    for region in regions:
        # The region's own letters, plus the space glyphs between them (which
        # extract_words leaves out). Letters are matched by identity, not by
        # area, so an overlapping box never pulls in another region's text.
        own = {_char_key(c) for seg in region for w in seg.words for c in w["chars"]}
        boxes = [(seg.x0 - 1, seg.top - 1, seg.x1 + 1, seg.bottom + 1) for seg in region]
        sub = page.filter(lambda o, own=own, boxes=boxes: o.get("object_type") == "char" and (
            _char_key(o) in own
            or (not o["text"].strip() and _center_in(o, boxes))
        ))
        raw = sub.extract_text(layout=True) or ""
        # layout=True pads with the page's blank space around the region;
        # strip it and keep at most one blank line in a row.
        lines = []
        for line in raw.split("\n"):
            line = _fix_rtl_visual(line).strip()
            if line or (lines and lines[-1]):
                lines.append(line)
        chunk = "\n".join(lines).strip()
        if chunk:
            chunks.append(chunk)
    return "\n\n".join(chunks)


def _extract_pdf(content: bytes) -> str:
    try:
        import pdfplumber

        pages_text = []
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            for page in pdf.pages:
                text = _plumber_page_text(page)
                if text:
                    pages_text.append(text)

        text = "\n".join(pages_text).strip()
    except Exception as exc:
        # Not "no text" — the parser failed. Logged as such, and the second
        # extractor below gets its chance.
        logger.warning("[cv_aggregator] pdfplumber failed (%s): %s", type(exc).__name__, exc)
        text = ""
    if text:
        return text
    return _extract_pdf_pymupdf(content)


def _pymupdf_page_text(page) -> str:
    """
    PyMuPDF's default order is the order the design tool drew the text in:
    on Canva exports that is all headings first, then paragraphs, sometimes
    bullets under the wrong job. On a multi-column page each region is read
    on its own, sorted by position. Sorting reverses Hebrew word order on
    Chromium-made PDFs (docs/research/02-ats-systems.md), so right-to-left
    pages keep the default order inside each region.
    """
    import fitz
    from backend.services import pdf_columns

    default = page.get_text()
    try:
        words = page.get_text("words")
        segments = pdf_columns.build_segments((w[0], w[1], w[2], w[3], w[4], w) for w in words)
        rtl = pdf_columns.page_is_rtl(default)
        regions = pdf_columns.reading_regions(segments, rtl)
    except Exception as exc:
        logger.warning("[cv_aggregator] PyMuPDF column detection failed (%s): %s", type(exc).__name__, exc)
        regions = None
    if not regions:
        return default
    chunks = [
        page.get_text(clip=fitz.Rect(*pdf_columns.region_bbox(r)), sort=not rtl).strip()
        for r in regions
    ]
    return "\n\n".join(c for c in chunks if c)


def _extract_pdf_pymupdf(content: bytes) -> str:
    """
    Second PDF extractor. pdfplumber returns nothing on some perfectly valid
    PDFs (certain embedded/CID fonts, some design-tool exports), and every such
    CV was rejected as "a scanned image". PyMuPDF reads many of those.
    """
    try:
        import fitz  # PyMuPDF
        with fitz.open(stream=content, filetype="pdf") as doc:
            text = "\n".join(_pymupdf_page_text(page) for page in doc).strip()
        if text:
            logger.info("[cv_aggregator] pdfplumber found no text; PyMuPDF recovered %d chars", len(text))
        return text
    except Exception as exc:
        logger.warning("[cv_aggregator] PyMuPDF failed (%s): %s", type(exc).__name__, exc)
        return ""


_OCR_PROMPT = (
    "This PDF is a CV (résumé). Transcribe all of its text exactly as written, "
    "in reading order, in its original language. Keep section headings, job "
    "titles, company names, dates and bullet points. Do not summarise, translate, "
    "correct or add anything. If there is no readable text at all, reply with an "
    "empty response."
)


async def ocr_pdf(content: bytes, filename: str, user_id: str) -> str:
    """
    Last resort for a PDF with no text layer — a scan, or a design-tool export
    where the text was turned into shapes. Both LLM providers read PDFs
    directly, so the file is passed as a document block and transcribed.
    User-initiated (a CV upload), so not charged to the background budget.
    Returns "" on any failure, logged.
    """
    import base64
    try:
        result = await call_llm(
            messages=[{
                "role": "user",
                "content": [
                    {"type": "document", "source": {
                        "type": "base64", "media_type": "application/pdf",
                        "data": base64.b64encode(content).decode("ascii"),
                    }},
                    {"type": "text", "text": _OCR_PROMPT},
                ],
            }],
            model      = _MODEL,
            max_tokens = _MAX_TOKENS,
            purpose    = "cv_ocr",
            user_id    = user_id,
        )
        text = (result.text or "").strip()
        logger.info("[cv_aggregator] OCR of %s produced %d chars", filename, len(text))
        return text
    except Exception as exc:
        logger.warning("[cv_aggregator] OCR failed for %s (%s): %s", filename, type(exc).__name__, exc)
        return ""


def _extract_docx(content: bytes) -> str:
    try:
        from docx import Document
        doc   = Document(io.BytesIO(content))
        lines = [para.text for para in doc.paragraphs if para.text.strip()]
        return "\n".join(lines).strip()
    except Exception as exc:
        logger.warning("[cv_aggregator] DOCX extraction failed: %s", exc)
        return ""


# ── LLM aggregation ───────────────────────────────────────────────────────────

# ── Date-Anchor cross-validation ─────────────────────────────────────────────
#
# Rule: explicit, dated job-boundary entries outrank any generic "X+ years"
# summary claims.  If the summary says "5+ years of SaaS experience" but the
# dated experience timeline only sums to 3 years, we treat the generic phrase
# as noise/typo and rewrite it to match the anchored reality.
#
# This prevents seniority inflation penalties caused by CV boilerplate.

_YEARS_CLAIM_RE = re.compile(
    r"(\d+)\s*\+?\s*years?(?:\s+of)?\s+([\w\s\-]+?)(?=\s*experience|\s*in\b|[,\.;]|$)",
    re.IGNORECASE,
)
_CURRENT_YEAR  = date.today().year
_CURRENT_MONTH = date.today().month


def _parse_year_fraction(token: str) -> float | None:
    """
    Return a fractional year from a date token so month-precision boundaries
    are respected.

    Supported formats:
        "2023"          → 2023.0
        "2023-03"       → 2023.167   (March = month 3 → (3-1)/12 = 0.167)
        "2026-02"       → 2026.083   (February)
        "present" / ""  → current year + (current_month - 1) / 12
        "2023-Mar"      → not currently supported → falls back to 2023.0

    Using (month - 1) / 12 anchors the fraction to the *start* of each month,
    which gives the most conservative (never over-inflated) tenure estimate.
    """
    token = token.strip().lower()
    if token in ("present", "current", "now", ""):
        return _CURRENT_YEAR + (_CURRENT_MONTH - 1) / 12

    # YYYY-MM
    m = re.match(r"^(\d{4})[.\-/](\d{1,2})$", token)
    if m:
        year  = int(m.group(1))
        month = max(1, min(12, int(m.group(2))))
        return year + (month - 1) / 12

    # YYYY only
    m = re.match(r"^(\d{4})", token)
    if m:
        return float(m.group(1))

    return None


def _compute_tenure_years(experiences: list[dict]) -> float:
    """
    Sum durations of all dated experience entries using fractional-year arithmetic
    so month-precision boundaries (e.g. "2023-03" → "2026-02") are counted
    correctly.  35 months = 2.917 years, which rounds to 3.
    """
    total = 0.0
    for exp in experiences:
        start = _parse_year_fraction(exp.get("start") or "")
        end   = _parse_year_fraction(exp.get("end")   or "")
        if start is not None and end is not None and end >= start:
            total += end - start
    return total


# Keywords that signal a SaaS / tech environment when found in a role or company name.
_SAAS_SIGNALS = frozenset([
    "saas", "software", "tech", "platform", "app", "digital", "product",
    "startup", "scale-up", "scaleup",
    # Deliberately no company names here: a specific employer in this set
    # classifies one person's history correctly and mis-classifies everyone
    # else's. The generic terms above carry the signal.
])

# Keywords that signal a non-SaaS industry (insurance, finance, events, etc.)
_NON_SAAS_SIGNALS = frozenset([
    "insurance", "pension", "bank", "finance", "financial", "government",
    "nonprofit", "lottery", "hapais", "mifal",
])


def _classify_saas(exp: dict) -> bool:
    """
    Heuristic: return True if the experience entry looks like a SaaS / tech role.

    Checks role title and company name for known signals.  Conservative —
    an entry is only marked SaaS if there is a positive SaaS signal AND no
    strong non-SaaS signal that would override it.
    """
    blob = " ".join([
        (exp.get("company") or ""),
        (exp.get("role") or ""),
        *((exp.get("bullets") or [])[:2]),  # first two bullets for context
    ]).lower()

    has_saas    = any(sig in blob for sig in _SAAS_SIGNALS)
    has_non_saas = any(sig in blob for sig in _NON_SAAS_SIGNALS)

    return has_saas and not has_non_saas


def _compute_domain_tenure(experiences: list[dict], domain_hint: str) -> float:
    """
    Compute years of experience SPECIFICALLY for a domain keyword.

    Strategy:
      1. If domain_hint contains "saas" (case-insensitive), sum only the
         entries classified as SaaS via _classify_saas().
      2. Otherwise fall back to total professional tenure.

    This prevents "5+ years of SaaS experience" from being validated against
    total tenure that includes unrelated insurance/pension roles.
    """
    hint_lower = domain_hint.lower()
    if "saas" in hint_lower or "software" in hint_lower or "tech" in hint_lower:
        relevant = [e for e in experiences if _classify_saas(e)]
        if relevant:
            return _compute_tenure_years(relevant)
    # Fallback: total tenure (conservative)
    return _compute_tenure_years(experiences)


def _cross_validate_experience_claims(claims: dict) -> dict:
    """
    Date-Anchor Overrides Text Rule
    ================================
    After LLM extraction, audit the 'summary' field for "X+ years"
    claims that exceed the years computable from the DOMAIN-SPECIFIC
    dated experience entries.  When a contradiction is found:

      1. Discard the inflated claim (treat as CV boilerplate / typo).
      2. Replace it with the date-anchored figure: "<N> years".
      3. Append "(date-anchored)" so downstream consumers see the correction.

    Key insight: "5+ years of SaaS experience" must be validated against
    ONLY the SaaS-classified experience entries, NOT total professional
    tenure.  A candidate with 3 years SaaS + 3 years insurance has 6 years
    total but only 3 years of SaaS — the summary claim of "5+ SaaS" is
    wrong even though total tenure matches.

    Examples
    --------
    Summary: "5+ years of SaaS experience"
    SaaS timeline: the profile's one SaaS role spans 2023-2025 = 2 years
    Corrected: "2 years of SaaS experience (date-anchored)"
    """
    experiences = claims.get("experiences", [])
    summary     = claims.get("summary", "")
    if not summary or not experiences:
        return claims

    corrected_summary = summary
    made_correction   = False

    for m in _YEARS_CLAIM_RE.finditer(summary):
        stated_years = int(m.group(1))
        domain_hint  = m.group(2).strip()

        # Compute tenure specific to this domain (not global total)
        computed_years = _compute_domain_tenure(experiences, domain_hint)
        if computed_years <= 0:
            continue

        # Correct only when the stated claim meaningfully exceeds the
        # anchored reality (0.5-year tolerance for rounding)
        if stated_years > computed_years + 0.5:
            anchored_years = round(computed_years)  # 2.917 yrs → 3, not floor→2
            old_phrase     = m.group(0).strip()
            # Include "experience" in the replacement only if the original phrase
            # did NOT already contain it (the regex lookahead stops before it).
            # Check if the word "experience" immediately follows old_phrase in summary.
            end_pos      = corrected_summary.find(old_phrase) + len(old_phrase)
            suffix       = corrected_summary[end_pos:end_pos + 12].lstrip()
            has_exp_word = suffix.lower().startswith("experience")
            suffix_str   = "" if has_exp_word else " experience"
            new_phrase   = f"{anchored_years} years of {domain_hint}{suffix_str} (date-anchored)"
            corrected_summary = corrected_summary.replace(old_phrase, new_phrase, 1)
            made_correction   = True
            logger.info(
                "[cv_aggregator] date-anchor override: '%s' → '%s' "
                "(domain=%r, computed=%.1f yrs, stated=%d yrs)",
                old_phrase, new_phrase, domain_hint, computed_years, stated_years,
            )

    if made_correction:
        claims = dict(claims)
        claims["summary"] = corrected_summary

    return claims


_AGGREGATION_SYSTEM = """\
You are a strict information-extraction engine.

You will be given raw text extracted from one or more CV documents.
Your task is to aggregate and deduplicate this information into a single
structured JSON object.

ABSOLUTE RULES:
- Extract ONLY what is explicitly stated in the source text.
- Never invent, infer, or embellish any value.
- If the same company or role appears in multiple CVs with slightly different
  wording, merge them into one entry and keep the most detailed version.
- Skills should be deduplicated (case-insensitive).
- Output ONLY a valid raw JSON object — no markdown, no explanation, no preamble.
- Extract ALL skills present — do not cap or truncate the skills array.
- skill_details.proficiency_level/years_of_experience/last_used_year: same
  never-invent rule as everything else — leave empty/null unless the CV text
  actually supports the value (an explicit level, or dated roles you can
  compute tenure/recency from). A skill merely being listed, with nothing
  else said about it, gets no proficiency_level and null for the other two —
  that is the correct, honest answer, not a gap to fill in.
- Extract ALL functional and industry domains present — do not cap at 2-4;
  emit every distinct domain the candidate has operated in (Ops, Finance,
  Legal, Product, Insurance, SaaS, etc. are all valid separate domains).
- Extract ALL experiences, including cross-functional roles and secondments.
- A degree, diploma, course or certification is EDUCATION, never an
  experience — even when the CV lists it among the jobs.
- Military / national service (IDF, צה"ל, שירות לאומי) IS an experience,
  with "kind": "military". Use the actual role as "role" (e.g. "Software
  Developer", "Operations Clerk") and the unit as "company"; never a rank
  alone. Every other experience has "kind": "job".

DATE-ANCHOR OVERRIDES TEXT RULE (critical):
- When writing the "summary" field, cross-validate any generic "X+ years of
  [domain]" claims against the explicit, dated job entries you are extracting.
- Compute the actual tenure from start/end years in the experience list.
- If a generic summary phrase claims MORE years than the dated timeline
  supports, DISCARD the generic phrase and use the date-anchored figure
  instead.  Example: summary says "5+ years of SaaS experience" but the
  only SaaS role in the experience list is 2023–2025 → write "3 years of
  SaaS experience (2023-2025)" in the summary, not "5+ years".
- Generic boilerplate ("X+ years") is treated as noise when it contradicts
  explicit dates.  Dated job boundaries are ground truth.

CONTACT EXTRACTION (the "personal" block):
- Contact details are frequently in a header, footer, sidebar, or contact bar
  at the very top of the document, often on one line separated by | / • or
  similar. Scan those regions explicitly — do not assume contact info appears
  as a normal labelled section.
- full_name: the candidate's own name. Never a company, employer, school, or
  a referee's name. Usually the largest/first text in the document.
- phone: keep the digits and any leading +country code. Strip spaces, dots,
  dashes, and parentheses (e.g. "(054) 245-9908" -> "+972542459908" only if
  the country code is actually stated; otherwise "0542459908").
- email: the candidate's own address, verbatim.
- linkedin_url: normalize to bare "linkedin.com/in/<handle>" — strip
  https://, www., any trailing slash, and any ?query parameters.
- location: "City, Country" or "City, State" as written. Never a full street
  address, and never an employer's office location.
- Emit "" (empty string) for any contact field not present in the text. Never
  guess, never fabricate, never carry a value over from an employer's details.

OUTPUT SCHEMA (all fields required, use empty list/string/array if not found):
{
  "personal": {
    "full_name":    "candidate's full name, or empty string",
    "phone":        "normalized phone, or empty string",
    "email":        "candidate's email, or empty string",
    "linkedin_url": "linkedin.com/in/handle, or empty string",
    "location":     "City, Country, or empty string"
  },
  "languages": [
    {
      "language": "language name, e.g. Hebrew",
      "level":    "EXACTLY ONE of: Native, Fluent, Professional Working, Limited Working, Elementary"
    }
  ],
  "skills": [
    "exact skill string — emit every distinct skill found, no upper limit"
  ],
  "skill_details": [
    {
      "name": "must exactly match one entry in the skills array above",
      "proficiency_level": "EXACTLY ONE of: beginner, intermediate, advanced, expert — ONLY if the CV states or clearly implies a level (e.g. 'expert in X', '2 years of Y'); empty string if not inferable, never guessed",
      "years_of_experience": "number of years of experience with this specific skill, computed from dated roles that mention it, or null if not determinable",
      "last_used_year": "YYYY integer for the most recent year this skill appears to have been used (e.g. the end year of the most recent role that mentions it), or null if not determinable"
    }
  ],
  "domains": [
    "one high-level professional domain string per distinct domain the candidate
has operated in, e.g. 'Product Management', 'Insurance & Pensions', 'Legal Ops',
'Finance', 'B2B SaaS', 'B2C', 'Data Analytics', 'Operations'. Emit as many as
are genuinely present. These are overarching knowledge domains, NOT individual skills."
  ],
  "experiences": [
    {
      "company":  "exact company name",
      "role":     "exact job title",
      "start":    "YYYY or YYYY-MM or empty string",
      "end":      "YYYY or YYYY-MM or 'present' or empty string",
      "summary":  "1-2 sentence description of responsibilities/achievements",
      "kind":     "job | military"
    }
  ],
  "education": [
    {
      "degree":      "exact degree title",
      "institution": "exact institution name",
      "years":       "YYYY-YYYY or YYYY or empty string"
    }
  ],
  "summary": "2-3 sentence professional background paragraph"
}
"""

_AGGREGATION_USER_TMPL = """\
CV TEXT (combined from {count} file(s)):
---
{combined_text}
---

Extract and aggregate the structured cv_claims JSON now.
"""


async def aggregate_cv_claims(texts: list[str], user_id: str) -> dict:
    """
    Pass combined CV text through the LLM aggregator.

    Returns the structured cv_claims dict. Empty input yields an empty stub;
    an LLM failure or unparseable output raises CvAggregationError.

    It used to return the same empty stub for a failure, which made "the LLM
    was down" indistinguishable from "this document has no CV content in it".
    Callers persisted that stub as the user's cv_data — overwriting a good
    earlier CV with nothing and reporting 200 — so a user whose upload had
    failed was told it succeeded.
    """
    if not texts:
        return _empty_claims()

    # Raised from 4 000 → 12 000 chars per file.
    # A typical multi-role CV is 6 000–10 000 chars; truncating at 4 000
    # silently drops later experience, skills, and entire departments.
    combined = "\n\n--- NEXT CV ---\n\n".join(t[:12_000] for t in texts if t.strip())
    if not combined.strip():
        return _empty_claims()

    user_prompt = _AGGREGATION_USER_TMPL.format(
        count         = len(texts),
        combined_text = combined,
    )

    try:
        result_llm = await call_llm(
            system     = _AGGREGATION_SYSTEM,
            messages   = [{"role": "user", "content": user_prompt}],
            model      = _MODEL,
            max_tokens = _MAX_TOKENS,
            purpose    = "cv_aggregate_claims",
            user_id    = user_id,
        )
        raw    = result_llm.text.strip()
        claims = _parse_json(raw)
        if claims is None:
            raise CvAggregationError("LLM returned output that is not valid JSON")
        # Apply the Date-Anchor Overrides Text rule as a deterministic
        # post-processing pass — catches any inflation the LLM missed.
        claims = _cross_validate_experience_claims(claims)
        # Degrees the model still filed as jobs move to education; army
        # service is tagged (services/cv_entry_kind.py). Deterministic, so it
        # holds even when the model ignores the prompt rule.
        from backend.services.cv_entry_kind import separate_degrees
        claims["experiences"], claims["education"] = separate_degrees(
            claims.get("experiences") or [], claims.get("education") or [],
        )
        # Contact block is normalized deterministically rather than trusted
        # as-emitted — the prompt asks for a canonical shape, this guarantees
        # it (and guarantees the key exists at all for older/partial output).
        claims["personal"] = _normalize_personal(claims.get("personal"))
        return claims
    except CvAggregationError:
        logger.error("[cv_aggregator] unparseable LLM output for user=%s", user_id)
        raise
    except Exception as exc:
        logger.error("[cv_aggregator] LLM aggregation failed for user=%s: %s", user_id, exc)
        raise CvAggregationError(str(exc)) from exc


class CvAggregationError(Exception):
    """The LLM could not turn the CV text into claims (call failed or bad output)."""


def claims_have_cv_content(claims: dict) -> bool:
    """
    True when the extraction found anything a CV is made of.

    A document with no experiences, no skills and no education is not a CV —
    in production this was a Bar Association regulations PDF. Persisting its
    empty claims would replace the user's real CV data with nothing.
    """
    return any(claims.get(k) for k in ("experiences", "skills", "education"))


def _parse_json(raw: str) -> Optional[dict]:
    text = re.sub(r"```(?:json)?", "", raw).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end   = text.rfind("}")
        if start != -1 and end != -1:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                pass
    return None


def _empty_personal() -> dict:
    return {"full_name": "", "phone": "", "email": "", "linkedin_url": "", "location": ""}


def _empty_claims() -> dict:
    return {
        "personal":    _empty_personal(),
        "languages":   [],
        "skills":      [],
        "skill_details": [],
        "domains":     [],
        "experiences": [],
        "education":   [],
        "summary":     "",
    }


_LINKEDIN_RE = re.compile(r"(?:https?://)?(?:[a-z]{2,3}\.)?(?:www\.)?linkedin\.com/in/([^/?\s]+)", re.I)


def _normalize_linkedin(value: str) -> str:
    """Bare 'linkedin.com/in/<handle>' — strips scheme, www/locale subdomain,
    trailing slash, and query params, whatever shape the LLM echoed back."""
    text = str(value or "").strip()
    if not text:
        return ""
    match = _LINKEDIN_RE.search(text)
    return f"linkedin.com/in/{match.group(1)}" if match else text.rstrip("/")


def _normalize_phone(value: str) -> str:
    """Strip formatting punctuation, preserving a leading + country code.
    Never invents a country code the source text didn't state."""
    text = str(value or "").strip()
    if not text:
        return ""
    digits = re.sub(r"[^\d]", "", text)
    return f"+{digits}" if text.lstrip().startswith("+") and digits else digits


def _normalize_personal(raw: object) -> dict:
    """Coerce the LLM's `personal` block into the fixed 5-key contact shape."""
    personal = raw if isinstance(raw, dict) else {}
    return {
        "full_name":    str(personal.get("full_name", "") or "").strip(),
        "phone":        _normalize_phone(personal.get("phone", "")),
        "email":        str(personal.get("email", "") or "").strip(),
        "linkedin_url": _normalize_linkedin(personal.get("linkedin_url", "")),
        "location":     str(personal.get("location", "") or "").strip(),
    }
