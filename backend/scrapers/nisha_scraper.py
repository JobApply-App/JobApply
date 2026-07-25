"""
NishaScraper — scrapes job listings from nisha.co.il.

Nisha is an Israeli technology recruitment and staffing agency.  Client
companies are often anonymous; those roles are normalised to
"Nisha (Confidential)".

Concurrency model
-----------------
Phase 1  (listing)  — all keywords searched concurrently via asyncio.gather().
                       Within each keyword, list pages are fetched sequentially
                       (page 1 → 2 → … until exhausted or no "next" button).
Phase 2  (details)  — all relevant detail pages fetched concurrently, bounded
                       by asyncio.Semaphore(_DETAIL_CONCURRENCY=20).

The synchronous scrape_nisha_jd() helper is kept for url_router / backfill.

Hebrew content is common; the parser handles RTL text without issue because
BeautifulSoup returns raw Unicode.
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Optional
from urllib.parse import urljoin, urlencode

import httpx
import requests
from bs4 import BeautifulSoup, Tag

from backend.schemas.job import JobMatch
from backend.scrapers.base_scraper import BaseScraper, make_job_id, minimal_job_match

logger = logging.getLogger(__name__)

_BASE_URL  = "https://www.nisha.co.il"
_JOBS_PATH = "/jobs/"
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
_HEADERS = {
    "User-Agent": _UA,
    "Accept-Language": "he-IL,he;q=0.9,en-US;q=0.8",
    "Accept": "text/html,application/xhtml+xml",
    "Referer": _BASE_URL,
}
_TIMEOUT          = 15                     # seconds — sync helpers only
_TIMEOUT_ASYNC    = httpx.Timeout(10.0)    # strict 10 s per async request
_DETAIL_CONCURRENCY = 20                   # max simultaneous detail-page fetches
_MAX_PAGES        = 5
_MAX_DETAIL_FETCH = 20

_CONFIDENTIAL_RE = re.compile(
    r"^(חברה|לקוח|ארגון|מיזם|סטארט(אפ|-אפ)|startup|company|client|"
    r"undisclosed|confidential|[א-ת]{1,4})[\s\-ב-ת]{0,20}$",
    re.IGNORECASE,
)
_AGENCY_LABEL = "Nisha (Confidential)"


def _is_confidential(name: str) -> bool:
    name = name.strip()
    if not name:
        return True
    return bool(_CONFIDENTIAL_RE.match(name))


def _clean_text(element: Optional[Tag]) -> str:
    if element is None:
        return ""
    return " ".join(element.get_text(separator=" ").split())


# ── Sync fetch helper (used by scrape_nisha_jd / url_router) ─────────────────

def _fetch_html(url: str, session: requests.Session) -> Optional[BeautifulSoup]:
    try:
        resp = session.get(url, headers=_HEADERS, timeout=_TIMEOUT)
        resp.raise_for_status()
        return BeautifulSoup(resp.content, "html.parser", from_encoding="utf-8")
    except Exception as exc:
        logger.warning("[NishaScraper] Failed to fetch %s: %s", url, exc)
        return None


# ── Async fetch helper ────────────────────────────────────────────────────────

async def _fetch_html_async(
    url: str, client: httpx.AsyncClient
) -> Optional[BeautifulSoup]:
    try:
        resp = await client.get(url)
        resp.raise_for_status()
        return BeautifulSoup(resp.content, "html.parser", from_encoding="utf-8")
    except Exception as exc:
        logger.warning("[NishaScraper] Failed to fetch %s: %s", url, exc)
        return None


# ── Parsers ───────────────────────────────────────────────────────────────────

def _parse_job_cards(soup: BeautifulSoup) -> list[dict]:
    """Extract job card data from a Nisha listing page."""
    items = (
        soup.find_all("article", class_=re.compile(r"job", re.I))
        or soup.find_all("div",   class_=re.compile(r"job[\-_]?(item|card|listing|row)", re.I))
        or soup.find_all("li",    class_=re.compile(r"job|position", re.I))
    )

    cards = []
    for item in items:
        link = item.find("a", href=True)
        href = link["href"] if link else ""
        if href and not href.startswith("http"):
            href = urljoin(_BASE_URL, href)

        title_el = (
            item.find(["h1", "h2", "h3", "h4"],
                      class_=re.compile(r"title|role|position|name", re.I))
            or item.find(["h1", "h2", "h3", "h4"])
            or item.find(class_=re.compile(r"title|position|role", re.I))
        )
        title = _clean_text(title_el) or _clean_text(link)

        company_el = item.find(class_=re.compile(r"company|employer|client|org", re.I))
        company = _clean_text(company_el)

        location_el = item.find(class_=re.compile(r"location|city|area|region|place", re.I))
        location = _clean_text(location_el)

        if title and href:
            cards.append({"title": title, "company": company, "location": location, "url": href})

    return cards


def _parse_detail_page(soup: BeautifulSoup) -> str:
    """Extract JD text from a Nisha job detail page."""
    for el in soup(["script", "style", "nav", "footer", "header", "aside"]):
        el.extract()

    jd_node = (
        soup.find(id=re.compile(r"job[\-_]?(description|content|detail|body)", re.I))
        or soup.find(class_=re.compile(
            r"job[\-_]?(description|content|detail|body)|"
            r"position[\-_]?(description|detail)|description|requirements|content[\-_]?area",
            re.I,
        ))
        or soup.find("main")
        or soup.find("article")
        or soup.body
    )

    text = (jd_node or soup).get_text(separator="\n")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return "\n".join(lines)


def scrape_nisha_jd(url: str) -> str:
    """
    Fetch the full JD text for a single Nisha job URL.
    Used by url_router for backfill and inline card fetch (sync).
    """
    session = requests.Session()
    soup = _fetch_html(url, session)
    if soup is None:
        raise ValueError(f"[NishaScraper] Could not load {url}")
    text = _parse_detail_page(soup)
    if len(text) < 50:
        raise ValueError(f"[NishaScraper] JD text too short ({len(text)} chars) for {url}")
    return text


# ── Scraper class ─────────────────────────────────────────────────────────────

class NishaScraper(BaseScraper):
    """
    Scrapes open positions from nisha.co.il.

    Concurrency
    -----------
    Phase 1: All keywords run concurrently.  Per keyword, listing pages are
             fetched sequentially until exhausted (page 1 → 2 → …).
    Phase 2: All relevant detail pages fetched concurrently via Semaphore(20).

    Parameters
    ----------
    keyword  : single keyword filter — kept for backward compatibility.
    keywords : list of search terms; pass TARGET_SEARCH_QUERIES from config.
    user_id  : owner of resulting JobMatch records
    max_jobs : cap on total detail page requests per run
    """

    def __init__(
        self,
        company_name: str = "Nisha",
        company_url:  str = _BASE_URL + _JOBS_PATH,
        user_id:      str = "default",
        keyword:      str = "",
        keywords:     Optional[list] = None,
        max_jobs:     int = _MAX_DETAIL_FETCH,
    ) -> None:
        super().__init__(company_name=company_name, company_url=company_url)
        self._user_id  = user_id
        self._keywords: list[str] = (
            keywords if keywords is not None
            else ([keyword] if keyword else [])
        )
        self._max_jobs = max_jobs

    @property
    def source_type(self) -> str:
        return "company_site"

    # ── Phase 1: gather listing cards ─────────────────────────────────────────

    async def _cards_for_keyword(
        self, term: str, client: httpx.AsyncClient
    ) -> list[dict]:
        """Fetch all listing cards for one keyword via sequential pagination."""
        all_cards: list[dict] = []
        for page in range(1, _MAX_PAGES + 1):
            params: dict[str, str] = {"page": str(page)}
            if term:
                params["keyword"] = term
            url  = _BASE_URL + _JOBS_PATH + "?" + urlencode(params)
            soup = await _fetch_html_async(url, client)
            if soup is None:
                break
            cards = _parse_job_cards(soup)
            if not cards:
                break
            all_cards.extend(cards)
            if not soup.find(class_=re.compile(r"next|pagination[\-_]?next", re.I)):
                break
        return all_cards

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
            "[NishaScraper] Found %d unique cards across %d keyword search(es)",
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
            detail_soup = await _fetch_html_async(card["url"], client)
            if detail_soup:
                jd_text = _parse_detail_page(detail_soup)
                if len(jd_text) < 50:
                    jd_text = None

        company = card["company"]
        if _is_confidential(company):
            company = _AGENCY_LABEL

        return minimal_job_match(
            job_id      = make_job_id(card["url"], prefix="nisha"),
            title       = card["title"],
            company     = company,
            location    = card["location"] or "Israel",
            apply_url   = card["url"],
            jd_text     = jd_text,
            source_type = "company_site",
            user_id     = self._user_id,
            locale      = "he",
        )

    # ── Entry point ───────────────────────────────────────────────────────────

    async def fetch_jobs(self) -> list[JobMatch]:
        from backend.scrapers.relevancy import is_title_relevant

        async with httpx.AsyncClient(
            headers=_HEADERS,
            timeout=_TIMEOUT_ASYNC,
            follow_redirects=True,
        ) as client:
            # Phase 1 — parallel keyword searches
            all_cards = await self._gather_listing_cards(client)

            # Relevancy gate before detail fetches
            relevant_cards = [c for c in all_cards if is_title_relevant(c["title"])]
            discarded = len(all_cards) - len(relevant_cards)
            if discarded:
                logger.info(
                    "[NishaScraper] Discarded %d irrelevant title(s) before detail fetch",
                    discarded,
                )

            # Phase 2 — concurrent detail fetches
            sem = asyncio.Semaphore(_DETAIL_CONCURRENCY)
            results: list[JobMatch] = list(await asyncio.gather(*[
                self._fetch_detail(card, client, sem)
                for card in relevant_cards[: self._max_jobs]
            ]))

        logger.info("[NishaScraper] Returning %d job(s)", len(results))
        return results
