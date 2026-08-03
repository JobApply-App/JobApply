"""
Recruiter email parser — AI-powered classification service.

parse_recruiter_email(subject, body) -> ParsedEmail

Calls Claude to extract:
  - company_name : canonical employer name
  - mapped_status: one of the six canonical pipeline stages,
                   or "Unknown" if the intent is ambiguous

The function is intentionally narrow: it ONLY classifies emails from
recruiters updating a candidate on their application status.  Unrelated
emails (newsletters, auto-replies, etc.) produce status "Unknown".

Status taxonomy returned by the LLM must match _VALID_STATUSES exactly.
Any deviation causes the response to be treated as "Unknown" so the DB
is never accidentally mutated by a hallucinated status string.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Optional, TypedDict

from dotenv import load_dotenv

from backend.services.llm_client import call_llm, LLMCallError
from backend.services.llm_validation import harden_system_prompt, sanitize_text

load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=True)

logger = logging.getLogger(__name__)

# ── Model config ───────────────────────────────────────────────────────────────
# Haiku is more than sufficient for structured classification; keeps cost low.
_MODEL      = "claude-haiku-4-5"
_MAX_TOKENS = 256

# ── Allowed output values ──────────────────────────────────────────────────────
_VALID_STATUSES: frozenset[str] = frozenset({
    "Phone Screen",
    "Technical",
    "Interview",
    "Offer",
    "Rejected",
    "Unknown",
})

# ── DB status string for each parsed stage ────────────────────────────────────
# These are the values written directly to ApplicationRow.status /
# user_job_matches.status. They match the stage keys used by the analytics funnel.
STATUS_TO_DB: dict[str, str] = {
    "Phone Screen": "phone screen",
    "Technical":    "technical",
    "Interview":    "interview",
    "Offer":        "offer",
    "Rejected":     "rejected",
}

_SYSTEM_PROMPT = """\
You are a structured data extractor for a job-search automation system.

Your sole job: read the recruiter email provided and extract two fields,
then return them as a JSON object — nothing else, no markdown, no prose.

JSON schema (return exactly this structure):
{
  "company_name": "<canonical employer name, e.g. 'Google' not 'Google LLC Careers'>",
  "mapped_status": "<one of: Phone Screen | Technical | Interview | Offer | Rejected | Unknown>"
}

STATUS DECISION RULES
─────────────────────
Phone Screen  — recruiter reaching out to schedule a first call or phone interview.
Technical     — invitation for a take-home test, coding challenge, or technical screen.
Interview     — invitation for an on-site, video, or panel interview (not first phone call).
Offer         — job offer extended (compensation, start date, or contract attached).
Rejected      — application declined, position filled, or "not moving forward" message.
Unknown       — email is ambiguous, unrelated (newsletter, OOO), or cannot be classified.

RULES
─────
• Return ONLY the JSON object. No other text before or after it.
• company_name must be the clean legal/brand name of the hiring company —
  strip suffixes like "Careers", "Recruiting", "HR", "LLC", "Inc.", "Ltd."
• If the company cannot be identified, set company_name to null.
• If status is ambiguous, set mapped_status to "Unknown".
• Do NOT invent a status. When in doubt: "Unknown".
"""


class ParsedEmail(TypedDict):
    company_name:  Optional[str]
    mapped_status: str           # one of _VALID_STATUSES
    db_status:     Optional[str] # STATUS_TO_DB value, or None for Unknown


async def parse_recruiter_email(subject: str, body: str) -> ParsedEmail:
    """
    Classify a recruiter email and return the structured result.

    Returns a ParsedEmail with:
      company_name  — employer name extracted by the LLM (may be None)
      mapped_status — one of _VALID_STATUSES
      db_status     — the string to write to ApplicationRow.status,
                      or None when mapped_status == "Unknown"

    Never raises: LLM or parse failures produce mapped_status="Unknown"
    and db_status=None so callers need no special error handling.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        logger.error("[email_parser] ANTHROPIC_API_KEY not set — skipping parse")
        return ParsedEmail(company_name=None, mapped_status="Unknown", db_status=None)

    # Defense in depth: the webhook route sanitizes before calling us, but any
    # future caller must get the same treatment — untrusted email text goes
    # through sanitize_text() before it is formatted into the prompt.
    user_msg = (
        f"Subject: {sanitize_text(subject.strip())}\n\n"
        f"Body:\n{sanitize_text(body.strip())[:3000]}"   # cap at 3 000 chars — more than enough
    )

    try:
        result_llm = await call_llm(
            system     = harden_system_prompt(_SYSTEM_PROMPT),
            messages   = [{"role": "user", "content": user_msg}],
            model      = _MODEL,
            max_tokens = _MAX_TOKENS,
            purpose    = "email_parse_recruiter",
        )
    except LLMCallError as exc:
        logger.exception("[email_parser] API call failed: %s", exc)
        return ParsedEmail(company_name=None, mapped_status="Unknown", db_status=None)

    raw = result_llm.text.strip()

    # Strip optional markdown fences
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("[email_parser] non-JSON response: %r", raw[:200])
        return ParsedEmail(company_name=None, mapped_status="Unknown", db_status=None)

    company_name  = parsed.get("company_name") or None
    mapped_status = str(parsed.get("mapped_status", "Unknown")).strip()

    # Guard: reject any value not in the strict allowed set
    if mapped_status not in _VALID_STATUSES:
        logger.warning(
            "[email_parser] LLM returned invalid status %r — treating as Unknown",
            mapped_status,
        )
        mapped_status = "Unknown"

    db_status = STATUS_TO_DB.get(mapped_status)   # None for "Unknown"

    logger.info(
        "[email_parser] company=%r  mapped_status=%r  db_status=%r",
        company_name, mapped_status, db_status,
    )
    return ParsedEmail(
        company_name=company_name,
        mapped_status=mapped_status,
        db_status=db_status,
    )
