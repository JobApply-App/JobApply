"""
Manual backfill: upserts an existing LinkedIn scraper CSV (backend/scripts/
linkedin_israel_jobs.py's old --out format) into `public.all_jobs`.

The live scrape path no longer goes through this script or any CSV at all
— backend/scripts/linkedin_israel_jobs.py now calls
backend/repositories/all_jobs_repository.py's bulk_upsert_all_jobs()
directly with its in-memory scraped rows, writing straight to Supabase.
This script exists only for backfilling `all_jobs` from a CSV you already
have on disk (e.g. one produced before this change, or a one-off import).

Same two-step network/write safety gate as linkedin_israel_jobs.py and
migrate_jobs_db_to_supabase.py: refuses to write unless BOTH --allow-write
and ALLOW_SUPABASE_APP_MIGRATION=true are set. Never makes a network call to
LinkedIn itself — reads a CSV file already on disk.

Usage
-----
    # Preview only (no Postgres connection):
    python -m backend.scripts.upsert_linkedin_csv_to_all_jobs --csv path/to/jobs.csv

    # Real upsert:
    ALLOW_SUPABASE_APP_MIGRATION=true python -m backend.scripts.upsert_linkedin_csv_to_all_jobs \\
        --csv path/to/jobs.csv --allow-write
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from backend.repositories.all_jobs_repository import (  # noqa: E402
    build_all_jobs_record,
    bulk_upsert_all_jobs,
)


def _guard_write(args: argparse.Namespace) -> None:
    env_allowed = os.environ.get("ALLOW_SUPABASE_APP_MIGRATION", "").strip().lower() in ("1", "true", "yes")
    cli_allowed = bool(getattr(args, "allow_write", False))
    if not (cli_allowed and env_allowed):
        print(
            "[GUARD] Refusing to write to Postgres: requires BOTH --allow-write "
            "AND ALLOW_SUPABASE_APP_MIGRATION=true in the environment. Omit "
            "--allow-write to run the safe preview instead.",
            file=sys.stderr,
        )
        sys.exit(1)


def _read_csv(path: str) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def run_preview(csv_path: str) -> None:
    rows = _read_csv(csv_path)
    print(f"[preview] {csv_path}: {len(rows)} row(s) — no Postgres connection made.")
    seen_keys = {build_all_jobs_record(r)["canonical_job_key"] for r in rows}
    print(f"[preview] {len(seen_keys)} distinct canonical_job_key value(s) among {len(rows)} row(s).")
    print("[preview] Run with --allow-write (+ ALLOW_SUPABASE_APP_MIGRATION=true) to actually upsert.")


def main():
    parser = argparse.ArgumentParser(description="Backfill public.all_jobs from an existing LinkedIn scraper CSV.")
    parser.add_argument("--csv", required=True, help="Path to a CSV in linkedin_israel_jobs.py's old --out format")
    parser.add_argument("--allow-write", action="store_true",
                         help="Required (together with ALLOW_SUPABASE_APP_MIGRATION=true) to actually write.")
    parser.add_argument("--batch-size", type=int, default=200)
    args = parser.parse_args()

    if not args.allow_write:
        run_preview(args.csv)
        return

    _guard_write(args)
    rows = _read_csv(args.csv)
    stats = bulk_upsert_all_jobs(rows, batch_size=args.batch_size)
    print(f"[upsert] {args.csv}: received={stats.received} skipped_dupes={stats.skipped_dupes} "
          f"inserted={stats.inserted} updated={stats.updated}")


if __name__ == "__main__":
    main()
