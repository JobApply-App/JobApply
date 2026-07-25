"""
OutreachService — generate personalized LinkedIn outreach messages.

Three message types
--------------------
1. CONSULTATION  (Step 1 — "Foot in the Door")
   A short, warm opening message to a Hiring Manager (Director, VP, C-level)
   asking for a 5-minute professional conversation or advice.
   NEVER mentions the job opening or asks for a referral.
   Goal: start a human relationship before revealing intent.

2. ESCALATION    (Step 2 — 24–48 hrs after a positive response)
   A follow-up that transitions the relationship into a referral request.
   Includes a ready-to-forward, 3rd-person executive summary of Ron's fit
   so the manager can forward it internally with zero effort.

3. HEADHUNTER    (Direct recruiter/agency routing)
   Targeted message to agency recruiters (Gotfriends, Nisha, SQLink, etc.)
   Leads with domain expertise, trajectory, and immediate readiness.
   Designed to land in the "place immediately" mental bucket.

All messages are grounded exclusively in USER_PROFILE data.
The LLM is forbidden from inventing experience, metrics, or claims.
"""
from __future__ import annotations

import logging
import os
from backend.utilities.ai_scrubber import clean_ai_text
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv

from backend.services.llm_client import call_llm
from backend.services.user_profile import USER_PROFILE, build_full_text
from backend.services.llm_validation import harden_system_prompt, sanitize_text
import backend.repositories.job_repository as job_store
from backend.schemas.job import RawJobPosting

load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=True)

logger = logging.getLogger(__name__)

_MODEL      = "claude-haiku-4-5"  # fast + cheap for message generation
_MAX_TOKENS = 800

MessageType = Literal["consultation", "escalation", "headhunter"]

# ── System prompt (shared across all types) ───────────────────────────────────

_SYSTEM = """\
You are a senior career strategist who writes highly targeted LinkedIn outreach \
messages for a job candidate.  You write in a natural, confident, human voice — \
never sycophantic, never salesy, never generic.

ABSOLUTE RULES:
• Ground every claim ONLY in the CANDIDATE_PROFILE provided — no invented facts.
• Keep messages concise: consultation ≤ 120 words, escalation ≤ 200 words, \
  headhunter ≤ 160 words.
• Write in first-person for consultation/escalation, third-person for the \
  embedded summary inside escalation messages.
• Output ONLY the raw message text — no subject line, no markdown, no meta-commentary.
• Do NOT use hollow phrases: "I hope this message finds you well", \
  "I am reaching out because...", "I would love to connect".
• Sound like a peer, not a supplicant.
"""

# ── Per-type user prompt templates ────────────────────────────────────────────

_CONSULTATION_TMPL = """\
CANDIDATE_PROFILE:
{profile}

TARGET:
  Name:    {target_name}
  Title:   {target_title}
  Company: {target_company}

CONTEXT (optional, use only if provided):
{context}

TASK — Write a LinkedIn CONSULTATION message (Step 1):
• Mention one genuine, specific thing about their company or role that prompted \
  you to reach out (use TARGET info to make it specific).
• Ask for a brief 5-minute conversation or a piece of advice — frame it as \
  seeking perspective from someone in that domain, NOT asking for a job.
• Reference one credible, relevant piece of Ron's background that earns the \
  ask (e.g. current role, relevant domain, a transition he's making).
• End with a low-friction call to action (e.g. "Happy to work around your schedule").
• Tone: warm, direct, peer-level. Max 120 words.
"""

_ESCALATION_TMPL = """\
CANDIDATE_PROFILE:
{profile}

TARGET:
  Name:    {target_name}
  Title:   {target_title}
  Company: {target_company}

JOB BEING TARGETED (if known):
{job_context}

PRIOR INTERACTION CONTEXT:
{context}

TASK — Write a LinkedIn ESCALATION message (Step 2, sent 24–48 hrs after positive response):
• Open by referencing the prior conversation naturally (without over-explaining it).
• Transition smoothly into expressing interest in the specific open role at their company.
• Include a self-contained 3rd-person EXECUTIVE SUMMARY (2–3 sentences) formatted \
  so the manager can forward it internally as-is. Label it clearly with a line break \
  before it, e.g.: "Here's a quick summary you could share with [your team / the \
  hiring team] if it helps:"
• End with an explicit, low-friction referral ask.
• Total message ≤ 200 words.
"""

_HEADHUNTER_TMPL = """\
CANDIDATE_PROFILE:
{profile}

TARGET RECRUITER:
  Name:    {target_name}
  Agency:  {target_company}
  Focus:   {target_title}

TASK — Write a LinkedIn HEADHUNTER message:
• Lead with domain clarity: state Ron's exact domain (Product / CS & Account Management) \
  and seniority level in the first sentence.
• Highlight the strongest 2 credentials from the profile (e.g. Team Lead at GO-OUT \
  managing 7 people across two countries; Dean's List while working 3 concurrent jobs).
• State immediate readiness and geography explicitly (Israel / Tel Aviv, open to hybrid).
• Invite the recruiter to reach out if they have relevant mandates now or soon.
• Tone: confident, value-first, no begging. Max 160 words.
"""


# ── Core generation function ──────────────────────────────────────────────────

async def generate_outreach_message(
    *,
    message_type:   MessageType,
    target_name:    str,
    target_title:   str,
    target_company: str,
    context:        str = "",
    job_id:         str | None = None,
    user_id:        str,
) -> str:
    """
    Generate a LinkedIn outreach message of the requested type.

    Parameters
    ----------
    message_type   : "consultation" | "escalation" | "headhunter"
    target_name    : Name of the person being messaged.
    target_title   : Their role (e.g. "VP Product", "Head of Talent").
    target_company : Their company or agency name.
    context        : Optional extra context (prior conversation snippet, specific role, notes).
    job_id         : Optional — if set, JD text is fetched and injected into escalation prompts.

    Returns
    -------
    str — the ready-to-send message text.
    """
    profile = build_full_text(user_id)

    # Build job context for escalation messages
    job_context = ""
    if job_id:
        cached = job_store.get_tailored_cv(job_id, user_id)
        if cached:
            job_context = f"Role: {cached.get('job_title', '')} at {cached.get('company', '')}"
        # Try fetching raw job metadata
        try:
            from backend.core.database import ENGINE
            from backend.models.job import JobRow
            from sqlalchemy.orm import Session
            with Session(ENGINE) as s:
                row = s.get(JobRow, job_id)
                if row and row.user_id == user_id:
                    job_context = (
                        f"Role: {row.title} at {row.company}\n"
                        f"Location: {row.location or 'Israel'}\n"
                        f"JD snippet: {sanitize_text((row.jd_text or '')[:400])}"
                    )
        except Exception:
            pass

    # Select and fill the right template
    if message_type == "consultation":
        user_prompt = _CONSULTATION_TMPL.format(
            profile        = profile,
            target_name    = target_name,
            target_title   = target_title,
            target_company = target_company,
            context        = context or "(none provided)",
        )
    elif message_type == "escalation":
        user_prompt = _ESCALATION_TMPL.format(
            profile        = profile,
            target_name    = target_name,
            target_title   = target_title,
            target_company = target_company,
            job_context    = job_context or "(specific role not provided)",
            context        = context or "(describe the prior conversation here)",
        )
    else:  # headhunter
        user_prompt = _HEADHUNTER_TMPL.format(
            profile        = profile,
            target_name    = target_name,
            target_title   = target_title or "Recruiter",
            target_company = target_company,
        )

    result = await call_llm(
        system     = harden_system_prompt(_SYSTEM),
        messages   = [{"role": "user", "content": user_prompt}],
        model      = _MODEL,
        max_tokens = _MAX_TOKENS,
        purpose    = "outreach_message",
        user_id    = user_id,
        job_id     = job_id,
    )

    message = clean_ai_text(result.text).strip()
    logger.info(
        "[OutreachService] Generated %s message for %s @ %s (%d chars)",
        message_type, target_name, target_company, len(message),
    )
    return message


# ═══════════════════════════════════════════════════════════════════════════════
# Phase 3 — job-anchored outreach (tailored-CV-aware, persisted per job)
# ═══════════════════════════════════════════════════════════════════════════════

_OUTREACH_SYSTEM = """\
You write a single, concise outreach message from a job candidate to the hiring \
manager for one specific role. Natural, confident, peer-level voice.

ABSOLUTE RULES:
• Ground EVERY claim ONLY in CANDIDATE_MATERIAL below — never invent employers, \
  titles, metrics, or skills. If the material does not support a claim, omit it.
• Directly map the candidate's real experience to the specific requirements in \
  JOB_DESCRIPTION — name the overlap, don't speak in generalities.
• ≤ 150 words. First person. No subject line.
• Output ONLY the raw message text — no markdown, no preamble, no sign-off block, \
  no "here is your message" wrapper, no options.
• Ban hollow phrases: "I hope this finds you well", "I am reaching out because", \
  "I would love to connect", "perfect fit", "passionate".
"""

_OUTREACH_USER_TMPL = """\
JOB:
  Title:   {title}
  Company: {company}
  Location:{location}

JOB_DESCRIPTION:
{jd_text}

CANDIDATE_MATERIAL (tailored for THIS role where available — the source of truth \
for every claim you may make):
{candidate_material}

TASK — Write one outreach message to the hiring manager for this role that maps \
the candidate's strongest, genuinely-relevant experience to this job's stated \
requirements. Concise, specific, professional.
"""


def _candidate_material(job_id: str, user_id: str) -> str:
    """
    Assemble the grounding material for the outreach, preferring the CV tailored
    to THIS job and falling back to the user's master profile narrative.
    """
    cached = job_store.get_tailored_cv(job_id, user_id)
    brief  = (cached or {}).get("tailor_brief") if isinstance(cached, dict) else None
    if isinstance(brief, dict):
        parts: list[str] = []
        if brief.get("positioning_summary"):
            parts.append(f"Positioning: {brief['positioning_summary']}")
        for sec in brief.get("tailored_sections", []):
            role    = f"{sec.get('role', '')} at {sec.get('company', '')} ({sec.get('dates', '')})".strip()
            bullets = "; ".join(str(b) for b in sec.get("bullets", []))
            parts.append(f"{role}: {bullets}")
        if parts:
            return "TAILORED CV FOR THIS ROLE:\n" + "\n".join(parts)
    # Fallback — master profile narrative (per-user, Phase 2 accessor).
    return "MASTER PROFILE:\n" + build_full_text(user_id)


async def generate_outreach(job_id: str, user_id: str) -> str:
    """
    Generate — and persist — a hiring-manager outreach message for one job.

    Tenancy: every read/write is scoped to user_id. Raises ValueError when the
    job does not exist for this user (the route maps that to HTTP 404).

    Returns the message text (also saved to jobs.outreach_text).
    """
    job = job_store.get_by_id(job_id, user_id)
    if job is None:
        raise ValueError(f"Job {job_id!r} not found.")

    jd_text = (getattr(job, "jd_text", "") or "").strip()
    if not jd_text:
        jd_text = f"(No full description stored — role: {job.title} at {job.company}.)"

    # Sanitize untrusted text (JD + assembled CV material) before it enters the prompt.
    user_prompt = _OUTREACH_USER_TMPL.format(
        title              = job.title,
        company            = job.company,
        location           = job.location or "Israel",
        jd_text            = sanitize_text(jd_text[:4000]),
        candidate_material = sanitize_text(_candidate_material(job_id, user_id)),
    )

    if not os.getenv("ANTHROPIC_API_KEY", ""):
        raise RuntimeError("ANTHROPIC_API_KEY is not set.")

    result = await call_llm(
        system     = harden_system_prompt(_OUTREACH_SYSTEM),
        messages   = [{"role": "user", "content": user_prompt}],
        model      = _MODEL,
        max_tokens = _MAX_TOKENS,
        purpose    = "outreach_generate",
        user_id    = user_id,
        job_id     = job_id,
    )
    message = clean_ai_text(result.text).strip()

    # Persist before returning so it survives reloads (tenancy-scoped write).
    job_store.save_outreach_text(job_id, user_id, message)
    logger.info(
        "[OutreachService] generate_outreach job=%s user=%s (%d chars, persisted)",
        job_id, user_id, len(message),
    )
    return message


_PITCH_SYSTEM = """You are a master technical recruiter advocating for your candidate directly to hiring companies.
Your goal is to write a highly concise, punchy, direct pitch message (under 120 words) for a recruiter or hiring manager based on raw scraped job data.

Rules:
1. NO subject line or pleasantries like "Hope this finds you well". Start directly.
2. Emphasize domain expertise, trajectory, and immediate readiness for the role.
3. The message must feel like it was sent by a human recruiter who just matched the perfect candidate to the job.
4. Output ONLY the message text.
5. NO hashtags, emojis, or corporate buzzwords.
6. The output MUST be strictly in English."""

_PITCH_USER_TMPL = """Write a direct pitch for this raw scraped job opening:

JOB DETAILS:
Title: {title}
Company: {company}
Location: {location}
Raw Description: {jd_text}

CANDIDATE PROFILE:
{candidate_material}"""


async def generate_pitch_from_raw(posting: RawJobPosting, user_profile: str) -> str:
    """
    Generate a direct pitch for recruiters based on unpersisted raw job data
    and a candidate's profile.
    """
    user_prompt = _PITCH_USER_TMPL.format(
        title              = posting.title,
        company            = posting.company,
        location           = "Israel",
        jd_text            = sanitize_text(posting.raw_text[:4000]),
        candidate_material = sanitize_text(user_profile),
    )

    if not os.getenv("ANTHROPIC_API_KEY", ""):
        raise RuntimeError("ANTHROPIC_API_KEY is not set.")

    result = await call_llm(
        system     = harden_system_prompt(_PITCH_SYSTEM),
        messages   = [{"role": "user", "content": user_prompt}],
        model      = _MODEL,
        max_tokens = _MAX_TOKENS,
        purpose    = "outreach_pitch_from_raw",
    )

    return clean_ai_text(result.text).strip()
