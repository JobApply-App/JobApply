"""
DrushimScraper — scrapes job listings from drushim.co.il (דרושים.co.il).

Drushim is one of Israel's largest job boards.  Content is primarily in
Hebrew (RTL), though many tech postings mix English terms freely.

Fetch strategy (primary → fallback)
-------------------------------------
1. **RSS feed** — `https://www.drushim.co.il/rss/` provides clean XML with
   title, company, link, and a partial description.  Fast and reliable.
2. **HTML listing scrape** — GET category listing pages with BeautifulSoup.
   Used when RSS is unavailable or returns fewer than expected items.

Concurrency model
-----------------
Phase 1  (listing)  — all keywords searched concurrently via asyncio.gather().
                       Within each keyword, RSS is tried first; pagination is
                       sequential (each page result decides whether to fetch
                       the next), but each keyword's chain runs in parallel.
Phase 2  (details)  — all relevant detail pages fetched concurrently, bounded
                       by a per-run asyncio.Semaphore(_DETAIL_CONCURRENCY=20).

The synchronous scrape_drushim_jd() helper at the bottom is kept for
url_router / backfill callers and uses the original requests library.

Hebrew JD structure awareness
-------------------------------
Israeli job descriptions frequently use:
  • "תפקיד:"  / "תיאור התפקיד:" (Role / Job description)
  • "דרישות:"  (Requirements)
  • "תנאים:"   (Conditions)
  • "אחריות:"  (Responsibilities)

Confidential companies
-----------------------
Job postings where the company name is missing or is a generic placeholder
(e.g. "חברה בתחום הטכנולוגיה") are normalised to "Drushim (Confidential)".
"""
from __future__ import annotations

import asyncio
import logging
import re
import xml.etree.ElementTree as ET
from html import unescape
from typing import Optional
from urllib.parse import urljoin, urlencode

import httpx
import requests
from bs4 import BeautifulSoup, Tag

from backend.schemas.job import JobMatch
from backend.scrapers.base_scraper import BaseScraper, make_job_id, minimal_job_match
from backend.config import CREDIT_CONSERVATION_MODE

logger = logging.getLogger(__name__)

_BASE_URL        = "https://www.drushim.co.il"
_RSS_URL         = f"{_BASE_URL}/rss/"
_JOBS_PATH       = "/jobs/"
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
_HEADERS = {
    "User-Agent": _UA,
    "Accept-Language": "he-IL,he;q=0.9,en-US;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": _BASE_URL,
}
_TIMEOUT          = 15                     # seconds — sync helpers only
_TIMEOUT_ASYNC    = httpx.Timeout(10.0)    # strict 10 s per async request
_DETAIL_CONCURRENCY = 20                   # max simultaneous detail-page fetches
_MAX_PAGES        = 5
_MAX_DETAIL_FETCH = 25

# Hebrew section-heading patterns
_HE_HEADINGS = re.compile(
    r"^(תפקיד|תיאור\s*התפקיד|דרישות|תנאים|אחריות|יתרון|ניסיון|כישורים|"
    r"השכלה|תחומי\s*אחריות|תיאור\s*המשרה|דרישות\s*חובה|דרישות\s*יתרון)\s*[:：]\s*",
    re.MULTILINE,
)

_CONFIDENTIAL_RE = re.compile(
    r"^(חברה|לקוח|ארגון|מיזם|סטארט(אפ|-אפ)|startup|company|client|"
    r"undisclosed|confidential|[א-ת]{1,4})[\s\-ב-ת]{0,20}$",
    re.IGNORECASE,
)
_AGENCY_LABEL = "Drushim (Confidential)"


def _is_confidential(name: str) -> bool:
    name = name.strip()
    return not name or bool(_CONFIDENTIAL_RE.match(name))


def _clean_text(element: Optional[Tag]) -> str:
    if element is None:
        return ""
    return " ".join(element.get_text(separator=" ").split())


# ── Sync fetch helpers (used by scrape_drushim_jd / url_router) ──────────────

def _fetch_html(url: str, session: requests.Session) -> Optional[BeautifulSoup]:
    try:
        resp = session.get(url, headers=_HEADERS, timeout=_TIMEOUT)
        resp.raise_for_status()
        return BeautifulSoup(resp.content, "html.parser", from_encoding="utf-8")
    except Exception as exc:
        logger.warning("[DrushimScraper] Failed to fetch %s: %s", url, exc)
        return None


# ── Async fetch helpers ───────────────────────────────────────────────────────

async def _fetch_html_async(
    url: str, client: httpx.AsyncClient
) -> Optional[BeautifulSoup]:
    try:
        resp = await client.get(url)
        resp.raise_for_status()
        return BeautifulSoup(resp.content, "html.parser", from_encoding="utf-8")
    except Exception as exc:
        logger.warning("[DrushimScraper] Failed to fetch %s: %s", url, exc)
        return None


async def _fetch_rss_async(keyword: str, client: httpx.AsyncClient) -> list[dict]:
    """Fetch and parse the Drushim RSS feed for one keyword."""
    params: dict[str, str] = {}
    if keyword:
        params["q"] = keyword
    url = _RSS_URL + ("?" + urlencode(params) if params else "")
    try:
        resp = await client.get(
            url,
            headers={**_HEADERS, "Accept": "application/rss+xml,text/xml,*/*"},
        )
        resp.raise_for_status()
        return _parse_rss(resp.text)
    except Exception as exc:
        logger.warning("[DrushimScraper] RSS fetch failed (%s): %s — using HTML fallback", keyword, exc)
        return []


# ── RSS parsing ───────────────────────────────────────────────────────────────

def _parse_rss(xml_text: str) -> list[dict]:
    """Parse Drushim RSS XML into a list of raw job dicts."""
    jobs = []
    try:
        root = ET.fromstring(xml_text)
        channel = root.find("channel")
        if channel is None:
            return jobs
        for item in channel.findall("item"):
            def _text(tag: str) -> str:
                el = item.find(tag)
                return unescape(el.text or "").strip() if el is not None else ""

            title   = _text("title")
            link    = _text("link")
            company = _text("author") or _text("{http://purl.org/dc/elements/1.1/}creator")
            desc    = _text("description")

            soup = BeautifulSoup(desc, "html.parser")
            desc_text = soup.get_text(separator="\n").strip()

            if title and link:
                jobs.append({
                    "title":    title,
                    "company":  company,
                    "location": "",
                    "url":      link,
                    "summary":  desc_text,
                })
    except ET.ParseError as exc:
        logger.warning("[DrushimScraper] RSS parse error: %s", exc)
    return jobs


# ── HTML listing parsing ──────────────────────────────────────────────────────

def _parse_html_cards(soup: BeautifulSoup) -> list[dict]:
    """Parse job cards from a Drushim HTML listing page."""
    items = (
        soup.find_all("article", class_=re.compile(r"job", re.I))
        or soup.find_all("div",   class_=re.compile(r"job[\-_]?(item|card|listing|row|result)", re.I))
        or soup.find_all("li",    class_=re.compile(r"job|vacancy|position", re.I))
    )

    cards = []
    for item in items:
        link = item.find("a", href=True)
        href = link["href"] if link else ""
        if href and not href.startswith("http"):
            href = urljoin(_BASE_URL, href)

        title_el = (
            item.find(["h2", "h3", "h4"], class_=re.compile(r"title|role|position|name", re.I))
            or item.find(["h2", "h3", "h4"])
            or item.find(class_=re.compile(r"title|position|role", re.I))
        )
        title = _clean_text(title_el) or _clean_text(link)

        company_el = item.find(class_=re.compile(r"company|employer|client|org|מעסיק", re.I))
        company = _clean_text(company_el)

        location_el = item.find(class_=re.compile(r"location|city|area|region|מיקום", re.I))
        location = _clean_text(location_el)

        if title and href:
            cards.append({
                "title":    title,
                "company":  company,
                "location": location,
                "url":      href,
                "summary":  "",
            })
    return cards


# ── Detail page parsing ───────────────────────────────────────────────────────

def _parse_hebrew_jd(soup: BeautifulSoup) -> str:
    """
    Extract and structure the JD text from a Drushim detail page.

    Preserves paragraph structure even when HTML tags are deeply nested.
    Hebrew section headings (דרישות:, תנאים: etc.) are promoted to their
    own lines so the frontend formatter recognises them as headings.
    """
    for el in soup(["script", "style", "nav", "footer", "header", "aside",
                    "iframe", "noscript"]):
        el.extract()
    for el in soup(attrs={"class": re.compile(
        r"sidebar|related|recommended|similar|widget|banner|ad[\-_]|promo|share|social",
        re.I,
    )}):
        el.decompose()

    jd_node = (
        soup.find(id=re.compile(r"job[\-_]?(description|content|detail|body|text|info)", re.I))
        or soup.find(class_=re.compile(
            r"job[\-_]?(description|content|detail|body|text|info)|"
            r"position[\-_]?(description|detail|content)|"
            r"description[\-_]?(content|area|wrap)|jd[\-_]?content",
            re.I,
        ))
        or soup.find("main")
        or soup.find("article")
        or soup.body
    )

    paragraphs: list[str] = []
    current: list[str] = []

    def _flush() -> None:
        text = " ".join(current).strip()
        if text:
            paragraphs.append(text)
        current.clear()

    BLOCK_TAGS = {
        "p", "div", "section", "article", "li", "ul", "ol",
        "h1", "h2", "h3", "h4", "h5", "h6", "br", "hr",
        "blockquote", "pre", "table", "tr", "td", "th",
    }

    for node in (jd_node or soup).descendants:
        if hasattr(node, "name"):
            if node.name in BLOCK_TAGS:
                _flush()
        elif hasattr(node, "strip"):
            text = node.strip()
            if text:
                current.append(text)
    _flush()

    result_lines: list[str] = []
    for para in paragraphs:
        m = _HE_HEADINGS.match(para)
        if m:
            heading = para[: m.end()].rstrip()
            rest    = para[m.end() :].strip()
            result_lines.append(heading)
            if rest:
                result_lines.append(rest)
        else:
            result_lines.append(para)

    return "\n".join(result_lines)


def scrape_drushim_jd(url: str) -> str:
    """
    Fetch the full JD text for a single Drushim job URL.
    Used by url_router for backfill and inline card fetch (sync).
    """
    session = requests.Session()
    soup = _fetch_html(url, session)
    if soup is None:
        raise ValueError(f"[DrushimScraper] Could not load {url}")
    text = _parse_hebrew_jd(soup)
    if len(text) < 50:
        raise ValueError(f"[DrushimScraper] JD text too short ({len(text)} chars) for {url}")
    return text


# ── Scraper class ─────────────────────────────────────────────────────────────

class DrushimScraper(BaseScraper):
    """
    Scrapes open positions from drushim.co.il.

    Concurrency
    -----------
    Phase 1: All keywords are searched concurrently.  Within each keyword the
             RSS feed is tried first; if empty the HTML listing pages are
             fetched sequentially (page 1 → 2 → … until exhausted).
    Phase 2: All relevant detail pages are fetched concurrently, bounded by
             asyncio.Semaphore(_DETAIL_CONCURRENCY).
    Total wall time: max(keyword chain) + max(detail fetch) ≈ 3–8 s.

    Parameters
    ----------
    keyword  : single keyword filter — kept for backward compatibility.
               Ignored when *keywords* is supplied.
    keywords : list of search terms to run as separate RSS/HTML queries.
    category : tag applied to every returned JobMatch
    user_id  : owner of resulting JobMatch records
    max_jobs : cap on total detail-page requests per run
    """

    def __init__(
        self,
        company_name: str = "Drushim",
        company_url:  str = _BASE_URL + _JOBS_PATH,
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
        """Fetch all listing cards for one keyword (RSS → HTML fallback)."""
        # Try RSS first — fast and structured
        cards = await _fetch_rss_async(term, client)
        if cards:
            logger.debug("[DrushimScraper] keyword=%r → %d card(s) via RSS", term, len(cards))
            return cards

        # HTML fallback — paginate sequentially within this keyword
        all_cards: list[dict] = []
        for page in range(1, _MAX_PAGES + 1):
            params: dict[str, str] = {"page": str(page)}
            if term:
                params["q"] = term
            url  = _BASE_URL + _JOBS_PATH + "?" + urlencode(params)
            soup = await _fetch_html_async(url, client)
            if soup is None:
                break
            page_cards = _parse_html_cards(soup)
            if not page_cards:
                break
            all_cards.extend(page_cards)
            if not soup.find(class_=re.compile(r"next|pagination[\-_]?next", re.I)):
                break

        logger.debug("[DrushimScraper] keyword=%r → %d card(s) via HTML", term, len(all_cards))
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
            "[DrushimScraper] Found %d unique cards across %d keyword search(es)",
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
                    jd_text = _parse_hebrew_jd(detail_soup)
                    if len(jd_text) < 50:
                        jd_text = None
            else:
                summary = card.get("summary", "").strip()
                if len(summary) >= 50:
                    jd_text = summary

        company = card["company"]
        if _is_confidential(company):
            company = _AGENCY_LABEL

        match = minimal_job_match(
            job_id      = make_job_id(card["url"], prefix="drushim"),
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
            headers=_HEADERS,
            timeout=_TIMEOUT_ASYNC,
            follow_redirects=True,
        ) as client:
            # Phase 1 — parallel keyword searches
            all_cards = await self._gather_listing_cards(client)

            # Relevancy gate before any detail fetch
            relevant_cards = [c for c in all_cards if is_title_relevant(c["title"])]
            discarded = len(all_cards) - len(relevant_cards)
            if discarded:
                logger.info(
                    "[DrushimScraper] Discarded %d irrelevant title(s) before detail fetch",
                    discarded,
                )

            # Phase 2 — concurrent detail page fetches
            sem = asyncio.Semaphore(_DETAIL_CONCURRENCY)
            results: list[JobMatch] = list(await asyncio.gather(*[
                self._fetch_detail(card, client, sem)
                for card in relevant_cards[: self._max_jobs]
            ]))

        logger.info("[DrushimScraper] Returning %d job(s)", len(results))
        return results
