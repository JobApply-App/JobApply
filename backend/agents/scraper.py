"""
Scraper Agent
Crawls job boards (LinkedIn, Greenhouse, Lever, Indeed, etc.) and normalises raw
postings into the canonical Job schema before handing off to the Analyzer.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import AsyncIterator

import httpx

from backend.schemas.job import RawJobPosting

logger = logging.getLogger(__name__)

SOURCES = [
    "https://boards.greenhouse.io",
    "https://jobs.lever.co",
    "https://www.linkedin.com/jobs",
    "https://www.indeed.com",
]


@dataclass
class ScraperConfig:
    sources: list[str] = field(default_factory=lambda: SOURCES)
    max_concurrent: int = 5
    request_timeout: float = 15.0
    delay_between_requests: float = 1.2


class ScraperAgent:
    """
    Continuously fetches new job postings from configured sources.
    Emits RawJobPosting objects to downstream consumers (AnalyzerAgent).
    """

    def __init__(self, config: ScraperConfig | None = None) -> None:
        self.config = config or ScraperConfig()
        self._running = False

    async def run(self) -> None:
        """Entry point — poll all sources in a loop."""
        self._running = True
        logger.info("ScraperAgent starting, sources=%d", len(self.config.sources))
        while self._running:
            async for posting in self._scrape_all():
                await self._emit(posting)
            await asyncio.sleep(300)  # re-scan every 5 min

    async def stop(self) -> None:
        self._running = False

    async def _scrape_all(self) -> AsyncIterator[RawJobPosting]:
        sem = asyncio.Semaphore(self.config.max_concurrent)
        async with httpx.AsyncClient(timeout=self.config.request_timeout) as client:
            tasks = [self._scrape_source(client, sem, src) for src in self.config.sources]
            for coro in asyncio.as_completed(tasks):
                try:
                    postings = await coro
                    for p in postings:
                        yield p
                except Exception as exc:
                    logger.warning("Scrape error: %s", exc)

    async def _scrape_source(
        self,
        client: httpx.AsyncClient,
        sem: asyncio.Semaphore,
        source_url: str,
    ) -> list[RawJobPosting]:
        async with sem:
            await asyncio.sleep(self.config.delay_between_requests)
            # TODO: implement per-source parsers (Greenhouse JSON API, Lever API, etc.)
            logger.debug("Scraping %s", source_url)
            return []

    async def _emit(self, posting: RawJobPosting) -> None:
        """Push posting onto the queue consumed by AnalyzerAgent."""
        # TODO: publish to Redis stream or Celery task
        logger.debug("Scraped posting: %s @ %s", posting.title, posting.company)
