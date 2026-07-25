"""
Profile Analyzer Agent — Investigator V4
Extracts high-fidelity UserProfile objects from raw CV text + chat context,
and structured JobAnalysis objects from raw job postings.

Robustness contract:
- _parse_json() never raises on truncated output; it repairs and retries first.
- Field mapping is validated against the real Pydantic models before returning.
- All Claude calls use explicit JSON-only system prompts.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Literal

import anthropic
import fitz  # PyMuPDF
from dotenv import load_dotenv

from backend.schemas.job import JobAnalysis, RawJobPosting
from backend.schemas.user import UserProfile

load_dotenv(override=True)

logger = logging.getLogger(__name__)

# ── Valid seniority levels (must match JobAnalysis Literal) ───────────────────
_SENIORITY_LEVELS = ("junior", "mid", "senior", "staff", "principal")

# ── System prompts ─────────────────────────────────────────────────────────────

_PROFILE_SYSTEM_PROMPT = """\
Return ONLY raw JSON, no conversational filler, no markdown blocks.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
BILINGUAL & RTL PROCESSING (HEBREW/ENGLISH)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
You must seamlessly comprehend mixed syntax, such as Hebrew sentences containing English technical terms or acronyms, without losing context or introducing translation artifacts.
Regardless of the input language (Hebrew, English, or mixed), all returned JSON structures MUST use English keys exclusively. Values may be in the source language, but keys must always be English.

Extract a structured candidate profile from the CV text and optional chat context.
Return this exact JSON shape — every key is required:

{
  "skills": ["<skill>", ...],
  "years_of_experience": <int>,
  "seniority_level": "<junior|mid|senior|staff|principal>",
  "preferred_locations": ["<city or country>", ...],
  "salary_target_min": <int in USD/year, or null>,
  "salary_target_max": <int in USD/year, or null>,
  "open_to_remote": <true|false>,
  "summary": "<2-3 sentence professional summary>"
}

Extraction rules:
- skills: every technical and domain skill found anywhere in the document; deduplicate.
- years_of_experience: total professional years; compute from date ranges if present.
- seniority_level: infer from actual responsibilities and scope, not from job title alone.
- preferred_locations: only from explicit mentions; empty list [] if none found.
- salary figures: annual USD; null if not mentioned anywhere.
- open_to_remote: true if the candidate mentions remote, hybrid, or flexible; false only if explicitly office-only.
- summary: synthesise the candidate's career arc and core strengths; do not repeat the CV verbatim.
"""

_POSTING_SYSTEM_PROMPT = """\
Return ONLY raw JSON, no conversational filler, no markdown blocks.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
BILINGUAL & RTL PROCESSING (HEBREW/ENGLISH)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
You must seamlessly comprehend mixed syntax, such as Hebrew sentences containing English technical terms or acronyms, without losing context or introducing translation artifacts.
Regardless of the input language (Hebrew, English, or mixed), all returned JSON structures MUST use English keys exclusively. Values may be in the source language, but keys must always be English.

Extract a structured job analysis from the job posting text.
Return this exact JSON shape — every key is required:

{
  "required_skills": ["<skill>", ...],
  "nice_to_have_skills": ["<skill>", ...],
  "seniority_level": "<junior|mid|senior|staff|principal>",
  "is_remote": <true|false>,
  "location": "<city, country — or 'Remote'>",
  "salary_min": <int in USD/year, or null>,
  "salary_max": <int in USD/year, or null>,
  "summary": "<2-3 sentence summary of the role and its core purpose>"
}

Extraction rules:
- required_skills: skills explicitly marked as required, must-have, or core.
- nice_to_have_skills: skills marked as preferred, bonus, or nice-to-have; empty list [] if none.
- seniority_level: map to the closest of junior/mid/senior/staff/principal.
- is_remote: true only if fully remote is offered; false for hybrid or on-site.
- salary figures: annual USD; null if not stated.
- summary: role purpose, not a restatement of requirements.
"""


# ── JSON parsing & repair ──────────────────────────────────────────────────────

def _repair_truncated_json(text: str) -> str:
    """
    Attempt to close a truncated JSON string by:
    1. Tracking open brackets/braces via a stack (skipping string contents).
    2. Closing any unterminated string literal.
    3. Stripping a trailing comma that would be left before a closing bracket.
    4. Appending the missing closing characters in reverse-open order.
    """
    stack: list[str] = []
    in_string = False
    escape_next = False

    for ch in text:
        if escape_next:
            escape_next = False
            continue
        if ch == "\\" and in_string:
            escape_next = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch in ("{", "["):
            stack.append("}" if ch == "{" else "]")
        elif ch in ("}", "]"):
            if stack and stack[-1] == ch:
                stack.pop()

    # Close any open string
    if in_string:
        text += '"'

    # Drop trailing comma that would be illegal before a closing bracket
    stripped = text.rstrip()
    if stripped.endswith(","):
        text = stripped[:-1]

    # Close every unclosed container
    text += "".join(reversed(stack))
    return text


def _parse_json(raw_text: str) -> dict:
    """
    Robustly extract a JSON object from Claude's raw output.

    Pass 1 — strip markdown fences if present, then try json.loads().
    Pass 2 — run _repair_truncated_json() and retry.
    Raises json.JSONDecodeError only if both passes fail (logged first).
    """
    text = raw_text.strip()

    # Strip opening/closing markdown fence (```json ... ``` or ``` ... ```)
    if text.startswith("```"):
        lines = text.splitlines()
        # Drop first line (``` or ```json)
        lines = lines[1:]
        # Drop last line if it's a closing fence
        while lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    # Pass 1: clean parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Pass 2: repair and retry
    repaired = _repair_truncated_json(text)
    try:
        result = json.loads(repaired)
        logger.warning("_parse_json: used truncation repair (response was likely cut off)")
        return result
    except json.JSONDecodeError as exc:
        logger.error(
            "_parse_json: both passes failed.\n"
            "  Error   : %s\n"
            "  Original: %.300s\n"
            "  Repaired: %.300s",
            exc, raw_text, repaired,
        )
        raise


# ── Safe coercion helpers ──────────────────────────────────────────────────────
# payload.get("key", default) returns None when the key IS present but Claude
# wrote `null`. These helpers treat None and missing as equivalent, making
# every field assignment null-safe without cluttering the call sites.

def _coerce_str(value: object, default: str = "") -> str:
    """Return str(value), or default when value is None / empty."""
    return str(value) if value is not None else default

def _coerce_list(value: object, default: list | None = None) -> list:
    """Return value unchanged when it is a list; otherwise return default."""
    return value if isinstance(value, list) else (default if default is not None else [])

def _coerce_int(value: object, default: int = 0) -> int:
    """Return int(value) when convertible; otherwise return default."""
    if value is None:
        return default
    try:
        return int(value)
    except (ValueError, TypeError):
        logger.warning("_coerce_int: could not convert %r to int — using %d", value, default)
        return default

def _coerce_optional_int(value: object) -> int | None:
    """Return int(value), or None when value is None or not numeric."""
    if value is None:
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        logger.warning("_coerce_optional_int: could not convert %r — using None", value)
        return None

def _coerce_bool(value: object, default: bool = False) -> bool:
    """Return bool(value), or default when value is None."""
    return default if value is None else bool(value)


# ── Config ─────────────────────────────────────────────────────────────────────

@dataclass
class AnalyzerConfig:
    model: str = "claude-sonnet-4-6"
    max_tokens_profile: int = 4096   # generous — long CVs produce verbose JSON
    max_tokens_posting: int = 1024   # posting analysis output is compact


# ── Agent ──────────────────────────────────────────────────────────────────────

class ProfileAnalyzerAgent:
    """
    Extracts structured profiles and job analyses from unstructured text.

    Usage:
        agent = ProfileAnalyzerAgent()
        cv_text  = agent.extract_text_from_pdf("path/to/cv.pdf")
        profile  = await agent.analyze_profile(cv_text, chat_context="...")
        analysis = await agent.analyze_posting(raw_posting)
    """

    def __init__(self, config: AnalyzerConfig | None = None) -> None:
        self.config = config or AnalyzerConfig()
        self._client = anthropic.AsyncAnthropic(
            api_key=os.getenv("ANTHROPIC_API_KEY")
        )

    # ── PDF extraction ─────────────────────────────────────────────────────────

    def extract_text_from_pdf(self, pdf_path: str) -> str:
        """
        Extract all text from a PDF using PyMuPDF.
        Returns an empty string (never raises) when the file is missing or corrupt.
        """
        if not os.path.exists(pdf_path):
            logger.warning("extract_text_from_pdf: file not found — %s", pdf_path)
            return ""
        try:
            import pdfplumber
            import re

            def fix_rtl_visual(text: str) -> str:
                if not text:
                    return text
                if not re.search(r'[\u0590-\u05FF\u0600-\u06FF]', text):
                    return text
                rev = text[::-1]
                def re_rev(m):
                    return m.group(0)[::-1]
                ltr_pattern = r'[A-Za-z0-9@#.$%^&*()[\]{}<>\-_|+]+(?:[\s]+[A-Za-z0-9@#.$%^&*()[\]{}<>\-_|+]+)*'
                return re.sub(ltr_pattern, re_rev, rev)

            pages_text = []
            with pdfplumber.open(pdf_path) as pdf:
                for page in pdf.pages:
                    text = page.extract_text(layout=True)
                    if text:
                        fixed_lines = [fix_rtl_visual(line) for line in text.split('\n')]
                        pages_text.append('\n'.join(fixed_lines))
            
            text = "\n".join(pages_text).strip()
            logger.debug("Extracted %d chars from %s", len(text), pdf_path)
            return text
        except Exception as exc:
            logger.error("extract_text_from_pdf failed for %s: %s", pdf_path, exc)
            return ""

    # ── Profile analysis ───────────────────────────────────────────────────────

    async def analyze_profile(
        self, cv_text: str, chat_context: str = ""
    ) -> UserProfile:
        """
        Fuse CV text and optional chat context into a validated UserProfile.
        """
        context_block = (
            f"\n\nChat context (use to refine preferences and goals):\n{chat_context}"
            if chat_context.strip()
            else ""
        )
        user_message = f"CV text:\n{cv_text}{context_block}\n\nReturn the JSON object now."

        message = await self._client.messages.create(
            model=self.config.model,
            max_tokens=self.config.max_tokens_profile,
            system=_PROFILE_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )

        payload = _parse_json(message.content[0].text)

        # Normalise seniority to a valid value; default to "mid" if unrecognised
        raw_seniority = str(payload.get("seniority_level", "mid")).lower()
        if raw_seniority not in _SENIORITY_LEVELS:
            logger.warning(
                "analyze_profile: unexpected seniority_level %r — defaulting to 'mid'",
                raw_seniority,
            )
            raw_seniority = "mid"

        profile = UserProfile(
            skills=               _coerce_list(payload.get("skills")),
            years_of_experience=  _coerce_int(payload.get("years_of_experience"), default=0),
            seniority_level=      raw_seniority,
            preferred_locations=  _coerce_list(payload.get("preferred_locations")),
            salary_target_min=    _coerce_optional_int(payload.get("salary_target_min")),
            salary_target_max=    _coerce_optional_int(payload.get("salary_target_max")),
            open_to_remote=       _coerce_bool(payload.get("open_to_remote"), default=True),
            summary=              _coerce_str(payload.get("summary")) or None,
        )

        logger.debug(
            "analyze_profile: %d skills, %d yoe, seniority=%s",
            len(profile.skills),
            profile.years_of_experience,
            profile.seniority_level,
        )
        return profile

    # ── Posting analysis ───────────────────────────────────────────────────────

    async def analyze_posting(self, posting: RawJobPosting) -> JobAnalysis:
        """
        Extract a structured JobAnalysis from a raw job posting.
        """
        message = await self._client.messages.create(
            model=self.config.model,
            max_tokens=self.config.max_tokens_posting,
            system=_POSTING_SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Job posting for {posting.title} at {posting.company}:\n\n"
                        f"{posting.raw_text}\n\nReturn the JSON object now."
                    ),
                }
            ],
        )

        payload = _parse_json(message.content[0].text)

        # Clamp seniority to valid Literal values
        raw_seniority = str(payload.get("seniority_level", "mid")).lower()
        if raw_seniority not in _SENIORITY_LEVELS:
            logger.warning(
                "analyze_posting: unexpected seniority_level %r — defaulting to 'mid'",
                raw_seniority,
            )
            raw_seniority = "mid"

        analysis = JobAnalysis(
            job_id=             posting.id,
            required_skills=    _coerce_list(payload.get("required_skills")),
            nice_to_have_skills=_coerce_list(payload.get("nice_to_have_skills")),
            seniority_level=    raw_seniority,  # type: ignore[arg-type]
            is_remote=          _coerce_bool(payload.get("is_remote"), default=False),
            location=           _coerce_str(payload.get("location"), default="Remote / Not Specified"),
            salary_min=         _coerce_optional_int(payload.get("salary_min")),
            salary_max=         _coerce_optional_int(payload.get("salary_max")),
            summary=            _coerce_str(payload.get("summary")),
        )

        logger.debug(
            "analyze_posting: job_id=%s required=%d nice=%d seniority=%s",
            analysis.job_id,
            len(analysis.required_skills),
            len(analysis.nice_to_have_skills),
            analysis.seniority_level,
        )
        return analysis
