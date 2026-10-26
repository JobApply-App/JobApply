"""
URL Router — maps a job posting URL to the correct scraper.

Public entry points:

1.  scrape_jd_text(url: str) -> str
    Fetches and returns the full JD text for a single job URL.
    Routes to a site-specific parser when available; falls back to the
    generic url_scraper.scrape_job_post() for unknown hosts.
    Used by:
      - backend.api.routes.jobs  → POST /{job_id}/fetch-jd
      - backend.services.jd_backfill_service → backfill_jd_text()

2.  get_scraper_for_url(url: str) -> Optional[BaseScraper]
    Returns a BaseScraper instance capable of calling fetch_jobs() for
    the host found in `url`.  Returns None for unknown hosts.

3.  scrape_linkedin_job(url: str) -> ScrapedJob
    Fetches a LinkedIn job posting via a RapidAPI LinkedIn-jobs provider
    (RAPIDAPI_KEY / RAPIDAPI_LINKEDIN_HOST / RAPIDAPI_LINKEDIN_PATH env vars)
    and returns JD text plus title/company. Raises LinkedInRapidApiAuthError /
    LinkedInRapidApiQuotaError / ValueError — callers (e.g. POST
    /api/jobs/analyze) should catch these explicitly to surface a precise,
    human-readable error instead of a generic scrape failure.

Domain routing table
--------------------
linkedin.com         → _linkedin_scrape  (unauthenticated requests, JSON-LD extraction)
gotfriends.co.il     → scrape_gotfriends_jd
dialog.co.il         → scrape_dialog_jd
nisha.co.il          → scrape_nisha_jd
alljobs.co.il        → scrape_alljobs_jd
drushim.co.il        → scrape_drushim_jd
comeet.co / .com     → generic scraper
<everything else>    → generic scrape_job_post

LinkedIn strategy
-----------------
scrape_jd_text() / scrape_jd_text_async() (bulk enrichment, fetch-jd, backfill)
still use the authentication-free direct-fetch path: discovery routes through
GoogleDorkScraper, which surfaces only public /jobs/view/ URLs indexed by
Google, and _linkedin_scrape() extracts the JSON-LD block those pages embed
without any session cookie or browser. If a page requires a login the
is_valid_job_content() gatekeeper marks it failed cleanly.

scrape_linkedin_job() (used by POST /api/jobs/analyze, a single ad-hoc URL
pasted by the user) instead goes through a RapidAPI LinkedIn-jobs provider —
LinkedIn's bot-detection blocks the direct-fetch path far more aggressively
for arbitrary, non-Google-indexed URLs (HTTP 999 / challenge pages), so this
path avoids hitting LinkedIn directly at all.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import re
import threading
import time
from typing import Callable, Optional
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from backend.scrapers.base_scraper import BaseScraper
from backend.utilities.html_guard import html_visible_text, visible_text

logger = logging.getLogger(__name__)

# ── RapidAPI LinkedIn-jobs provider config ────────────────────────────────────
# LinkedIn's own pages reliably block direct, unauthenticated fetches (HTTP 999
# / challenge pages / login walls — see _linkedin_fetch_soup below, still used
# by the legacy _linkedin_scrape() path for non-analyze callers). For the
# /api/jobs/analyze flow we instead go through a RapidAPI LinkedIn-jobs
# provider, which proxies the request through infrastructure LinkedIn doesn't
# block the same way.
#
# Default host/path/params below match "LinkedIn Job Search API" by Fantastic
# Jobs (https://rapidapi.com/fantastic-jobs-fantastic-jobs-default/api/
# linkedin-job-search-api) — verified live against a real subscription:
#   GET /active-jb?time_frame=6m&linkedin_id={id}&description_format=text&limit=1
# Response is a bare JSON array (not a dict wrapper); an empty array means no
# job matched that linkedin_id within the time_frame window (job.title,
# job.organization, job.description_text carry the fields we need).
#
# All are configurable via env so the provider can be swapped without a code
# change — different RapidAPI LinkedIn-jobs listings expose different
# hosts/paths/param/field names.
RAPIDAPI_KEY                = os.environ.get("RAPIDAPI_KEY", "")
RAPIDAPI_LINKEDIN_HOST      = os.environ.get("RAPIDAPI_LINKEDIN_HOST", "linkedin-job-search-api.p.rapidapi.com")
RAPIDAPI_LINKEDIN_PATH      = os.environ.get("RAPIDAPI_LINKEDIN_PATH", "/active-jb")
RAPIDAPI_LINKEDIN_TIME_FRAME = os.environ.get("RAPIDAPI_LINKEDIN_TIME_FRAME", "6m")


# ── Exception hierarchy ───────────────────────────────────────────────────────

class LinkedInAuthWallError(Exception):
    """LinkedIn returned a login/authwall page — no cookie or session expired."""

class LinkedInRedirectError(Exception):
    """
    LinkedIn redirected to a challenge/checkpoint URL — bot-detection signal.
    Callers must NOT increment enrichment_failures; record in KV and halt.
    """

class LinkedInChallengeError(Exception):
    """
    LinkedIn returned a challenge/CAPTCHA page body (2xx but bad content).
    raw_html carries the page source for optional LLM salvage.
    """
    def __init__(self, message: str, raw_html: str = "") -> None:
        super().__init__(message)
        self.raw_html = raw_html


class LinkedInRapidApiError(Exception):
    """Base class for RapidAPI-provider-specific LinkedIn scrape failures."""


class LinkedInRapidApiAuthError(LinkedInRapidApiError):
    """
    RAPIDAPI_KEY is missing, or the provider rejected it (401/403).
    This is a server misconfiguration, not a user auth failure — callers must
    NOT map this to HTTP 401, since the frontend treats 401 as "your session
    expired" and force-logs the user out.
    """


class LinkedInRapidApiQuotaError(LinkedInRapidApiError):
    """RapidAPI returned 429 — the subscribed plan's request quota is exhausted."""


# ── LinkedIn scraper constants ────────────────────────────────────────────────

_LI_MIN_CHARS = 250

_LINKEDIN_NOISE_PATTERNS: list[re.Pattern] = [
    re.compile(p, re.IGNORECASE) for p in [
        r"Agree\s*&\s*Join\s*LinkedIn",
        r"Sign\s+in\s+to\s+(?:view|see|access|apply|create\s+(?:a\s+)?job\s+alert)",
        r"Join\s+to\s+apply",
        r"Join\s+now",
        r"Cookie\s+Policy",
        r"Privacy\s+Policy",
        r"User\s+Agreement",
        r"See\s+more\s+jobs",
        r"Show\s+more",
        r"Show\s+less",
        r"Get\s+notified\s+about\s+new",
        r"Be\s+an\s+early\s+applicant",
        r"Actively\s+Hiring",
        r"Easy\s+Apply",
        r"Save\s+this\s+job",
        r"Report\s+this\s+job",
        r"Dismiss",
        r"Submit\s+application",
        r"Back\s+to\s+job\s+search",
        r"Similar\s+jobs",
        r"People\s+also\s+viewed",
        r"You\s+may\s+also\s+like",
        r"Set\s+alert\s+for\s+similar\s+jobs",
        r"להגיש\s+מועמדות",
        r"הסכמה\s+והצטרפות",
        r"מדיניות\s+עוגיות",
        r"ראה\s+עוד",
        r"הצג\s+פחות",
        r"התחבר\s+כדי\s+לצפות",
    ]
]

_LOGINWALL_SIGNALS = [
    "sign in", "join linkedin", "cookie policy", "agree & join",
    "create an account", "join now",
]

_LINKEDIN_CHALLENGE_SIGNALS: tuple[str, ...] = (
    "linkedin.com/checkpoint/",
    "linkedin.com/authwall",
    "challenge?",
    "/uas/login",
    "verify your identity",
    "security verification",
    "are you a robot",
    "prove you're human",
)

# Rotating pool of realistic desktop User-Agent strings.
_LINKEDIN_UA_POOL: tuple[str, ...] = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.7151.55 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.7103.116 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:127.0) Gecko/20100101 Firefox/127.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
)

# Rate-limiter state (shared across threads)
_LINKEDIN_RATE_LOCK     = threading.Lock()
_LINKEDIN_LAST_REQ_TIME = 0.0
_LINKEDIN_MIN_INTERVAL  = 1.2   # seconds between requests
_LINKEDIN_JITTER        = 0.6   # additional random jitter


# ── LinkedIn helpers ──────────────────────────────────────────────────────────

def _clean_linkedin_text(raw: str) -> str:
    """Strip LinkedIn UI boilerplate and normalise whitespace."""
    for pattern in _LINKEDIN_NOISE_PATTERNS:
        raw = pattern.sub("", raw)
    lines = [line.strip() for line in raw.splitlines() if len(line.strip()) > 2]
    return "\n".join(lines)


def _is_loginwall(text: str) -> bool:
    """Return True when ≥ 3 login-wall signals appear in text."""
    lower = text.lower()
    return sum(1 for sig in _LOGINWALL_SIGNALS if sig in lower) >= 3


def _linkedin_rate_wait() -> None:
    """Block the calling thread until safe to fire the next LinkedIn request."""
    global _LINKEDIN_LAST_REQ_TIME
    with _LINKEDIN_RATE_LOCK:
        now   = time.time()
        gap   = _LINKEDIN_MIN_INTERVAL + random.uniform(0, _LINKEDIN_JITTER)
        since = now - _LINKEDIN_LAST_REQ_TIME
        if since < gap:
            time.sleep(gap - since)
        _LINKEDIN_LAST_REQ_TIME = time.time()


def _linkedin_headers() -> dict[str, str]:
    """Build browser-grade headers with a randomly selected UA."""
    return {
        "User-Agent":                random.choice(_LINKEDIN_UA_POOL),
        "Accept":                    "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language":           "en-US,en;q=0.9",
        "Accept-Encoding":           "gzip, deflate, br",
        "Referer":                   "https://www.linkedin.com/jobs/",
        "Sec-Fetch-Dest":            "document",
        "Sec-Fetch-Mode":            "navigate",
        "Sec-Fetch-Site":            "same-origin",
        "Upgrade-Insecure-Requests": "1",
        "Connection":                "keep-alive",
    }


def _extract_jd_from_soup(soup: BeautifulSoup, url: str) -> Optional[str]:
    """
    Try to extract JD text from a parsed LinkedIn page.

    Strategy 1: JSON-LD <script type="application/ld+json"> description field.
    Strategy 2: Known CSS class selectors.

    Returns extracted text if ≥ _LI_MIN_CHARS and not a login wall, else None.
    """
    # JSON-LD (most reliable — present even in static HTML skeleton)
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
            desc_html = ""
            if isinstance(data, dict):
                desc_html = data.get("description", "")
            elif isinstance(data, list):
                for item in data:
                    if isinstance(item, dict) and item.get("description"):
                        desc_html = item["description"]
                        break
            if desc_html:
                desc = html_visible_text(desc_html, " ", strip=True)
                desc = _clean_linkedin_text(desc)
                if len(desc) >= _LI_MIN_CHARS and not _is_loginwall(desc):
                    logger.info("[linkedin_scraper] ✓ JSON-LD: %d chars from %s", len(desc), url)
                    return desc
        except (json.JSONDecodeError, TypeError, AttributeError):
            continue

    # CSS selectors
    for cls in (
        "jobs-description-content__text",
        "jobs-description__content",
        "jobs-description",
        "description__text",
    ):
        node = soup.find(class_=cls)
        if not node:
            continue
        text = _clean_linkedin_text(visible_text(node, " ", strip=True))
        if len(text) >= _LI_MIN_CHARS and not _is_loginwall(text):
            logger.info("[linkedin_scraper] ✓ CSS .%s: %d chars from %s", cls, len(text), url)
            return text

    return None


# ── LinkedIn public scraper ───────────────────────────────────────────────────

def _linkedin_fetch_soup(url: str) -> BeautifulSoup:
    """
    Fetch a LinkedIn /jobs/view/ page with unauthenticated requests and return
    the parsed HTML. Shared by _linkedin_scrape() and scrape_linkedin_job() so
    the network/redirect/challenge handling lives in exactly one place.

    Raises
    ------
    LinkedInRedirectError   Redirected to a challenge/checkpoint URL.
    LinkedInChallengeError  2xx but body contains bot-check signals.
    ValueError              Request failed outright (network error).
    """
    _linkedin_rate_wait()

    try:
        resp = requests.get(url, headers=_linkedin_headers(), timeout=20, allow_redirects=True)
    except requests.TooManyRedirects as exc:
        raise LinkedInRedirectError(
            f"LinkedIn ERR_TOO_MANY_REDIRECTS for {url}"
        ) from exc
    except requests.RequestException as exc:
        raise ValueError(f"LinkedIn request failed for {url}: {exc}") from exc

    # Check final URL after redirect chain
    final_lower = resp.url.lower()
    if any(sig in final_lower for sig in _LINKEDIN_CHALLENGE_SIGNALS):
        logger.warning("[linkedin_scraper] Challenge redirect for %s → %s", url, resp.url)
        raise LinkedInRedirectError(f"LinkedIn redirected to challenge page: {resp.url}")

    if resp.status_code >= 300:
        logger.warning("[linkedin_scraper] HTTP %d for %s", resp.status_code, url)
        raise LinkedInChallengeError(
            f"LinkedIn returned HTTP {resp.status_code} for {url}",
            raw_html=resp.text,
        )

    raw_html = resp.text

    # In-body challenge detection
    body_lower = raw_html.lower()
    challenge_hits = sum(1 for sig in _LINKEDIN_CHALLENGE_SIGNALS if sig in body_lower)
    if challenge_hits >= 2:
        logger.warning("[linkedin_scraper] %d challenge signals in body for %s", challenge_hits, url)
        raise LinkedInChallengeError(
            f"LinkedIn challenge page for {url} ({challenge_hits} signals).",
            raw_html=raw_html,
        )

    return BeautifulSoup(raw_html, "html.parser")


def _linkedin_scrape(url: str) -> str:
    """
    Fetch a LinkedIn /jobs/view/ page with unauthenticated requests.

    No cookie, no session, no browser.  Public job-view pages embed a
    JSON-LD block in their static HTML that contains the full JD text.

    Raises
    ------
    LinkedInRedirectError   Redirected to a challenge/checkpoint URL.
    LinkedInChallengeError  2xx but body contains bot-check signals.
    LinkedInAuthWallError   Page is a login wall.
    ValueError              No extractable content or request failure.
    """
    soup = _linkedin_fetch_soup(url)
    text = _extract_jd_from_soup(soup, url)
    if text:
        return text

    if _is_loginwall(soup.get_text(" ", strip=True)):
        raise LinkedInAuthWallError(
            f"LinkedIn login wall on {url}. Page requires authentication."
        )

    raise ValueError(
        f"LinkedIn scraper: no extractable JD on {url}. "
        "Posting may be expired or removed."
    )


def _extract_linkedin_meta(soup: BeautifulSoup) -> tuple[str, str]:
    """
    Best-effort (title, company) from a LinkedIn JobPosting JSON-LD block —
    the same <script type="application/ld+json"> element _extract_jd_from_soup()
    already reads for the description field.  Returns ("", "") if absent.
    """
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        candidates = data if isinstance(data, list) else [data]
        for item in candidates:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "").strip()
            org = item.get("hiringOrganization")
            company = ""
            if isinstance(org, dict):
                company = str(org.get("name") or "").strip()
            if title or company:
                return title, company
    return "", ""


_LINKEDIN_JOB_ID_RE = re.compile(r"/jobs/view/(?:[\w-]*-)?(\d+)(?:[/?]|$)")


def _extract_linkedin_job_id(url: str) -> str:
    """
    Pull the numeric job ID out of a LinkedIn job URL.

    Handles both URL shapes LinkedIn uses:
      - /jobs/view/4231563678/                              (bare ID)
      - /jobs/view/software-engineer-at-acme-4231563678/    (slug + trailing ID)
    The ID is always the final run of digits in the path segment.
    """
    match = _LINKEDIN_JOB_ID_RE.search(url)
    if not match:
        raise ValueError(f"Could not extract a LinkedIn job ID from {url}")
    return match.group(1)


def _rapidapi_headers() -> dict[str, str]:
    if not RAPIDAPI_KEY:
        raise LinkedInRapidApiAuthError(
            "RAPIDAPI_KEY is not configured on this server — set it in backend/.env."
        )
    return {
        "X-RapidAPI-Key":  RAPIDAPI_KEY,
        "X-RapidAPI-Host": RAPIDAPI_LINKEDIN_HOST,
    }


def _first_str(payload: dict, *keys: str) -> str:
    """Return the first non-empty string value found across the given keys."""
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def scrape_linkedin_job(url: str):
    """
    Fetch a LinkedIn job posting via a RapidAPI LinkedIn-jobs provider instead
    of a direct request to LinkedIn — LinkedIn's own bot-detection (HTTP 999,
    challenge pages, login walls) blocks the unauthenticated direct-fetch path
    reliably (see _linkedin_scrape / _linkedin_fetch_soup above, retained for
    other callers). RapidAPI providers proxy the request through
    infrastructure LinkedIn doesn't block the same way.

    Default provider is "LinkedIn Job Search API" by Fantastic Jobs, which is
    a filtered-search endpoint (GET /active-jb) rather than a get-by-id
    lookup — we filter it down to one job via the linkedin_id param and take
    the first (only) match. It returns a bare JSON array; an empty array
    means the job wasn't found within the time_frame window (e.g. an old or
    expired posting), which is surfaced as a ValueError, not a RapidAPI error.

    Raises
    ------
    LinkedInRapidApiAuthError   RAPIDAPI_KEY missing, or the provider returned
                                401/403 (invalid/revoked key, or not
                                subscribed to this API). Server
                                misconfiguration — do NOT surface as HTTP 401,
                                the frontend treats 401 as "your session
                                expired" and force-logs the user out.
    LinkedInRapidApiQuotaError  Provider returned 429 — the plan's request
                                quota (e.g. monthly free tier) is exhausted.
    ValueError                  Job ID couldn't be parsed from the URL, the
                                request failed outright, no job matched that
                                ID within the time_frame window, or the
                                response contained no usable job description
                                text.
    """
    from backend.url_scraper import ScrapedJob  # local import avoids a cycle at module load

    job_id  = _extract_linkedin_job_id(url)
    headers = _rapidapi_headers()

    try:
        resp = requests.get(
            f"https://{RAPIDAPI_LINKEDIN_HOST}{RAPIDAPI_LINKEDIN_PATH}",
            headers=headers,
            params={
                "linkedin_id":        job_id,
                "time_frame":         RAPIDAPI_LINKEDIN_TIME_FRAME,
                "description_format": "text",
                "limit":              1,
            },
            timeout=20,
        )
    except requests.RequestException as exc:
        raise ValueError(f"RapidAPI LinkedIn request failed for {url}: {exc}") from exc

    if resp.status_code in (401, 403):
        logger.error("[linkedin_rapidapi] HTTP %d for %s — key missing/invalid", resp.status_code, url)
        raise LinkedInRapidApiAuthError(
            f"RapidAPI rejected the request ({resp.status_code}) — RAPIDAPI_KEY is missing, "
            "invalid, or not subscribed to this API."
        )

    if resp.status_code == 429:
        logger.warning("[linkedin_rapidapi] HTTP 429 for %s — quota exceeded", url)
        raise LinkedInRapidApiQuotaError(
            "Monthly free quota exceeded for the LinkedIn jobs API. Please try again later or "
            "upgrade the RapidAPI plan."
        )

    if resp.status_code >= 400:
        raise ValueError(
            f"RapidAPI returned HTTP {resp.status_code} for {url}: {resp.text[:300]}"
        )

    try:
        data = resp.json()
    except ValueError as exc:
        raise ValueError(f"RapidAPI returned a non-JSON response for {url}") from exc

    # This provider returns a bare JSON array of matches (filtered-search
    # endpoint, not a get-by-id lookup) — unwrap defensively in case a
    # differently-configured provider wraps it in a dict instead.
    payload = data
    if isinstance(data, dict):
        for key in ("data", "result", "job", "results"):
            nested = data.get(key)
            if isinstance(nested, list):
                payload = nested
                break
            if isinstance(nested, dict):
                payload = nested
                break

    if isinstance(payload, list):
        if not payload:
            raise ValueError(
                f"RapidAPI found no LinkedIn job matching ID {job_id} for {url} "
                f"(outside the {RAPIDAPI_LINKEDIN_TIME_FRAME} lookup window, or expired/removed)."
            )
        payload = payload[0]

    if not isinstance(payload, dict):
        raise ValueError(f"RapidAPI response for {url} was not a job object: {type(payload).__name__}")

    title       = _first_str(payload, "title", "job_title", "jobTitle")
    company     = _first_str(payload, "organization", "company", "company_name", "companyName", "hiring_company")
    if not company:
        org = payload.get("companyDetails") or payload.get("company_details") or {}
        if isinstance(org, dict):
            company = _first_str(org, "name", "companyName")
    description = _first_str(
        payload,
        "description_text", "description", "job_description", "jobDescription", "descriptionText",
    )

    if not description:
        raise ValueError(f"RapidAPI response for {url} contained no job description text.")

    return ScrapedJob(title=title or "LinkedIn Job Posting", company=company, raw_text=description)


# ── Generic scraper ───────────────────────────────────────────────────────────

def _generic_scrape(url: str) -> str:
    from backend.url_scraper import scrape_job_post
    return scrape_job_post(url).raw_text


def _lazy(source: str, url: str) -> str:
    """Lazily import and call the site-specific JD scraper."""
    if source == "gotfriends":
        from backend.scrapers.gotfriends_scraper import scrape_gotfriends_jd
        return scrape_gotfriends_jd(url)
    if source == "dialog":
        from backend.scrapers.dialog_scraper import scrape_dialog_jd
        return scrape_dialog_jd(url)
    if source == "nisha":
        from backend.scrapers.nisha_scraper import scrape_nisha_jd
        return scrape_nisha_jd(url)
    if source == "drushim":
        from backend.scrapers.drushim_scraper import scrape_drushim_jd
        return scrape_drushim_jd(url)
    if source == "alljobs":
        from backend.scrapers.alljobs_scraper import scrape_alljobs_jd
        return scrape_alljobs_jd(url)
    raise ValueError(f"Unknown source key: {source!r}")


# ── Domain → handler routing table ───────────────────────────────────────────

_JD_HANDLERS: list[tuple[str, Callable[[str], str]]] = [
    ("linkedin.com",     _linkedin_scrape),
    ("gotfriends.co.il", lambda url: _lazy("gotfriends", url)),
    ("dialog.co.il",     lambda url: _lazy("dialog", url)),
    ("nisha.co.il",      lambda url: _lazy("nisha", url)),
    ("drushim.co.il",    lambda url: _lazy("drushim", url)),
    ("alljobs.co.il",    lambda url: _lazy("alljobs", url)),
]


# ── JD content gatekeeper ─────────────────────────────────────────────────────

_GATE_MIN_CHARS = 300

_GATE_ROLE_KEYWORDS: tuple[str, ...] = (
    "responsibilities", "requirements", "qualifications",
    "you will", "what you'll do", "what you will do",
    "about the role", "about the job", "about this role",
    "the role", "position overview", "job description",
    "key responsibilities", "role overview",
)
_GATE_COMPANY_KEYWORDS: tuple[str, ...] = (
    "description", "we are", "we're", "our team",
    "join us", "about us", "who we are",
)


def is_valid_job_content(text: str) -> bool:
    """
    Return True when text looks like genuine job-description content.

    Requires minimum length AND at least one structural keyword (role or company).
    Login walls, 404s, and sidebar-only scrapes all fail this check.
    """
    if len(text) < _GATE_MIN_CHARS:
        return False
    lower = text.lower()
    return any(kw in lower for kw in _GATE_ROLE_KEYWORDS) or \
           any(kw in lower for kw in _GATE_COMPANY_KEYWORDS)


# ── Public API ────────────────────────────────────────────────────────────────

def scrape_jd_text(url: str) -> str:
    """
    Fetch and return the full JD text for a job posting URL (synchronous).

    Routes to a site-specific handler for known domains; falls back to the
    generic scraper for everything else.  The is_valid_job_content gatekeeper
    is applied to every result before returning.

    Raises ValueError when the page is unreachable or contains no usable content.
    """
    host = (urlparse(url).hostname or "").lower().removeprefix("www.")

    for domain, handler in _JD_HANDLERS:
        if host == domain or host.endswith("." + domain):
            logger.debug("[url_router] %s → %s handler", url, domain)
            text = handler(url)
            if not is_valid_job_content(text):
                raise ValueError(
                    f"[url_router] Gatekeeper FAILED for {url} — {len(text)} chars, "
                    "no structural JD keywords. Likely login wall or expired posting."
                )
            return text

    logger.debug("[url_router] No specific handler for %s — using generic scraper", host)
    text = _generic_scrape(url)
    if not is_valid_job_content(text):
        raise ValueError(
            f"[url_router] Gatekeeper FAILED for {url} — {len(text)} chars, "
            "no structural JD keywords. Likely login wall or expired posting."
        )
    return text


async def scrape_jd_text_async(url: str) -> str:
    """
    Async entry point for JD fetching.

    Routing
    -------
    linkedin.com  → _linkedin_scrape (unauthenticated requests, JSON-LD)
    all others    → asyncio.to_thread(scrape_jd_text)

    LinkedInChallengeError is caught here: the raw HTML is stripped to plain
    text and returned if it passes the gatekeeper — allowing partial salvage
    from challenge pages that still embed job data.  Otherwise re-raised as
    LinkedInRedirectError so the caller can record the block event.

    Raises
    ------
    LinkedInAuthWallError   Login wall — caller routes to status='auth_wall'.
    LinkedInRedirectError   Challenge/redirect — caller records block event.
    ValueError              No usable content or gatekeeper failure.
    """
    host = (urlparse(url).hostname or "").lower().removeprefix("www.")
    is_linkedin = host == "linkedin.com" or host.endswith(".linkedin.com")

    if is_linkedin:
        logger.debug("[url_router_async] LinkedIn → unauthenticated requests")
        try:
            text = await asyncio.to_thread(_linkedin_scrape, url)
        except LinkedInChallengeError as challenge_exc:
            raw_html = challenge_exc.raw_html
            logger.warning(
                "[url_router_async] LinkedIn Challenge for %s — "
                "attempting plain-text salvage (%d chars raw HTML)",
                url, len(raw_html),
            )
            if len(raw_html) >= _LI_MIN_CHARS:
                plain = _clean_linkedin_text(
                    html_visible_text(raw_html, " ", strip=True)
                )
                if len(plain) >= _LI_MIN_CHARS and not _is_loginwall(plain):
                    logger.info(
                        "[url_router_async] Challenge HTML salvaged: %d chars for %s",
                        len(plain), url,
                    )
                    text = plain
                else:
                    raise LinkedInRedirectError(
                        f"LinkedIn Challenge for {url} — salvage failed (login wall or too short)."
                    ) from challenge_exc
            else:
                raise LinkedInRedirectError(
                    f"LinkedIn Challenge for {url} — raw HTML too short ({len(raw_html)} chars)."
                ) from challenge_exc

        if not is_valid_job_content(text):
            raise ValueError(
                f"[url_router_async] Gatekeeper FAILED for {url} — {len(text)} chars, "
                "no structural JD keywords. Likely login wall or expired posting."
            )
        return text

    logger.debug("[url_router_async] Non-LinkedIn → sync scraper (thread): %s", host)
    return await asyncio.to_thread(scrape_jd_text, url)


def get_scraper_for_url(url: str) -> Optional[BaseScraper]:
    """
    Return a configured BaseScraper instance for the given source URL,
    or None if no specific scraper is registered for that host.
    """
    host = (urlparse(url).hostname or "").lower().removeprefix("www.")

    if "gotfriends.co.il" in host:
        from backend.scrapers.gotfriends_scraper import GotfriendsScraper
        return GotfriendsScraper(company_url=url)
    if "dialog.co.il" in host:
        from backend.scrapers.dialog_scraper import DialogScraper
        return DialogScraper(company_url=url)
    if "nisha.co.il" in host:
        from backend.scrapers.nisha_scraper import NishaScraper
        return NishaScraper(company_url=url)
    if "drushim.co.il" in host:
        from backend.scrapers.drushim_scraper import DrushimScraper
        return DrushimScraper(company_url=url)
    if "alljobs.co.il" in host:
        from backend.scrapers.alljobs_scraper import AllJobsScraper
        return AllJobsScraper(company_url=url)
    if "comeet.co" in host or "comeet.com" in host:
        from backend.scrapers.comeet_adapter import ComeetAdapter
        return ComeetAdapter(company_name="Comeet", company_url=url)

    logger.debug("[url_router] No registered scraper for host '%s'", host)
    return None
