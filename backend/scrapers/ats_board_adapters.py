"""
Company-level Greenhouse and Lever adapters.

ats_api_scraper.py fetches ONE posting from its URL. These adapters fetch
EVERY open posting a company has, in a single call to each platform's
public, unauthenticated list API:

    Greenhouse  GET https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true
                → {"jobs": [{id, title, absolute_url, location{name}, content, departments, first_published, ...}]}
    Lever       GET https://api.lever.co/v0/postings/{slug}?mode=json
                → [{id, text, hostedUrl, categories{location, team, commitment}, createdAt(ms), descriptionPlain, lists, ...}]

Accepted company_url formats:
    Greenhouse  https://boards.greenhouse.io/wizinc  ·  https://job-boards.greenhouse.io/wizinc  ·  wizinc
    Lever       https://jobs.lever.co/palantir  ·  palantir

Only jobs in Israel or open to remote work are kept (founder's call,
2026-11-28). A remote posting stays even when its office is abroad: it can be
done from Israel. A posting listed in several places is kept when any one of
them is in Israel.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse

import httpx

from backend.schemas.job import JobMatch
from backend.scrapers.base_scraper import BaseScraper, make_job_id, minimal_job_match
from backend.scrapers.parsing_engine import ParsingEngine
from backend.services.israel_cities import resolve_city

logger = logging.getLogger(__name__)

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
_TIMEOUT = 20
_SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_ISRAEL_RE = re.compile(r"\bisrael\b|ישראל", re.IGNORECASE)   # not "IL": that is Illinois too
_REMOTE_RE = re.compile(r"\bremote\b|work from home|\bwfh\b|anywhere|מהבית", re.IGNORECASE)


def in_israel(location: str) -> bool:
    """True when this one location string names Israel or an Israeli locality."""
    if not location:
        return False
    if _ISRAEL_RE.search(location.strip()):
        return True
    return any(resolve_city(part) for part in re.split(r"[;/|]", location))


def israel_or_remote(locations: list[str], remote: bool = False) -> bool:
    """True when any listed location is in Israel or the job can be done remotely."""
    if remote:
        return True
    return any(loc and (_REMOTE_RE.search(loc) or in_israel(loc)) for loc in locations)


def _board_slug(company_url: str, hosts: tuple[str, ...]) -> Optional[str]:
    """First path segment of a board URL on one of `hosts`, or a bare slug."""
    raw = company_url.strip()
    if "://" not in raw:
        return raw if _SLUG_RE.match(raw) else None
    parsed = urlparse(raw)
    if (parsed.hostname or "").lower() not in hosts:
        return None
    first = parsed.path.strip("/").split("/")[0]
    return first if first and _SLUG_RE.match(first) else None


def _age_label(dt: Optional[datetime]) -> str:
    """Same labels the Comeet adapter uses for posted_at."""
    if dt is None:
        return ""
    age = (datetime.now(timezone.utc) - dt).days
    if age <= 0:
        return "today"
    if age == 1:
        return "1d ago"
    if age < 30:
        return f"{age}d ago"
    return f"{age // 30}mo ago"


class _BoardAdapter(BaseScraper):
    """Shared fetch-and-parse loop. Subclasses define the URL and the parsing."""

    _name  = "BoardAdapter"
    _hosts: tuple[str, ...] = ()

    def __init__(self, company_name: str, company_url: str, user_id: str = "default") -> None:
        super().__init__(company_name, company_url)
        self._user_id = user_id
        self._slug    = _board_slug(company_url, self._hosts)

    def _api_url(self, slug: str) -> str:
        raise NotImplementedError

    def _postings(self, data: object) -> list:
        raise NotImplementedError

    def _parse(self, posting: dict) -> Optional[JobMatch]:
        raise NotImplementedError

    async def fetch_jobs(self) -> list[JobMatch]:
        """Fetch all open postings for this company. Never raises."""
        if not self._slug:
            logger.warning(
                "[%s] %s — no board slug in %r", self._name, self.company_name, self.company_url,
            )
            return []
        url = self._api_url(self._slug)
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
                resp = await client.get(
                    url, headers={"User-Agent": _USER_AGENT, "Accept": "application/json"},
                )
                resp.raise_for_status()
            postings = self._postings(resp.json())
        except Exception as exc:
            logger.warning("[%s] %s — list fetch failed (%s): %s", self._name, self.company_name, url, exc)
            return []

        dicts = [p for p in postings if isinstance(p, dict)]
        local = [p for p in dicts if self._in_scope(p)]
        jobs  = [self._parse(p) for p in local]
        valid = [j for j in jobs if j is not None]
        logger.info(
            "[%s] %s — API returned %d posting(s), %d in Israel or remote, %d valid",
            self._name, self.company_name, len(postings), len(local), len(valid),
        )
        return valid

    def _in_scope(self, posting: dict) -> bool:
        raise NotImplementedError

    def _job(self, *, prefix: str, title: str, apply_url: str, location: str,
             jd_text: Optional[str], posted: Optional[datetime]) -> JobMatch:
        return minimal_job_match(
            job_id      = make_job_id(apply_url, prefix=prefix),
            title       = title,
            company     = self.company_name,
            location    = location or "Unknown",
            apply_url   = apply_url,
            jd_text     = jd_text or None,
            posted_at   = _age_label(posted),
            source_type = self.source_type,
            user_id     = self._user_id,
        )


class GreenhouseBoardAdapter(_BoardAdapter):
    _name  = "GreenhouseBoardAdapter"
    _hosts = ("boards.greenhouse.io", "job-boards.greenhouse.io")

    def _api_url(self, slug: str) -> str:
        return f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"

    def _postings(self, data: object) -> list:
        if not isinstance(data, dict) or not isinstance(data.get("jobs"), list):
            raise ValueError(f"unexpected Greenhouse response: {type(data).__name__}")
        return data["jobs"]

    def _in_scope(self, p: dict) -> bool:
        locations = [(p.get("location") or {}).get("name") or ""]
        for office in p.get("offices") or []:
            if isinstance(office, dict):
                locations += [office.get("name") or "", office.get("location") or ""]
        return israel_or_remote(locations)

    def _parse(self, p: dict) -> Optional[JobMatch]:
        title     = (p.get("title") or "").strip()
        apply_url = (p.get("absolute_url") or "").strip()
        if not title or not apply_url:
            return None

        parts = [f"Position: {title}"]
        depts = ", ".join(d.get("name", "") for d in p.get("departments") or [] if isinstance(d, dict))
        if depts:
            parts.append(f"Department: {depts}")
        body = ParsingEngine.html_to_text(p.get("content") or "")
        if body:
            parts.append(body)

        posted = None
        ts = p.get("first_published") or p.get("updated_at")
        if ts:
            try:
                posted = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
            except ValueError:
                posted = None

        return self._job(
            prefix    = "greenhouse",
            title     = title,
            apply_url = apply_url,
            location  = ((p.get("location") or {}).get("name") or "").strip(),
            jd_text   = "\n\n".join(parts),
            posted    = posted,
        )


class LeverBoardAdapter(_BoardAdapter):
    _name  = "LeverBoardAdapter"
    _hosts = ("jobs.lever.co",)

    def _api_url(self, slug: str) -> str:
        return f"https://api.lever.co/v0/postings/{slug}?mode=json"

    def _postings(self, data: object) -> list:
        if not isinstance(data, list):
            raise ValueError(f"unexpected Lever response: {type(data).__name__}")
        return data

    def _in_scope(self, p: dict) -> bool:
        cats = p.get("categories") or {}
        locations = [cats.get("location") or "", *(cats.get("allLocations") or [])]
        if (p.get("country") or "").upper() == "IL":
            locations.append("Israel")
        return israel_or_remote(locations, remote=(p.get("workplaceType") or "").lower() == "remote")

    def _parse(self, p: dict) -> Optional[JobMatch]:
        title     = (p.get("text") or "").strip()
        apply_url = (p.get("hostedUrl") or p.get("applyUrl") or "").strip()
        if not title or not apply_url:
            return None

        cats = p.get("categories") or {}
        parts = [f"Position: {title}"]
        team = cats.get("department") or cats.get("team") or ""
        if team:
            parts.append(f"Department: {team}")
        if cats.get("commitment"):
            parts.append(f"Employment: {cats['commitment']}")
        if p.get("descriptionPlain"):
            parts.append(p["descriptionPlain"].strip())
        for section in p.get("lists") or []:
            if not isinstance(section, dict):
                continue
            body = ParsingEngine.html_to_text(section.get("content") or "")
            heading = (section.get("text") or "").strip()
            if body:
                parts.append(f"{heading}\n{body}" if heading else body)
        if p.get("additionalPlain"):
            parts.append(p["additionalPlain"].strip())

        location = (cats.get("location") or "").strip()
        if (p.get("workplaceType") or "").lower() == "remote":
            location = f"Remote{' · ' + location if location else ''}"

        posted = None
        if isinstance(p.get("createdAt"), (int, float)):
            posted = datetime.fromtimestamp(p["createdAt"] / 1000, tz=timezone.utc)

        return self._job(
            prefix    = "lever",
            title     = title,
            apply_url = apply_url,
            location  = location,
            jd_text   = "\n\n".join(parts),
            posted    = posted,
        )
