"""
linkedin_bulk_validator — re-checks open LinkedIn Bulk Import jobs for closure.

JOB-81 (Converge): ports the guest-mode page-fetch + closure-detection logic
originally written in backend/ingestion/validator_agent.py (deleted
2026-07-13, recovered from git history at commit fa8ee7a). The scraping
logic itself (fetch, parse, "No longer accepting applications" detection)
is provider-scraping, not Postgres-coupled, and is ported near-verbatim —
only the read/write side changes, from a dedicated ingestion_jobs Postgres
table to the main SQLite job_store.

Scope: only re-checks jobs this pipeline itself created (job_id prefixed
li-bulk-, see linkedin_bulk_scraper.py) for a given user. Deliberately does
NOT touch JOB-63's territory (continuous checks on a user's own
saved/applied ATS links) — different mechanism, different ticket, assigned
to someone else.
"""
from __future__ import annotations

import asyncio
import logging
import random
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

import aiohttp
from bs4 import BeautifulSoup

from backend.scrapers.linkedin_bulk_scraper import normalize_linkedin_job_url
import backend.repositories.job_repository as job_store

logger = logging.getLogger(__name__)

CLOSED_MARKER = "No longer accepting applications"

DEFAULT_CONCURRENCY = 5
MIN_DELAY_SECONDS = 1.0
MAX_DELAY_SECONDS = 3.0
REQUEST_TIMEOUT_SECONDS = 15

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

_JOB_ID_PREFIX = "li-bulk"


def _parse_relative_posted_at(text: str) -> Optional[datetime]:
    """Best-effort parse of LinkedIn's relative posting strings ('2 days ago')."""
    if not text:
        return None
    match = re.search(r"(\d+)\s+(day|hour|week|month|minute)s?\s+ago", text, re.I)
    if not match:
        return None
    amount, unit = int(match.group(1)), match.group(2).lower()
    now = datetime.now(timezone.utc)
    unit_map = {
        "minute": timedelta(minutes=amount),
        "hour":   timedelta(hours=amount),
        "day":    timedelta(days=amount),
        "week":   timedelta(weeks=amount),
        "month":  timedelta(days=amount * 30),
    }
    delta = unit_map.get(unit)
    return now - delta if delta else None


def _extract_job_details(html: str) -> dict:
    """Parse description text and posted-at timestamp out of a guest job page."""
    soup = BeautifulSoup(html, "html.parser")

    description_el = soup.select_one(
        ".description__text, .show-more-less-html__markup, [class*='description']"
    )
    description = description_el.get_text(separator="\n", strip=True) if description_el else None

    posted_at_el = soup.select_one(
        ".posted-time-ago__text, [class*='posted-time-ago'], time"
    )
    posted_text = posted_at_el.get_text(strip=True) if posted_at_el else ""
    linkedin_posted_at = _parse_relative_posted_at(posted_text)

    return {"description": description, "linkedin_posted_at": linkedin_posted_at}


async def _fetch_job_page(
    session: aiohttp.ClientSession, job_id: str, linkedin_id: str,
) -> tuple[str, Optional[str]]:
    url = normalize_linkedin_job_url(linkedin_id)
    try:
        async with session.get(
            url,
            headers={"User-Agent": USER_AGENT},
            timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_SECONDS),
        ) as response:
            if response.status != 200:
                logger.warning("[linkedin_bulk_validator] Job %s fetch returned HTTP %s", job_id, response.status)
                return job_id, None
            return job_id, await response.text()
    except Exception as exc:
        # Broad on purpose: expired/removed LinkedIn postings can return
        # malformed or non-UTF8 bodies, unexpected content types, or other
        # provider-side oddities beyond plain network errors. Any single
        # job's fetch failing must never abort the rest of the batch.
        logger.warning("[linkedin_bulk_validator] Job %s fetch failed: %s", job_id, exc)
        return job_id, None


async def _validate_one_job(
    job_id: str,
    linkedin_id: str,
    http_session: aiohttp.ClientSession,
    semaphore: asyncio.Semaphore,
) -> Optional[dict]:
    """Fetch + parse one job page. Returns an update payload, or None on fetch/expired failure."""
    try:
        async with semaphore:
            await asyncio.sleep(random.uniform(MIN_DELAY_SECONDS, MAX_DELAY_SECONDS))
            job_id, html = await _fetch_job_page(http_session, job_id, linkedin_id)

        if html is None:
            return None

        if CLOSED_MARKER in html:
            return {"job_id": job_id, "status": "closed"}

        details = _extract_job_details(html)
        return {"job_id": job_id, "status": "open", "description": details["description"]}
    except Exception as exc:
        # A single expired/malformed posting (bad markup, unexpected
        # redirect, etc.) must never take down the whole validation pass —
        # log it as a skipped record and let the batch continue.
        logger.warning(
            "[linkedin_bulk_validator] Job %s failed to validate, skipping: %s", job_id, exc,
        )
        return None


def _extract_linkedin_id(apply_url: Optional[str]) -> Optional[str]:
    """Pull the numeric LinkedIn job ID back out of a normalized apply_url."""
    if not apply_url:
        return None
    match = re.search(r"(\d{9,10})", apply_url)
    return match.group(1) if match else None


async def validate_open_linkedin_bulk_jobs(user_id: str, concurrency: int = DEFAULT_CONCURRENCY) -> dict:
    """
    Re-validate every still-open job this pipeline created for user_id against
    its live LinkedIn guest page. Closed postings are marked via
    job_store.mark_closed(); still-open ones get a refreshed jd_text.
    """
    all_jobs = job_store.get_all(user_id)
    bulk_open = [
        j for j in all_jobs
        if j.job_id.startswith(f"{_JOB_ID_PREFIX}-") and j.is_open
    ]

    if not bulk_open:
        logger.info("[linkedin_bulk_validator] No open bulk-import jobs to validate for user_id=%s", user_id)
        return {"checked": 0, "closed": 0, "still_open": 0, "failed": 0}

    targets = [(j.job_id, _extract_linkedin_id(j.apply_url)) for j in bulk_open]
    targets = [(jid, lid) for jid, lid in targets if lid is not None]

    semaphore = asyncio.Semaphore(concurrency)
    async with aiohttp.ClientSession() as http_session:
        tasks = [_validate_one_job(jid, lid, http_session, semaphore) for jid, lid in targets]
        # return_exceptions=True is defense-in-depth: _validate_one_job already
        # catches everything internally, but this guarantees one job's
        # unhandled exception can never cancel the rest of the in-flight batch.
        results = await asyncio.gather(*tasks, return_exceptions=True)

    updates = []
    failed  = 0
    for jid_lid, result in zip(targets, results):
        if isinstance(result, Exception):
            logger.warning(
                "[linkedin_bulk_validator] Job %s raised during validation, skipping: %s",
                jid_lid[0], result,
            )
            failed += 1
        elif result is None:
            failed += 1
        else:
            updates.append(result)
    closed = 0

    for update in updates:
        try:
            if update["status"] == "closed":
                job_store.mark_closed(update["job_id"], user_id)
                closed += 1
            elif update.get("description"):
                job_store.update_jd_text(update["job_id"], update["description"])
        except Exception as exc:
            logger.warning(
                "[linkedin_bulk_validator] Failed to persist update for job %s, skipping: %s",
                update["job_id"], exc,
            )

    summary = {
        "checked":    len(targets),
        "closed":     closed,
        "still_open": len(updates) - closed,
        "failed":     failed,
    }
    logger.info("[linkedin_bulk_validator] Validation pass complete: %s", summary)
    return summary
