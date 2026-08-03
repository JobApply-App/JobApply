"""
RevisionGatekeeper — validates user CV revision requests against hard constraints,
then produces an updated cv_data + regenerated PDF if the request is approved.

Public API
----------
result = await RevisionGatekeeper(user_id).revise(
    revision_text: str,
    cv_data:       dict,
    job:           JobMatch,
) -> GatekeeperResult

GatekeeperResult
    .status    — "approved" | "rejected"
    .message   — rejection reason string (if rejected), empty string (if approved)
    .cv_data   — updated cv_data dict (if approved), None (if rejected)
    .pdf_bytes — regenerated PDF bytes (if approved), None (if rejected)
"""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Optional

from dotenv import load_dotenv

from backend.agents.tailor import _enforce_limits
from backend.services.llm_client import call_llm
from backend.services.pdf_builder import build_pdf
from backend.schemas.job import JobMatch

load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=True)

logger = logging.getLogger(__name__)

_MODEL      = "claude-sonnet-4-6"
_MAX_TOKENS = 3500


# ── Result dataclass ──────────────────────────────────────────────────────────

@dataclass
class GatekeeperResult:
    status:    Literal["approved", "rejected"]
    message:   str        = ""
    cv_data:   Optional[dict]  = field(default=None)
    pdf_bytes: Optional[bytes] = field(default=None)


# ── System prompt ─────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
You are a senior CV editor and page-layout specialist. Your role is to evaluate \
user revision requests for a single-page A4 CV and either apply them or reject \
them with a clear reason.

══════════════════════════════════════════════════════════════
HARD CONSTRAINTS — any request that violates these is REJECTED
══════════════════════════════════════════════════════════════
1. PAGE LIMIT: The CV must remain a single A4 page. The layout has fixed capacity:
   • Experience: max 5 entries, max 4 bullets each, bullets 55–90 chars
   • Summary: max 360 chars (≈3 sentences)
   • Skills: max 4 categories, 6 items each, items ≤25 chars
   • Sidebar sections (Languages, Military, Volunteering) share limited space
   Adding new sections, expanding bullets beyond limits, or adding many new entries
   will push content off the page — REJECT such requests.

2. NO FABRICATION: The CV is grounded exclusively in the candidate's real profile.
   Do NOT add tools, metrics, companies, degrees, certifications, or achievements
   that are not already present in the current cv_data or explicitly named in the
   user's request with a credible, profile-consistent source. Invented content = REJECT.

3. RELEVANCE: Do not remove or weaken bullets/skills that are directly relevant to
   the target job. If the user asks to replace high-signal content with lower-signal
   content, REJECT with an explanation.

4. COMPLETENESS: All required fields must be present. Do not delete entire sections.

══════════════════════════════════════════════════════════════
APPROVAL CRITERIA
══════════════════════════════════════════════════════════════
Approve requests that:
  • Rephrase or sharpen existing bullets
  • Reorder entries or bullets for better emphasis
  • Adjust wording (tone, vocabulary) without inventing new facts
  • Correct factual errors the user points out
  • Swap between existing profile content (move something from lower to higher)
  • Minor additions of tools/skills clearly present in the profile

══════════════════════════════════════════════════════════════
OUTPUT FORMAT — JSON ONLY, no markdown, no extra text
══════════════════════════════════════════════════════════════
If REJECTING:
{{
  "status": "rejected",
  "reason": "<1–2 sentence plain-English explanation starting with 'Request denied:'>",
  "cv_data": null
}}

If APPROVING, return the complete updated cv_data object — every field, including
fields you did not change. Do not omit or summarise unchanged sections:
{{
  "status": "approved",
  "reason": "",
  "cv_data": {{
    "title":        "<string ≤58 chars>",
    "summary":      "<string ≤360 chars, ends with full stop>",
    "experience":   [... complete array ...],
    "education":    [... complete array ...],
    "military":     {{...}},
    "skills":       {{...}},
    "languages":    [...],
    "volunteering": "<string ≤200 chars, ends with full stop>"
  }}
}}
"""


# ── Agent ─────────────────────────────────────────────────────────────────────

class RevisionGatekeeper:
    def __init__(self, user_id: str) -> None:
        """
        user_id scopes the PDF's contact header (name/email/phone/linkedin/
        location) rendered on approval.
        """
        if not os.getenv("ANTHROPIC_API_KEY"):
            raise ValueError("ANTHROPIC_API_KEY not set")
        self.user_id = user_id

    async def revise(
        self,
        revision_text: str,
        cv_data: dict,
        job: JobMatch,
    ) -> GatekeeperResult:
        """
        Evaluate a user revision request and return a GatekeeperResult.

        On approval: applies the revision, enforces limits, regenerates the PDF,
        and returns both the updated cv_data and raw PDF bytes.

        On rejection: returns the rejection reason; cv_data and pdf_bytes are None.
        """
        rationale_block = ""
        if job.scoring_rationale:
            rationale_block = (
                f"\nSCORING_RATIONALE (axis scores — use to judge relevance impact):\n"
                f"{job.scoring_rationale}\n"
            )

        user_msg = (
            f"TARGET JOB: {job.title} @ {job.company}\n"
            f"CATEGORY: {job.category or 'N/A'}\n"
            f"SCORE: {job.score:.1f}\n"
            f"{rationale_block}"
            f"\nCURRENT_CV_DATA (JSON):\n{json.dumps(cv_data, ensure_ascii=False, indent=2)}\n"
            f"\nUSER_REVISION_REQUEST:\n{revision_text.strip()}\n"
            "\nEvaluate the request and respond with the JSON result now."
        )

        logger.info(
            "RevisionGatekeeper → '%s' @ %s  revision_len=%d",
            job.title, job.company, len(revision_text),
        )

        result = await call_llm(
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
            model=_MODEL,
            max_tokens=_MAX_TOKENS,
            temperature=0.0,
            purpose="gatekeeper_revise",
        )

        raw = result.text.strip()
        # Strip markdown fences if the model wraps anyway
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)

        try:
            result = json.loads(raw)
        except json.JSONDecodeError as exc:
            logger.error(
                "RevisionGatekeeper JSON parse error: %s\n--- raw ---\n%s\n---",
                exc, raw,
            )
            # Treat parse failure as a soft rejection rather than a 500
            return GatekeeperResult(
                status="rejected",
                message="Request denied: The revision could not be processed. Please rephrase and try again.",
            )

        status = result.get("status", "rejected")

        if status == "rejected":
            reason = result.get("reason", "Request denied: The revision violates CV constraints.")
            logger.info("RevisionGatekeeper REJECTED: %s", reason)
            return GatekeeperResult(status="rejected", message=reason)

        # ── Approved — apply limits and regenerate PDF ────────────────────────
        updated_cv = result.get("cv_data") or {}
        if not updated_cv:
            return GatekeeperResult(
                status="rejected",
                message="Request denied: The revision produced an empty CV. Please try again.",
            )

        updated_cv = _enforce_limits(updated_cv)
        pdf_bytes  = await build_pdf(updated_cv, user_id=self.user_id)

        logger.info(
            "RevisionGatekeeper APPROVED  title='%s'  pdf=%d bytes",
            updated_cv.get("title", ""), len(pdf_bytes),
        )

        return GatekeeperResult(
            status="approved",
            message="",
            cv_data=updated_cv,
            pdf_bytes=pdf_bytes,
        )
