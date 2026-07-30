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


def _extract_pdf(content: bytes) -> str:
    try:
        import pdfplumber
        import io
        import re

        def fix_rtl_visual(text: str) -> str:
            if not text:
                return text
            # If no Hebrew/Arabic is present, return text as-is
            if not re.search(r'[\u0590-\u05FF\u0600-\u06FF]', text):
                return text
            
            rev = text[::-1]
            def re_rev(m):
                return m.group(0)[::-1]
                
            # Match LTR sequences (words, numbers, symbols) separated by spaces
            ltr_pattern = r'[A-Za-z0-9@#.$%^&*()[\]{}<>\-_|+]+(?:[\s]+[A-Za-z0-9@#.$%^&*()[\]{}<>\-_|+]+)*'
            return re.sub(ltr_pattern, re_rev, rev)

        pages_text = []
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            for page in pdf.pages:
                text = page.extract_text(layout=True)
                if text:
                    # Fix RTL for each line
                    fixed_lines = [fix_rtl_visual(line) for line in text.split('\n')]
                    pages_text.append('\n'.join(fixed_lines))

        return "\n".join(pages_text).strip()
    except Exception as exc:
        logger.warning("[cv_aggregator] PDF extraction failed: %s", exc)
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
    "startup", "scale-up", "scaleup", "go-out", "goout",
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
    SaaS timeline: GO-OUT 2023–2025 = 2 years
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
- Extract ALL functional and industry domains present — do not cap at 2-4;
  emit every distinct domain the candidate has operated in (Ops, Finance,
  Legal, Product, Insurance, SaaS, etc. are all valid separate domains).
- Extract ALL experiences, including cross-functional roles and secondments.

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
      "summary":  "1-2 sentence description of responsibilities/achievements"
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

    Returns the structured cv_claims dict, or a minimal stub if the LLM call
    fails so callers always receive a valid object.
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
        # Apply the Date-Anchor Overrides Text rule as a deterministic
        # post-processing pass — catches any inflation the LLM missed.
        claims = _cross_validate_experience_claims(claims)
        # Contact block is normalized deterministically rather than trusted
        # as-emitted — the prompt asks for a canonical shape, this guarantees
        # it (and guarantees the key exists at all for older/partial output).
        claims["personal"] = _normalize_personal(claims.get("personal"))
        return claims
    except Exception as exc:
        logger.error("[cv_aggregator] LLM aggregation failed for user=%s: %s", user_id, exc)
        return _empty_claims()


def _parse_json(raw: str) -> dict:
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
    return _empty_claims()


def _empty_personal() -> dict:
    return {"full_name": "", "phone": "", "email": "", "linkedin_url": "", "location": ""}


def _empty_claims() -> dict:
    return {
        "personal":    _empty_personal(),
        "languages":   [],
        "skills":      [],
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
