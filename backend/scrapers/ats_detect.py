"""
Which applicant-tracking system is behind a company's careers page.

Stage 0 of docs/research/10-company-page-watching-pilot.md. Many "own site"
careers pages are a skin over a known ATS: on 2026-11-28 Mobileye's page
linked to jobs.eu.lever.co/mobileye, NICE's to boards.eu.greenhouse.io/nice,
Fiverr's to comeet.com/jobs/fiverr/60.002, and CyberArk's to Palo Alto
Networks' Workday site. Each of those already has an adapter with a public
JSON API, so the careers page itself never needs to be scraped.

    detect_from_url(url)        the URL is itself on an ATS
    detect_from_html(html)      the page links to or embeds one
    await detect_ats(url)       both, fetching the page once when needed

Each returns (adapter, company_url) for scraper_from_config, or None. No AI.
A page that loads its board from a script (Playtika's greenHouseMain.js) or
uses an ATS we have no adapter for (Ashby, HiBob, Eightfold) gives None.
"""
from __future__ import annotations

import logging
import re
from collections import Counter
from typing import Optional
from urllib.parse import urlparse

import httpx

from backend.utilities.safe_url import httpx_guard_hooks

logger = logging.getLogger(__name__)

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
_TIMEOUT = 20
_MAX_HTML = 5_000_000           # Mobileye's careers page alone is 2.2 MB

_SLUG = r"[A-Za-z0-9][A-Za-z0-9_.-]*"

# (adapter, pattern, company_url template). Each pattern's groups fill the
# template. Words that follow a host but are not a company (embed, v0, ...)
# are excluded by _NOT_A_COMPANY.
_PATTERNS: tuple[tuple[str, re.Pattern[str], str], ...] = (
    ("greenhouse",
     re.compile(rf"https?://(?:job-boards|boards)(\.eu)?\.greenhouse\.io/({_SLUG})", re.I),
     "https://job-boards{0}.greenhouse.io/{1}"),
    ("greenhouse",
     re.compile(rf"boards-api\.greenhouse\.io/v1/boards/({_SLUG})", re.I),
     "https://job-boards.greenhouse.io/{0}"),
    ("greenhouse",
     re.compile(rf"greenhouse\.io/embed/job_board(?:/js)?\?for=({_SLUG})", re.I),
     "https://job-boards.greenhouse.io/{0}"),
    ("lever",
     re.compile(rf"https?://jobs(\.eu)?\.lever\.co/({_SLUG})", re.I),
     "https://jobs{0}.lever.co/{1}"),
    ("lever",
     re.compile(rf"api(\.eu)?\.lever\.co/v0/postings/({_SLUG})", re.I),
     "https://jobs{0}.lever.co/{1}"),
    ("workday",
     re.compile(rf"https?://([a-z0-9-]+\.wd\d+\.myworkdayjobs\.com)/(?:[a-z]{{2}}-[A-Z]{{2}}/)?({_SLUG})"),
     "https://{0}/{1}"),
    ("comeet",
     re.compile(r"comeet\.(?:co|com)/jobs/([A-Za-z0-9_-]+)/([0-9A-Fa-f]{2}\.[0-9A-Fa-f]{3})\b", re.I),
     "https://www.comeet.com/jobs/{0}/{1}"),
)
_NOT_A_COMPANY = {"embed", "v0", "v1", "jobs", "wday", "api", "js", "static", "assets"}


def _normalise(groups: tuple) -> tuple:
    return tuple(g or "" for g in groups)


def _matches(text: str) -> Counter:
    """(adapter, company_url) → how many times the text points at it."""
    found: Counter = Counter()
    for adapter, pattern, template in _PATTERNS:
        for m in pattern.finditer(text):
            groups = _normalise(m.groups())
            if groups[-1].casefold() in _NOT_A_COMPANY:
                continue
            found[(adapter, template.format(*groups))] += 1
    return found


def detect_from_url(url: str) -> Optional[tuple[str, str]]:
    """(adapter, company_url) when `url` itself is on an ATS we can read."""
    found = _matches(url)
    return found.most_common(1)[0][0] if found else None


def detect_from_html(html: str) -> Optional[tuple[str, str]]:
    """
    The ATS board a careers page points at most often. Mobileye's page links
    to its own Lever board 150+ times and to a subsidiary's Comeet board 13
    times; the count picks the company's own.
    """
    found = _matches(html or "")
    if not found:
        return None
    (best, count), *rest = found.most_common()
    if rest:
        logger.info("[ats_detect] %s (%d links) over %d other board(s)", best, count, len(rest))
    return best


async def detect_ats(url: str) -> Optional[tuple[str, str]]:
    """
    (adapter, company_url) for a careers page, or None. Fetches the page once,
    through the SSRF guard (redirects to private addresses are refused), only
    when the URL itself is not on an ATS. Never raises.
    """
    direct = detect_from_url(url)
    if direct:
        return direct
    host = (urlparse(url).hostname or "").lower()
    try:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT, follow_redirects=True, event_hooks=httpx_guard_hooks(),
            headers={"User-Agent": _USER_AGENT, "Accept": "text/html"},
        ) as client:
            resp = await client.get(url)
        if resp.status_code >= 400:
            logger.warning("[ats_detect] %s answered %d", host, resp.status_code)
            return None
        # A redirect can land on the ATS itself (careers.example.com → jobs.lever.co/example).
        return detect_from_url(str(resp.url)) or detect_from_html(resp.text[:_MAX_HTML])
    except Exception as exc:
        logger.warning("[ats_detect] could not read %s: %s", host, type(exc).__name__)
        return None
