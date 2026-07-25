"""
AllJobsScraper — scrapes job listings from alljobs.co.il (AllJobs).

AllJobs (alljobs.co.il) is Israel's largest job aggregator.  Their site is
powered by ASP.NET with AJAX-heavy search.

Fetch strategy (primary → fallback)
-------------------------------------
1. **JSON AJAX endpoint** — AllJobs exposes a semi-public POST endpoint:
       POST /SearchResultsCareerAjax.aspx/GetAllJobsByParam
   with a JSON body.  This returns structured data without full JS rendering.
2. **HTML listing scrape** — BS4 parse of the regular search result page.
   Less reliable but covers cases where the AJAX endpoint changes.

Concurrency model
-----------------
Phase 1  (listing)  — all keywords searched concurrently via asyncio.gather().
                       Within each keyword, AJAX pages are tried sequentially
                       (each page decides whether to fetch the next) then HTML
                       fallback, but each keyword's chain runs in parallel.
Phase 2  (details)  — all relevant detail pages fetched concurrently, bounded
                       by asyncio.Semaphore(_DETAIL_CONCURRENCY=20).

The synchronous scrape_alljobs_jd() helper is kept for url_router / backfill.

Confidential companies
-----------------------
Agency-forwarded roles without a company name are normalised to
"AllJobs (Confidential)".
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, Optional
from urllib.parse import urljoin, urlencode

import httpx
import requests
from bs4 import BeautifulSoup, Tag

from backend.schemas.job import JobMatch
from backend.scrapers.base_scraper import BaseScraper, make_job_id, minimal_job_match
from backend.config import CREDIT_CONSERVATION_MODE

logger = logging.getLogger(__name__)

_BASE_URL   = "https://www.alljobs.co.il"
_SEARCH_URL = f"{_BASE_URL}/searchresultscareer.aspx"
_AJAX_URL   = f"{_BASE_URL}/SearchResultsCareerAjax.aspx/GetAllJobsByParam"
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
_HEADERS = {
    "User-Agent":   _UA,
    "Accept-Language": "he-IL,he;q=0.9,en-US;q=0.8",
    "Referer": _BASE_URL,
}
_AJAX_HEADERS = {
    **_HEADERS,
    "Accept":           "application/json, text/javascript, */*; q=0.01",
    "Content-Type":     "application/json; charset=UTF-8",
    "X-Requested-With": "XMLHttpRequest",
}
_HTML_HEADERS = {**_HEADERS, "Accept": "text/html,application/xhtml+xml"}

_TIMEOUT          = 15                     # seconds — sync helpers only
_TIMEOUT_ASYNC    = httpx.Timeout(10.0)    # strict 10 s per async request
_DETAIL_CONCURRENCY = 20                   # max simultaneous detail-page fetches
_MAX_PAGES        = 5
_MAX_DETAIL_FETCH = 25

_CONFIDENTIAL_RE = re.compile(
    r"^(חברה|לקוח|ארגון|מיזם|סטארט(אפ|-אפ)|startup|company|client|"
    r"undisclosed|confidential|[א-ת]{1,4})[\s\-ב-ת]{0,20}$",
    re.IGNORECASE,
)
_AGENCY_LABEL = "AllJobs (Confidential)"


def _is_confidential(name: str) -> bool:
    name = name.strip()
    return not name or bool(_CONFIDENTIAL_RE.match(name))


def _clean_text(element: Optional[Tag]) -> str:
    if element is None:
        return ""
    return " ".join(element.get_text(separator=" ").split())


# ── Sync fetch helpers (used by scrape_alljobs_jd / url_router) ──────────────

def _fetch_html(url: str, session: requests.Session) -> Optional[BeautifulSoup]:
    try:
        resp = session.get(url, headers=_HTML_HEADERS, timeout=_TIMEOUT)
        resp.raise_for_status()
        return BeautifulSoup(resp.content, "html.parser", from_encoding="utf-8")
    except Exception as exc:
        logger.warning("[AllJobsScraper] Failed to fetch %s: %s", url, exc)
        return None


# ── Async fetch helpers ───────────────────────────────────────────────────────

async def _fetch_html_async(
    url: str, client: httpx.AsyncClient
) -> Optional[BeautifulSoup]:
    try:
        resp = await client.get(url, headers=_HTML_HEADERS)
        resp.raise_for_status()
        return BeautifulSoup(resp.content, "html.parser", from_encoding="utf-8")
    except Exception as exc:
        logger.warning("[AllJobsScraper] Failed to fetch %s: %s", url, exc)
        return None


async def _fetch_ajax_async(
    keyword: str, page: int, client: httpx.AsyncClient
) -> list[dict]:
    """POST to AllJobs' AJAX search endpoint. Returns [] on any failure."""
    payload = {
        "searchtext": keyword,
        "cityId":     "0",
        "categoryId": "0",
        "jobTypeId":  "0",
        "seniority":  "0",
        "pageNum":    page,
        "pageSize":   25,
        "sortBy":     "Date",
    }
    try:
        resp = await client.post(
            _AJAX_URL,
            content=json.dumps(payload).encode(),
            headers=_AJAX_HEADERS,
        )
        resp.raise_for_status()
        data: Any = resp.json()
        items = data.get("d") or (data if isinstance(data, list) else [])

        jobs = []
        for item in items:
            if not isinstance(item, dict):
                continue
            title    = str(item.get("Title")   or item.get("JobTitle")    or "").strip()
            company  = str(item.get("Company") or item.get("CompanyName") or "").strip()
            location = str(item.get("City")    or item.get("Location")    or "").strip()
            job_url  = str(item.get("Url")     or item.get("JobUrl")      or "").strip()
            if not job_url.startswith("http"):
                job_url = urljoin(_BASE_URL, job_url)
            if title and job_url:
                jobs.append({"title": title, "company": company, "location": location, "url": job_url})
        return jobs

    except Exception as exc:
        logger.warning("[AllJobsScraper] AJAX request failed (page=%d): %s", page, exc)
        return []


# ── HTML listing fallback ─────────────────────────────────────────────────────

def _parse_html_cards(soup: BeautifulSoup) -> list[dict]:
    """Parse job cards from an AllJobs HTML listing page."""
    items = (
        soup.find_all("div",   class_=re.compile(r"job[\-_]?(item|card|listing|row|result|box)", re.I))
        or soup.find_all("article", class_=re.compile(r"job", re.I))
        or soup.find_all("li",      class_=re.compile(r"job|vacancy|position|result", re.I))
    )

    cards = []
    for item in items:
        link = item.find("a", href=True)
        href = link["href"] if link else ""
        if href and not href.startswith("http"):
            href = urljoin(_BASE_URL, href)

        title_el = (
            item.find(["h2", "h3", "h4"], class_=re.compile(r"title|role|position", re.I))
            or item.find(["h2", "h3", "h4"])
            or item.find(class_=re.compile(r"title|position|role", re.I))
        )
        title = _clean_text(title_el) or _clean_text(link)

        company_el = item.find(class_=re.compile(r"company|employer|client|org", re.I))
        company = _clean_text(company_el)

        location_el = item.find(class_=re.compile(r"location|city|area|region", re.I))
        location = _clean_text(location_el)

        if title and href:
            cards.append({"title": title, "company": company, "location": location, "url": href})
    return cards


# ── Detail page parsing ───────────────────────────────────────────────────────

def _parse_alljobs_jd(soup: BeautifulSoup) -> str:
    """Extract JD text from an AllJobs detail page (reuses Hebrew-aware parser)."""
    from backend.scrapers.drushim_scraper import _parse_hebrew_jd
    return _parse_hebrew_jd(soup)


def scrape_alljobs_jd(url: str) -> str:
    """
    Fetch the full JD text for a single AllJobs posting URL.
    Used by url_router for backfill and inline card fetch (sync).
    """
    session = requests.Session()
    soup = _fetch_html(url, session)
    if soup is None:
        raise ValueError(f"[AllJobsScraper] Could not load {url}")
    text = _parse_alljobs_jd(soup)
    if len(text) < 50:
        from backend.url_scraper import scrape_job_post
        try:
            scraped = scrape_job_post(url)
            return scraped.raw_text
        except Exception:
            pass
        raise ValueError(f"[AllJobsScraper] JD text too short ({len(text)} chars) for {url}")
    return text


# ── Scraper class ─────────────────────────────────────────────────────────────

class AllJobsScraper(BaseScraper):
    """
    Scrapes open positions from alljobs.co.il.

    Attempts the JSON AJAX endpoint first; falls back to HTML listing scrape.

    Concurrency
    -----------
    Phase 1: All keywords run concurrently.  Per keyword, AJAX pages are
             fetched sequentially (page 1 → 2 → …) then HTML fallback if empty.
    Phase 2: All relevant detail pages fetched concurrently via Semaphore(20).

    Parameters
    ----------
    keyword  : single keyword filter — kept for backward compatibility.
    keywords : list of search terms; pass TARGET_SEARCH_QUERIES from config.
    category : tag applied to every returned JobMatch
    user_id  : owner of resulting JobMatch records
    max_jobs : cap on total detail-page requests per run
    """

    def __init__(
        self,
        company_name: str = "AllJobs",
        company_url:  str = _BASE_URL,
        user_id:      str = "default",
        keyword:      str = "",
        keywords:     Optional[list] = None,
        category:     str = "",
        max_jobs:     int = _MAX_DETAIL_FETCH,
    ) -> None:
        super().__init__(company_name=company_name, company_url=company_url)
        self._user_id  = user_id
        self._keywords: list[str] = (
            keywords if keywords is not None
            else ([keyword] if keyword else [])
        )
        self.category  = category
        self._max_jobs = max_jobs

    @property
    def source_type(self) -> str:
        return "company_site"

    # ── Phase 1: gather listing cards ─────────────────────────────────────────

    async def _cards_for_keyword(
        self, term: str, client: httpx.AsyncClient
    ) -> list[dict]:
        """Fetch all listing cards for one keyword (AJAX → HTML fallback)."""
        term_cards: list[dict] = []

        # AJAX primary
        for page in range(1, _MAX_PAGES + 1):
            page_cards = await _fetch_ajax_async(term, page, client)
            if not page_cards:
                break
            term_cards.extend(page_cards)

        # HTML fallback
        if not term_cards:
            for page in range(1, _MAX_PAGES + 1):
                params: dict[str, str] = {"page": str(page)}
                if term:
                    params["q"] = term
                url  = _SEARCH_URL + "?" + urlencode(params)
                soup = await _fetch_html_async(url, client)
                if soup is None:
                    break
                page_cards = _parse_html_cards(soup)
                if not page_cards:
                    break
                term_cards.extend(page_cards)
                if not soup.find(class_=re.compile(r"next|pagination[\-_]?next", re.I)):
                    break

        logger.debug("[AllJobsScraper] keyword=%r → %d card(s)", term, len(term_cards))
        return term_cards

    async def _gather_listing_cards(self, client: httpx.AsyncClient) -> list[dict]:
        """Fetch listing cards for all keywords concurrently, deduplicating URLs."""
        search_terms = self._keywords if self._keywords else [""]
        per_keyword: list[list[dict]] = await asyncio.gather(
            *[self._cards_for_keyword(term, client) for term in search_terms]
        )
        seen_urls: set[str] = set()
        all_cards: list[dict] = []
        for cards in per_keyword:
            for card in cards:
                if card["url"] not in seen_urls:
                    seen_urls.add(card["url"])
                    all_cards.append(card)
        logger.info(
            "[AllJobsScraper] Found %d unique cards across %d keyword search(es)",
            len(all_cards), len(search_terms),
        )
        return all_cards

    # ── Phase 2: fetch detail pages concurrently ──────────────────────────────

    async def _fetch_detail(
        self,
        card: dict,
        client: httpx.AsyncClient,
        sem: asyncio.Semaphore,
    ) -> JobMatch:
        """Fetch one detail page under the shared semaphore and build a JobMatch."""
        async with sem:
            jd_text: Optional[str] = None
            if not CREDIT_CONSERVATION_MODE:
                detail_soup = await _fetch_html_async(card["url"], client)
                if detail_soup:
                    jd_text = _parse_alljobs_jd(detail_soup)
                    if len(jd_text) < 50:
                        jd_text = None

        company = card["company"]
        if _is_confidential(company):
            company = _AGENCY_LABEL

        match = minimal_job_match(
            job_id      = make_job_id(card["url"], prefix="alljobs"),
            title       = card["title"],
            company     = company,
            location    = card["location"] or "Israel",
            apply_url   = card["url"],
            jd_text     = jd_text,
            source_type = "company_site",
            user_id     = self._user_id,
            locale      = "he",
        )
        if self.category:
            match.category = self.category
        return match

    # ── Entry point ───────────────────────────────────────────────────────────

    async def fetch_jobs(self) -> list[JobMatch]:
        from backend.scrapers.relevancy import is_title_relevant

        async with httpx.AsyncClient(
            timeout=_TIMEOUT_ASYNC,
            follow_redirects=True,
        ) as client:
            # Phase 1 — parallel keyword searches
            all_cards = await self._gather_listing_cards(client)

            # Relevancy gate
            relevant_cards = [c for c in all_cards if is_title_relevant(c["title"])]
            discarded = len(all_cards) - len(relevant_cards)
            if discarded:
                logger.info(
                    "[AllJobsScraper] Discarded %d irrelevant title(s) before detail fetch",
                    discarded,
                )

            # Phase 2 — concurrent detail fetches
            sem = asyncio.Semaphore(_DETAIL_CONCURRENCY)
            results: list[JobMatch] = list(await asyncio.gather(*[
                self._fetch_detail(card, client, sem)
                for card in relevant_cards[: self._max_jobs]
            ]))

        logger.info("[AllJobsScraper] Returning %d job(s)", len(results))
        return results
