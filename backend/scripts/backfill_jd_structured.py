#!/usr/bin/env python3
"""
Retroactive backfill of job_postings.jd_structured.

Only three code paths ever wrote jd_structured — discovery.py, POST
/api/jobs/analyze, and jd_backfill_service — so every posting that entered the
database any other way (catalogue ingests, pasted jobs, the all_jobs bridge)
has raw jd_text and a NULL jd_structured. Those rows render without a
requirements panel in JobCard, and score through the regex heading-splitter
fallback instead of LLM-parsed requirements. This script closes that gap for
rows already in the table; the enrichment loop now handles new arrivals.

Uses jd_structure_service.structure_jd() and nothing else — same StructuredJd
schema, same prompt, same validation as every other writer. No second parser.

Why it writes by posting id, not job_id
-----------------------------------------
job_repository.update_jd_structured() resolves its target through
user_job_matches, because job_id is that table's column. Most rows needing this
backfill have NO match row at all — on Dev, 10 of 11 — so that helper's
subquery yields NULL and its UPDATE silently matches nothing. This script uses
update_jd_structured_by_posting_id(), which addresses job_postings.id directly
and reports whether a row was actually written.

Safety
------
Dry-run by default: without --apply, nothing is written and the script prints
exactly what it WOULD do, without spending a single LLM call. --apply is the
only thing that costs money or mutates rows.

Usage
-----
    # preview (no LLM calls, no writes)
    python -m backend.scripts.backfill_jd_structured

    # real run
    python -m backend.scripts.backfill_jd_structured --apply

    # cautious real run
    python -m backend.scripts.backfill_jd_structured --apply --limit 5 --batch-size 2
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path

# Allow `python backend/scripts/backfill_jd_structured.py` as well as -m.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from sqlalchemy import text

from backend.core.database import ENGINE
from backend.repositories import job_repository as job_store
from backend.services.jd_structure_service import structure_jd

logger = logging.getLogger("backfill_jd_structured")

# structure_jd() itself refuses anything under 200 chars (both before and after
# its nuclear cleaner). Filtering at the same threshold in SQL means those rows
# are reported as skipped up front rather than each burning a function call to
# be rejected — same outcome, honest accounting.
_MIN_JD_CHARS = 200

_DEFAULT_BATCH_SIZE = 5
_DEFAULT_SLEEP_SECONDS = 2.0


@dataclass
class BackfillStats:
    selected:      int = 0
    structured:    int = 0
    write_failed:  int = 0
    llm_failed:    int = 0
    failures:      list[tuple[str, str]] = field(default_factory=list)   # (posting_id, reason)

    def log_summary(self, *, applied: bool) -> None:
        mode = "APPLIED" if applied else "DRY RUN (nothing written)"
        logger.info("─" * 62)
        logger.info("Backfill complete — %s", mode)
        logger.info("  selected      : %d", self.selected)
        logger.info("  structured    : %d", self.structured)
        logger.info("  LLM failed    : %d", self.llm_failed)
        logger.info("  write failed  : %d", self.write_failed)
        if self.failures:
            logger.info("  failure detail:")
            for posting_id, reason in self.failures:
                logger.info("    %s  %s", posting_id, reason)
        logger.info("─" * 62)


def select_targets(limit: int | None, include_closed: bool, min_chars: int) -> list[dict]:
    """
    Postings needing a backfill: jd_structured IS NULL and enough jd_text to
    structure. Ordered longest-JD-first so that if a run is cut short by
    --limit or an outage, the richest postings are the ones that got done.

    Closed postings are excluded by default — spending LLM calls to improve the
    rendering of a job nobody can apply to is waste, not thoroughness.
    """
    where = ["jd_structured IS NULL", "coalesce(length(jd_text), 0) >= :min_chars"]
    params: dict = {"min_chars": min_chars}
    if not include_closed:
        where.append("is_open IS TRUE")

    sql = f"""
        SELECT id, title, company, coalesce(length(jd_text), 0) AS jd_len, jd_text
        FROM public.job_postings
        WHERE {' AND '.join(where)}
        ORDER BY jd_len DESC
    """
    if limit is not None:
        sql += " LIMIT :limit"
        params["limit"] = limit

    with ENGINE.connect() as conn:
        rows = conn.execute(text(sql), params).fetchall()

    return [
        {"id": str(r.id), "title": r.title, "company": r.company,
         "jd_len": r.jd_len, "jd_text": r.jd_text}
        for r in rows
    ]


def report_skipped(min_chars: int, include_closed: bool) -> None:
    """
    Explain the rows that are NULL but were NOT selected, so a run that leaves
    NULLs behind doesn't look like a silent partial failure. A row with no JD
    text isn't a backfill failure — there is genuinely nothing to structure,
    and it needs jd_backfill_service to fetch the text first.
    """
    where = ["jd_structured IS NULL", "coalesce(length(jd_text), 0) < :min_chars"]
    if not include_closed:
        where.append("is_open IS TRUE")

    with ENGINE.connect() as conn:
        rows = conn.execute(text(f"""
            SELECT id, title, coalesce(length(jd_text), 0) AS jd_len
            FROM public.job_postings WHERE {' AND '.join(where)}
            ORDER BY jd_len DESC
        """), {"min_chars": min_chars}).fetchall()

    if not rows:
        return
    logger.info(
        "%d NULL row(s) skipped — jd_text under %d chars, nothing to structure. "
        "These need jd_backfill_service to fetch the JD text first:",
        len(rows), min_chars,
    )
    for r in rows:
        logger.info("   skip  %s  jd_len=%-5d  %s", r.id, r.jd_len, (r.title or "")[:44])


async def process_row(row: dict, *, apply: bool, stats: BackfillStats) -> None:
    """
    Structure and persist one posting.

    Every failure mode is contained here: one malformed JD, one LLM timeout, or
    one bad write must never abort the batch or the run. Both the LLM call and
    the DB write are guarded, because they fail for entirely different reasons
    and conflating them makes the summary useless for deciding what to retry.
    """
    posting_id = row["id"]
    label = f"{(row['title'] or '?')[:40]} @ {(row['company'] or '?')[:24]}"

    if not apply:
        logger.info("   [dry-run] would structure %s  jd_len=%-5d  %s",
                    posting_id, row["jd_len"], label)
        return

    try:
        structured = await structure_jd(row["jd_text"], job_id=posting_id)
    except Exception as exc:
        stats.llm_failed += 1
        stats.failures.append((posting_id, f"structure_jd raised {type(exc).__name__}: {exc}"))
        logger.warning("   FAIL  %s  structure_jd raised %s: %s", posting_id, type(exc).__name__, exc)
        return

    if not structured:
        # structure_jd returns None on its own guards (too short after cleaning)
        # and on schema-validation failure. It logs the reason itself; it is
        # explicitly documented as non-retryable, so this is terminal, not a
        # candidate for a retry loop.
        stats.llm_failed += 1
        stats.failures.append((posting_id, "structure_jd returned None (see its log line above)"))
        logger.warning("   FAIL  %s  structure_jd returned None — %s", posting_id, label)
        return

    try:
        written = job_store.update_jd_structured_by_posting_id(posting_id, structured)
    except Exception as exc:
        stats.write_failed += 1
        stats.failures.append((posting_id, f"write raised {type(exc).__name__}: {exc}"))
        logger.warning("   FAIL  %s  write raised %s: %s", posting_id, type(exc).__name__, exc)
        return

    if not written:
        stats.write_failed += 1
        stats.failures.append((posting_id, "UPDATE matched 0 rows (posting deleted mid-run?)"))
        logger.warning("   FAIL  %s  UPDATE matched 0 rows", posting_id)
        return

    stats.structured += 1
    logger.info("   OK    %s  %s", posting_id, label)


async def run(
    *,
    apply: bool,
    limit: int | None,
    batch_size: int,
    sleep_seconds: float,
    include_closed: bool,
    min_chars: int,
) -> BackfillStats:
    stats = BackfillStats()
    targets = select_targets(limit, include_closed, min_chars)
    stats.selected = len(targets)

    logger.info("Selected %d posting(s) with jd_structured IS NULL and jd_text >= %d chars%s.",
                stats.selected, min_chars, "" if include_closed else " (open only)")
    report_skipped(min_chars, include_closed)

    if not targets:
        logger.info("Nothing to do.")
        return stats

    if not apply:
        logger.info("DRY RUN — no LLM calls, no writes. Re-run with --apply to execute.")

    batches = [targets[i:i + batch_size] for i in range(0, len(targets), batch_size)]
    for index, batch in enumerate(batches, start=1):
        logger.info("Batch %d/%d (%d row(s))", index, len(batches), len(batch))
        # Sequential within a batch: these are LLM calls against a shared rate
        # limit, and the batch boundary is where the pause happens. Firing a
        # batch concurrently would defeat the point of batching at all.
        for row in batch:
            await process_row(row, apply=apply, stats=stats)

        if apply and index < len(batches) and sleep_seconds > 0:
            logger.info("   … sleeping %.1fs before next batch", sleep_seconds)
            await asyncio.sleep(sleep_seconds)

    stats.log_summary(applied=apply)
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Backfill job_postings.jd_structured using jd_structure_service.",
    )
    parser.add_argument("--apply", action="store_true",
                        help="Actually call the LLM and write. Without this the script "
                             "is a dry run: no LLM calls, no writes.")
    parser.add_argument("--limit", type=int, default=None,
                        help="Max postings to process (longest JD first).")
    parser.add_argument("--batch-size", type=int, default=_DEFAULT_BATCH_SIZE,
                        help=f"Rows per batch (default {_DEFAULT_BATCH_SIZE}).")
    parser.add_argument("--sleep", type=float, default=_DEFAULT_SLEEP_SECONDS,
                        help=f"Seconds to pause between batches (default {_DEFAULT_SLEEP_SECONDS}).")
    parser.add_argument("--include-closed", action="store_true",
                        help="Also process postings with is_open = false.")
    parser.add_argument("--min-chars", type=int, default=_MIN_JD_CHARS,
                        help=f"Minimum jd_text length to attempt (default {_MIN_JD_CHARS}; "
                             f"structure_jd rejects anything shorter anyway).")
    args = parser.parse_args()

    if args.batch_size < 1:
        parser.error("--batch-size must be >= 1")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        force=True,
    )

    stats = asyncio.run(run(
        apply          = args.apply,
        limit          = args.limit,
        batch_size     = args.batch_size,
        sleep_seconds  = args.sleep,
        include_closed = args.include_closed,
        min_chars      = args.min_chars,
    ))

    # Non-zero exit when an applied run had failures, so this is usable from a
    # scheduler without someone having to read the log to notice.
    if args.apply and (stats.llm_failed or stats.write_failed):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
