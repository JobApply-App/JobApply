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

# How many candidate all_jobs rows to inspect per user per cycle, before
# per-user existing-match filtering narrows it down to DEFAULT_CYCLE_LIMIT
# actually-new ones. Wider than the save limit since most rows in a mature
# catalog will already be matched for an established user.
_CANDIDATE_POOL_SIZE = 300


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


def _candidate_all_jobs_rows(limit: int):
    """Most-recently-seen all_jobs rows, capped at *limit*. Lives on the
    dedicated LinkedIn/all_jobs Postgres engine (backend/core/postgres.py),
    not the primary app engine — see all_jobs_repository.py's module
    docstring for why these are separate connections."""
    from backend.core.postgres import get_pg_session
    from backend.models.all_jobs import AllJobRow

    with get_pg_session() as session:
        return (
            session.query(AllJobRow)
            .order_by(AllJobRow.last_seen_at.desc())
            .limit(limit)
            .all()
        )


def run_all_jobs_matching_cycle(user_id: str, *, limit: int = DEFAULT_CYCLE_LIMIT) -> int:
    """
    For one user: find all_jobs rows they don't already have a match for,
    map up to *limit* of them into zero-score JobMatch objects, and save
    them via the standard relevancy-gated save path. The already-running
    enrichment loop scores anything saved here on its own schedule — see
    this module's docstring for why scoring isn't done inline here.

    Returns the number of new user_job_matches rows actually inserted
    (mirrors ScraperManager._save_new's own return contract).
    """
    from backend.scrapers.base_scraper import make_job_id, make_tenant_job_id
    from backend.scrapers.relevancy import is_title_relevant
    from backend.scrapers.scraper_manager import ScraperManager

    existing = _existing_job_ids(user_id)
    candidates = _candidate_all_jobs_rows(_CANDIDATE_POOL_SIZE)

    # Relevancy is checked here too (not just inside _save_new) so that a
    # candidate pool front-loaded with irrelevant rows (ads, unrelated
    # postings) doesn't exhaust *limit* before a single real job is found —
    # _save_new alone would silently save nothing in that case, since it
    # stops filtering only the slice it's handed, not the whole pool.
    to_save = []
    for row in candidates:
        if len(to_save) >= limit:
            break

        apply_url = (row.job_url or "").strip()
        title = (row.job_title or "").strip()
        if not apply_url or not is_title_relevant(title):
            continue
        # Predict the salted id _save_new will produce (it re-salts
        # job_id internally when user_id is passed) so this check and what
        # actually gets saved agree — without pre-salting the JobMatch we
        # hand to _save_new ourselves, which would double-salt it.
        salted_id = make_tenant_job_id(make_job_id(apply_url, prefix=_JOB_ID_PREFIX), user_id)
        if salted_id in existing:
            continue

        job = _all_jobs_row_to_job_match(row, user_id)
        if job is not None:
            to_save.append(job)

    if not to_save:
        return 0

    saved = ScraperManager._save_new(to_save, limit=limit, user_id=user_id)
    logger.info(
        "[all_jobs_match] user=%s  candidates=%d  new_matches=%d",
        user_id, len(candidates), saved,
    )
    return saved
