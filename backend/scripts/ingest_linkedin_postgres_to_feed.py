"""
ingest_linkedin_postgres_to_feed.py

Bridges backend/models/linkedin_job.py's `linkedin.jobs` table (a separate
PostgreSQL datastore populated by backend/scripts/linkedin_israel_jobs.py)
into the app's actual primary datastore — the SQLite `jobs` table that the
"Matches" feed (GET /api/jobs/feed) reads from.

No bridge previously existed between these two tables (linkedin.jobs is only
read by GET /api/linkedin/jobs for its own "All Jobs" tab). This script is
the one-time/on-demand ingestion step; it reuses the exact same JobMatch
construction and persistence path as the existing LinkedIn Bulk CSV pipeline
(backend/scrapers/linkedin_bulk_scraper.py + backend/scripts/
run_linkedin_bulk_ingest.py) — same job_id prefix ("li-bulk"), same
ScraperManager._save_new() relevancy gate and source-priority dedup — so
these rows behave identically to any other bulk-imported LinkedIn job to
the rest of the app (is_bulk_import flag, closure validator, etc).

Rows are saved with real metadata but zeroed AI scores (score_is_proxy=True,
match_score=0.0), matching every other freshly-scraped job's shape — the
already-running background enrichment loop (backend/main.py's
_enrichment_loop -> feed_service.refresh_user_scores()) picks them up and
runs the full ATS/LLM scoring pass automatically. Pass --score-now to also
run that pass synchronously and print each job's final match_score before
exiting, instead of waiting for the next background cycle.

Usage
-----
    python -m backend.scripts.ingest_linkedin_postgres_to_feed --user-id default
    python -m backend.scripts.ingest_linkedin_postgres_to_feed --user-id default --score-now
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import backend.repositories.job_repository as job_store
from backend.core.postgres import get_pg_session
from backend.models.linkedin_job import LinkedInJobRow
from backend.scrapers.base_scraper import make_job_id, make_tenant_job_id, minimal_job_match, now_iso
from backend.scrapers.linkedin_bulk_scraper import _JOB_ID_PREFIX
from backend.scrapers.relevancy import is_title_relevant

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def _fetch_all_linkedin_jobs() -> list[dict]:
    """
    Every row in linkedin.jobs, INCLUDING `description` — deliberately not
    using get_paginated_jobs()/its list-view columns, which strip
    `description` for a lighter pagination payload (see
    test_response_items_include_expected_fields_and_exclude_description).
    Without the real JD text, every job here would look "thin" to
    feed_service._needs_enrichment(), and since they're all linkedin.com
    URLs, _needs_enrichment() treats thin-JD LinkedIn jobs as permanently
    unhydratable and skips them forever — silently stuck at match_score=0.0.
    """
    with get_pg_session() as session:
        orm_rows = session.query(LinkedInJobRow).all()
        return [
            {
                "title": row.title,
                "company": row.company,
                "location": row.location,
                "job_url": row.job_url,
                "description": row.description,
            }
            for row in orm_rows
        ]


def _to_job_match(row: dict, user_id: str):
    apply_url = row["job_url"]
    return minimal_job_match(
        job_id      = make_job_id(apply_url, prefix=_JOB_ID_PREFIX),
        title       = row["title"],
        company     = row["company"],
        location    = row.get("location") or "Unknown",
        apply_url   = apply_url,
        jd_text     = row.get("description") or None,
        posted_at   = now_iso(),
        source_type = "linkedin",
        user_id     = user_id,
    )


def _save_new_bypassing_relevancy(jobs: list, user_id: str) -> int:
    """
    Same tenant-salting + save_with_source_priority dedup as
    ScraperManager._save_new(), minus the is_title_relevant() gate.

    Deliberately NOT a change to ScraperManager itself — that gate stays in
    force for every regular scraper. This bridge is a manual, one-off
    operation explicitly requested to force a specific fixture through
    regardless of relevancy, so it calls the same save primitive directly.
    """
    saved = 0
    for job in jobs:
        if not is_title_relevant(job.title):
            logger.info("[bypass] Forcing through despite relevancy gate: '%s' @ %s", job.title, job.company)
        job = job.model_copy(update={
            "user_id": user_id,
            "job_id": make_tenant_job_id(job.job_id, user_id),
        })
        try:
            if job_store.save_with_source_priority(job):
                saved += 1
        except Exception as exc:
            logger.warning("Failed to save job %s (%s): %s", job.job_id, job.title, exc)
    return saved


async def run(user_id: str, score_now: bool, bypass_relevancy: bool) -> None:
    pg_rows = _fetch_all_linkedin_jobs()
    logger.info("Fetched %d row(s) from linkedin.jobs", len(pg_rows))

    jobs = [_to_job_match(row, user_id) for row in pg_rows]
    if bypass_relevancy:
        saved = _save_new_bypassing_relevancy(jobs, user_id=user_id)
    else:
        from backend.scrapers.scraper_manager import ScraperManager
        saved = ScraperManager._save_new(jobs, user_id=user_id)
    logger.info(
        "Ingestion complete: %d fetched, %d new — user_id=%s (rest were dedup/relevancy-skipped)",
        len(jobs), saved, user_id,
    )

    if not score_now:
        return

    from backend.services.feed_service import refresh_user_scores
    enriched = await refresh_user_scores(user_id)
    logger.info("Scoring pass complete: %d job(s) enriched", enriched)

    # feed_service.refresh_user_scores() (the background enrichment loop) never
    # sets jd_structured — only the synchronous POST /api/jobs/analyze endpoint
    # does. Without it, GET /api/jobs/feed's Zero-Click completeness gate
    # silently drops every background-enriched job, no matter how it scored.
    # This affects the pre-existing LinkedIn Bulk Import pipeline too, not just
    # this bridge — flagged separately; closing the gap here so THESE jobs are
    # actually feed-visible.
    from backend.services.jd_structure_service import structure_jd
    feed = job_store.get_feed(user_id)
    linkedin_jobs = [j for j in feed if j.job_id.startswith(_JOB_ID_PREFIX)]
    for j in linkedin_jobs:
        if (j.jd_structured or "").strip() or not (j.jd_text or "").strip():
            continue
        try:
            structured_json = await structure_jd(j.jd_text, user_id=user_id, job_id=j.job_id)
            if structured_json:
                job_store.update_jd_structured(j.job_id, structured_json)
                j.jd_structured = structured_json
        except Exception as exc:
            logger.warning("JD structuring failed for %s (%s): %s", j.job_id, j.title, exc)

    for j in sorted(linkedin_jobs, key=lambda j: j.match_score, reverse=True):
        logger.info(
            "  match_score=%.1f%s  %-45s @ %s",
            j.match_score, " (proxy)" if j.score_is_proxy else "",
            j.title[:45], j.company,
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ingest linkedin.jobs (Postgres) into the SQLite feed for a user"
    )
    parser.add_argument("--user-id", default="default", help="Owner of the ingested jobs")
    parser.add_argument(
        "--score-now", action="store_true",
        help="Also run the LLM/ATS scoring pass synchronously before exiting",
    )
    parser.add_argument(
        "--bypass-relevancy", action="store_true",
        help=(
            "Force jobs through even if is_title_relevant() would normally reject them. "
            "Off by default — every other scraper goes through this gate; only pass this "
            "for a deliberate, explicitly-requested override."
        ),
    )
    args = parser.parse_args()
    asyncio.run(run(args.user_id, args.score_now, args.bypass_relevancy))


if __name__ == "__main__":
    main()
