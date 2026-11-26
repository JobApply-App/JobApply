"""
Hebrew job summaries for Hebrew-UI users (job_postings.jd_structured_he).

jd_structured is English by design: the scorer reads its requirement lines,
and the structuring prompt asks for English. A Hebrew interface therefore
showed English summaries on every card, even for jobs posted in Hebrew
(founder's call, 2026-11-26: summaries follow the interface language).

The enrichment loop calls translate_next() once per sweep. It translates the
English structure of up to _BATCH postings that sit in some Hebrew-UI user's
feed, best matches first, in one LLM call, and stores the result in
jd_structured_he. job_postings is shared, so a posting is translated once for
every Hebrew user. The English structure is never touched. A posting whose
English structure is re-written gets its translation cleared
(job_repository.update_jd_structured*) and is picked up again.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

_MODEL         = "claude-haiku-4-5"
_BATCH         = 4      # postings per call (~1.5k chars of JSON each)
_DAILY_BATCHES = 15     # global: 60 postings a day, well under a dollar of Haiku
_MAX_TOKENS    = 8000
_HEBREW        = re.compile(r"[א-ת]")
_LISTS         = ("responsibilities", "requirements", "advantages")
_TEXTS         = ("company_details", "role_overview", "additional_info")

_SYSTEM = (
    "You translate structured job descriptions from English to Hebrew for an "
    "Israeli job-search app. Input: a JSON array of objects. Output ONLY a JSON "
    "array with one object per input, in the same order, with exactly the same "
    "keys and the same number of items in every list. Translate every string "
    "value except company_name, which you copy unchanged. Keep company and "
    "product names, technologies, tools and acronyms (SQL, SaaS, B2B, CRM, "
    "Zendesk, QBR) in English, keep numbers exactly, and use gender-neutral "
    "Hebrew where it reads naturally (מנהל/ת). Do not add, drop or merge content."
)

# Postings whose translation came back unusable; not retried until restart.
_skipped: set[str] = set()


def _consume_daily() -> bool:
    """Reserve one of today's _DAILY_BATCHES (kv table, survives restarts)."""
    from backend.repositories import kv_repository
    key = f"jd_translation:{datetime.now(timezone.utc).date().isoformat()}"
    entry = kv_repository.get(key)
    try:
        used = int(entry.value) if entry else 0
    except (TypeError, ValueError):
        used = 0
    if used >= _DAILY_BATCHES:
        return False
    kv_repository.upsert(key, str(used + 1))
    return True


def _usable(source: dict, out: object) -> Optional[dict]:
    """The translation if it has the source's shape and is actually Hebrew."""
    if not isinstance(out, dict):
        return None
    result: dict = {"company_name": source.get("company_name", "")}
    for key in _TEXTS:
        val = out.get(key, "")
        if not isinstance(val, str) or (source.get(key) and not val.strip()):
            return None
        result[key] = val.strip()
    for key in _LISTS:
        src, val = source.get(key) or [], out.get(key)
        if not isinstance(val, list) or len(val) != len(src) or not all(isinstance(v, str) for v in val):
            return None
        result[key] = [v.strip() for v in val]
    text = " ".join([result[k] for k in _TEXTS] + [v for k in _LISTS for v in result[k]])
    if not _HEBREW.search(text):
        return None
    return result


def _parse(raw: str, sources: list[dict]) -> Optional[list[Optional[dict]]]:
    raw = re.sub(r"```(?:json)?", "", raw).strip()
    try:
        out = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(out, list) or len(out) != len(sources):
        return None
    return [_usable(src, o) for src, o in zip(sources, out)]


async def translate_next() -> int:
    """Translate one batch of Hebrew users' postings; return how many were saved."""
    import asyncio
    from backend.repositories import job_repository
    from backend.services.llm_client import call_llm, providers_unavailable

    try:
        rows = await asyncio.to_thread(
            job_repository.list_untranslated_jd_for_hebrew_users, _BATCH + len(_skipped),
        )
    except Exception as exc:
        logger.warning("[jd_translation] could not list postings: %s", exc)
        return 0
    pending = [(pid, jd) for pid, jd in rows if pid not in _skipped and isinstance(jd, dict)][:_BATCH]
    if not pending:
        return 0
    if providers_unavailable() or not _consume_daily():
        logger.info("[jd_translation] %d posting(s) waiting — today's %d batches used or AI providers down",
                    len(pending), _DAILY_BATCHES)
        return 0

    sources = [jd for _, jd in pending]
    try:
        result = await call_llm(
            system     = _SYSTEM,
            messages   = [{"role": "user", "content": json.dumps(sources, ensure_ascii=False)}],
            model      = _MODEL,
            max_tokens = _MAX_TOKENS,
            purpose    = "jd_translation",
        )
    except Exception as exc:
        # Never break the enrichment sweep.
        logger.warning("[jd_translation] LLM call failed: %s", exc)
        return 0
    translated = _parse(result.text, sources)
    if translated is None:
        logger.warning("[jd_translation] unusable response for %d posting(s)", len(sources))
        return 0

    saved = 0
    for (posting_id, source), he in zip(pending, translated):
        if he is None:
            _skipped.add(posting_id)
            continue
        if await asyncio.to_thread(job_repository.save_jd_structured_he, posting_id, source, he):
            saved += 1
    logger.info("[jd_translation] translated %d/%d posting(s)", saved, len(pending))
    return saved
