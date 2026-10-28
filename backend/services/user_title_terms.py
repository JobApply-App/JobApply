"""
Per-user job-title search terms: which jobs are "relevant" to THIS user.

Why this exists
----------------
Every automated source used to admit a job only if its title matched
TARGET_SEARCH_QUERIES (config.py) — one global list built from the founder's
own target roles (Product, Customer Success, Operations). For every other user
the feed was filtered through someone else's career: in production the
first testers were a government-affairs lead, an FP&A analyst and a digital
marketing manager, and of 8,560 catalog jobs only ~7% could ever reach any of
them, all of them Product/CS roles none of them wanted.

What it does
-------------
1. Source titles, most explicit first:
     a. the roles the user picked in onboarding (role_preferences), else
     b. the most recent job titles on their parsed CV (cv_data.experiences).
   A user with neither gets no automatic matches until they name a role or
   upload a readable CV. The global list used to be the fallback, but it is
   the founder's own roles, and a new user's feed filled with them.
2. One cheap LLM call expands those into title search terms: synonyms,
   common variants and Hebrew equivalents ("FP&A Analyst" -> "Financial
   Analyst", "אנליסט פיננסי", ...). Exact substrings alone miss most real
   postings; a raw CV title like "Head of Policy and Governmental Affairs"
   matches almost nothing verbatim.
3. The result is cached in profile_answers under `title_search_terms`
   together with a hash of the source titles, and regenerated only when those
   titles change. An LLM failure falls back to a deterministic expansion
   (seniority words stripped) rather than to the global list.

This is a feed-admission filter, not scoring. It decides which postings get
scored at all; match_score_service still scores each one on the full CV, so
the Core Scoring Principles are untouched. Exploration Freedom is served,
not violated: a user who picks a pivot role in onboarding gets that role's
jobs even if their CV has never held the title.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from typing import Optional

from sqlalchemy import text

logger = logging.getLogger(__name__)

_ANSWER_KEY      = "title_search_terms"
_MODEL           = "claude-haiku-4-5"
_MAX_TERMS       = 40
_CV_TITLES_USED  = 3      # most recent CV roles, when the user picked none

# Leading/trailing words that make a title more specific without changing the
# profession. Stripping them is the deterministic fallback expansion.
_SENIORITY_WORDS = re.compile(
    r"\b(senior|sr\.?|junior|jr\.?|lead|principal|head of|chief|vp( of)?|"
    r"director( of)?|associate|assistant|intern|staff|group|global|regional)\b",
    re.IGNORECASE,
)

_SYSTEM = (
    "You generate job-title search terms for a job board filter. Given a "
    "person's target job titles, return the titles and phrases that real job "
    "postings use for the SAME profession: the titles themselves, common "
    "synonyms and variants, abbreviations used in titles, and Hebrew "
    "equivalents (Israeli job boards post in Hebrew; include both masculine "
    "and feminine forms where they differ). Stay inside the profession — do "
    "not drift to adjacent careers. Prefer phrases of 1-4 words that would "
    "appear inside a posting title. Return ONLY a JSON array of strings."
)


# ── Sources ───────────────────────────────────────────────────────────────────

def _profile(user_id: str) -> dict:
    from backend.repositories import profile_repository
    return profile_repository.get_profile_json(user_id) or {}


def _cv_experiences(profile: dict) -> list:
    """The CV's work entries: older uploads under cv_data.experiences, the
    relational schema as top-level "experience" (cv_claims)."""
    cv = profile.get("cv_data") or {}
    return (cv.get("experiences") if isinstance(cv, dict) else None) or profile.get("experience") or []


def cv_needs_reupload(profile: dict) -> bool:
    """
    True when the user uploaded a CV but no work experience was saved from it.

    Before #55 (2026-10-16) an upload the model failed to read — or a file that
    was not a CV — was saved as an empty result and reported as success. Those
    users have a CV on record that gives matching nothing, and no way to know.
    """
    cv = profile.get("cv_data")
    uploaded = bool(profile.get("cv_imported_at")) or (isinstance(cv, dict) and bool(cv))
    return uploaded and not _cv_experiences(profile)


def source_titles(profile: dict) -> list[str]:
    """The titles that describe what this user is looking for. Empty = no signal."""
    # Roles the user picked. Onboarding writes role_preferences.target_titles;
    # Ariel's update_career_goals / update_profile_base tools write
    # career_goals.target_roles. Reading only the first made a user who told
    # Ariel their role look like they had picked nothing (production,
    # 2026-10-28: user_preferences held their role, the cache held no terms).
    prefs = profile.get("role_preferences") or {}
    goals = profile.get("career_goals") or {}
    if not isinstance(prefs, dict):
        prefs = {}
    if not isinstance(goals, dict):
        goals = {}
    raw_picked = prefs.get("target_titles") or goals.get("target_roles") or []
    picked = [str(t).strip() for t in raw_picked if str(t).strip()]
    if picked:
        return picked[:10]

    # CV titles. Older uploads live under cv_data.experiences; the relational
    # schema returns the same entries as top-level "experience" (cv_claims).
    # Reading only the old key left users with a CV in cv_claims — the
    # founder's own account among them — with no terms at all.
    titles: list[str] = []
    for exp in _cv_experiences(profile):
        if not isinstance(exp, dict):
            continue
        t = str(exp.get("title") or exp.get("role") or "").strip()
        if t and t.lower() not in {x.lower() for x in titles}:
            titles.append(t)
        if len(titles) >= _CV_TITLES_USED:
            break
    return titles


def _hash(titles: list[str]) -> str:
    return hashlib.sha256(json.dumps(sorted(t.lower() for t in titles)).encode()).hexdigest()[:16]


# ── Expansion ────────────────────────────────────────────────────────────────

def deterministic_terms(titles: list[str]) -> list[str]:
    """Titles plus their seniority-stripped core ("Senior FP&A Analyst" -> "FP&A Analyst")."""
    out: list[str] = []
    for t in titles:
        for cand in (t, re.sub(r"\s+", " ", _SENIORITY_WORDS.sub(" ", t)).strip(" ,-&/")):
            if len(cand) >= 3 and cand.lower() not in {x.lower() for x in out}:
                out.append(cand)
    return out


def _clean_terms(raw: list, titles: list[str]) -> list[str]:
    out: list[str] = []
    for item in [*titles, *raw]:
        s = str(item or "").strip()
        if 2 <= len(s) <= 60 and s.lower() not in {x.lower() for x in out}:
            out.append(s)
    return out[:_MAX_TERMS]


async def expand_titles(titles: list[str], user_id: str) -> list[str]:
    """LLM expansion of titles into search terms; deterministic fallback on any failure."""
    from backend.services.llm_client import call_llm

    try:
        result = await call_llm(
            system     = _SYSTEM,
            messages   = [{"role": "user", "content": "Target titles:\n" + "\n".join(f"- {t}" for t in titles)}],
            model      = _MODEL,
            max_tokens = 800,
            purpose    = "title_search_terms",
            user_id    = user_id,
        )
        raw = result.text.strip()
        raw = re.sub(r"```(?:json)?", "", raw).strip()
        start, end = raw.find("["), raw.rfind("]")
        parsed = json.loads(raw[start:end + 1]) if start != -1 and end != -1 else None
        if not isinstance(parsed, list) or not parsed:
            raise ValueError("expansion was not a non-empty JSON array")
        return _clean_terms(parsed, titles)
    except Exception as exc:
        # Loud on purpose: a silent fallback here would look like a working
        # expansion that just happens to match less.
        logger.warning("[title_terms] LLM expansion failed for user=%s, using deterministic: %s", user_id, exc)
        return _clean_terms(deterministic_terms(titles), titles)


# ── Cache ────────────────────────────────────────────────────────────────────

def _store(user_id: str, payload: dict) -> None:
    from backend.core.database import ENGINE
    with ENGINE.begin() as conn:
        conn.execute(
            text("DELETE FROM public.profile_answers WHERE user_id = CAST(:u AS uuid) AND question_id = :q"),
            {"u": user_id, "q": _ANSWER_KEY},
        )
        conn.execute(
            text("""
                INSERT INTO public.profile_answers (user_id, question_id, answer, updated_at)
                VALUES (CAST(:u AS uuid), :q, CAST(:a AS jsonb), now())
            """),
            {"u": user_id, "q": _ANSWER_KEY, "a": json.dumps(payload)},
        )


async def refresh_user_terms(user_id: str, *, force: bool = False) -> Optional[list[str]]:
    """
    Make sure the cached terms match the user's current titles; return them.

    Returns None when the user has no titles at all — the caller then makes
    no automatic matches. Cheap when nothing changed (one profile read).
    """
    profile = _profile(user_id)
    titles = source_titles(profile)
    if not titles:
        return None

    cached = profile.get(_ANSWER_KEY) or {}
    digest = _hash(titles)
    if not force and cached.get("source_hash") == digest and cached.get("terms"):
        return list(cached["terms"])

    terms = await expand_titles(titles, user_id)
    _store(user_id, {"source_hash": digest, "source_titles": titles, "terms": terms})
    logger.info("[title_terms] user=%s titles=%s -> %d terms", user_id, titles, len(terms))
    return terms


def cached_user_terms(user_id: str) -> Optional[list[str]]:
    """Synchronous read of the cached terms (no LLM). None = no terms, no automatic matches."""
    terms = (_profile(user_id).get(_ANSWER_KEY) or {}).get("terms")
    return list(terms) if terms else None


def cached_terms_for_users(user_ids: list[str], *, limit: int = 1000) -> dict[str, list[str]]:
    """
    Cached terms for many users in ONE narrow query (no LLM, no profile read).

    For background loops that need every user's terms at once. Unlike
    cached_user_terms() it does not load the whole profile (CV, answers, ...)
    per user: it reads only the terms array out of one profile_answers row
    each, so a cycle over every user costs ~1-2 KB of database egress per user
    (the Supabase free-plan egress cap once suspended the whole product).
    Users with nothing cached are simply absent from the result.
    """
    ids = [u for u in user_ids if u and u.strip()]
    if not ids:
        return {}
    from backend.core.database import ENGINE
    with ENGINE.connect() as conn:
        rows = conn.execute(
            text("""
                SELECT CAST(user_id AS text), answer -> 'terms'
                FROM public.profile_answers
                WHERE question_id = :q AND user_id = ANY(CAST(:ids AS uuid[]))
                LIMIT :lim
            """),
            {"q": _ANSWER_KEY, "ids": ids, "lim": limit},
        ).fetchall()
    out: dict[str, list[str]] = {}
    for uid, terms in rows:
        if isinstance(terms, str):
            terms = json.loads(terms)
        if isinstance(terms, list) and terms:
            out[uid] = [str(t) for t in terms if str(t).strip()]
    return out
