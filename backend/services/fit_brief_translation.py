"""
"Ariel's analysis" (user_job_matches.fit_brief) in the interface language.

The scorer writes fit_brief once, in the interface language of that moment
(#81). This sweep used to translate English briefs into Hebrew *in place*,
so a user who later switched to English saw Hebrew on every card, with no
English left to go back to (Ron, 2026-11-28: 213 of 214 briefs).

Now fit_brief stays as the scorer wrote it, and its translation into the
user's interface language is stored beside it, in fit_brief_i18n
(job_repository.save_fit_brief_translation). Both directions: Hebrew to
English and English to Hebrew. The card shows the translation for its
language and falls back to fit_brief until one exists.

The enrichment loop calls translate_all() once per sweep. For each user with
a stored interface language it reads at most _BATCH briefs not written in
that language and not yet translated into it, translates them in one LLM
call, and stores those that came back in the right language. Scores are
untouched. A user with nothing left is skipped for the rest of the process,
until their interface language changes.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

_MODEL      = "claude-haiku-4-5"
_BATCH      = 20
# Per user a day: 300 briefs, enough to turn a whole feed around in the day
# the interface language changes; a few cents of Haiku at most.
_DAILY_BATCHES = 15
_MAX_TOKENS = 4000
_HEBREW     = re.compile(r"[א-ת]")
_LANGS      = ("he", "en")

_SYSTEM = {
    "he": (
        "You translate short job-fit analyses from English to Hebrew for an Israeli "
        "job-search app. Keep product names, technologies and acronyms (SQL, SaaS, "
        "B2B, PRD) in English, and keep numbers exactly. Do not add or remove "
        "content. Output ONLY a JSON array of strings, one translation per input, "
        "in the same order."
    ),
    "en": (
        "You translate short job-fit analyses from Hebrew to English for a "
        "job-search app. Keep company and product names, technologies and acronyms "
        "as they are, and keep numbers exactly. Write natural, concise English. Do "
        "not add or remove content. Output ONLY a JSON array of strings, one "
        "translation per input, in the same order."
    ),
}

# Each user's interface language, re-read every sweep (one small SELECT every
# 2 minutes), so a language switch is picked up without a restart.
_locales: dict[str, str] = {}

# (user, language) pairs whose backlog is empty in this process, and briefs
# that came back unusable (kept as written, not retried); reset on restart.
_done: set[tuple[str, str]] = set()
_skipped: dict[tuple[str, str], set[str]] = {}


def _consume_daily(user_id: str) -> bool:
    """Reserve one batch of today's _DAILY_BATCHES for user_id (kv table, survives restarts)."""
    from backend.repositories import kv_repository
    key = f"fit_brief_translation:{user_id}:{datetime.now(timezone.utc).date().isoformat()}"
    entry = kv_repository.get(key)
    try:
        used = int(entry.value) if entry else 0
    except (TypeError, ValueError):
        used = 0
    if used >= _DAILY_BATCHES:
        return False
    kv_repository.upsert(key, str(used + 1))
    return True


def _in_language(text: str, lang: str) -> bool:
    """Hebrew has Hebrew letters; English has none (product names stay Latin in both)."""
    return bool(_HEBREW.search(text)) == (lang == "he")


def _parse(raw: str, expected: int) -> Optional[list[str]]:
    raw = re.sub(r"```(?:json)?", "", raw).strip()
    try:
        out = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(out, list) or len(out) != expected or not all(isinstance(s, str) for s in out):
        return None
    return out


async def translate_batch(user_id: str, lang: str) -> int:
    """Translate up to _BATCH of user_id's briefs into lang; return how many were saved."""
    if lang not in _LANGS or (user_id, lang) in _done:
        return 0

    import asyncio
    from backend.repositories import job_repository
    from backend.services.llm_client import call_llm, providers_unavailable

    skipped = _skipped.setdefault((user_id, lang), set())
    rows = await asyncio.to_thread(
        job_repository.list_briefs_to_translate, user_id, lang, _BATCH + len(skipped),
    )
    pending = [r for r in rows if r[0] not in skipped][:_BATCH]
    if not pending:
        _done.add((user_id, lang))
        logger.info("[fit_brief_translation] nothing left to translate into %s for user=%s", lang, user_id)
        return 0
    # Its own daily cap, not the scoring budget (llm_budget): a translation
    # must never cost a user a scored job.
    if providers_unavailable() or not _consume_daily(user_id):
        logger.info(
            "[fit_brief_translation] user=%s has %d brief(s) waiting for %s — "
            "today's %d batches used or AI providers down", user_id, len(pending), lang, _DAILY_BATCHES,
        )
        return 0

    sources = [brief for _, brief in pending]
    try:
        result = await call_llm(
            system     = _SYSTEM[lang],
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
    for (job_id, src), new in zip(pending, translated):
        new = new.strip()
        if not new or not _in_language(new, lang) or len(new) > 2 * len(src) + 100:
            skipped.add(job_id)
            continue
        if await asyncio.to_thread(job_repository.save_fit_brief_translation, job_id, user_id, src, lang, new):
            saved += 1
    logger.info("[fit_brief_translation] user=%s translated %d/%d into %s", user_id, saved, len(sources), lang)
    return saved


async def translate_all() -> int:
    """One batch for each user whose briefs are not all in their interface language."""
    import asyncio
    from backend.repositories import profile_repository
    try:
        locales = await asyncio.to_thread(profile_repository.list_ui_locales)
    except Exception as exc:
        logger.warning("[fit_brief_translation] could not list interface languages: %s", exc)
        return 0
    # A user who switched language is checked again for the new one.
    for user_id, lang in locales.items():
        if _locales.get(user_id) not in (None, lang):
            _done.discard((user_id, lang))
            logger.info("[fit_brief_translation] user=%s switched to %s, to check", user_id, lang)
    _locales.clear()
    _locales.update(locales)
    saved = 0
    for user_id, lang in locales.items():
        if (user_id, lang) not in _done:
            saved += await translate_batch(user_id, lang)
    return saved
