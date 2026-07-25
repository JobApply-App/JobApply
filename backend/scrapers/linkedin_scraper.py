"""
LinkedInScraper — wraps the existing get_latest_jobs() integration so that
LinkedIn search queries can be driven through the ScraperManager / Strategy
pattern like every other source.

One LinkedInScraper instance corresponds to one (query, location) pair.
Register multiple instances in SCRAPER_MANAGER to cover different job titles.

JD scraping (individual listing URLs → raw text) is handled by
backend.scrapers.url_router, which routes linkedin.com URLs to a dedicated
parser that survives LinkedIn's aggressive bot detection as best as possible.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from backend.schemas.job import JobMatch
from backend.scrapers.base_scraper import BaseScraper, make_job_id, minimal_job_match, now_iso
from backend.config import CREDIT_CONSERVATION_MODE

logger = logging.getLogger(__name__)


class LinkedInScraper(BaseScraper):
    """
    Wraps backend.integrations.job_scraper.get_latest_jobs() as a BaseScraper.

    Parameters
    ----------
    query : str
        LinkedIn job-title search query, e.g. "Product Manager".
    location : str
        LinkedIn location filter, e.g. "Israel".
    category : str
        Tag applied to every returned JobMatch (used by the discovery feed).
    user_id : str
        Owner of the resulting JobMatch records.
    """

    def __init__(
        self,
        query:     str,
        location:  str  = "Israel",
        category:  str  = "",
        user_id:   str  = "default",
    ) -> None:
        # company_name used for logging; company_url is the conceptual "source"
        super().__init__(
            company_name=f"LinkedIn:{query}",
            company_url=f"https://www.linkedin.com/jobs/search/?keywords={query}&location={location}",
        )
        self._query    = query
        self._location = location
        self.category  = category
        self._user_id  = user_id

    @property
    def source_type(self) -> str:
        return "linkedin"

    async def fetch_jobs(self) -> list[JobMatch]:
        """
        Run a LinkedIn search and convert results to minimal JobMatch objects.

        Respects CREDIT_CONSERVATION_MODE — when True, description text is NOT
        fetched so no extra HTTP requests are made per-listing.
        """
        from backend.integrations.job_scraper import get_latest_jobs

        logger.info(
            "[LinkedInScraper] Searching '%s' in %s (credit_conservation=%s)",
            self._query, self._location, CREDIT_CONSERVATION_MODE,
        )

        try:
            raw_jobs = await asyncio.to_thread(
                get_latest_jobs,
                job_title=self._query,
                location=self._location,
                fetch_descriptions=not CREDIT_CONSERVATION_MODE,
            )
        except Exception as exc:
            logger.warning(
                "[LinkedInScraper] Search failed for '%s': %s", self._query, exc
            )
            return []

        results: list[JobMatch] = []
        for job in raw_jobs:
            # Skip simulated fallback entries — they are not real postings
            if job.get("source") == "simulated":
                continue

            url = (job.get("url") or "").strip()
            if not url:
                continue

            job_id = job.get("job_id") or make_job_id(url, prefix="li")

            description = job.get("description", "") or ""
            raw_text = "\n\n".join(filter(None, [
                f"{job.get('title', '')} — {job.get('company', '')} — {job.get('location', '')}",
                description,
            ]))

            match = minimal_job_match(
                job_id      = job_id,
                title       = job.get("title", "Unknown Title"),
                company     = job.get("company", "Unknown Company"),
                location    = job.get("location", ""),
                apply_url   = url,
                jd_text     = raw_text if len(raw_text) > 50 else None,
                posted_at   = job.get("posted_at", ""),
                source_type = "linkedin",
                user_id     = self._user_id,
            )
            if self.category:
                match.category = self.category

            results.append(match)

        logger.info(
            "[LinkedInScraper] '%s' → %d result(s)", self._query, len(results)
        )
        return results
