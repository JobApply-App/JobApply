"""
GoogleDorkScraper — find open roles directly on ATS domains via Google Search.

Strategy: "Under the Radar"
-----------------------------
Most candidates apply through saturated aggregators (LinkedIn, Drushim).
This scraper bypasses them by querying Google with site-specific dork queries
that surface jobs posted directly on company ATS platforms:

    site:boards.greenhouse.io "Product Manager" "Israel"
    site:jobs.lever.co "Customer Success" "Tel Aviv"

Results arrive before aggregators re-index them, and the competition surface
is far smaller (only people using the same technique).

ATS domains targeted
---------------------
• boards.greenhouse.io  — Greenhouse (very common in Israeli tech startups)
• jobs.lever.co         — Lever (popular mid-size companies)
• comeet.co             — Comeet (Israeli ATS, widely used)
• myworkdayjobs.com     — Workday (enterprise companies, banks, large corps)
• jobs.ashbyhq.com      — Ashby (growing fast in EMEA tech)
• apply.workable.com    — Workable (SMBs, Israeli startups)

Search mechanics
-----------------
• Keywords are batched into OR groups so N queries (not N×D queries) are sent.
• Each query is separated by _INTER_QUERY_DELAY seconds to avoid rate limits.
• The `googlesearch-python` library's `advanced=True` mode returns (url, title,
  description) without extra HTTP round-trips to each result page.
• The relevancy gate in relevancy.py is applied before any result is returned.

Rate-limit notes
-----------------
Google blocks aggressive crawlers. We use:
  • 3-second inter-query sleep (configurable via _INTER_QUERY_DELAY)
  • max 5 results per query (low footprint, Google won't throttle)
  • A realistic browser User-Agent is set automatically by the library.

If Google returns a 429, the error is caught and logged; other queries continue.
"""
from __future__ import annotations

import asyncio
import logging
import random
import re
import time
from typing import Optional

from backend.schemas.job import JobMatch
from backend.scrapers.base_scraper import BaseScraper, make_job_id, minimal_job_match
from backend.scrapers.relevancy import is_title_relevant
from backend.config import TARGET_SEARCH_QUERIES, CREDIT_CONSERVATION_MODE

logger = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────

# ATS domains to target, each as a Google site: operator value.
# Split into two tiers:
#   _ATS_DOMAINS        — direct ATS platforms (unauthenticated requests work)
#   _LINKEDIN_DOMAINS   — LinkedIn job-view pages (indexed by Google, read-only;
#                         no cookie or Playwright used — public JSON-LD only)
_ATS_DOMAINS: list[str] = [
    # Global ATS platforms common in Israeli tech
    "boards.greenhouse.io",
    "jobs.lever.co",
    "comeet.co",
    "myworkdayjobs.com",
    "jobs.ashbyhq.com",
    "apply.workable.com",
    # Israeli job boards (public, unauthenticated)
    "alljobs.co.il",
    "drushim.co.il",
    "gotfriends.co.il",
]

# LinkedIn is included only as a Google index source — we never authenticate.
# Public /jobs/view/ pages embed a JSON-LD block that our scraper can extract
# without a session cookie.  Login-wall pages are filtered by is_valid_job_content.
_LINKEDIN_DOMAINS: list[str] = [
    "linkedin.com/jobs/view",
]

# Location qualifiers appended to every query.
_LOCATION_TERMS: list[str] = ["Israel", "Tel Aviv"]

# How many Google results to request per query (keep low to avoid blocks).
_RESULTS_PER_QUERY = 5

# Seconds to sleep between consecutive Google queries.
_INTER_QUERY_DELAY     = 3.0    # minimum sleep between queries (seconds)
_INTER_QUERY_JITTER_LO = 60.0   # random jitter lower bound (seconds) — ~1 min
_INTER_QUERY_JITTER_HI = 120.0  # random jitter upper bound (seconds) — ~2 min

# When Google returns a 429, we sleep this long then abandon the remaining
# queries for the cycle.  The next discovery cycle will retry from scratch.
_BACKOFF_ON_429 = 600.0   # 10 minutes

# Maximum keywords per OR batch (keep Google query strings manageable).
_BATCH_SIZE = 4

# ── Keyword batching ──────────────────────────────────────────────────────────

def _keyword_batches(keywords: list[str], size: int) -> list[list[str]]:
    """Split keywords into chunks of `size` for OR-grouping."""
    return [keywords[i : i + size] for i in range(0, len(keywords), size)]


def _build_queries(domains: list[str], keywords: list[str]) -> list[tuple[str, str]]:
    """
    Produce (domain, query_string) tuples.

    Each query covers one domain and one keyword batch (OR-joined), plus the
    location filter.  Returns far fewer queries than the full Cartesian product.
    """
    location_filter = " OR ".join(f'"{t}"' for t in _LOCATION_TERMS)
    batches = _keyword_batches(keywords, _BATCH_SIZE)
    queries: list[tuple[str, str]] = []
    for domain in domains:
        for batch in batches:
            kw_filter = " OR ".join(f'"{kw}"' for kw in batch)
            q = f'site:{domain} ({kw_filter}) ({location_filter})'
            queries.append((domain, q))
    return queries


# ── Result parsing ────────────────────────────────────────────────────────────

def _clean_title(raw: str) -> str:
    """
    Strip common ATS boilerplate from Google search result titles.

    Examples of raw titles:
      "Senior Product Manager at Wiz | Greenhouse"
      "Customer Success Manager - Wiz - Tel Aviv | Lever"
      "Product Lead | Comeet"
    """
    # Remove trailing " | Platform" or " - Platform"
    cleaned = re.sub(r'\s*[|–\-]\s*(?:Greenhouse|Lever|Comeet|Workday|Ashby|Workable)\s*$', '', raw, flags=re.IGNORECASE)
    # Strip leading/trailing whitespace
    return cleaned.strip()


def _extract_company(url: str, title: str, domain: str) -> str:
    """
    Derive company name from URL slug (most ATS embed it as the first path segment).

    Examples:
      https://boards.greenhouse.io/wiz/jobs/123   → "Wiz"
      https://jobs.lever.co/monday/abc-123         → "Monday"
      https://apply.workable.com/gong-io/j/123     → "Gong Io"
    """
    try:
        # Strip scheme + domain
        path = url.split(domain, 1)[-1].lstrip('/')
        slug = path.split('/')[0]
        if not slug or slug in {'jobs', 'j', 'careers', 'external'}:
            # Fall back to second segment
            parts = [p for p in path.split('/') if p]
            slug = parts[1] if len(parts) > 1 else ''
        # Humanise slug: hyphens/underscores → spaces, title-case
        company = re.sub(r'[-_]', ' ', slug).title()
        return company or "Unknown"
    except Exception:
        return "Unknown"


def _extract_location(description: str) -> str:
    """Best-effort location extraction from the Google snippet."""
    # Common patterns: "Tel Aviv", "Israel", "Remote, Israel", "Hybrid · Tel Aviv"
    if not description:
        return "Israel"
    for term in ("Tel Aviv", "Jerusalem", "Haifa", "Remote", "Hybrid"):
        if term.lower() in description.lower():
            return term
    return "Israel"


# ── Scraper class ─────────────────────────────────────────────────────────────

class GoogleDorkScraper(BaseScraper):
    """
    Discovers jobs on ATS platforms via Google Dork queries.

    Registered in ScraperManager as a board-level scraper; runs once per
    discovery cycle alongside the Israeli job-board scrapers.

    Parameters
    ----------
    keywords : list[str]
        List of job-title search terms (defaults to TARGET_SEARCH_QUERIES).
    domains  : list[str]
        ATS domains to search (defaults to _ATS_DOMAINS).
    user_id  : str
        Owner of discovered jobs.
    """

    def __init__(
        self,
        keywords:         Optional[list[str]] = None,
        domains:          Optional[list[str]] = None,
        include_linkedin: bool = True,
        user_id:          str = "default",
    ) -> None:
        super().__init__("Google Dork (ATS Direct)", "https://www.google.com")
        self._keywords = keywords or TARGET_SEARCH_QUERIES
        base_domains   = domains or _ATS_DOMAINS
        # Append LinkedIn read-only domains unless explicitly excluded.
        # They are queried last so ATS results (higher quality) come first.
        self._domains  = base_domains + (_LINKEDIN_DOMAINS if include_linkedin else [])
        self._user_id  = user_id

    @property
    def source_type(self) -> str:
        return "company_site"

    async def fetch_jobs(self) -> list[JobMatch]:
        """
        Run all dork queries, collect results, and return de-duplicated JobMatch list.
        """
        # Run blocking Google queries in a thread pool to avoid blocking the event loop.
        jobs = await asyncio.get_event_loop().run_in_executor(None, self._run_queries)
        logger.info(
            "[GoogleDorkScraper] fetch_jobs complete — %d relevant jobs found across %d domains",
            len(jobs), len(self._domains),
        )
        return jobs

    # ── Internal (synchronous, runs in thread pool) ───────────────────────────

    def _run_queries(self) -> list[JobMatch]:
        try:
            from googlesearch import search as google_search
        except ImportError:
            logger.error(
                "[GoogleDorkScraper] googlesearch-python not installed. "
                "Run: pip install googlesearch-python"
            )
            return []

        queries   = _build_queries(self._domains, self._keywords)
        seen_urls: set[str] = set()
        results:   list[JobMatch] = []

        logger.info(
            "[GoogleDorkScraper] Running %d dork queries across %d ATS domains",
            len(queries), len(self._domains),
        )

        for domain, query in queries:
            # Jittered delay before every query — including the first — to stay
            # well under Google's 429 threshold.  The base _INTER_QUERY_DELAY is
            # a minimum; actual sleep is uniformly random within the jitter range.
            jitter = random.uniform(_INTER_QUERY_JITTER_LO, _INTER_QUERY_JITTER_HI)
            logger.debug(
                "[GoogleDorkScraper] sleeping %.1fs before query domain=%s", jitter, domain,
            )
            time.sleep(jitter)

            try:
                raw_results = list(google_search(
                    query,
                    num_results    = _RESULTS_PER_QUERY,
                    advanced       = True,   # returns SearchResult(url, title, description)
                    sleep_interval = 0,      # we handle sleep ourselves
                    lang           = "en",
                ))
            except Exception as exc:
                exc_str = str(exc)
                # 429 from Google means we are already blocked for this IP/session.
                # Firing more queries immediately will extend the block.  Instead:
                # sleep for _BACKOFF_ON_429, then abandon the rest of this cycle.
                # The next discovery cycle (hours later) will retry from scratch.
                if "429" in exc_str or "too many requests" in exc_str.lower():
                    logger.warning(
                        "[GoogleDorkScraper] 429 rate-limit hit (domain=%s). "
                        "Sleeping %.0fs then aborting this cycle — %d queries skipped.",
                        domain, _BACKOFF_ON_429, len(queries) - queries.index((domain, query)) - 1,
                    )
                    time.sleep(_BACKOFF_ON_429)
                    break   # exit the for-loop; return whatever we collected so far
                logger.warning(
                    "[GoogleDorkScraper] Query failed for domain=%s: %s",
                    domain, exc,
                )
                continue

            for result in raw_results:
                url = getattr(result, 'url', None) or str(result)
                if not url or url in seen_urls:
                    continue

                # Only accept URLs that actually contain the targeted domain/path.
                # For linkedin.com/jobs/view we check the sub-path, not just the host.
                if domain not in url:
                    continue

                # Never accept LinkedIn URLs that require a login wall —
                # only /jobs/view/ pages carry a public JSON-LD block.
                if "linkedin.com" in url and "/jobs/view/" not in url:
                    logger.debug(
                        "[GoogleDorkScraper] SKIP (linkedin non-view url): %s", url,
                    )
                    continue

                seen_urls.add(url)

                raw_title   = getattr(result, 'title', '') or ''
                description = getattr(result, 'description', '') or ''

                title   = _clean_title(raw_title) if raw_title else ""
                company = _extract_company(url, title, domain)
                location = _extract_location(description)

                # Extract the actual job title from the combined "Title at Company" string
                if ' at ' in title and not title.startswith('at '):
                    title = title.split(' at ')[0].strip()
                elif ' - ' in title:
                    title = title.split(' - ')[0].strip()

                if not title:
                    continue

                # Apply relevancy gate
                if not is_title_relevant(title):
                    logger.debug(
                        "[GoogleDorkScraper] SKIP (irrelevant): '%s' @ %s",
                        title, url,
                    )
                    continue

                job_id = make_job_id(url, prefix="dork")
                job    = minimal_job_match(
                    job_id      = job_id,
                    title       = title,
                    company     = company,
                    location    = location,
                    apply_url   = url,
                    jd_text     = description or None,  # snippet as thin JD proxy
                    source_type = "company_site",
                    user_id     = self._user_id,
                )
                results.append(job)
                logger.info(
                    "[GoogleDorkScraper] FOUND: '%s' @ %s (%s)",
                    title, company, domain,
                )

        logger.info(
            "[GoogleDorkScraper] Total: %d relevant jobs from %d queries",
            len(results), len(queries),
        )
        return results
