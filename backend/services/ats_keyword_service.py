"""
ATS Keyword Extraction Service — "The Grocery List".

What it does
-------------
1. Reads the raw JD text for a given job_id.
2. Uses Claude Haiku to extract the exact keyword/skill strings that an ATS
   parser would scan for — verbatim, as they appear in the JD.
3. Compares the extracted list against the candidate's profile and the skills
   already listed on their LinkedIn (approximated from USER_PROFILE).
4. Returns three lists:
     • jd_keywords  — every keyword/skill found in the JD
     • present      — keywords already in the candidate's profile/LinkedIn
     • missing      — keywords the candidate must ADD to their LinkedIn
                       "Skills" section to pass automated filtering

Caching
--------
Results are stored in the job's `tailored_cv` JSON column under the key
"ats_keywords" so repeated opens are instant:
   {"cv_data": {...}, "ats_keywords": {…}, "tailor_brief": {...}}

Design note on "exact" extraction
------------------------------------
ATS parsers tokenise on exact strings — "Product Management" and "Product
Manager" are different tokens.  The LLM is instructed to extract keywords
verbatim, not to paraphrase or categorise, so the output maps directly to
what the recruiter's system will scan for.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

import backend.repositories.job_repository as job_store
from backend.core.database import ENGINE
from backend.models.job import JobRow
from backend.services.llm_client import call_llm
from sqlalchemy.orm import Session

load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=True)

logger = logging.getLogger(__name__)

_MODEL      = "claude-haiku-4-5"
_MAX_TOKENS = 1500

# ── System prompt ─────────────────────────────────────────────────────────────

_SYSTEM = """\
You are an ATS (Applicant Tracking System) expert who specialises in keyword \
optimisation for job applications.

Your task is to extract the exact keyword strings from a job description that \
an ATS parser would scan for, then classify them against a candidate profile.

RULES:
• Extract keywords VERBATIM as they appear in the JD — do not paraphrase, \
  generalise, or group.
• Include: job titles, skills, tools, methodologies, certifications, domain terms, \
  seniority indicators (e.g. "Senior", "Lead"), and must-have qualifiers.
• Exclude: generic verbs ("manage", "lead"), soft-skill adjectives ("passionate", \
  "motivated"), and location/compensation terms.
• Output ONLY a raw JSON object — no markdown, no preamble.
• Schema:
  {
    "jd_keywords": ["exact phrase from JD", ...],
    "present":     ["keywords already in candidate profile/CV", ...],
    "missing":     ["keywords NOT in candidate profile — must add to LinkedIn", ...]
  }
"""

_USER_TMPL = """\
JOB DESCRIPTION:
{jd_text}

─────────────────────────────────────────────────────────────────
CANDIDATE PROFILE SNAPSHOT (to classify keywords as present/missing):

Skills listed: {skills}
Recent roles: {roles}
Education: {education}

─────────────────────────────────────────────────────────────────
Extract all ATS keywords from the JD and classify them as present or missing.
"""


# ── Profile snapshot builder ──────────────────────────────────────────────────

def _build_profile_snapshot(user_id: str) -> dict[str, str]:
    """Flatten the user's profile into compact strings for keyword comparison."""
    from backend.services.user_profile import get_profile
    profile = get_profile(user_id)
    skills = ", ".join(profile.get("skills") or [])

    roles: list[str] = []
    for exp in profile.get("experience", []):
        if "roles" in exp:
            for r in exp["roles"]:
                roles.append(f"{r['title']} at {exp.get('company', '')}")
        else:
            role = exp.get("role") or exp.get("unit", "")
            company = exp.get("company") or exp.get("unit", "")
            roles.append(f"{role} at {company}")

    edu: list[str] = []
    for e in profile.get("education", []):
        degree = e.get("degree") or e.get("certification", "")
        school = e.get("school") or e.get("provider", "")
        edu.append(f"{degree} from {school}")

    return {
        "skills":    skills,
        "roles":     "; ".join(roles[:6]),
        "education": "; ".join(edu),
    }


# ── JSON extraction ───────────────────────────────────────────────────────────

def _extract_json(raw: str) -> dict:
    text = re.sub(r"```(?:json)?", "", raw).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end   = text.rfind("}")
        if start != -1 and end != -1:
            return json.loads(text[start : end + 1])
        raise


# ── Main extraction function ──────────────────────────────────────────────────

async def extract_ats_keywords(job_id: str, user_id: str) -> dict:
    """
    Extract ATS keywords for a job and return a {present, missing, jd_keywords} dict.

    Results are cached in the job's tailored_cv JSON blob under "ats_keywords".
    Raises ValueError if the job has no JD text.
    """
    # ── Check cache first ─────────────────────────────────────────────────────
    cached_blob = job_store.get_tailored_cv(job_id, user_id)
    if cached_blob and "ats_keywords" in cached_blob:
        logger.info("[AtsKeywordService] Cache hit for job_id=%s", job_id)
        return cached_blob["ats_keywords"]

    # ── Fetch job from DB ─────────────────────────────────────────────────────
    with Session(ENGINE) as session:
        row = session.get(JobRow, job_id)
        if not row or row.user_id != user_id:
            raise ValueError(f"Job {job_id!r} not found")
        jd_text  = (row.jd_text or "").strip()
        job_title = row.title or ""
        company   = row.company or ""

    if not jd_text or len(jd_text) < 100:
        raise ValueError(
            f"Job {job_id!r} has insufficient JD text ({len(jd_text)} chars). "
            "Fetch the full JD first."
        )

    # ── Build prompt ──────────────────────────────────────────────────────────
    snapshot    = _build_profile_snapshot(user_id)
    user_prompt = _USER_TMPL.format(
        jd_text   = jd_text[:3000],  # cap to avoid token overrun
        skills    = snapshot["skills"],
        roles     = snapshot["roles"],
        education = snapshot["education"],
    )

    # ── Call Haiku ────────────────────────────────────────────────────────────
    result_llm = await call_llm(
        system     = _SYSTEM,
        messages   = [{"role": "user", "content": user_prompt}],
        model      = _MODEL,
        max_tokens = _MAX_TOKENS,
        purpose    = "ats_keyword_extraction",
        user_id    = user_id,
        job_id     = job_id,
    )

    raw    = result_llm.text.strip()
    result = _extract_json(raw)

    # Normalise keys and ensure lists
    keywords_result = {
        "job_title":    job_title,
        "company":      company,
        "jd_keywords":  sorted(set(result.get("jd_keywords", []))),
        "present":      sorted(set(result.get("present", []))),
        "missing":      sorted(set(result.get("missing", []))),
    }

    logger.info(
        "[AtsKeywordService] %s @ %s — %d total kw, %d present, %d missing",
        job_title, company,
        len(keywords_result["jd_keywords"]),
        len(keywords_result["present"]),
        len(keywords_result["missing"]),
    )

    # ── Persist in cache ──────────────────────────────────────────────────────
    with Session(ENGINE) as session:
        row = session.get(JobRow, job_id)
        if row:
            blob = dict(row.tailored_cv or {})
            blob["ats_keywords"] = keywords_result
            row.tailored_cv = blob
            session.commit()

    return keywords_result
