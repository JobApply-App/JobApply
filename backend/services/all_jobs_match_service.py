"""
Bridges `public.all_jobs` (the global, cross-provider job catalog fed by the
LinkedIn scraper — see backend/models/all_jobs.py) into each user's Matches
feed (`job_postings`/`user_job_matches`).

Why this exists
----------------
`all_jobs` and the Matches feed were, until now, two completely disconnected
schemas: `all_jobs` is read-only (GET /api/all-jobs, the "All Jobs" tab), and
nothing ever moved a row from there into anyone's personal, scored feed.
This module is that bridge.

Design: map, don't score
-------------------------
This module deliberately does NOT call compute_match_score_async() itself.
It builds a zero-score minimal_job_match() for each unmatched all_jobs row
(same shape every other scraper adapter produces) and saves it via
ScraperManager._save_new() — the exact same save primitive
backend/scripts/ingest_linkedin_postgres_to_feed.py already uses for the
sibling linkedin.jobs -> feed bridge. The EXISTING enrichment loop
(backend/main.py's _enrichment_loop -> feed_service.refresh_user_scores())
already picks up any match_score == 0.0 row via get_unscored_new_jobs() and
runs the real LLM-backed scoring pass on its own schedule. Reusing that path
means: no new LLM-call code to get wrong, no risk of this loop and the
enrichment loop racing to score the same row differently, and the exact
same relevancy gate (is_title_relevant, applied inside _save_new) every
other automated source already goes through.

Idempotency / the bug this module is careful to avoid
--------------------------------------------------------
save_with_source_priority() UPSERTS — for a user_job_matches row that
already exists, it unconditionally overwrites score/match_score/etc. from
whatever JobMatch it's given (see job_repository._update_match_from_jobmatch).
A background loop that re-ran every cycle and re-saved a *zero-score*
minimal_job_match() for a job the user already has — and has since been
scored — would silently reset that real score back to 0.0 forever. This
module avoids that by checking each candidate against the user's EXISTING
job_ids first (_existing_job_ids) and only ever building/saving JobMatch
objects for ones not already present. An existing match is never touched
here; if it needs re-scoring, that is refresh_user_scores()'s job, not
this module's.
"""
from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import text

logger = logging.getLogger(__name__)

_JOB_ID_PREFIX = "allj"

# Per-user, per-cycle cap — bounds both the write volume into user_job_matches
# and (indirectly) the LLM-scoring load the enrichment loop picks up right
# after. Candidates are pulled most-recently-seen-first, so a user with a
# large unmatched backlog surfaces the freshest listings first and works
# through the rest over subsequent cycles rather than in one burst.
DEFAULT_CYCLE_LIMIT = 20

# How many all_jobs titles to scan per user per cycle (a light id/title/url
# query). Covers the whole current catalog (~8.5k rows) with headroom; the
# bound only keeps a runaway catalog from turning one cycle into a full-table
# load per user.
_CANDIDATE_POOL_SIZE = 20_000


def _location_to_string(location: Optional[dict]) -> str:
    """
    all_jobs.location is {"city": str|None, "district": str|None,
    "country": str|None} (backend/services/linkedin_job_normalize.py's
    parse_location()); job_postings/canonical_dedup_key need a flat display
    string. Joins whichever parts are present, in city -> district -> country
    order, comma-separated. "Unknown" (matching job_repository's own
    location default) if nothing is present at all.
    """
    if not location:
        return "Unknown"
    parts = [
        str(location.get(key)).strip()
        for key in ("city", "district", "country")
        if location.get(key) and str(location.get(key)).strip()
    ]
    return ", ".join(parts) if parts else "Unknown"


def _source_type_from_all_jobs_source(source: Optional[str]) -> str:
    """Map all_jobs.source (free text, default 'linkedin') to JobMatch's
    closed SourceType. Anything not recognized falls back to 'other' rather
    than guessing — 'other' is the lowest dedup priority, so an unrecognized
    source never wrongly outranks a real company-site/linkedin match."""
    s = (source or "").strip().lower()
    if s == "linkedin":
        return "linkedin"
    if s in ("company_site", "ats", "career_page"):
        return "company_site"
    return "other"


def _all_jobs_row_to_job_match(row, user_id: str):
    """
    Map one public.all_jobs row to a JobMatch with real metadata and zeroed
    AI scores — same contract as every scraper adapter's fetch_jobs() output
    (see base_scraper.py's minimal_job_match docstring). Returns None for a
    row missing the one genuinely required field (job_url — apply_url is the
    dedup/identity anchor everywhere downstream).
    """
    from backend.scrapers.base_scraper import make_job_id, minimal_job_match

    apply_url = (row.job_url or "").strip()
    if not apply_url:
        return None

    return minimal_job_match(
        job_id      = make_job_id(apply_url, prefix=_JOB_ID_PREFIX),
        title       = (row.job_title or "").strip(),
        company     = (row.company_name or "").strip(),
        location    = _location_to_string(row.location),
        apply_url   = apply_url,
        jd_text     = row.description or None,
        posted_at   = row.posted_at.isoformat() if row.posted_at else "",
        source_type = _source_type_from_all_jobs_source(row.source),
        user_id     = user_id,
    )


def _existing_job_ids(user_id: str) -> set[str]:
    """Every job_id this user already has a user_job_matches row for — one
    query, so the per-candidate check below is an in-memory set lookup
    rather than a query per row."""
    from backend.core.database import ENGINE

    with ENGINE.connect() as conn:
        rows = conn.execute(
            text("SELECT job_id FROM public.user_job_matches WHERE user_id = CAST(:uid AS uuid)"),
            {"uid": user_id},
        ).fetchall()
    return {r[0] for r in rows}


# The catalog title index (id, title, url, company, location) is the same for
# every user in a cycle, so it is loaded once and reused for a few minutes
# instead of re-read from Postgres per user. Re-reading it per user — ~8.6k
# rows over a cross-region connection — was most of a ~23s per-user cycle.
# Kept for one loop interval: the loop is the main reader, and reloading the
# index more often than the catalog changes was pure database egress.
_INDEX_TTL_S = 21600.0
_INDEX_CACHE: dict = {"at": 0.0, "rows": None}


def _catalog_index():
    import time
    from backend.core.postgres import get_pg_session
    from backend.models.all_jobs import AllJobRow

    now = time.monotonic()
    if _INDEX_CACHE["rows"] is not None and now - _INDEX_CACHE["at"] < _INDEX_TTL_S:
        return _INDEX_CACHE["rows"]
    with get_pg_session() as session:
        rows = (
            session.query(
                AllJobRow.id, AllJobRow.job_title, AllJobRow.job_url,
                AllJobRow.company_name, AllJobRow.location,
            )
            .order_by(AllJobRow.last_seen_at.desc())
            .limit(_CANDIDATE_POOL_SIZE)
            .all()
        )
    _INDEX_CACHE.update(at=now, rows=rows)
    return rows


def _existing_posting_keys(user_id: str) -> set[str]:
    """canonical_job_key of every posting this user already has a match for."""
    from backend.core.database import ENGINE

    with ENGINE.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT jp.canonical_job_key FROM public.user_job_matches ujm "
                "JOIN public.job_postings jp ON jp.id = ujm.job_posting_id "
                "WHERE ujm.user_id = CAST(:uid AS uuid)"
            ),
            {"uid": user_id},
        ).fetchall()
    return {r[0] for r in rows if r[0]}


def _candidate_all_jobs_rows(matcher, existing: set[str], user_id: str, limit: int):
    """
    Up to *limit* all_jobs rows whose title passes *matcher* and that the user
    doesn't already have, most-recently-seen first. Lives on the dedicated
    LinkedIn/all_jobs Postgres engine (backend/core/postgres.py), not the
    primary app engine — see all_jobs_repository.py's module docstring for
    why these are separate connections.

    Scans titles across the whole catalog rather than the 300 most recent
    rows: with a per-user title filter a niche role can be a handful of rows
    in 8,000+.

    "Already has" is checked two ways, because the save path dedups two ways:
    by salted job_id, and by the posting's canonical (title, company,
    location) key. Checking only the job_id let the same role re-posted under
    another URL through as "new" every cycle; save then matched the existing
    posting and inserted nothing, so the same ~20 duplicates filled every
    cycle's limit and the user never received a genuinely new job.
    """
    from backend.core.postgres import get_pg_session
    from backend.models.all_jobs import AllJobRow
    from backend.repositories.job_repository import canonical_dedup_key
    from backend.scrapers.base_scraper import make_job_id, make_tenant_job_id

    have_keys = _existing_posting_keys(user_id)
    chosen: list = []
    for row_id, title, url, company, location in _catalog_index():
        apply_url = (url or "").strip()
        clean_title = (title or "").strip()
        if not apply_url or not matcher(clean_title):
            continue
        if make_tenant_job_id(make_job_id(apply_url, prefix=_JOB_ID_PREFIX), user_id) in existing:
            continue
        key = canonical_dedup_key(clean_title, (company or "").strip(), _location_to_string(location))
        if key in have_keys:
            continue
        have_keys.add(key)   # also dedups within this batch
        chosen.append(row_id)
        if len(chosen) >= limit:
            break
    if not chosen:
        return []
    with get_pg_session() as session:
        rows = session.query(AllJobRow).filter(AllJobRow.id.in_(chosen)).all()
    order = {rid: i for i, rid in enumerate(chosen)}
    return sorted(rows, key=lambda r: order[r.id])


def retire_off_target_matches(user_id: str, matcher) -> int:
    """
    Remove this bridge's untouched matches whose title no longer fits the
    user's roles. Returns how many were removed.

    Matches are admitted by the title filter in force when they arrive, and
    nothing ever took them out again. When a user's roles changed — or, as
    happened in production, when the first cycles ran on the founder's global
    list before the user's roles were known — the old jobs stayed in the feed
    for good.

    Only rows the user never acted on go: status 'new', not applied, no
    tailored CV, and only rows this bridge created ('allj-' ids). A job the
    user pasted in, saved, skipped or tailored is never touched. Only the
    per-user match row is deleted; the shared job_postings row stays.
    """
    from backend.core.database import ENGINE

    with ENGINE.connect() as conn:
        rows = conn.execute(
            text("""
                SELECT ujm.job_id, jp.title
                FROM public.user_job_matches ujm
                JOIN public.job_postings jp ON jp.id = ujm.job_posting_id
                WHERE ujm.user_id = CAST(:uid AS uuid)
                  AND ujm.job_id LIKE :prefix
                  AND ujm.status = 'new'
                  AND COALESCE(ujm.applied, false) = false
                  AND (ujm.tailored_cv IS NULL
                       OR ujm.tailored_cv IN ('null'::jsonb, '{}'::jsonb))
            """),
            {"uid": user_id, "prefix": f"{_JOB_ID_PREFIX}-%"},
        ).fetchall()

    stale = [job_id for job_id, title in rows if not matcher(title or "")]
    if not stale:
        return 0
    with ENGINE.begin() as conn:
        conn.execute(
            text("DELETE FROM public.user_job_matches "
                 "WHERE user_id = CAST(:uid AS uuid) AND job_id = ANY(:ids)"),
            {"uid": user_id, "ids": stale},
        )
    logger.info("[all_jobs_match] user=%s retired %d off-target matches", user_id, len(stale))
    return len(stale)


def run_all_jobs_matching_cycle(
    user_id: str, *, limit: int = DEFAULT_CYCLE_LIMIT, terms: Optional[list[str]] = None,
) -> int:
    """
    For one user: find all_jobs rows they don't already have a match for,
    map up to *limit* of them into zero-score JobMatch objects, and save
    them via the standard relevancy-gated save path. The already-running
    enrichment loop scores anything saved here on its own schedule — see
    this module's docstring for why scoring isn't done inline here.

    Returns the number of new user_job_matches rows actually inserted
    (mirrors ScraperManager._save_new's own return contract).
    """
    from backend.scrapers.relevancy import build_title_matcher
    from backend.scrapers.scraper_manager import ScraperManager

    # No terms = no matches yet. This used to fall back to the global list
    # (config.TARGET_SEARCH_QUERIES), which is the founder's own Product /
    # Customer Success roles. A new user whose roles were not known yet got
    # those jobs: in production a senior software engineer's feed opened with
    # "Product Manager" postings that read like someone else's data had leaked
    # into her account, and they stayed after her real roles arrived. A user
    # with no roles gets matches once onboarding or a CV names them.
    if not terms:
        logger.info("[all_jobs_match] user=%s has no title terms yet — skipping cycle", user_id)
        return 0

    # Relevancy is checked here, across the whole catalog, not just inside
    # _save_new — so a pool front-loaded with irrelevant rows can't exhaust
    # *limit* before a single real job is found.
    matcher = build_title_matcher(terms)
    retire_off_target_matches(user_id, matcher)
    existing = _existing_job_ids(user_id)
    candidates = _candidate_all_jobs_rows(matcher, existing, user_id, limit)

    from backend.scrapers.base_scraper import make_job_id, make_tenant_job_id

    to_save = []
    for row in candidates:
        if len(to_save) >= limit:
            break
        # Re-checked here even though the candidate query already excludes
        # existing matches: re-saving a zero-score row for a job the user
        # already has would reset its real score (module docstring), so this
        # guard must not depend on how candidates were selected.
        apply_url = (row.job_url or "").strip()
        if not apply_url or make_tenant_job_id(make_job_id(apply_url, prefix=_JOB_ID_PREFIX), user_id) in existing:
            continue
        job = _all_jobs_row_to_job_match(row, user_id)
        if job is not None:
            to_save.append(job)

    if not to_save:
        return 0

    saved = ScraperManager._save_new(to_save, limit=limit, user_id=user_id, matcher=matcher)
    logger.info(
        "[all_jobs_match] user=%s  candidates=%d  new_matches=%d",
        user_id, len(candidates), saved,
    )
    return saved


# ── Immediate refresh after a profile change ─────────────────────────────────

_REFRESH_TASKS: set = set()


def schedule_refresh_for_user(user_id: str) -> None:
    """
    Fire-and-forget: refresh this user's title terms and run one matching
    cycle now, instead of leaving them on the old filter until the next
    6-hour loop tick. Called after a CV upload or a roles change.

    Only for users already in the pipeline (onboarding complete) — the same
    gate the background loop applies, so this never feeds anyone the loop
    itself wouldn't. Must be called from a running event loop.
    """
    import asyncio

    async def _run() -> None:
        from backend.repositories import profile_repository
        from backend.services.user_title_terms import refresh_user_terms

        try:
            handle = profile_repository.get(user_id)
            if handle is None or handle.onboarding_status != "complete":
                return
            terms = await refresh_user_terms(user_id)
            saved = await asyncio.to_thread(run_all_jobs_matching_cycle, user_id, terms=terms)
            logger.info("[all_jobs_match] immediate refresh user=%s new_matches=%d", user_id, saved)
        except Exception:
            logger.exception("[all_jobs_match] immediate refresh failed for user=%s", user_id)

    task = asyncio.create_task(_run())
    # Strong reference until done — asyncio keeps only a weak one.
    _REFRESH_TASKS.add(task)
    task.add_done_callback(_REFRESH_TASKS.discard)
