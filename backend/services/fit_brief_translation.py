"""
One-time Hebrew backfill of "Ariel's analysis" (user_job_matches.fit_brief).

#81 made the scorer write fit_brief in the user's UI language, but only for
jobs scored after it. A Hebrew user's existing jobs kept their English
analysis (96 of 100 for the first tester), and a job is re-scored only when
its JD or the profile changes — so they would stay English for weeks.

The enrichment loop calls translate_all() once per sweep. It covers every
user whose UI is Hebrew, not only the pipeline's onboarding-complete users —
accounts that predate that flag hold the most English briefs. Per user it reads at most _BATCH briefs with no Hebrew letter, translates them
in a single LLM call, and writes back only those that came back in Hebrew.
Scores are untouched. Once a user has nothing left, they are skipped for
the rest of the process, so a finished backfill costs no further queries.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

_MODEL      = "claude-haiku-4-5"
_BATCH      = 20
_MAX_TOKENS = 4000
_HEBREW     = re.compile(r"[א-ת]")

_SYSTEM = (
    "You translate short job-fit analyses from English to Hebrew for an Israeli "
    "job-search app. Keep product names, technologies and acronyms (SQL, SaaS, "
    "B2B, PRD) in English, and keep numbers exactly. Do not add or remove "
    "content. Output ONLY a JSON array of strings, one translation per input, "
    "in the same order."
)

# Hebrew-UI users, read once per process (users scored after #81 need nothing).
_users: Optional[list[str]] = None

# Users whose backlog is empty in this process, and briefs that came back
# unusable (kept English, not retried); both reset on restart.
_done: set[str] = set()
_skipped: dict[str, set[str]] = {}


def _wants_hebrew(user_id: str) -> bool:
    from backend.repositories import profile_repository
    try:
        return profile_repository.get_locales(user_id).get("ui_locale") == "he"
    except profile_repository.LocalesUnavailable:
        return False


def _parse(raw: str, expected: int) -> Optional[list[str]]:
    raw = re.sub(r"```(?:json)?", "", raw).strip()
    try:
        out = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(out, list) or len(out) != expected or not all(isinstance(s, str) for s in out):
        return None
    return out


async def translate_batch(user_id: str) -> int:
    """Translate up to _BATCH English briefs for user_id; return how many were saved."""
    if user_id in _done:
        return 0
    if not _wants_hebrew(user_id):
        _done.add(user_id)
        return 0

    import asyncio
    from backend.repositories import job_repository
    from backend.services import llm_budget
    from backend.services.llm_client import call_llm

    skipped = _skipped.setdefault(user_id, set())
    rows = await asyncio.to_thread(
        job_repository.list_untranslated_fit_briefs, user_id, _BATCH + len(skipped),
    )
    pending = [r for r in rows if r[0] not in skipped][:_BATCH]
    if not pending:
        _done.add(user_id)
        logger.info("[fit_brief_translation] backlog empty for user=%s", user_id)
        return 0
    # One batch costs one unit of the background budget, like one enriched job.
    if not llm_budget.background_llm_allowed(user_id) or not llm_budget.consume(user_id):
        return 0

    sources = [brief for _, brief in pending]
    try:
        result = await call_llm(
            system     = _SYSTEM,
            messages   = [{"role": "user", "content": json.dumps(sources, ensure_ascii=False)}],
            model      = _MODEL,
            max_tokens = _MAX_TOKENS,
            purpose    = "fit_brief_translation",
            user_id    = user_id,
        )
    except Exception as exc:
        # Never break the enrichment sweep for the users after this one.
        logger.warning("[fit_brief_translation] LLM call failed for user=%s: %s", user_id, exc)
        return 0
    translated = _parse(result.text, len(sources))
    if translated is None:
        logger.warning("[fit_brief_translation] unusable response for user=%s, %d briefs", user_id, len(sources))
        return 0

    saved = 0
    for (job_id, old), new in zip(pending, translated):
        new = new.strip()
        if not _HEBREW.search(new) or len(new) > 2 * len(old) + 100:
            skipped.add(job_id)
            continue
        if await asyncio.to_thread(job_repository.replace_fit_brief, job_id, user_id, old, new):
            saved += 1
    logger.info("[fit_brief_translation] user=%s translated %d/%d", user_id, saved, len(sources))
    return saved


async def translate_all() -> int:
    """One batch for each Hebrew-UI user with English briefs left; return how many were saved."""
    global _users
    import asyncio
    from backend.repositories import profile_repository
    if _users is None:
        try:
            _users = await asyncio.to_thread(profile_repository.list_hebrew_ui_user_ids)
        except Exception as exc:
            logger.warning("[fit_brief_translation] could not list Hebrew users: %s", exc)
            return 0
        logger.info("[fit_brief_translation] %d Hebrew-UI user(s) to check", len(_users))
    saved = 0
    for user_id in _users:
        if user_id not in _done:
            saved += await translate_batch(user_id)
    return saved
