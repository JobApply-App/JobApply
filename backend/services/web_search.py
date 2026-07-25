"""
Web Search Service — ScraperAPI-backed, with a DuckDuckGo scrape as last resort.

PRIMARY: ScraperAPI's structured Google Search endpoint
(https://api.scraperapi.com/structured/google/search), authenticated via
SCRAPER_API_KEY (backend/.env). Returns parsed JSON organic_results directly —
no HTML scraping, no bot-detection cat-and-mouse. Costs real ScraperAPI credits
per call (observed: 25 credits/request as of 2026-07 — check your plan before
running a large research batch).

FALLBACK: raw DuckDuckGo HTML scraping (no API key, free). Used only when
SCRAPER_API_KEY is missing/invalid/exhausted, or USE_SCRAPER_API=false. Kept
as a last resort, not a real backend — DuckDuckGo has been observed serving an
anti-bot CAPTCHA challenge (HTTP 202, "Select all squares containing a duck")
that silently looks like zero results, so treat any zero-result run through
this path as "possibly blocked", not "confirmed no hits".

Every successful result is cached indefinitely to backend/web_search_cache.json
(gitignored, same convention as personal_overrides.json / supplemental_
answers.json), keyed by normalised query text. A repeat query — e.g.
re-running entity research after a profile edit — is served from disk and
spends 0 ScraperAPI credits. Pass force=True to bypass the cache for one call.

Public API
----------
search(query, max_results=5, force=False) -> list[SearchResult]   (async)

Never raises — every failure path (missing key, quota exceeded, network
error, bad HTML) returns an empty list and logs loudly. Callers (e.g.
ResearcherAgent) are built to degrade to "Unknown domain" / unverified on an
empty result set rather than abort the whole research run, so silence here
would silently degrade CV quality with no trace in the logs.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import urllib.parse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx
from bs4 import BeautifulSoup
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# When the app runs normally (uvicorn backend.main:app), main.py has already
# loaded backend/.env into the process by the time this module is imported,
# so this is a no-op. When this module is imported standalone (a script, a
# one-off research run, a test), nothing has primed os.environ yet — without
# this call SCRAPER_API_KEY silently reads as "" and every search silently
# falls back to the blocked DuckDuckGo path.
#
# override=False deliberately: don't let a stale backend/.env value clobber
# a real env var the process was actually started with (e.g. injected
# directly in a deployed environment rather than via a .env file).
#
# NOTE: several other backend/services/*.py modules load env via
# `Path(__file__).resolve().parents[2] / ".env"` — two levels up from
# backend/services/ is the PROJECT ROOT .env, not backend/.env (CLAUDE.md:
# "Env vars come from backend/.env (not root .env)"). Root .env only holds
# ANTHROPIC_API_KEY/TAVILY_API_KEY today so it happens not to clobber
# anything, but it's the wrong path for any of those modules if backend/.env
# ever diverges from root .env. Not fixed here — out of scope for this
# change and touches several unrelated files.
load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)

# ── ScraperAPI (primary) ──────────────────────────────────────────────────────
_SCRAPERAPI_SEARCH_URL = "https://api.scraperapi.com/structured/google/search"
_SCRAPER_API_KEY       = os.environ.get("SCRAPER_API_KEY", "")
_USE_SCRAPER_API        = os.environ.get("USE_SCRAPER_API", "true").strip().lower() not in (
    "false", "0", "",
)
_SCRAPERAPI_TIMEOUT_S  = 30.0

# ── DuckDuckGo (fallback) ─────────────────────────────────────────────────────
_DDG_URL         = "https://html.duckduckgo.com/html/"
_MIN_INTERVAL_S  = 1.5          # polite rate-limit between requests
_REQUEST_TIMEOUT = 10.0         # seconds
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Content-Type":    "application/x-www-form-urlencoded",
}

_last_ddg_request_at: float = 0.0

# Logged once per process so a misconfigured deployment is loud on startup
# without spamming a warning on every single search() call.
_warned_missing_key = False


@dataclass
class SearchResult:
    title:   str
    snippet: str
    url:     str


# ── Persistent result cache ───────────────────────────────────────────────────
# ScraperAPI charges real credits per query (see module docstring). The
# ResearcherAgent issues 1-2 deterministic queries per entity (temperature=0.0
# domain synthesis, so the Step B query is stable run-to-run) — without a
# cache, simply re-running research for the same entity set (e.g. to pick up
# one new job entry) re-spends the full credit cost of every entity, including
# ones that haven't changed. Cached indefinitely: a company's industry domain
# doesn't go stale on any timescale that matters here. Pass force=True to
# bypass the cache for one call (e.g. a user explicitly asks to re-verify an
# entity) — the fresh result still overwrites the cache entry afterward, so
# subsequent calls benefit again.
_CACHE_PATH        = Path(__file__).resolve().parents[1] / "web_search_cache.json"
_CACHE_MAX_RESULTS = 10   # per-query cap; enough to satisfy any caller's max_results


def _cache_key(query: str) -> str:
    """Normalise so trivial whitespace/case differences still hit the cache."""
    return " ".join(query.strip().lower().split())


def _load_cache() -> dict:
    if not _CACHE_PATH.exists():
        return {}
    try:
        data = json.loads(_CACHE_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("[web_search] cache read failed (%s) — treating as empty", exc)
        return {}


def _save_cache(cache: dict) -> None:
    try:
        _CACHE_PATH.write_text(
            json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError as exc:
        logger.warning("[web_search] cache write failed (non-fatal): %s", exc)


def _cache_get(query: str) -> Optional[list[SearchResult]]:
    entry = _load_cache().get(_cache_key(query))
    if not entry:
        return None
    return [SearchResult(**r) for r in entry.get("results", [])]


def _cache_set(query: str, results: list[SearchResult], backend: str) -> None:
    if not results:
        return  # never cache empty/blocked results — let the next call retry
    cache = _load_cache()
    cache[_cache_key(query)] = {
        "results":   [asdict(r) for r in results[:_CACHE_MAX_RESULTS]],
        "backend":   backend,
        "cached_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    _save_cache(cache)


async def search(
    query: str,
    max_results: int = 5,
    force: bool = False,
) -> list[SearchResult]:
    """
    Search the web and return up to max_results results.

    Checks the persistent cache first (see _CACHE_PATH) unless force=True.
    On a miss, tries ScraperAPI first (if USE_SCRAPER_API and SCRAPER_API_KEY
    are set), falling back to unauthenticated DuckDuckGo scraping if
    ScraperAPI is unconfigured or the request fails for any reason (auth,
    quota, network). A successful result is cached before returning.

    force=True skips the cache lookup and always hits the network, then
    overwrites the cache entry with the fresh result.

    Never raises — returns [] on total failure.
    """
    if not force:
        cached = _cache_get(query)
        if cached is not None:
            logger.info(
                "[web_search] cache hit for %r (%d result(s)) — 0 ScraperAPI credits spent",
                query, len(cached),
            )
            return cached[:max_results]

    if _USE_SCRAPER_API:
        if _SCRAPER_API_KEY:
            results = await _search_scraperapi(query, max_results)
            if results:
                _cache_set(query, results, backend="scraperapi")
                return results
            # _search_scraperapi already logged the specific failure reason
            # (auth/quota/network/empty). Fall through to the free backend
            # rather than give up outright.
        else:
            _warn_missing_key_once()

    results = await _search_duckduckgo(query, max_results)
    if results:
        _cache_set(query, results, backend="duckduckgo")
    return results


def _warn_missing_key_once() -> None:
    global _warned_missing_key
    if _warned_missing_key:
        return
    _warned_missing_key = True
    logger.error(
        "[web_search] USE_SCRAPER_API is enabled but SCRAPER_API_KEY is not set in "
        "backend/.env — every search will fall back to unauthenticated DuckDuckGo "
        "scraping, which is frequently blocked by an anti-bot challenge. Entity "
        "research and domain verification will silently degrade until a key is set."
    )


# ── ScraperAPI backend ────────────────────────────────────────────────────────

async def _search_scraperapi(query: str, max_results: int) -> list[SearchResult]:
    try:
        async with httpx.AsyncClient(timeout=_SCRAPERAPI_TIMEOUT_S) as client:
            resp = await client.get(
                _SCRAPERAPI_SEARCH_URL,
                params={"api_key": _SCRAPER_API_KEY, "query": query},
            )
    except Exception as exc:
        # ScraperAPI's structured-search endpoint proxies+renders a real Google
        # SERP server-side, so slow queries can exceed the timeout with an
        # httpx exception that stringifies to "" (e.g. ReadTimeout) — log the
        # exception type too, or this line is silent about the actual cause.
        logger.warning(
            "[web_search] ScraperAPI request failed for %r: %s: %s",
            query, type(exc).__name__, exc,
        )
        return []

    if resp.status_code in (401, 403):
        logger.error(
            "[web_search] ScraperAPI rejected the request (HTTP %d) for %r — "
            "SCRAPER_API_KEY is invalid/expired, or the account's plan doesn't "
            "cover this endpoint. Falling back to DuckDuckGo scraping. Body: %s",
            resp.status_code, query, resp.text[:200],
        )
        return []
    if resp.status_code == 429:
        logger.error(
            "[web_search] ScraperAPI quota exceeded (HTTP 429) for %r — this "
            "billing period's credits are exhausted. Falling back to DuckDuckGo "
            "scraping (unreliable — expect degraded results until quota resets "
            "or the plan is upgraded).",
            query,
        )
        return []
    if resp.status_code != 200:
        logger.warning(
            "[web_search] ScraperAPI returned HTTP %d for %r: %s",
            resp.status_code, query, resp.text[:200],
        )
        return []

    try:
        data = resp.json()
    except Exception as exc:
        logger.warning("[web_search] ScraperAPI returned unparseable JSON for %r: %s", query, exc)
        return []

    organic = data.get("organic_results") or []
    results: list[SearchResult] = []
    for item in organic:
        title = (item.get("title") or "").strip()
        if not title:
            continue
        results.append(SearchResult(
            title=title,
            snippet=(item.get("snippet") or "").strip(),
            url=(item.get("link") or "").strip(),
        ))
        if len(results) >= max_results:
            break

    if not results:
        logger.info("[web_search] ScraperAPI returned zero organic results for %r", query)
    return results


# ── DuckDuckGo backend (fallback, unauthenticated) ───────────────────────────

async def _search_duckduckgo(query: str, max_results: int) -> list[SearchResult]:
    """
    Search DuckDuckGo and return up to max_results results.

    Returns an empty list on any network or parse failure — never raises.
    Rate-limits itself to _MIN_INTERVAL_S between calls.
    """
    global _last_ddg_request_at

    elapsed = time.monotonic() - _last_ddg_request_at
    if elapsed < _MIN_INTERVAL_S:
        await asyncio.sleep(_MIN_INTERVAL_S - elapsed)
    _last_ddg_request_at = time.monotonic()

    try:
        async with httpx.AsyncClient(
            timeout=_REQUEST_TIMEOUT,
            follow_redirects=True,
            headers=_HEADERS,
        ) as client:
            resp = await client.post(
                _DDG_URL,
                data={"q": query, "kl": "us-en", "ia": "web"},
            )
            resp.raise_for_status()
    except Exception as exc:
        logger.warning("[web_search] DDG request failed for %r: %s", query, exc)
        return []

    # Anti-bot interstitial. DDG serves this with HTTP 202 (a SUCCESS status),
    # so raise_for_status() waves it through and the parse below simply finds
    # no .result nodes — the caller then sees an ordinary empty result set and
    # silently degrades (ResearcherAgent records "Unknown domain"/unverified).
    # Detect it explicitly so a blocked scraper is loud instead of looking like
    # "no search hits". There is no bypass here by design: solving the
    # challenge is not something this client should attempt.
    if _is_bot_challenge(resp):
        logger.error(
            "[web_search] DuckDuckGo returned an anti-bot challenge (HTTP %s) for %r — "
            "search is BLOCKED, not empty. Configure SCRAPER_API_KEY to avoid this "
            "fallback path entirely.",
            resp.status_code, query,
        )
        return []

    return _parse_results(resp.text, max_results)


def _is_bot_challenge(resp: httpx.Response) -> bool:
    """True when DDG served a CAPTCHA/anti-bot interstitial instead of results."""
    if resp.status_code == 202:
        return True
    head = resp.text[:4000].lower()
    return "bots use duckduckgo too" in head or "confirm this search was made by a human" in head


def _parse_results(html: str, max_results: int) -> list[SearchResult]:
    soup    = BeautifulSoup(html, "html.parser")
    results: list[SearchResult] = []

    for div in soup.select(".result")[:max_results * 2]:  # oversample, filter below
        title_a    = div.select_one(".result__title a")
        snippet_el = div.select_one(".result__snippet")

        if not title_a:
            continue

        title   = title_a.get_text(strip=True)
        snippet = snippet_el.get_text(strip=True) if snippet_el else ""
        raw_href = title_a.get("href", "")
        url     = _extract_url(raw_href)

        if not title and not snippet:
            continue

        results.append(SearchResult(title=title, snippet=snippet, url=url))
        if len(results) >= max_results:
            break

    return results


def _extract_url(href: str) -> str:
    """
    DDG redirects have the form //duckduckgo.com/l/?uddg=<encoded-url>&...
    Extract the real destination URL from the uddg param, or return href as-is.
    """
    if not href:
        return ""
    if href.startswith("//"):
        href = "https:" + href
    try:
        parsed = urllib.parse.urlparse(href)
        qs     = urllib.parse.parse_qs(parsed.query)
        if "uddg" in qs:
            return urllib.parse.unquote(qs["uddg"][0])
    except Exception:
        pass
    return href
