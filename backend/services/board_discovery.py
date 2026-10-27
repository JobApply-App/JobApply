"""
Board discovery — the Israeli job boards, searched for every user's own roles.

Why this exists
----------------
Drushim, AllJobs, Gotfriends, Dialog and Nisha searched only
config.TARGET_SEARCH_QUERIES (the founder's Product/CS/Ops roles), and only
when a user pressed "sync" — nothing ran them in the background. An insurance
agent or a nurse who picked their role in onboarding got close to nothing
from them, because the board was never asked for that profession and the
global title gate discarded the rest before the detail page was fetched.

What one cycle does
--------------------
1. Reads every pipeline user's cached title terms in one narrow query
   (user_title_terms.cached_terms_for_users). A user with nothing cached is
   represented by the global list, as everywhere else.
2. Merges them (board_search_terms.union_terms), caps and rotates them
   (select_for_cycle, Hebrew first) and runs each board ONCE with that list.
3. Fetches a detail page only for cards whose title matches at least one
   user, then saves each job only for the users whose own matcher
   (relevancy.build_title_matcher) accepts it — the insurance-agent job goes
   to the insurance agent, not to the product manager.

How cost is bounded
--------------------
* Search requests: BOARD_TERMS_PER_CYCLE terms × 5 boards × at most
  _MAX_PAGES pages; detail pages stay capped per board by each scraper's own
  max_jobs. The bound is logged every cycle as `request_bound`.
* Switch: BOARD_DISCOVERY_ENABLED, off by default — every board answers
  Render's IP with 403 (first production cycle, 2026-10-27).
* Frequency: BOARD_DISCOVERY_INTERVAL_SECONDS, gated on a last-run time in
  kv_store so Render's restart-on-wake does not add cycles.
* LLM: none. Terms come from the cache refresh_user_terms already fills;
  scoring of saved jobs stays under the existing per-user daily budget.
* Database egress: one narrow terms query plus two tiny kv rows per cycle;
  saving is an upsert and a `SELECT 1` per job and user. At most
  BOARD_MAX_NEW_JOBS_PER_USER new jobs per user per cycle, which bounds how
  fast the enrichment sweep's per-user feed reads grow.

This gate decides which jobs enter a feed. It does not change any score.
"""
from __future__ import annotations

import asyncio
import logging
import time
from itertools import zip_longest
from typing import Callable, Optional

from backend.schemas.job import JobMatch

logger = logging.getLogger(__name__)

_LAST_RUN_KEY = "board_discovery:last_run"


def _board_scraper_classes() -> list:
    from backend.scrapers.alljobs_scraper    import AllJobsScraper
    from backend.scrapers.dialog_scraper     import DialogScraper
    from backend.scrapers.drushim_scraper    import DrushimScraper
    from backend.scrapers.gotfriends_scraper import GotfriendsScraper
    from backend.scrapers.nisha_scraper      import NishaScraper
    return [DrushimScraper, AllJobsScraper, GotfriendsScraper, DialogScraper, NishaScraper]


def _pages_per_term() -> int:
    from backend.scrapers.drushim_scraper import _MAX_PAGES
    return _MAX_PAGES


def plan_cycle(
    user_ids: list[str],
    cached: dict[str, list[str]],
    *,
    cap: int,
    cycle: int,
    hebrew_share: float,
) -> tuple[list[str], dict[str, Callable[[str], bool]]]:
    """
    Pure part of a cycle: the terms to search and each user's matcher.

    Users without cached terms search (and are gated by) the global list, so
    the global list is the search when nobody has terms of their own.
    """
    from backend.config import TARGET_SEARCH_QUERIES
    from backend.scrapers.relevancy import build_title_matcher
    from backend.services.board_search_terms import select_for_cycle, union_terms

    per_user = {uid: (cached.get(uid) or list(TARGET_SEARCH_QUERIES)) for uid in user_ids}
    matchers = {uid: build_title_matcher(cached.get(uid)) for uid in user_ids}
    union = union_terms(per_user)
    keywords = select_for_cycle(union, cap, cycle, hebrew_share=hebrew_share)
    return keywords, matchers


def _interleave(per_board: list[list[JobMatch]]) -> list[JobMatch]:
    """Round-robin across boards so the per-user cap is not spent on board #1 alone."""
    out: list[JobMatch] = []
    seen: set[str] = set()
    for row in zip_longest(*per_board):
        for job in row:
            if job is None:
                continue
            url = (job.apply_url or "").strip()
            if url and url in seen:
                continue
            seen.add(url)
            out.append(job)
    return out


def distribute(
    jobs: list[JobMatch],
    matchers: dict[str, Callable[[str], bool]],
    *,
    per_user_limit: int,
    save: Optional[Callable] = None,
) -> dict[str, int]:
    """Save each job only for the users whose matcher accepts its title."""
    from backend.scrapers.scraper_manager import ScraperManager

    save = save or ScraperManager._save_new
    saved: dict[str, int] = {}
    for uid, matcher in matchers.items():
        mine = [j for j in jobs if matcher(j.title or "")]
        saved[uid] = save(mine, limit=per_user_limit, user_id=uid, matcher=matcher) if mine else 0
    return saved


def _interval_elapsed(interval: int) -> bool:
    from backend.repositories import kv_repository
    try:
        entry = kv_repository.get(_LAST_RUN_KEY)
        last = float(entry.value) if entry else 0.0
    except Exception as exc:
        logger.warning("[board-discovery] last-run time unavailable (%s) — running", exc)
        return True
    return time.time() - last >= interval


def _mark_run() -> None:
    from backend.repositories import kv_repository
    try:
        kv_repository.upsert(_LAST_RUN_KEY, str(time.time()))
    except Exception as exc:
        logger.warning("[board-discovery] could not store last-run time: %s", exc)


async def run_board_discovery_cycle(
    user_ids: Optional[list[str]] = None,
    *,
    respect_interval: bool = True,
    scraper_classes: Optional[list] = None,
) -> dict[str, int]:
    """
    One board cycle for *user_ids* (default: every pipeline user).

    respect_interval=False is the manual "sync" path for one user: it skips
    the interval gate and rotates that user's own cursor, not the shared one.
    Returns {user_id: new jobs saved}.
    """
    from backend import config
    from backend.config import (
        BOARD_HEBREW_SHARE, BOARD_DISCOVERY_INTERVAL_SECONDS, BOARD_MAX_NEW_JOBS_PER_USER,
        BOARD_TERMS_PER_CYCLE, DEV_MAX_JOBS_PER_BOARD, DEV_MODE,
    )

    # Paused by default: every board answers Render's IP with 403 (see
    # config.BOARD_DISCOVERY_ENABLED). Checked here, not only in the loop, so
    # the "sync" button stops hitting the blocked sites too.
    if not config.BOARD_DISCOVERY_ENABLED:
        logger.info("[board-discovery] paused (BOARD_DISCOVERY_ENABLED=false) — no board requests sent")
        return {}
    from backend.services.board_search_terms import next_cycle
    from backend.services.tenant_registry import list_pipeline_user_ids
    from backend.services.user_title_terms import cached_terms_for_users

    shared = user_ids is None
    if user_ids is None:
        user_ids = list_pipeline_user_ids()
    if not user_ids:
        logger.info("[board-discovery] no pipeline users — nothing to search for")
        return {}
    if respect_interval and not _interval_elapsed(BOARD_DISCOVERY_INTERVAL_SECONDS):
        logger.info("[board-discovery] interval not elapsed — skipping")
        return {}

    try:
        cached = cached_terms_for_users(user_ids)
    except Exception:
        # Loud: without terms every user would silently be searched with the
        # global list again, which is exactly the bug this module fixes.
        logger.exception("[board-discovery] could not read cached terms — skipping cycle")
        return {}

    cursor = "boards" if shared else "boards:" + ",".join(sorted(user_ids))
    keywords, matchers = plan_cycle(
        user_ids, cached,
        cap=BOARD_TERMS_PER_CYCLE, cycle=next_cycle(cursor), hebrew_share=BOARD_HEBREW_SHARE,
    )
    if respect_interval:
        _mark_run()
    if not keywords:
        # A scraper given no keywords runs one EMPTY search ([""]): the
        # board's whole listing, unrelated to any user. Never send that.
        logger.info("[board-discovery] no terms to search — skipping cycle")
        return {}

    def any_user(title: str) -> bool:
        return any(m(title) for m in matchers.values())

    board_kw: dict = {"max_jobs": DEV_MAX_JOBS_PER_BOARD} if DEV_MODE else {}
    scrapers = [
        cls(keywords=keywords, user_id="default", title_filter=any_user, **board_kw)
        for cls in (scraper_classes or _board_scraper_classes())
    ]
    request_bound = (
        len(keywords) * _pages_per_term() * len(scrapers)
        + sum(getattr(s, "_max_jobs", 0) for s in scrapers)
    )
    logger.info(
        "[board-discovery] users=%d with_own_terms=%d terms=%d request_bound=%d keywords=%s",
        len(user_ids), len(cached), len(keywords), request_bound, keywords,
    )

    async def _fetch(s) -> list[JobMatch]:
        try:
            return await s.fetch_jobs()
        except Exception as exc:
            logger.exception("[board-discovery] %s failed: %s", s.__class__.__name__, exc)
            return []

    per_board = await asyncio.gather(*[_fetch(s) for s in scrapers])
    jobs = _interleave(list(per_board))
    # Saving is synchronous DB work; keep it off the event loop.
    saved = await asyncio.to_thread(
        distribute, jobs, matchers, per_user_limit=BOARD_MAX_NEW_JOBS_PER_USER,
    )
    logger.info(
        "[board-discovery] done — fetched=%d per_board=%s saved=%s",
        len(jobs), [len(b) for b in per_board], saved,
    )
    return saved
