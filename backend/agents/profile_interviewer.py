"""
ProfileInterviewer — conversational profile builder with confidence scoring.

Architecture
------------
Each user turn triggers TWO sequential LLM calls:

  1. EXTRACTOR (claude-haiku-4-5, fast):
     Reads the new user message and the accumulated draft_profile, then
     outputs a structured JSON delta describing what was explicitly stated.
     Anti-hallucination: if a value was not stated, the field is null.
     If a stated value is vague or missing critical sub-detail, the extractor
     marks it INCOMPLETE with a list of exactly what is missing.

  2. INTERVIEWER (claude-sonnet-4-6, quality):
     Reads the full conversation history and the updated draft/confidence state,
     then generates the next conversational turn — typically an acknowledgment
     followed by ONE targeted probe about the most critical missing detail.

Confidence levels
-----------------
  INCOMPLETE       = 15  — stated but too vague to use (missing dates, metrics)
  UNVERIFIED       = 30  — stated clearly but not cross-referenced
  CONSISTENT       = 60  — mentioned multiple times with consistent details
  DOCUMENT_PENDING = 75  — document uploaded but analysis not yet complete
  DOCUMENT_VERIFIED= 100 — confirmed in uploaded document

Session persistence
-------------------
State is stored via profile_interview_repository (backend/models/profile.py's
ProfileInterviewRow) so sessions survive server restarts.
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

from backend.repositories import profile_interview_repository
from backend.services.llm_client import call_llm

load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=True)
logger = logging.getLogger(__name__)

# ── Confidence constants ──────────────────────────────────────────────────────
CONF_INCOMPLETE        = 15
CONF_UNVERIFIED        = 30
CONF_CONSISTENT        = 60
CONF_DOCUMENT_PENDING  = 75
CONF_DOCUMENT_VERIFIED = 100

# ── Models ────────────────────────────────────────────────────────────────────
_EXTRACTOR_MODEL   = "claude-haiku-4-5"
_INTERVIEWER_MODEL = "claude-sonnet-4-6"
_MAX_TOKENS_EXT    = 1500
_MAX_TOKENS_INT    = 600
_MAX_TOKENS_OPEN   = 350   # opening messages are short — cap tightly


# ── First-name extraction ─────────────────────────────────────────────────────

def _extract_first_name(
    name_hint:  str | None = None,
    email_hint: str | None = None,
) -> str:
    """
    Return a capitalized first name from the best available source.

    Priority order:
      1. name_hint that looks like a real name (not an email): split on spaces,
         take the first token, strip stray digits, capitalize.
      2. email_hint: take the local part (before @), split on . _ - +,
         take the first token, strip digits, capitalize.
      3. Fall back to "there" so the opening still reads naturally.

    Examples
    --------
      _extract_first_name("Jamie Smith")                    → "Jamie"
      _extract_first_name("jamie")                          → "Jamie"
      _extract_first_name(None, "jamie.smith@example.com")  → "Jamie"
      _extract_first_name(None, "jamiesmith98@example.com") → "Jamiesmith"  (no separator — best effort)
      _extract_first_name("Jamie Smith", "jamie@x.com")     → "Jamie"  (name_hint wins)
    """
    # 1. name_hint that is a proper name (no @ sign).
    #    If the caller accidentally forwarded an email address as name_hint,
    #    fall through to the email-based path below rather than mangling it
    #    into "Jamiesmith" (no separator) or "Jamiesmith98" (with digits).
    if name_hint and "@" not in name_hint:
        token = name_hint.strip().split()[0]        # "Jamie Smith" → "Jamie"
        token = re.sub(r"^\d+|\d+$", "", token)    # strip leading/trailing digits
        if token:
            return token.capitalize()

    # Treat an email passed as name_hint the same as email_hint
    effective_email = email_hint or (name_hint if (name_hint and "@" in name_hint) else None)

    # 2. email-based extraction
    if effective_email and "@" in effective_email:
        local = effective_email.split("@")[0]
        # Split on common separators — covers firstname.lastname@ and firstname_lastname@
        parts = re.split(r"[.\-_+]", local)
        token = parts[0] if parts else local
        token = re.sub(r"^\d+|\d+$", "", token)   # strip leading/trailing digits
        if token:
            return token.capitalize()

    return "there"

# ── Extractor system prompt ───────────────────────────────────────────────────

_EXTRACTOR_SYSTEM = """\
You are a strict, zero-hallucination data extraction engine embedded in a \
profile-building interview system.

YOUR ONLY JOB: extract what the candidate EXPLICITLY AND CLEARLY STATED in \
their most recent message. Nothing more.

ABSOLUTE RULES — violation breaks the system:
• If a value was NOT stated: set it to null. Do NOT guess, infer, or assume.
• If a date range is incomplete (e.g. only a start year, no end): mark it as \
  INCOMPLETE and list "end_date" in missing_details.
• If a role title is vague (e.g. "I worked in tech"): mark INCOMPLETE, \
  missing_details: ["exact_job_title"].
• If a metric is implied but not stated (e.g. "managed a big team"): mark \
  INCOMPLETE, missing_details: ["team_size"].
• Do NOT paraphrase — preserve the exact words the candidate used for names, \
  titles, and institutions.
• Do NOT promote any field to CONSISTENT unless the candidate has now mentioned \
  it with consistent details in more than one message.
• Output ONLY a raw JSON object — no markdown, no explanation.

CONFIDENCE_STATUS values: "incomplete" | "unverified" | "consistent"
(Document verification happens separately and upgrades these externally.)

CONFIDENCE_SCORE:
  incomplete  = 15
  unverified  = 30
  consistent  = 60
"""

_EXTRACTOR_USER_TMPL = """\
CURRENT DRAFT PROFILE (already extracted from prior turns):
{draft}

CONVERSATION HISTORY (for consistency checking only — extract from LATEST message):
{history_snippet}

LATEST USER MESSAGE:
{user_message}

Extract a JSON delta from the LATEST MESSAGE only.
Schema:
{{
  "education_updates": [
    {{
      "degree":          "exact string or null",
      "institution":     "exact string or null",
      "start_year":      "YYYY or null",
      "end_year":        "YYYY or null",
      "honors":          "exact string or null",
      "gpa":             "X.X or null",
      "certification":   "exact string or null",
      "status":          "incomplete | unverified | consistent",
      "missing_details": ["list of what is still missing", ...]
    }}
  ],
  "experience_updates": [
    {{
      "company":         "exact name or null",
      "role":            "exact title or null",
      "start_date":      "YYYY-MM or YYYY or null",
      "end_date":        "YYYY-MM or YYYY or 'present' or null",
      "team_size":       "number or null",
      "responsibilities": ["explicitly stated responsibility strings"],
      "status":          "incomplete | unverified | consistent",
      "missing_details": ["list of gaps"]
    }}
  ],
  "skills_updates":   ["exact skill string", ...],
  "military_update": {{
    "unit":   "exact or null",
    "role":   "exact or null",
    "start":  "YYYY or null",
    "end":    "YYYY or null",
    "status": "incomplete | unverified | consistent",
    "missing_details": []
  }},
  "personal_updates": {{
    "name":     "exact or null",
    "email":    "exact or null",
    "phone":    "exact or null",
    "location": "exact or null"
  }},
  "probe_triggers": [
    {{
      "field":  "e.g. experience.0.team_size",
      "reason": "user said 'managed a team' but did not state size",
      "probe":  "suggested follow-up question to ask"
    }}
  ],
  "request_document": {{
    "for_claim":   "e.g. 'BA in Business Administration from Reichman'",
    "document_type": "transcript | diploma | employment_letter | military_record | certificate"
  }}
}}

If nothing new was stated for a section, return an empty list/null for that key.
"""

# ── Interviewer system prompt ─────────────────────────────────────────────────

_INTERVIEWER_SYSTEM = """\
Your name is Ariel. You are a personal career agent and professional profile specialist \
working for a job-application platform. Your sole purpose is to build the user's \
verified professional profile through natural conversation, covering work experience, \
education, skills, and military service.

IDENTITY:
You are Ariel. Never call yourself anything else. If the user asks your name, answer: \
"I'm Ariel, your personal career agent." You introduced yourself in the opening message \
of this session. Do not re-introduce yourself on every turn. \
Address the user by name if they have shared it.

VOICE AND TONE:
Speak like a professional colleague who is genuinely engaged. Be warm, supportive, \
and direct. Cut filler phrases and robotic enthusiasm. Acknowledge what the user \
shared in 1 to 2 sentences, then ask exactly one focused follow-up question. \
Never ask two questions in the same message. \
Respond in English unless the user writes in Hebrew, in which case respond entirely \
in Hebrew. When responding in Hebrew, use natural Hebrew phrasing, not a translation \
of English sentence structure.

PLAIN TEXT ONLY - THIS IS NON-NEGOTIABLE:
The chat interface does not render any markdown. You must output plain text only. \
Never use asterisks for bold or italic. Never use underscores for emphasis. \
Never use long dashes (the em dash character). Never use hyphens as bullet points. \
Never use hash characters for headers. If you want to emphasise something, \
do it through word choice and sentence structure, not through symbols.

STRICT SCOPE:
Your only topic is building the professional profile. Do not answer questions about \
job searching, career advice, salary benchmarks, technology, or any other subject. \
If the user goes off-topic, redirect them directly: "That is worth exploring, but \
let me keep us on the profile for now. Could you tell me more about [missing field]?"

TECHNICAL SUPPORT DEFLECTION:
If the user asks about password resets, billing, login issues, account settings, \
bugs, or any platform technical question, respond with exactly: \
"I'm focused on your career path. Please ask Eliya in the Help chat for technical \
support." Then return the conversation to profile building.

ACCURACY AND ANTI-HALLUCINATION:
Base every data point exclusively on what the user has explicitly stated or what \
appears in a verified uploaded document. Never guess, infer, or fill in gaps. \
If an answer is vague or missing a critical sub-detail, do not accept it and move on. \
Ask a precise follow-up for the exact missing piece such as exact dates, team size, \
or a measurable outcome. Never use phrases like "it sounds like you probably" \
or "I assume you mean". If a value was not stated, treat it as unknown and probe for it.

WHAT YOU ALREADY KNOW - DO NOT ASK FOR ANY OF THIS:
The following information has been loaded directly from the user's existing CV and \
profile data. Treat every item below as fully established fact. Never ask the user \
to confirm, repeat, or re-explain anything listed here. Your job is to go deeper \
than this data - surface the quantified achievements, key decisions, leadership \
challenges, and measurable outcomes that this profile does not yet capture.

{profile_context}

WHAT HAS BEEN EXTRACTED IN THIS SESSION:
{draft_summary}

PRIORITY ORDER for your next question, from highest to lowest:
1. Critical gaps listed in PENDING PROBES below.
2. Measurable outcomes or numbers behind any role or achievement already on file.
3. Exact start and end dates for any entry that is missing them.
4. Team size or scope of responsibility for leadership roles.
5. Document verification for high-value claims such as a degree, certification, \
   or a leadership position.

PENDING PROBES (address these first, in order):
{pending_probes}

YOUR TASK:
Acknowledge the user's last message in 1 to 2 sentences, then ask exactly one \
question. Use the first item from PENDING PROBES if the list is not empty, \
otherwise ask about the highest-priority gap. Do not move to the next topic until \
the current missing detail has been provided clearly.
"""

# ── Resume system prompt ─────────────────────────────────────────────────────

_RESUME_SYSTEM = """\
Your name is Ariel. You are a personal career agent and professional profile specialist. \
The user is returning to a profile-building session that was already started. \
Your task is to generate a single welcome-back message. \
If the user asks your name, answer: "I'm Ariel, your personal career agent."

Follow this structure in order, keeping the total to 6 to 10 sentences:

First, welcome the user back in one sentence. Acknowledge they are returning. \
Do not repeat the original introduction or re-introduce yourself at length.

Second, summarise what has already been recorded in 2 to 3 sentences. Be specific: \
name actual values such as company names, degree titles, dates, and skills. \
Cover education, experience, military service, and skills naturally in flowing sentences.

Third, in 1 to 2 sentences highlight the most impressive high-confidence items from the profile. \
Be genuinely encouraging but strictly factual. Never invent or exaggerate.

Fourth, in 1 to 2 sentences name the 2 to 3 most critical pieces of information \
still missing, such as exact dates, team sizes, or measurable outcomes.

Fifth, end with exactly one focused question about the top-priority gap. \
Do not ask multiple questions.

PLAIN TEXT ONLY - THIS IS NON-NEGOTIABLE:
The chat interface does not render any markdown. Output plain text only. \
Never use asterisks, underscores, long dashes, hyphens as bullet points, \
or hash characters. No formatting symbols of any kind.

ACCURACY:
Only reference data explicitly present in the profile summary provided. \
Never fabricate, infer, or assume any value.

Tone: warm and professional. Not robotic. Not a list. \
Write in English unless the profile context is in Hebrew, in which case respond in Hebrew.
"""

# ── Ariel gap-analysis interviewer system prompt ──────────────────────────
#
# Used when intent == "optimize_gaps" for all turns AFTER the opening.
# Ariel's role is to probe against the cv_claims the user uploaded —
# treating them as unverified assertions, not established facts.

_ARIEL_GAP_INTERVIEWER_SYSTEM = """\
Your name is Ariel. You are a senior career strategist and professional profile analyst working for \
a job-application platform. You are conducting a gap-analysis interview. \
Your sole purpose is to validate — through probing, scenario-based questions — \
whether the user actually possesses the skills and experiences stated in their uploaded CVs.

IDENTITY:
You introduced yourself in the opening message. Do not re-introduce yourself. \
Address the user by name if they have shared it.

VOICE AND TONE:
Be direct, professional, and incisive. Zero corporate filler. \
Treat the user as a capable adult. Acknowledge their last answer in 1 to 2 sentences, \
then ask exactly one focused scenario-based or outcome-based follow-up question. \
Never ask two questions in the same message.
Respond in English unless the user writes in Hebrew, in which case respond entirely in Hebrew.

PLAIN TEXT ONLY - THIS IS NON-NEGOTIABLE:
The chat interface does not render markdown. Output plain text only. \
Never use asterisks, underscores, long dashes, hyphens as bullets, or hash symbols.

STRICT SCOPE:
Stay on the profile gap-analysis. Do not answer questions about job searching, \
salary, career advice, or any topic outside validating the user's background.

CV CLAIMS — TREAT AS UNVERIFIED ASSERTIONS:
The section below contains skills and experiences extracted from the user's uploaded CVs. \
These are UNVERIFIED CLAIMS, not established facts. \
The user wrote these on their CV — but having written them does not prove competence. \
Your objective is to use this data to drive a gap-analysis interview: \
ask probing, scenario-based questions to determine whether the user actually possesses \
these specific skills and genuinely understands the experiences they claimed. \
Never accept a vague answer. If the user gives a surface-level response, \
press for concrete examples, measurable outcomes, team sizes, or specific decisions made.

{cv_claims_block}

WHAT HAS BEEN EXTRACTED IN THIS SESSION SO FAR:
{draft_summary}

PENDING PROBES (address these first, in order):
{pending_probes}

YOUR TASK:
Acknowledge the user's last message in 1 to 2 sentences, then ask exactly one \
targeted question. Prefer scenario-based prompts ("Walk me through a time when…", \
"What specific outcome did you drive at…") over closed yes/no questions. \
Use the first item from PENDING PROBES if the list is not empty.
"""

# ── Ariel optimize-gaps opening prompt ─────────────────────────────────────────────
#
# Used exclusively when intent == "optimize_gaps".
# Ariel opens the conversation.  The three-part structure is
# mandatory and must not be reordered:
#   1. Brief familiarity acknowledgment — name + role/company.
#   2. Purpose statement — why this conversation matters and what more detail does.
#   3. One targeted question — aimed at the lowest-confidence / thinnest area.

_ARIEL_OPTIMIZE_GAPS_OPENING_SYSTEM = """\
Your name is Ariel. You are a senior career strategist and professional profile analyst working for \
a job-application platform. The user is opening a Profile Strength Review session. \
Your task is to write the opening message of this session.

IDENTITY AND TONE:
You are Ariel. Never call yourself anything else. \
Be direct and professional. Zero artificial enthusiasm, zero corporate filler \
phrases such as "That's great!", "Absolutely!", or "Certainly!". \
Treat the user as a capable adult.

MANDATORY THREE-PART STRUCTURE — follow this order exactly:

PART 1 — FAMILIARITY (one sentence):
Acknowledge that you have reviewed their file. State their first name, then briefly \
reference their most recent role and company from the profile below. \
Use exactly this pattern: \
"Hi [First Name], I'm Ariel. I've reviewed your file and I'm familiar with \
your background as [Most Recent Role] at [Most Recent Company]."

PART 2 — PURPOSE (two sentences, no more):
State clearly why this session exists and what deeper detail achieves. \
Use exactly this pattern: \
"I am here to strengthen your profile and understand your capabilities on a deeper \
level. The more precise detail you provide, the more accurately I can map your \
true strengths."

PART 3 — TARGETED QUESTION (one focused question, no lead-in praise):
Look at the PROFILE DATA below. Find the area that is most thinly described — \
missing quantified outcomes, missing dates, missing team sizes, or skills listed \
without any project context. That is your target. \
Ask one specific question about that exact area. The question must name the \
specific role, company, skill, or credential you are probing — never ask a \
generic "tell me about yourself" question. \
Do not use a transition phrase like "So," or "To start,". \
Just ask the question directly as the third paragraph.

PLAIN TEXT ONLY:
Never use asterisks, underscores, hyphens as bullets, long dashes, or hash symbols. \
No markdown of any kind. Plain text paragraphs separated by a blank line.

ACCURACY:
Only reference data explicitly present in the PROFILE DATA section. \
Never invent a company, role, date, or skill.
"""

_OPTIMIZE_GAPS_OPENING_USER_TMPL = """\
PROFILE DATA:
{profile_snapshot}

Write the three-part opening message for {first_name}. \
Do not add any preamble or explanation — output only the message itself.
"""


async def _build_optimize_gaps_opening(
    first_name:       str,
    profile_snapshot: str,
) -> str:
    """
    Generate Ariel's personalized opening for the optimize_gaps flow.

    Uses haiku (fast, cheap) because this is a short, structured generation task.
    Falls back to a hard-coded message if the LLM call fails.
    """
    user_prompt = _OPTIMIZE_GAPS_OPENING_USER_TMPL.format(
        profile_snapshot = profile_snapshot,
        first_name       = first_name,
    )
    try:
        result = await call_llm(
            system     = _ARIEL_OPTIMIZE_GAPS_OPENING_SYSTEM,
            messages   = [{"role": "user", "content": user_prompt}],
            model      = _EXTRACTOR_MODEL,    # haiku — sufficient for structured generation
            max_tokens = _MAX_TOKENS_OPEN,
            purpose    = "profile_interview_optimize_gaps_opening",
        )
        return result.text.strip()
    except Exception as exc:
        logger.error("[ProfileInterviewer] optimize_gaps opening LLM call failed: %s", exc)
        # Deterministic fallback that still follows the three-part structure
        return (
            f"Hi {first_name}, I'm Ariel. I've reviewed your file and I'm familiar "
            f"with your background.\n\n"
            f"I am here to strengthen your profile and understand your capabilities on a "
            f"deeper level. The more precise detail you provide, the more accurately I can "
            f"map your true strengths.\n\n"
            f"Looking at your experience, I notice some of your roles are missing quantified "
            f"outcomes. Could you walk me through a specific result you drove in your most "
            f"recent position — something with a measurable number attached to it?"
        )


# ── Profile context loader ────────────────────────────────────────────────────

def _build_profile_context(
    user_id:               str,
    user_name_override:    str | None = None,
    current_role_override: str | None = None,
    user_email:            str | None = None,
) -> dict:
    """
    Build a structured snapshot of the user's known profile.

    For user_id='default' the authoritative source is USER_PROFILE (the
    backend constant loaded from the legacy flat-file).  For any real user
    the per-user store (backend/data/users/{user_id}/profile.json) is used instead,
    supplemented by the global USER_PROFILE structure for CV data.

    Optional overrides let the API layer inject frontend-supplied hints
    (e.g. from the auth session) without changing the source of truth.

    Returns:
        first_name       – given name to address the user ("Jamie")
        full_name        – full name ("Jamie Smith")
        current_role     – most recent role title + company
        profile_snapshot – plain-text block for injection into system prompts
    """
    try:
        from backend.services.user_profile import USER_PROFILE

        personal = USER_PROFILE.get("personal", {})
        # Only treat user_name_override as a real name if it contains no @.
        # An email address in this field is a frontend bug — ignore it and
        # fall back to the stored profile name so we never mangle it.
        _name_override = user_name_override if (user_name_override and "@" not in user_name_override) else None
        full_name = _name_override or personal.get("name", "")

        # For real (non-default) users, prefer their stored personal data
        if user_id != "default":
            try:
                from backend.services.user_profile_store import load as _store_load
                stored = _store_load(user_id)
                stored_personal = stored.get("personal", {})
                if not full_name:
                    full_name = stored_personal.get("full_name", "")
            except Exception:
                pass

        # Resolve first name: profile full_name → name override → email → "there"
        first_name = _extract_first_name(full_name or user_name_override, user_email)

        # ── Most recent role ──────────────────────────────────────────────────
        experience   = USER_PROFILE.get("experience", [])
        current_role = current_role_override or ""
        if not current_role:
            for exp in reversed(experience):
                if "roles" in exp:
                    # Multi-role entry — first listed is most recent
                    top_role = exp["roles"][0]
                    current_role = f"{top_role['title']} at {exp.get('company', '')}"
                    break
                elif exp.get("role") and exp.get("company"):
                    current_role = f"{exp['role']} at {exp['company']}"
                    break

        # ── Education summary ─────────────────────────────────────────────────
        edu_lines: list[str] = []
        for e in USER_PROFILE.get("education", []):
            if e.get("degree"):
                edu_lines.append(
                    f"{e['degree']} from {e.get('school', '?')} ({e.get('period', '')})"
                    + (f", {e['status']}" if e.get("status") else "")
                )
            elif e.get("certification"):
                edu_lines.append(
                    f"{e['certification']} certification, {e.get('provider', '?')} ({e.get('period', '')})"
                )

        # ── Experience summary (most recent 5 entries) ────────────────────────
        exp_lines: list[str] = []
        for exp in experience[-5:]:
            if "roles" in exp:
                for r in exp["roles"]:
                    exp_lines.append(
                        f"{r['title']} at {exp.get('company', '?')} ({r.get('period', '')})"
                    )
            elif exp.get("company") and exp.get("role"):
                exp_lines.append(
                    f"{exp['role']} at {exp['company']} ({exp.get('period', '')})"
                )

        # ── Military ─────────────────────────────────────────────────────────
        mil_lines: list[str] = []
        for exp in experience:
            if exp.get("unit"):
                mil_lines.append(
                    f"{exp.get('role', '?')} in {exp['unit']} ({exp.get('period', '')})"
                )

        # ── Supplemental answers already captured ─────────────────────────────
        answered_topics: list[str] = []
        try:
            from backend.services.user_profile_store import load as _store_load
            stored  = _store_load(user_id)
            metrics = stored.get("metrics", {})
            # Surface the topic key only — enough context to avoid re-asking
            answered_topics = [
                k.replace("_", " ")
                for k in list(metrics.keys())[:10]  # cap to avoid prompt bloat
            ]
        except Exception:
            pass

        # ── Assemble snapshot ─────────────────────────────────────────────────
        parts = [f"Full name: {full_name}"]
        if current_role:
            parts.append(f"Current / most recent role: {current_role}")
        if edu_lines:
            parts.append("Education: " + " | ".join(edu_lines))
        if exp_lines:
            parts.append("Experience: " + " | ".join(exp_lines))
        if mil_lines:
            parts.append("Military service: " + " | ".join(mil_lines))
        if answered_topics:
            parts.append(
                "Topics already answered in supplemental Q&A: "
                + ", ".join(answered_topics)
            )

        # ── CV claims ─────────────────────────────────────────────────────────
        cv_claims: dict = {}
        try:
            from backend.services.user_profile_store import load as _store_load
            stored    = _store_load(user_id)
            cv_claims = stored.get("cv_claims") or {}
        except Exception:
            pass

        return {
            "first_name":       first_name,
            "full_name":        full_name,
            "current_role":     current_role,
            "profile_snapshot": "\n".join(parts),
            "cv_claims":        cv_claims,
        }

    except Exception as exc:
        logger.warning("[ProfileInterviewer] _build_profile_context failed: %s", exc)
        return {
            "first_name":       _extract_first_name(user_name_override, user_email),
            "full_name":        user_name_override or "",
            "current_role":     current_role_override or "",
            "profile_snapshot": "(Profile data unavailable — starting fresh.)",
            "cv_claims":        {},
        }


# ── Dynamic opening message ───────────────────────────────────────────────────

def _build_opening_message(first_name: str, current_role: str) -> str:
    """
    Generate Ariel's personalized opening message for a new session.
    Kept deliberately short and conversational — the tone should feel like
    a first Slack message from a sharp colleague, not a corporate introduction.
    """
    role_clause = f"as {current_role}" if current_role else "in your field"
    return (
        f"Hi {first_name}, great to meet you. "
        f"I'm Ariel, your profile specialist. "
        f"I've already reviewed your background {role_clause} - "
        f"everything is on file, so we won't waste time repeating the basics. "
        f"I'm just here to help you pull out your strongest professional achievements. "
        f"To kick things off: what's one major achievement from your most recent role "
        f"that you're most proud of?"
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _format_cv_claims(cv_claims: dict) -> str:
    """
    Render cv_claims as a readable plain-text block for injection into
    Ariel's gap-analysis system prompt.  Returns a placeholder if claims are empty.
    """
    if not cv_claims or not any([
        cv_claims.get("skills"),
        cv_claims.get("experiences"),
        cv_claims.get("education"),
        cv_claims.get("summary"),
    ]):
        return "(No CV claims uploaded yet — proceed with general gap-analysis probing.)"

    parts: list[str] = []

    summary = cv_claims.get("summary", "").strip()
    if summary:
        parts.append(f"CV SUMMARY (claimed): {summary}")

    skills = cv_claims.get("skills", [])
    if skills:
        parts.append("CLAIMED SKILLS: " + ", ".join(skills[:30]))

    experiences = cv_claims.get("experiences", [])
    if experiences:
        exp_lines = []
        for e in experiences[:10]:
            co   = e.get("company", "?")
            role = e.get("role", "?")
            span = " ".join(filter(None, [e.get("start", ""), e.get("end", "")]))
            note = e.get("summary", "")
            line = f"  {role} at {co}" + (f" ({span})" if span else "")
            if note:
                line += f" — {note}"
            exp_lines.append(line)
        parts.append("CLAIMED EXPERIENCES:\n" + "\n".join(exp_lines))

    education = cv_claims.get("education", [])
    if education:
        edu_lines = [
            f"  {e.get('degree', '?')} from {e.get('institution', '?')}"
            + (f" ({e.get('years', '')})" if e.get("years") else "")
            for e in education[:5]
        ]
        parts.append("CLAIMED EDUCATION:\n" + "\n".join(edu_lines))

    return "\n\n".join(parts)


def _extract_json(raw: str) -> dict:
    text = re.sub(r"```(?:json)?", "", raw).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end   = text.rfind("}")
        if start != -1 and end != -1:
            return json.loads(text[start : end + 1])
        return {}


def _draft_summary(draft: dict | None) -> str:
    """Compact one-screen summary of what has been extracted so far."""
    if not draft:
        return "(Nothing extracted yet — first turn.)"
    parts: list[str] = []
    edu = draft.get("education", [])
    if edu:
        parts.append("Education: " + "; ".join(
            f"{e.get('degree') or e.get('certification','?')} at {e.get('institution','?')} "
            f"({e.get('status','?')})"
            for e in edu[:3]
        ))
    exp = draft.get("experience", [])
    if exp:
        parts.append("Experience: " + "; ".join(
            f"{e.get('role','?')} @ {e.get('company','?')} "
            f"{e.get('start_date','?')}–{e.get('end_date','?')} ({e.get('status','?')})"
            for e in exp[:5]
        ))
    mil = draft.get("military")
    if mil:
        parts.append(
            f"Military: {mil.get('role','?')} at {mil.get('unit','?')} "
            f"{mil.get('start','?')}–{mil.get('end','?')} ({mil.get('status','?')})"
        )
    skills = draft.get("skills", [])
    if skills:
        parts.append("Skills: " + ", ".join(skills[:8]))
    return "\n".join(parts) if parts else "(Nothing extracted yet.)"


def _merge_draft(existing: dict | None, delta: dict) -> dict:
    """
    Merge an extraction delta into the accumulated draft profile.

    Rules:
    - Education and experience entries are identified by (institution+degree) or
      (company+role) keys; if an existing entry matches, it is UPDATED in-place.
    - New entries are appended.
    - Skills are union-merged (no duplicates).
    - Military is replaced if the new delta has a role set.
    """
    draft = dict(existing or {})

    # ── Education ─────────────────────────────────────────────────────────────
    edu_updates = delta.get("education_updates") or []
    draft.setdefault("education", [])
    for upd in edu_updates:
        if not upd or (not upd.get("degree") and not upd.get("certification")):
            continue
        key = (upd.get("institution") or "").lower()
        matched = False
        for i, e in enumerate(draft["education"]):
            if (e.get("institution") or "").lower() == key:
                draft["education"][i] = {**e, **{k: v for k, v in upd.items() if v is not None}}
                matched = True
                break
        if not matched:
            draft["education"].append(upd)

    # ── Experience ────────────────────────────────────────────────────────────
    exp_updates = delta.get("experience_updates") or []
    draft.setdefault("experience", [])
    for upd in exp_updates:
        if not upd or not upd.get("company"):
            continue
        co_key   = (upd.get("company") or "").lower()
        role_key = (upd.get("role") or "").lower()
        matched  = False
        for i, e in enumerate(draft["experience"]):
            if (e.get("company") or "").lower() == co_key and \
               (not role_key or (e.get("role") or "").lower() == role_key):
                draft["experience"][i] = {**e, **{k: v for k, v in upd.items() if v is not None}}
                matched = True
                break
        if not matched:
            draft["experience"].append(upd)

    # ── Skills ────────────────────────────────────────────────────────────────
    new_skills = delta.get("skills_updates") or []
    draft.setdefault("skills", [])
    existing_lower = {s.lower() for s in draft["skills"]}
    for sk in new_skills:
        if sk and sk.lower() not in existing_lower:
            draft["skills"].append(sk)
            existing_lower.add(sk.lower())

    # ── Military ──────────────────────────────────────────────────────────────
    mil_upd = delta.get("military_update")
    if mil_upd and mil_upd.get("role"):
        existing_mil = draft.get("military") or {}
        draft["military"] = {**existing_mil, **{k: v for k, v in mil_upd.items() if v is not None}}

    # ── Personal ──────────────────────────────────────────────────────────────
    pers_upd = delta.get("personal_updates") or {}
    draft.setdefault("personal", {})
    for k, v in pers_upd.items():
        if v:
            draft["personal"][k] = v

    return draft


def _merge_confidence(existing: dict | None, delta: dict, draft: dict) -> dict:
    """
    Build/update the flat confidence map from the extraction delta.

    confidence_map: {claim_id: {score, status, missing_details, evidence}}
    """
    cmap = dict(existing or {})

    score_map = {
        "incomplete": CONF_INCOMPLETE,
        "unverified": CONF_UNVERIFIED,
        "consistent": CONF_CONSISTENT,
    }

    # Education
    for idx, upd in enumerate(delta.get("education_updates") or []):
        if not upd:
            continue
        status = upd.get("status", "unverified")
        score  = score_map.get(status, CONF_UNVERIFIED)
        key    = f"education.{idx}"
        existing_entry = cmap.get(key, {})
        cmap[key] = {
            "score":           max(existing_entry.get("score", 0), score),
            "status":          status,
            "missing_details": upd.get("missing_details", []),
            "evidence":        existing_entry.get("evidence"),
            "label":           f"{upd.get('degree') or upd.get('certification','?')} — "
                               f"{upd.get('institution','?')}",
        }

    # Experience
    for idx, upd in enumerate(delta.get("experience_updates") or []):
        if not upd:
            continue
        status = upd.get("status", "unverified")
        score  = score_map.get(status, CONF_UNVERIFIED)
        key    = f"experience.{idx}"
        existing_entry = cmap.get(key, {})
        cmap[key] = {
            "score":           max(existing_entry.get("score", 0), score),
            "status":          status,
            "missing_details": upd.get("missing_details", []),
            "evidence":        existing_entry.get("evidence"),
            "label":           f"{upd.get('role','?')} @ {upd.get('company','?')}",
        }

    # Military
    mil = delta.get("military_update")
    if mil and mil.get("role"):
        status = mil.get("status", "unverified")
        cmap["military"] = {
            "score":           score_map.get(status, CONF_UNVERIFIED),
            "status":          status,
            "missing_details": mil.get("missing_details", []),
            "evidence":        cmap.get("military", {}).get("evidence"),
            "label":           f"{mil.get('role','?')} — {mil.get('unit','?')}",
        }

    return cmap


# ── Main interview functions ──────────────────────────────────────────────────

async def start_session(
    user_id:               str,
    user_name_override:    str | None = None,
    current_role_override: str | None = None,
    user_email:            str | None = None,
    intent:                str | None = None,
) -> dict:
    """
    Create a new interview session and return its initial state.

    The opening message is generated dynamically from the user's existing profile
    data so the agent can address them by name and skip redundant onboarding questions.

    When intent == "optimize_gaps", Ariel opens in gap-analysis mode instead
    of builder mode: she acknowledges known strengths, surfaces the lowest-confidence area,
    and asks one targeted deep-dive question about it.

    user_id is stored on the row; all subsequent operations must present the same
    user_id or they will receive a PermissionError.

    Optional override parameters allow the API layer to inject hints from the
    auth session (e.g. name/email from the JWT).  The backend's own USER_PROFILE
    always takes precedence — overrides are only used when profile data is unavailable.
    """
    ctx = _build_profile_context(
        user_name_override    = user_name_override,
        current_role_override = current_role_override,
        user_id               = user_id,
        user_email            = user_email,
    )

    if intent == "optimize_gaps":
        opening = await _build_optimize_gaps_opening(
            first_name       = ctx["first_name"],
            profile_snapshot = ctx["profile_snapshot"],
        )
    else:
        opening = _build_opening_message(ctx["first_name"], ctx["current_role"])
    session_id = str(uuid.uuid4())
    now        = _now()

    opening_msg = {"role": "assistant", "content": opening, "ts": now}

    profile_interview_repository.create(
        session_id = session_id,
        user_id    = user_id,
        messages   = [opening_msg],
        status     = "active",
        intent     = intent,
        now        = now,
    )

    logger.info("[ProfileInterviewer] Session started: %s (user=%s)", session_id, user_id)
    return {
        "session_id":     session_id,
        "messages":       [opening_msg],
        "draft_profile":  None,
        "confidence_map": {},
        "pending_probes": [],
        "status":         "active",
    }


async def process_message(session_id: str, user_text: str, user_id: str) -> dict:
    """
    Process one user turn:
      1. Append the user message to history.
      2. Run the extractor to update draft_profile + confidence_map.
      3. Run the interviewer to generate the next agent reply.
      4. Persist state.
      5. Return the updated session payload.

    Raises ValueError    if session_id not found or session is not active.
    Raises PermissionError if the session belongs to a different user_id.
    """
    row = profile_interview_repository.get(session_id)
    if not row:
        raise ValueError(f"Session {session_id!r} not found.")
    if row["user_id"] != user_id:
        raise PermissionError(
            f"Session {session_id!r} does not belong to the authenticated user."
        )
    if row["status"] != "active":
        raise ValueError(f"Session {session_id!r} is {row['status']}, not active.")

    messages       = list(row["messages"] or [])
    draft          = dict(row["draft_profile"] or {}) or None
    confidence_map = dict(row["confidence_map"] or {})
    pending_probes = list(row["pending_probes"] or [])
    session_intent = row["intent"]  # "optimize_gaps" or None

    # Append user message
    now = _now()
    messages.append({"role": "user", "content": user_text, "ts": now})

    # ── Phase 1: Extractor ────────────────────────────────────────────────────
    history_snippet = "\n".join(
        f"{m['role'].upper()}: {m['content'][:200]}"
        for m in messages[-6:]  # last 3 exchanges
    )
    ext_prompt = _EXTRACTOR_USER_TMPL.format(
        draft           = json.dumps(draft or {}, ensure_ascii=False, indent=2)[:2000],
        history_snippet = history_snippet,
        user_message    = user_text,
    )

    try:
        ext_result = await call_llm(
            system     = _EXTRACTOR_SYSTEM,
            messages   = [{"role": "user", "content": ext_prompt}],
            model      = _EXTRACTOR_MODEL,
            max_tokens = _MAX_TOKENS_EXT,
            purpose    = "profile_interview_extractor",
            user_id    = user_id,
        )
        delta = _extract_json(ext_result.text)
    except Exception as exc:
        logger.warning("[ProfileInterviewer] Extractor failed: %s — continuing with empty delta", exc)
        delta = {}

    # Merge extraction into draft
    draft          = _merge_draft(draft, delta)
    confidence_map = _merge_confidence(confidence_map, delta, draft)

    # Collect new probe triggers and document request
    new_probes = [
        p.get("probe", p.get("reason", ""))
        for p in (delta.get("probe_triggers") or [])
        if p.get("probe") or p.get("reason")
    ]
    pending_probes = (pending_probes + new_probes)[:10]  # cap at 10

    doc_request = delta.get("request_document")

    # ── Phase 2: Interviewer ──────────────────────────────────────────────────
    # Rebuild profile context on every turn so the agent is always current with
    # the latest supplemental answers and cv_claims stored for this user.
    _ctx = _build_profile_context(user_id=user_id)

    if session_intent == "optimize_gaps":
        # Ariel (gap mode): probes against uploaded cv_claims
        int_prompt = _ARIEL_GAP_INTERVIEWER_SYSTEM.format(
            cv_claims_block = _format_cv_claims(_ctx.get("cv_claims", {})),
            draft_summary   = _draft_summary(draft),
            pending_probes  = "\n".join(f"- {p}" for p in pending_probes[:3]) or "(none yet)",
        )
    else:
        # Ariel (builder mode): standard profile builder
        int_prompt = _INTERVIEWER_SYSTEM.format(
            profile_context = _ctx["profile_snapshot"],
            draft_summary   = _draft_summary(draft),
            pending_probes  = "\n".join(f"- {p}" for p in pending_probes[:3]) or "(none yet)",
        )

    # Build the conversation history for the interviewer
    interview_messages = []
    for m in messages[1:]:  # skip the opening message (already in system context)
        interview_messages.append({"role": m["role"], "content": m["content"]})

    try:
        int_result = await call_llm(
            system     = int_prompt,
            messages   = interview_messages,
            model      = _INTERVIEWER_MODEL,
            max_tokens = _MAX_TOKENS_INT,
            purpose    = "profile_interview_interviewer",
            user_id    = user_id,
        )
        agent_reply = int_result.text.strip()
    except Exception as exc:
        logger.error("[ProfileInterviewer] Interviewer failed: %s", exc)
        agent_reply = (
            "Thanks for sharing that. Could you tell me more about your most recent role — "
            "specifically the exact dates and your main responsibilities?"
        )

    # If the extractor flagged a document request, append a prompt for it
    if doc_request and doc_request.get("for_claim"):
        agent_reply += (
            f"\n\nAlso, to confirm your {doc_request['for_claim']}, "
            f"please upload the relevant {doc_request.get('document_type', 'document')} "
            f"using the upload button below."
        )

    # Append agent reply
    messages.append({"role": "assistant", "content": agent_reply, "ts": _now()})

    # Remove the probe that was just asked (first in list) from pending
    if pending_probes and new_probes is not None:
        pending_probes = pending_probes[1:]

    # ── Persist ───────────────────────────────────────────────────────────────
    profile_interview_repository.update_full(
        session_id,
        messages       = messages,
        draft_profile  = draft,
        confidence_map = confidence_map,
        pending_probes = pending_probes,
        now            = _now(),
    )

    logger.info(
        "[ProfileInterviewer] Turn processed — session=%s  edu=%d  exp=%d  claims=%d",
        session_id,
        len((draft or {}).get("education", [])),
        len((draft or {}).get("experience", [])),
        len(confidence_map),
    )

    return {
        "session_id":     session_id,
        "messages":       messages,
        "draft_profile":  draft,
        "confidence_map": confidence_map,
        "pending_probes": pending_probes,
        "doc_request":    doc_request,
        "status":         "active",
    }


def get_session(session_id: str, user_id: str) -> dict:
    """
    Fetch full session state.

    Raises ValueError     if session_id not found.
    Raises PermissionError if the session belongs to a different user_id.
    """
    row = profile_interview_repository.get(session_id)
    if not row:
        raise ValueError(f"Session {session_id!r} not found.")
    if row["user_id"] != user_id:
        raise PermissionError(
            f"Session {session_id!r} does not belong to the authenticated user."
        )
    return {
        "session_id":     row["session_id"],
        "messages":       row["messages"],
        "draft_profile":  row["draft_profile"],
        "confidence_map": row["confidence_map"],
        "pending_probes": row["pending_probes"],
        "document_refs":  row["document_refs"],
        "status":         row["status"],
        "intent":         row["intent"],
    }


async def resume_session(session_id: str, user_id: str) -> dict:
    """
    Generate a context-aware "Resume & Status" message for a returning user,
    append it to the session history, persist it, and return the updated state.

    The message:
      - Welcomes the user back (1 sentence)
      - Summarises what has been captured so far (specific values)
      - Highlights the strongest / highest-confidence items
      - Lists the 2–3 most critical gaps still outstanding
      - Ends with exactly one focused follow-up question

    Raises ValueError     if session_id not found.
    Raises PermissionError if the session belongs to a different user_id.
    """
    row = profile_interview_repository.get(session_id)
    if not row:
        raise ValueError(f"Session {session_id!r} not found.")
    if row["user_id"] != user_id:
        raise PermissionError(
            f"Session {session_id!r} does not belong to the authenticated user."
        )
    messages       = list(row["messages"] or [])
    draft          = row["draft_profile"]
    confidence_map = dict(row["confidence_map"] or {})
    pending_probes = list(row["pending_probes"] or [])

    # ── Idempotency guard ─────────────────────────────────────────────────────
    # If the last message in the chat already came from the assistant, the
    # session is in a clean "waiting for user input" state — no resume message
    # is needed.  Generating one would inject a duplicate "Welcome back" every
    # time the page is refreshed or the session is hot-reloaded.
    #
    # A new resume message is generated ONLY when the last message was from the
    # user, meaning the user dropped off mid-turn before the assistant replied.
    if messages and messages[-1].get("role") == "assistant":
        logger.info(
            "[ProfileInterviewer] resume_session skipped for %s — "
            "last message is already from assistant",
            session_id,
        )
        return {
            "session_id":     session_id,
            "messages":       messages,
            "draft_profile":  draft,
            "confidence_map": confidence_map,
            "pending_probes": pending_probes,
            "status":         "active",
        }

    # ── Build context for the LLM ─────────────────────────────────────────────
    strengths = [
        v.get("label", k)
        for k, v in confidence_map.items()
        if v.get("score", 0) >= 60
    ]

    gaps = []
    for k, v in confidence_map.items():
        if v.get("score", 0) < 60:
            label   = v.get("label", k)
            missing = v.get("missing_details") or []
            gaps.append(f"{label}" + (f" — missing: {', '.join(missing)}" if missing else ""))

    # Also pull probes as potential gaps
    for p in pending_probes[:3]:
        if p not in gaps:
            gaps.append(p)

    _resume_ctx   = _build_profile_context(user_id=user_id)
    context_block = (
        f"USER: {_resume_ctx['full_name']}\n"
        f"KNOWN ROLE: {_resume_ctx['current_role']}\n\n"
        f"DRAFT PROFILE SUMMARY:\n{_draft_summary(draft)}\n\n"
        f"HIGH-CONFIDENCE ITEMS (score >= 60): "
        f"{', '.join(strengths) if strengths else 'none yet'}\n\n"
        f"KNOWN GAPS (priority order):\n"
        + ("\n".join(f"- {g}" for g in gaps[:5]) if gaps else "- (none identified yet)")
        + f"\n\nTOP PENDING PROBE:\n"
        + (pending_probes[0] if pending_probes else "(generate the most impactful next question)")
    )

    # ── Call the interviewer model ────────────────────────────────────────────
    try:
        result = await call_llm(
            system     = _RESUME_SYSTEM,
            messages   = [{"role": "user", "content": context_block}],
            model      = _INTERVIEWER_MODEL,
            max_tokens = _MAX_TOKENS_INT,
            purpose    = "profile_interview_resume",
            user_id    = user_id,
        )
        resume_msg = result.text.strip()
    except Exception as exc:
        logger.error("[ProfileInterviewer] resume_session LLM call failed: %s", exc)
        resume_msg = (
            "Welcome back! Let's pick up right where we left off. "
            + (
                f"So far I have {len((draft or {}).get('experience', []))} role(s) and "
                f"{len((draft or {}).get('education', []))} education entr(y/ies) on file. "
                if draft else ""
            )
            + (f"{pending_probes[0]}" if pending_probes else
               "Could you tell me more about the dates or responsibilities for your most recent role?")
        )

    now         = _now()
    resume_entry = {"role": "assistant", "content": resume_msg, "ts": now}
    messages.append(resume_entry)

    # ── Persist ───────────────────────────────────────────────────────────────
    profile_interview_repository.update_messages(session_id, messages=messages, now=now)

    logger.info("[ProfileInterviewer] Session resumed: %s", session_id)

    return {
        "session_id":     session_id,
        "messages":       messages,
        "draft_profile":  draft,
        "confidence_map": confidence_map,
        "pending_probes": pending_probes,
        "status":         "active",
    }
