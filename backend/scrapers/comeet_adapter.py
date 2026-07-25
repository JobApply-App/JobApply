"""
Comeet ATS adapter.

How Comeet's public API works
------------------------------
Every Comeet-hosted careers page embeds a JSON blob called COMPANY_DATA
in its HTML.  That blob contains:
  - company_uid: numeric UID like "30.005"
  - token:       opaque string like "359F1DD13E1DD1DD1A813E6A6A"

The careers-api endpoint then requires both:
    GET https://www.comeet.co/careers-api/1.0/company/{uid}/positions?token={token}
    → JSON array of position objects (list-level data)

Each position has a `position_uid` that unlocks a richer detail endpoint:
    GET https://www.comeet.co/careers-api/1.0/company/{uid}/positions/{pos_uid}?token={token}
    → adds `description` and `requirements` HTML fields

This adapter:
1. Parses the company_url to extract the numeric UID (pattern XX.YYY in the path).
2. Fetches the Comeet careers page to scrape COMPANY_DATA.token.
3. Calls the list endpoint.
4. Concurrently fetches each position's detail (up to _DETAIL_CONCURRENCY at a time).
5. Strips HTML, combines fields into jd_text, and returns JobMatch objects.

Accepted company_url formats
-----------------------------
  "https://www.comeet.co/jobs/spark-hire/30.005/all"  ← standard Comeet-hosted URL
  "https://www.comeet.com/jobs/acme/12.3AB"           ← .com variant
  "12.3AB"                                             ← bare UID (requires token param)

If you already know the token, pass it as the `token` kwarg and the
page-scrape step is skipped entirely.
"""
from __future__ import annotations

import asyncio
import logging
import re
from html.parser import HTMLParser
from typing import Optional

import httpx

from backend.schemas.job import JobMatch
from backend.scrapers.base_scraper import BaseScraper, make_job_id, minimal_job_match, now_iso

logger = logging.getLogger(__name__)

_USER_AGENT       = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
_TIMEOUT          = 20           # seconds per request
_DETAIL_CONCURRENCY = 8          # max parallel detail fetches
_CAREERS_BASE     = "https://www.comeet.co"
_API_BASE         = f"{_CAREERS_BASE}/careers-api/1.0/company"

# Pattern: two hex chars, dot, three hex chars — e.g. "30.005" or "E5.866"
_UID_RE = re.compile(r'\b([0-9A-Fa-f]{2}\.[0-9A-Fa-f]{3})\b')


# ── HTML → plain text ─────────────────────────────────────────────────────────

class _HTMLStripper(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []

    def handle_data(self, data: str) -> None:
        text = data.strip()
        if text:
            self._parts.append(text)

    def result(self) -> str:
        return " ".join(self._parts)


def _strip_html(html: str) -> str:
    if not html:
        return ""
    p = _HTMLStripper()
    p.feed(html)
    return p.result().strip()


# ── URL / UID helpers ─────────────────────────────────────────────────────────

def _extract_uid_from_url(url: str) -> Optional[str]:
    """Return the first XX.YYY UID found in the URL path, or None."""
    m = _UID_RE.search(url)
    return m.group(1) if m else None


def _careers_page_url(url: str) -> str:
    """
    Build the Comeet-hosted careers page URL for a given input.

    The /all suffix on comeet.co job URLs triggers a 301 redirect to comeet.com
    which returns 404.  Strip it so we land on the actual SPA page.
    """
    url = url.strip().rstrip("/")
    # Strip trailing /all — it causes a 301→.com→404 chain on www.comeet.co
    if url.endswith("/all"):
        url = url[:-4]
    if url.startswith("http"):
        # Normalise: always use www.comeet.co host
        url = re.sub(r"https?://(?:www\.)?comeet\.(com|co)", _CAREERS_BASE, url)
        return url
    # Bare UID
    return f"{_CAREERS_BASE}/jobs/{url}"


# ── Comeet adapter ────────────────────────────────────────────────────────────

class ComeetAdapter(BaseScraper):
    """
    Scraper for Comeet-hosted career pages.

    Parameters
    ----------
    company_name : str
        Human-readable company name, e.g. "Spark Hire".
    company_url : str
        Any URL containing the Comeet company UID (XX.YYY), e.g.
        "https://www.comeet.co/jobs/spark-hire/30.005/all".
    token : str | None
        Comeet API token.  When provided, skips the page-scrape step.
        Obtain from COMPANY_DATA.token on the careers page.
    user_id : str
        Platform user these jobs are assigned to.
    fetch_details : bool
        Fetch per-position detail endpoint for richer JD text (default True).
        Disable for faster scrapes when description quality matters less.
    """

    def __init__(
        self,
        company_name:   str,
        company_url:    str,
        token:          Optional[str] = None,
        user_id:        str = "default",
        fetch_details:  bool = True,
    ) -> None:
        super().__init__(company_name, company_url)
        self._uid           = _extract_uid_from_url(company_url)
        self._token: Optional[str] = token
        self._user_id       = user_id
        self._fetch_details = fetch_details
        self._page_url      = _careers_page_url(company_url)

    # ── Public ────────────────────────────────────────────────────────────────

    async def fetch_jobs(self) -> list[JobMatch]:
        """
        Fetch all open positions for this company.  Never raises.
        """
        logger.info(
            "[ComeetAdapter] %s — starting fetch (careers_page=%r)",
            self.company_name, self._page_url,
        )

        try:
            uid, token = await self._resolve_credentials()
        except Exception as exc:
            logger.warning(
                "[ComeetAdapter] %s — could not resolve credentials: %s",
                self.company_name, exc,
            )
            return []

        logger.info(
            "[ComeetAdapter] %s — credentials resolved uid=%r token=%s",
            self.company_name, uid, token[:6] + "…" if token else "MISSING",
        )

        try:
            positions = await self._fetch_positions_list(uid, token)
        except Exception as exc:
            logger.warning(
                "[ComeetAdapter] %s — positions list failed: %s",
                self.company_name, exc,
            )
            return []

        logger.info(
            "[ComeetAdapter] %s — API returned %d position(s)",
            self.company_name, len(positions),
        )

        if self._fetch_details:
            positions = await self._enrich_with_details(uid, token, positions)

        jobs = [self._parse_position(pos) for pos in positions]
        valid = [j for j in jobs if j is not None]
        filtered = len(positions) - len(valid)
        logger.info(
            "[ComeetAdapter] %s — %d parsed, %d valid, %d filtered (missing title/url)",
            self.company_name, len(positions), len(valid), filtered,
        )
        return valid  # type: ignore[return-value]

    # ── Credential resolution ─────────────────────────────────────────────────

    async def _resolve_credentials(self) -> tuple[str, str]:
        """
        Return (uid, token).  Scrapes the careers page when either is missing.
        """
        if self._uid and self._token:
            return self._uid, self._token

        uid, token = await self._scrape_credentials(self._page_url)

        if not uid:
            raise ValueError(
                f"Could not find Comeet company UID in URL '{self.company_url}' "
                "or on the careers page."
            )
        if not token:
            raise ValueError(
                f"Could not find Comeet API token on '{self._page_url}'."
            )

        self._uid   = uid
        self._token = token
        return uid, token

    @staticmethod
    async def _fetch_html_with_fallback(client: httpx.AsyncClient, url: str) -> str:
        """
        Try `url`; if a 4xx is returned, retry with the last path segment
        stripped (up to 2 times) so that URL-schema mismatches don't block
        credential extraction.
        """
        candidate = url
        for _ in range(3):
            resp = await client.get(candidate, headers={"User-Agent": _USER_AGENT})
            if resp.status_code < 400:
                return resp.text
            logger.debug(
                "[ComeetAdapter] %d on %s — trimming path and retrying",
                resp.status_code, candidate,
            )
            # Strip last path segment (e.g. /uid or /slug)
            trimmed = candidate.rsplit("/", 1)[0]
            if trimmed == candidate or not trimmed.startswith("http"):
                break
            candidate = trimmed
        # Last attempt: raise so the caller can surface the error
        resp = await client.get(url, headers={"User-Agent": _USER_AGENT})
        resp.raise_for_status()
        return resp.text

    async def _scrape_credentials(self, page_url: str) -> tuple[Optional[str], Optional[str]]:
        """
        Fetch a Comeet careers page and extract the numeric UID and API token
        from the embedded COMPANY_DATA JavaScript variable.

        Falls back to progressively shorter URL paths when a 4xx is returned
        (e.g. /jobs/slug/uid → /jobs/slug → company-site root).
        """
        async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
            html = await self._fetch_html_with_fallback(client, page_url)

        uid   = self._uid or _extract_uid_from_url(html)
        token: Optional[str] = None

        # COMPANY_DATA.company_uid
        m_uid = re.search(r'"company_uid"\s*:\s*"([0-9A-Fa-f]{2}\.[0-9A-Fa-f]{3})"', html)
        if m_uid:
            uid = m_uid.group(1)

        # COMPANY_DATA.token
        m_tok = re.search(r'"token"\s*:\s*"([A-F0-9]{20,})"', html)
        if m_tok:
            token = m_tok.group(1)

        logger.debug(
            "[ComeetAdapter] Scraped credentials uid=%r token=%s",
            uid, "found" if token else "NOT FOUND",
        )
        return uid, token

    # ── API calls ─────────────────────────────────────────────────────────────

    async def _fetch_positions_list(self, uid: str, token: str) -> list[dict]:
        url = f"{_API_BASE}/{uid}/positions"
        logger.info("[ComeetAdapter] %s — fetching positions from %s", self.company_name, url)
        async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
            resp = await client.get(
                url,
                params  = {"token": token},
                headers = {
                    "User-Agent":      _USER_AGENT,
                    "Accept":          "application/json, text/plain, */*",
                    "Referer":         self._page_url,
                    "X-Requested-With": "XMLHttpRequest",
                },
            )
            raw_preview = resp.text[:200]
            logger.info(
                "[ComeetAdapter] %s — positions API status=%d raw_preview=%r",
                self.company_name, resp.status_code, raw_preview,
            )
            resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, list):
            raise ValueError(f"Unexpected positions response: {type(data).__name__}")
        logger.info(
            "[ComeetAdapter] %s — positions list returned %d items",
            self.company_name, len(data),
        )
        if data:
            first = data[0]
            logger.info(
                "[ComeetAdapter] %s — first position keys=%s title=%r apply_url=%r",
                self.company_name,
                list(first.keys()),
                first.get("name"),
                first.get("careers_page_active_url")
                    or first.get("careers_page_url")
                    or first.get("position_url"),
            )
        return data

    async def _fetch_one_detail(
        self,
        client:  httpx.AsyncClient,
        uid:     str,
        pos_uid: str,
        token:   str,
        sem:     asyncio.Semaphore,
    ) -> Optional[dict]:
        async with sem:
            try:
                resp = await client.get(
                    f"{_API_BASE}/{uid}/positions/{pos_uid}",
                    params  = {"token": token},
                    headers = {
                        "User-Agent": _USER_AGENT,
                        "Accept":     "application/json",
                    },
                )
                if resp.status_code == 200:
                    return resp.json() if isinstance(resp.json(), dict) else None
            except Exception as exc:
                logger.debug(
                    "[ComeetAdapter] Detail fetch failed for pos %s: %s", pos_uid, exc
                )
            return None

    async def _enrich_with_details(
        self, uid: str, token: str, positions: list[dict]
    ) -> list[dict]:
        """
        Fetch per-position detail pages concurrently and merge the richer
        fields (description, requirements) back into each list item.
        """
        sem = asyncio.Semaphore(_DETAIL_CONCURRENCY)
        async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
            tasks = [
                self._fetch_one_detail(client, uid, pos.get("position_uid", ""), token, sem)
                for pos in positions
                if pos.get("position_uid")
            ]
            details = await asyncio.gather(*tasks, return_exceptions=False)

        enriched: list[dict] = []
        detail_iter = iter(details)
        for pos in positions:
            if pos.get("position_uid"):
                detail = next(detail_iter, None)
                if detail:
                    pos = {**pos, **detail}   # detail fields win for completeness
            enriched.append(pos)
        return enriched

    # ── Parsing ───────────────────────────────────────────────────────────────

    def _parse_position(self, pos: dict) -> Optional[JobMatch]:
        if not isinstance(pos, dict):
            return None

        title     = (pos.get("name") or "").strip()
        apply_url = (
            pos.get("careers_page_active_url")
            or pos.get("careers_page_url")
            or pos.get("position_url")
            or ""
        ).strip() or None

        if not title or not apply_url:
            return None

        location  = self._build_location(pos)
        jd_text   = self._build_jd_text(pos)
        posted_at = self._format_posted(pos.get("time_updated") or pos.get("time_created"))
        job_id    = make_job_id(apply_url, prefix="comeet")

        return minimal_job_match(
            job_id      = job_id,
            title       = title,
            company     = self.company_name,
            location    = location,
            apply_url   = apply_url,
            jd_text     = jd_text,
            posted_at   = posted_at,
            source_type = self.source_type,
            user_id     = self._user_id,
        )

    @staticmethod
    def _build_location(pos: dict) -> str:
        remote = pos.get("Remote") or ""
        if remote.lower() == "remote":
            city = (pos.get("location_object") or {}).get("city", "")
            return f"Remote{' · ' + city if city else ''}"
        loc_obj = pos.get("location_object") or {}
        city    = loc_obj.get("city")    or pos.get("location") or ""
        country = loc_obj.get("country") or ""
        parts   = [p for p in (city, country) if p]
        return ", ".join(parts) or "Unknown"

    @staticmethod
    def _build_jd_text(pos: dict) -> Optional[str]:
        parts: list[str] = []
        name   = pos.get("name", "")
        dept   = pos.get("department", "")
        emp    = pos.get("employment_type", "")
        exp    = pos.get("experience_level", "")

        if name:
            parts.append(f"Position: {name}")
        if dept:
            parts.append(f"Department: {dept}")
        if emp or exp:
            parts.append(f"Employment: {emp} {exp}".strip())

        for field in ("description", "Responsibilities", "responsibilities",
                      "requirements", "Requirements", "nice_to_have"):
            raw = pos.get(field) or ""
            if raw:
                parts.append(_strip_html(raw))

        return "\n\n".join(p for p in parts if p) or None

    @staticmethod
    def _format_posted(ts: object) -> str:
        if not ts:
            return ""
        from datetime import datetime, timezone
        try:
            dt  = datetime.fromisoformat(str(ts).rstrip("Z")).replace(tzinfo=timezone.utc)
            age = (datetime.now(timezone.utc) - dt).days
            if age == 0:   return "today"
            if age == 1:   return "1d ago"
            if age < 30:   return f"{age}d ago"
            return f"{age // 30}mo ago"
        except Exception:
            return ""
