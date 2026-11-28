"""
Company-level Workday adapter.

ats_api_scraper.try_workday_api reads ONE posting. This adapter reads a
company's Israeli postings from Workday's public JSON API:

    list    POST https://{tenant}.wd{N}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs
            {"appliedFacets": {...}, "limit": 20, "offset": n, "searchText": ""}
            → {total, facets, jobPostings: [{title, externalPath, locationsText, postedOn}]}
    detail  GET  https://{host}/wday/cxs/{tenant}/{site}{externalPath}
            → {jobPostingInfo: {title, jobDescription, location, additionalLocations, country, externalUrl, startDate}}

Workday caps `total` at 2000, so a large employer cannot be paged through
whole. The list is filtered server-side with the location facet for Israel
instead, up to MAX_POSTINGS per company per run, because every posting costs
one detail call (the JD text is only on the detail endpoint).

Israel only, no remote jobs abroad (Ron's call, 2026-11-28, as for Comeet;
Greenhouse/Lever keep remote too). ats_board_adapters.in_israel is applied
again on the detail's own locations, since a facet can be mislabelled.

company_url: the career site root, e.g.
    https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite
    https://intel.wd1.myworkdayjobs.com/en-US/External
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse

import httpx

from backend.schemas.job import JobMatch
from backend.scrapers.ats_api_scraper import _WORKDAY_HOST_RE, _WORKDAY_LOCALE_RE
from backend.scrapers.ats_board_adapters import _age_label, in_israel
from backend.scrapers.base_scraper import BaseScraper, make_job_id, minimal_job_match
from backend.scrapers.parsing_engine import ParsingEngine

logger = logging.getLogger(__name__)

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
_TIMEOUT = 20
_PAGE = 20                  # Workday's largest page size
_DETAIL_CONCURRENCY = 3     # Workday sits behind Cloudflare, which answers bursts with 429
MAX_POSTINGS = 50           # per company per run: one detail call each, and run_all saves
                            # at most MAX_RELEVANT_JOBS (50) per sync across all companies
_RETRIES = 3                # on 429/503, waiting Retry-After or 2, 4, 8 s. Never more than that:
                            # a site that keeps refusing gets a warning, not a workaround.


async def _send(client: httpx.AsyncClient, method: str, url: str, **kw) -> httpx.Response:
    """One request, retried politely while Workday answers 429/503."""
    for attempt in range(_RETRIES + 1):
        resp = await client.request(method, url, **kw)
        if resp.status_code not in (429, 503) or attempt == _RETRIES:
            return resp
        try:
            wait = float(resp.headers.get("Retry-After", ""))
        except ValueError:
            wait = 2.0 ** (attempt + 1)
        await asyncio.sleep(min(wait, 30.0))
    return resp


def parse_site(company_url: str) -> Optional[tuple[str, str, str]]:
    """(host, tenant, site) from a Workday career-site URL, or None."""
    parsed = urlparse(company_url.strip())
    host = (parsed.hostname or "").lower()
    m = _WORKDAY_HOST_RE.match(host)
    if not m:
        return None
    parts = [p for p in parsed.path.split("/") if p]
    if parts and _WORKDAY_LOCALE_RE.match(parts[0]):
        parts = parts[1:]
    if not parts:
        return None
    return host, m.group(1), parts[0]


def _facet_values(facets: list) -> dict[str, list[dict]]:
    """facetParameter → its leaf values, flattening Workday's nested groups."""
    groups: dict[str, list[dict]] = {}
    stack = [(f.get("facetParameter", ""), f) for f in facets or [] if isinstance(f, dict)]
    while stack:
        param, node = stack.pop()
        for v in node.get("values") or []:
            if not isinstance(v, dict):
                continue
            if "values" in v:
                stack.append((v.get("facetParameter") or param, v))
            elif v.get("id") and v.get("descriptor"):
                groups.setdefault(param, []).append(v)
    return groups


def _location_filter(groups: dict[str, list[dict]], word: str) -> Optional[dict[str, list[str]]]:
    """
    appliedFacets selecting every value that names `word`, all in ONE facet
    group. A group with a value that is exactly `word` ("Israel", "Remote")
    wins; otherwise the group with the most matching postings.
    """
    best: Optional[tuple[bool, int, str, list[str]]] = None
    for param, values in groups.items():
        hits = [v for v in values if word in v["descriptor"].casefold()]
        if not hits:
            continue
        exact = any(v["descriptor"].casefold() == word for v in hits)
        score = (exact, sum(int(v.get("count") or 0) for v in hits), param, [v["id"] for v in hits])
        if best is None or score[:2] > best[:2]:
            best = score
    return {best[2]: best[3]} if best else None


class WorkdayBoardAdapter(BaseScraper):

    def __init__(self, company_name: str, company_url: str, user_id: str = "default") -> None:
        super().__init__(company_name, company_url)
        self._user_id = user_id
        self._site = parse_site(company_url)

    async def fetch_jobs(self) -> list[JobMatch]:
        """Fetch this company's Israeli postings. Never raises."""
        if not self._site:
            logger.warning("[WorkdayBoardAdapter] %s — not a Workday site URL: %r", self.company_name, self.company_url)
            return []
        host, tenant, site = self._site
        base = f"https://{host}/wday/cxs/{tenant}/{site}"
        headers = {"User-Agent": _USER_AGENT, "Accept": "application/json"}

        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True, headers=headers) as client:
                first = await self._page(client, base, {}, 0)
                groups = _facet_values(first.get("facets") or [])
                paths: list[str] = []
                applied = _location_filter(groups, "israel")
                if applied:
                    await self._collect(client, base, applied, paths)
                else:
                    logger.info("[WorkdayBoardAdapter] %s — no Israel location facet", self.company_name)
                infos = await self._details(client, base, paths)
        except Exception as exc:
            logger.warning("[WorkdayBoardAdapter] %s — list fetch failed (%s): %s", self.company_name, base, exc)
            return []

        got = [info for info in infos if info]
        jobs = [self._parse(info) for info in got]
        valid = [j for j in jobs if j is not None]
        level = logging.WARNING if len(got) < len(paths) else logging.INFO
        logger.log(
            level,
            "[WorkdayBoardAdapter] %s — %d listed in Israel, %d details fetched (%d refused), %d valid",
            self.company_name, len(paths), len(got), len(paths) - len(got), len(valid),
        )
        return valid

    async def _page(self, client: httpx.AsyncClient, base: str, applied: dict, offset: int) -> dict:
        resp = await _send(
            client, "POST", f"{base}/jobs",
            json={"appliedFacets": applied, "limit": _PAGE, "offset": offset, "searchText": ""},
        )
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, dict) or not isinstance(data.get("jobPostings"), list):
            raise ValueError(f"unexpected Workday response: {type(data).__name__}")
        return data

    async def _collect(self, client: httpx.AsyncClient, base: str, applied: dict, paths: list[str]) -> None:
        """Append this query's postings to `paths`, skipping repeats, up to MAX_POSTINGS."""
        offset, total = 0, None
        while len(paths) < MAX_POSTINGS and (total is None or offset < total):
            data = await self._page(client, base, applied, offset)
            total = int(data.get("total") or 0)
            postings = data["jobPostings"]
            if not postings:
                break
            for p in postings:
                path = p.get("externalPath") if isinstance(p, dict) else None
                if path and path not in paths and len(paths) < MAX_POSTINGS:
                    paths.append(path)
            offset += _PAGE

    async def _details(self, client: httpx.AsyncClient, base: str, paths: list[str]) -> list[Optional[dict]]:
        sem = asyncio.Semaphore(_DETAIL_CONCURRENCY)

        async def one(path: str) -> Optional[dict]:
            async with sem:
                try:
                    resp = await _send(client, "GET", f"{base}{path}")
                    if resp.status_code == 200:
                        info = resp.json().get("jobPostingInfo")
                        return info if isinstance(info, dict) else None
                except Exception as exc:
                    logger.debug("[WorkdayBoardAdapter] detail failed for %s: %s", path, exc)
                return None

        return list(await asyncio.gather(*(one(p) for p in paths)))

    def _parse(self, info: dict) -> Optional[JobMatch]:
        title     = (info.get("title") or "").strip()
        apply_url = (info.get("externalUrl") or "").strip()
        if not title or not apply_url:
            return None

        location = (info.get("location") or "").strip()
        locations = [str(loc) for loc in (location, *(info.get("additionalLocations") or []),
                                          (info.get("country") or {}).get("descriptor") or "") if loc]
        israeli = next((loc for loc in locations if in_israel(loc)), None)
        if israeli is None:
            return None
        # A posting kept for its Israeli office shows that office, not "US, CA, Santa Clara".
        location = israeli

        body = ParsingEngine.html_to_text(info.get("jobDescription") or "")
        jd_text = "\n\n".join(p for p in (f"Position: {title}", body) if p)

        posted = None
        if info.get("startDate"):
            try:
                posted = datetime.fromisoformat(str(info["startDate"])).replace(tzinfo=timezone.utc)
            except ValueError:
                posted = None

        return minimal_job_match(
            job_id      = make_job_id(apply_url, prefix="workday"),
            title       = title,
            company     = self.company_name,
            location    = location or "Unknown",
            apply_url   = apply_url,
            jd_text     = jd_text,
            posted_at   = _age_label(posted),
            source_type = self.source_type,
            user_id     = self._user_id,
        )
