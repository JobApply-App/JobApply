#!/usr/bin/env python3
"""
One-shot backfill: map every relevant `public.all_jobs` row into a user's feed.

Why this exists (and why it is not just a loop over the service function)
--------------------------------------------------------------------------
`all_jobs_match_service.run_all_jobs_matching_cycle()` cannot drain a backlog.
Its candidate query is:

    ORDER BY last_seen_at DESC LIMIT _CANDIDATE_POOL_SIZE   (300)

with no offset. Calling it repeatedly re-reads the same newest 300 rows; once
those are matched it returns 0 forever, and every row past position 300 is
unreachable. That is fine for its actual job — absorbing newly-scraped rows as
they arrive at the top — but it means a catalog that grew faster than the loop
ran can never be caught up by running the loop more often.

This script pages through the WHOLE table by a stable key and reuses the same
mapping and save primitives, so a backfilled row is byte-identical to one the
loop would have produced:

    _all_jobs_row_to_job_match()  — the mapper
    ScraperManager._save_new()    — the relevancy-gated, id-salting save

Scoring is deliberately NOT done here
---------------------------------------
`_save_new` writes rows with match_score == 0.0. The enrichment loop
(main.py -> feed_service.refresh_user_scores) already picks those up and runs
the real LLM-backed scoring pass. Doing it here too would mean a second
scoring code path that can disagree with the first.

That has one sharp edge worth knowing before running with a large batch:
`refresh_user_scores()` enriches EVERY pending job in a single sweep, with no
per-sweep cap. Backfilling N jobs therefore queues N LLM calls for whenever the
backend next runs its 30-second enrichment tick. `--dry-run` reports that number
before you commit to it.

Idempotency
-------------
Safe to re-run and safe to interrupt. Rows already matched for the user are
skipped via the same salted-id check the service uses, so a resumed run
continues where it stopped rather than duplicating.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# Import as `backend.*` (CLAUDE.md): bare imports load a second module instance
# with its own DB engines and caches.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend.services.all_jobs_match_service import (  # noqa: E402
    _JOB_ID_PREFIX,
    _all_jobs_row_to_job_match,
    _existing_job_ids,
)

logger = logging.getLogger("backfill_all_jobs")

DEFAULT_PAGE_SIZE = 200


def _page_all_jobs(page_size: int, offset: int):
    """One page of all_jobs, ordered by a STABLE key.

    Ordered by `id`, not `last_seen_at`: last_seen_at is rewritten by the
    scraper as it re-observes listings, so paging by it would let rows shift
    between pages mid-run and be skipped. `id` does not move.
    """
    from backend.core.postgres import get_pg_session
    from backend.models.all_jobs import AllJobRow

    with get_pg_session() as session:
        return (
            session.query(AllJobRow)
            .order_by(AllJobRow.id)
            .offset(offset)
            .limit(page_size)
            .all()
        )


def run(user_id: str, page_size: int, dry_run: bool, max_rows: int | None) -> int:
    from backend.scrapers.base_scraper import make_job_id, make_tenant_job_id
    from backend.scrapers.relevancy import is_title_relevant
    from backend.scrapers.scraper_manager import ScraperManager

    existing = _existing_job_ids(user_id)
    logger.info("[backfill] user=%s already has %d matched job(s)", user_id, len(existing))

    offset = scanned = skipped_no_url = skipped_irrelevant = skipped_existing = 0
    saved_total = 0
    would_save = 0

    while True:
        rows = _page_all_jobs(page_size, offset)
        if not rows:
            break
        offset += len(rows)

        batch = []
        for row in rows:
            scanned += 1
            apply_url = (row.job_url or "").strip()
            title = (row.job_title or "").strip()

            if not apply_url:
                skipped_no_url += 1
                continue
            if not is_title_relevant(title):
                skipped_irrelevant += 1
                continue

            # Predict the salted id _save_new will produce, exactly as the
            # service does — without pre-salting the JobMatch we hand over,
            # which would double-salt it.
            salted = make_tenant_job_id(make_job_id(apply_url, prefix=_JOB_ID_PREFIX), user_id)
            if salted in existing:
                skipped_existing += 1
                continue

            job = _all_jobs_row_to_job_match(row, user_id)
            if job is None:
                continue
            batch.append(job)
            existing.add(salted)   # guard against duplicates within this run

            if max_rows is not None and (would_save + len(batch)) >= max_rows:
                break

        if batch:
            if dry_run:
                would_save += len(batch)
            else:
                # limit=len(batch): _save_new's limit slices the list it is
                # handed, so anything smaller would silently drop the rest.
                saved = ScraperManager._save_new(batch, limit=len(batch), user_id=user_id)
                saved_total += saved
                logger.info("[backfill] offset=%-6d batch=%-4d saved=%-4d running_total=%d",
                            offset, len(batch), saved, saved_total)

        if max_rows is not None and (would_save if dry_run else saved_total) >= max_rows:
            logger.info("[backfill] --max-rows reached, stopping")
            break

    mapped = would_save if dry_run else saved_total
    print()
    print(f"  {'scanned':<28}{scanned:>7}")
    print(f"  {'skipped: no job_url':<28}{skipped_no_url:>7}")
    print(f"  {'skipped: not relevant':<28}{skipped_irrelevant:>7}")
    print(f"  {'skipped: already matched':<28}{skipped_existing:>7}")
    print(f"  {'-'*35}")
    print(f"  {'WOULD MAP' if dry_run else 'MAPPED':<28}{mapped:>7}")
    print()
    if dry_run:
        print(f"  Dry run — nothing written. Those {mapped} row(s) would be saved with")
        print(f"  match_score=0.0 and would queue ~{mapped} LLM scoring call(s) for the")
        print("  enrichment loop (it enriches every pending job in one sweep).")
    else:
        print(f"  {mapped} row(s) written with match_score=0.0. The enrichment loop will")
        print("  score them on its next sweep; run with the backend up, or trigger")
        print("  refresh_user_scores() explicitly.")
    return mapped


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill relevant all_jobs rows into a user's feed (one-shot, resumable)."
    )
    parser.add_argument("--user-id", required=True, help="Owner of the backfilled matches")
    parser.add_argument("--page-size", type=int, default=DEFAULT_PAGE_SIZE,
                        help=f"Rows per all_jobs page (default {DEFAULT_PAGE_SIZE})")
    parser.add_argument("--max-rows", type=int, default=None,
                        help="Stop after mapping this many rows (default: no limit)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Report what would be mapped and the LLM calls it would queue; write nothing")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    run(args.user_id, args.page_size, args.dry_run, args.max_rows)


if __name__ == "__main__":
    main()
