"""
JD Backfill Service — fetches full job description text for jobs that currently
hold only thin proxy content (title + company, < 100 chars).

Entry point:
    await backfill_jd_text(user_id, min_score=50.0)

Behaviour:
1. Selects jobs for user_id with score >= min_score and short/missing jd_text.
2. Scrapes each job's apply_url using the existing url_scraper.scrape_job_post().
3. Persists the raw_text via job_store.update_jd_text().
4. After the loop, calls feed_service.force_rescore_all() so proficiency-aware
   ATS scoring fires on the newly populated JD content.

Rate limiting: 1.0–1.5 s jitter between requests to avoid hammering sources.
LinkedIn URLs returning HTTP 999 / 403 are caught and skipped gracefully.
"""
from __future__ import annotations

import asyncio
import logging
import random
from typing import TypedDict

from backend.repositories import job_repository as job_store
from backend.services import jd_structure_service
from backend.scrapers.url_router import scrape_jd_text

logger = logging.getLogger(__name__)

# Minimum chars for a raw_text to be considered a real JD worth keeping.
_MIN_JD_CHARS = 100

# Per-request delay range (seconds) — respects robots.txt spirit.
_DELAY_MIN = 1.0
_DELAY_MAX = 1.5


class BackfillResult(TypedDict):
    queued:  int   # number of jobs selected for backfill
    fetched: int   # successfully scraped + saved
    failed:  int   # scraping failed or text too short


async def backfill_jd_text(
    user_id:   str,
    min_score: float = 50.0,
) -> BackfillResult:
    """
    Fetch and persist JD text for all eligible jobs, then trigger a full rescore.

    This function is designed to run as a FastAPI BackgroundTasks coroutine.
    It never raises — all per-job errors are caught and logged.
    """
    candidates = job_store.get_jobs_missing_jd_text(user_id, min_score=min_score)
    queued  = len(candidates)
    fetched = 0
    failed  = 0

    logger.info(
        "[jd_backfill] Starting backfill for user=%s — %d candidate job(s) "
        "(score >= %.1f, jd_text missing/short)",
        user_id, queued, min_score,
    )

    if not candidates:
        return {"queued": 0, "fetched": 0, "failed": 0}

    for i, job in enumerate(candidates):
        url = job.apply_url
        if not url:
            failed += 1
            continue

        try:
            # Run the synchronous scraper in a thread to avoid blocking the
            # event loop.  asyncio.to_thread is available in Python ≥ 3.9.
            # scrape_jd_text routes to a site-specific parser (Gotfriends,
            # Dialog, Nisha, …) or falls back to the generic html scraper.
            text = await asyncio.to_thread(scrape_jd_text, url)
            text = text.strip()

            if len(text) < _MIN_JD_CHARS:
                logger.debug(
                    "[jd_backfill] Skipping job %s (%s @ %s) — text too short (%d chars)",
                    job.job_id, job.title, job.company, len(text),
                )
                failed += 1
            else:
                job_store.update_jd_text(job.job_id, text)
                fetched += 1
                logger.info(
                    "[jd_backfill] Saved JD for job %s (%s @ %s) — %d chars",
                    job.job_id, job.title, job.company, len(text),
                )
                # Structure the JD via LLM so the job can satisfy the readiness gate.
                structured_ok = False
                try:
                    structured = await jd_structure_service.structure_jd(text, user_id=user_id, job_id=job.job_id)
                    if structured:
                        job_store.update_jd_structured(job.job_id, structured)
                        structured_ok = True
                        logger.debug("[jd_backfill] Structured JD saved for job %s", job.job_id)
                        extracted_company = jd_structure_service.extract_company_from_structured(structured)
                        if extracted_company:
                            job_store.update_company(job.job_id, extracted_company)
                            logger.info(
                                "[jd_backfill] company overwritten → '%s' (was '%s') — job_id=%s",
                                extracted_company, job.company, job.job_id,
                            )
                except Exception as exc:
                    logger.warning("[jd_backfill] Structuring failed for job %s: %s", job.job_id, exc)

                # If the job was still 'analysing' (never enriched by discovery),
                # flip it to 'new' as soon as structuring succeeds so it surfaces
                # in the feed without waiting for the end-of-batch rescore.
                if structured_ok and job.status == "analysing":
                    job_store.update_status(job.job_id, user_id, "new")
                    logger.info(
                        "[jd_backfill] Flipped job %s → 'new' after structuring", job.job_id
                    )

        except Exception as exc:
            failed += 1
            logger.warning(
                "[jd_backfill] Failed to scrape job %s (%s): %s",
                job.job_id, url, exc,
            )

        # Rate-limit between requests; skip delay after the last job.
        if i < len(candidates) - 1:
            await asyncio.sleep(random.uniform(_DELAY_MIN, _DELAY_MAX))

    logger.info(
        "[jd_backfill] Backfill complete — user=%s queued=%d fetched=%d failed=%d",
        user_id, queued, fetched, failed,
    )

    # Re-score only if at least one JD was successfully fetched so that
    # proficiency-aware tags reflect the new content.
    if fetched > 0:
        try:
            from backend.services import feed_service
            scored = await feed_service.force_rescore_all(user_id)
            logger.info(
                "[jd_backfill] Auto-rescore after backfill: %d jobs re-scored", scored
            )
        except Exception as exc:
            logger.warning("[jd_backfill] Auto-rescore failed: %s", exc)

    return {"queued": queued, "fetched": fetched, "failed": failed}
