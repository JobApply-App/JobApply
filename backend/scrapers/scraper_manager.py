"""
ScraperManager — registry and parallel runner for all job-source adapters.

Usage (API route or background task)
-------------------------------------
    from backend.scrapers.scraper_manager import SCRAPER_MANAGER
    new_jobs = await SCRAPER_MANAGER.run_all()

Adding a new adapter
---------------------
1. Subclass BaseScraper (base_scraper.py).
2. Implement fetch_jobs() → list[JobMatch].
3. Add the adapter class to SCRAPER_CLASSES below.
4. Register instances with SCRAPER_MANAGER.register(...) at startup.

Concurrency model
-----------------
run_all() fires every registered scraper simultaneously via asyncio.gather().
Individual scrapers are responsible for their own internal concurrency
(bounded Semaphore for detail pages, parallel keyword searches, etc.).
Exceptions in any one scraper are caught and logged; others continue.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Dict, Optional, Type

from backend.schemas.job import JobMatch
from backend.scrapers.base_scraper import BaseScraper, make_tenant_job_id
import backend.repositories.job_repository as job_store

logger = logging.getLogger(__name__)

# ── Adapter registry — maps adapter string → class ───────────────────────────
# Import adapters here so scraper_from_config can resolve them by name.
from backend.scrapers.comeet_adapter     import ComeetAdapter       # noqa: E402
from backend.scrapers.gotfriends_scraper import GotfriendsScraper   # noqa: E402
from backend.scrapers.dialog_scraper     import DialogScraper        # noqa: E402
from backend.scrapers.nisha_scraper      import NishaScraper         # noqa: E402
from backend.scrapers.drushim_scraper    import DrushimScraper       # noqa: E402
from backend.scrapers.alljobs_scraper    import AllJobsScraper       # noqa: E402

SCRAPER_CLASSES: Dict[str, Type[BaseScraper]] = {
    "comeet":      ComeetAdapter,
    "gotfriends":  GotfriendsScraper,
    "dialog":      DialogScraper,
    "nisha":       NishaScraper,
    "drushim":     DrushimScraper,
    "alljobs":     AllJobsScraper,
}


class ScraperManager:
    """
    Maintains a registry of BaseScraper instances and orchestrates their
    parallel execution.  Results are deduplicated against the DB by apply_url
    before being persisted.
    """

    def __init__(self) -> None:
        self._scrapers: list[BaseScraper] = []

    # ── Registry ──────────────────────────────────────────────────────────────

    def register(self, scraper: BaseScraper) -> None:
        """Add a scraper to the registry.  Duplicates are allowed (idempotent save)."""
        self._scrapers.append(scraper)
        logger.info(
            "[ScraperManager] Registered %s → %s",
            scraper.__class__.__name__, scraper.company_name,
        )

    def clear(self) -> None:
        """Remove all registered scrapers (useful in tests)."""
        self._scrapers.clear()

    @property
    def scraper_count(self) -> int:
        return len(self._scrapers)

    # ── Execution ─────────────────────────────────────────────────────────────

    async def _safe_fetch(self, scraper: BaseScraper) -> list[JobMatch]:
        """
        Run one scraper, returning an empty list on any unhandled exception.
        Wrapping individually means a single broken scraper never aborts the run.
        """
        try:
            return await scraper.fetch_jobs()
        except Exception as exc:
            logger.exception(
                "[ScraperManager] Unhandled error in %s.fetch_jobs(): %s",
                scraper.__class__.__name__, exc,
            )
            return []

    async def run_all(self, user_id: Optional[str] = None) -> int:
        """
        Run every registered scraper in parallel via asyncio.gather(), save new
        jobs to the store, and return the total count of newly persisted jobs.

        Parameters
        ----------
        user_id : str | None
            When supplied, every newly saved job is stamped with this user_id
            so it appears immediately in the correct user's feed.  When None,
            each scraper's own user_id (set at construction time) is used.

        All scrapers fire concurrently.  After all complete their job lists are
        merged, deduplicated, relevancy-gated, and saved up to MAX_RELEVANT_JOBS.
        """
        from backend.config import MAX_RELEVANT_JOBS

        if not self._scrapers:
            logger.info("[ScraperManager] No scrapers registered — nothing to run.")
            return 0

        logger.info(
            "[ScraperManager] Launching %d scraper(s) in parallel…",
            len(self._scrapers),
        )

        # ── Fire all scrapers concurrently ────────────────────────────────────
        outcomes: list[list[JobMatch]] = await asyncio.gather(
            *[self._safe_fetch(s) for s in self._scrapers]
        )

        # ── Merge, cap, and save results ──────────────────────────────────────
        total_new = 0
        for scraper, jobs in zip(self._scrapers, outcomes):
            if total_new >= MAX_RELEVANT_JOBS:
                logger.info(
                    "[ScraperManager] Hit MAX_RELEVANT_JOBS=%d — stopping.", MAX_RELEVANT_JOBS
                )
                break
            remaining = MAX_RELEVANT_JOBS - total_new
            saved = self._save_new(jobs, limit=remaining, user_id=user_id)
            logger.info(
                "[ScraperManager] %s — %d fetched, %d new (total %d/%d)",
                scraper.company_name, len(jobs), saved,
                total_new + saved, MAX_RELEVANT_JOBS,
            )
            total_new += saved

        logger.info("[ScraperManager] run_all complete — %d new jobs saved.", total_new)
        return total_new

    async def run_one(self, company_name: str, user_id: Optional[str] = None) -> Optional[int]:
        """
        Run the first registered scraper whose company_name matches.
        Returns the count of new jobs saved, or None if no match found.
        """
        from backend.config import MAX_RELEVANT_JOBS

        for scraper in self._scrapers:
            if scraper.company_name.lower() == company_name.lower():
                jobs  = await scraper.fetch_jobs()
                saved = self._save_new(jobs, limit=MAX_RELEVANT_JOBS, user_id=user_id)
                logger.info(
                    "[ScraperManager] run_one(%s) — %d fetched, %d new",
                    company_name, len(jobs), saved,
                )
                return saved
        logger.warning("[ScraperManager] No scraper registered for '%s'", company_name)
        return None

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _save_new(
        jobs: list[JobMatch],
        limit: Optional[int] = None,
        user_id: Optional[str] = None,
    ) -> int:
        """
        Upsert jobs with source priority, up to *limit* new inserts.

        Parameters
        ----------
        user_id : str | None
            When supplied, overrides each job's user_id before saving so new
            jobs land in the authenticated user's feed rather than 'default'.

        The relevancy gate is re-applied here as a safety net — individual
        scrapers should have already filtered, but Comeet / other company-site
        adapters don't always run keyword searches, so this catches any
        residual irrelevant postings before they hit the DB.

        Returns count of net-new inserts.
        """
        from backend.scrapers.relevancy import is_title_relevant

        saved = 0
        for job in jobs:
            if limit is not None and saved >= limit:
                break
            # Safety-net: gate out irrelevant titles even from company-site scrapers
            if not is_title_relevant(job.title):
                logger.debug(
                    "[ScraperManager] SKIP (irrelevant): '%s' @ %s",
                    job.title, job.company,
                )
                continue
            # Stamp the correct owner before persisting. job_id is salted with
            # user_id here too — it's a deterministic hash of the apply URL
            # alone (make_job_id), so two different users scraping the same
            # posting would otherwise collide on the jobs table's PK (JOB-92).
            if user_id is not None:
                job = job.model_copy(update={
                    "user_id": user_id,
                    "job_id": make_tenant_job_id(job.job_id, user_id),
                })
            try:
                is_new = job_store.save_with_source_priority(job)
                if is_new:
                    saved += 1
            except Exception as exc:
                logger.warning(
                    "[ScraperManager] Failed to save job %s (%s): %s",
                    job.job_id, job.title, exc,
                )
        return saved


# ── Module-level singleton ────────────────────────────────────────────────────
# Import and register scrapers at app startup in main.py or via the API.

SCRAPER_MANAGER = ScraperManager()


# ── Convenience: build a scraper from a plain config dict ─────────────────────

def scraper_from_config(config: dict) -> Optional[BaseScraper]:
    """
    Instantiate the correct adapter from a config dict using SCRAPER_CLASSES.

    Expected keys:
        company_name  – human-readable name (required)
        company_url   – careers page URL or bare UID (required)
        adapter       – key in SCRAPER_CLASSES, default "comeet"
        user_id       – owner of the scraped jobs, default "default"

    Returns None for unknown/misconfigured entries so callers can skip gracefully.
    """
    adapter_type = config.get("adapter", "comeet").lower()
    company_name = config.get("company_name", "").strip()
    company_url  = config.get("company_url",  "").strip()
    user_id      = config.get("user_id", "default")

    if not company_name or not company_url:
        logger.warning("[scraper_from_config] Skipping config with missing name/url: %r", config)
        return None

    cls = SCRAPER_CLASSES.get(adapter_type)
    if cls is None:
        logger.warning(
            "[scraper_from_config] Unknown adapter '%s'. Available: %s",
            adapter_type, list(SCRAPER_CLASSES.keys()),
        )
        return None

    logger.info(
        "[scraper_from_config] Building %s adapter for '%s' url=%r user_id=%r",
        cls.__name__, company_name, company_url, user_id,
    )
    return cls(company_name, company_url, user_id=user_id)  # type: ignore[call-arg]
