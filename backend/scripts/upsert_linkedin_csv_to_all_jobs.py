"""
Upserts a LinkedIn scraper CSV (backend/scripts/linkedin_israel_jobs.py's
--out format) into the canonical `public.all_jobs` table
(backend/alembic_app_schema/versions/9f25d77ed964_create_all_jobs_table.py).

Separate from the linkedin.jobs dual-persistence already built into
linkedin_israel_jobs.py itself — this script is the second, independent
write target for the SAME single scrape run's CSV, so a live scrape never
needs to run more than once to populate both `linkedin.jobs` (raw, verbatim
LinkedIn shape) and `all_jobs` (canonical, cross-provider shape).

Reuses backend/services/linkedin_job_normalize.py's build_normalized_job()/
extract_linkedin_job_id()/normalize_url() — the exact same normalization
already tested against linkedin.jobs — so a job's canonical_job_key here is
derived identically to its linkedin_job_id/job_url_normalized there.

Identity / dedup: canonical_job_key = extracted LinkedIn numeric job id when
available, else normalized_job_url (same two-tier fallback as
backend/models/linkedin_job.py). Upsert target: UNIQUE(source, canonical_job_key).

Idempotent upsert semantics (matches the task spec exactly):
  - New job      -> insert; first_seen_at/insertion_time/created_at = now(),
                    last_seen_at/last_scraped_at/updated_at = now() too.
  - Existing job -> only last_seen_at/last_scraped_at/updated_at and the
                    mutable job fields + raw_payload move; first_seen_at/
                    insertion_time/created_at are NEVER touched on conflict.

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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from sqlalchemy import text  # noqa: E402
from sqlalchemy.dialects.postgresql import insert as pg_insert  # noqa: E402
from sqlalchemy import MetaData, Table  # noqa: E402

from backend.core.postgres import get_pg_session  # noqa: E402
from backend.services.linkedin_job_normalize import (  # noqa: E402
    build_normalized_job,
    extract_linkedin_job_id,
    normalize_url,
    normalize_list_field,
)

_ALL_JOBS_COLUMNS = (
    "source", "source_job_id", "canonical_job_key",
    "job_title", "company_name", "company_url", "company_logo_url",
    "job_url", "normalized_job_url", "location", "seniority_level",
    "employment_type", "job_function", "industries", "description",
    "posted_text", "exact_posted_text", "applicants_text", "raw_payload",
)

# Never updated once a row exists — these are set only at insert time.
_NEVER_UPDATED = {"canonical_job_key", "source", "source_job_id",
                  "first_seen_at", "insertion_time", "created_at"}


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


def _build_all_jobs_record(raw_row: dict) -> dict[str, Any]:
    """CSV row (JobListing field names) -> a public.all_jobs-shaped record."""
    normalized = build_normalized_job(raw_row)
    linkedin_job_id = normalized["linkedin_job_id"]
    normalized_url = normalized["job_url_normalized"]
    canonical_job_key = linkedin_job_id or normalized_url

    return {
        "source": "linkedin",
        "source_job_id": linkedin_job_id,
        "canonical_job_key": canonical_job_key,
        "job_title": normalized["title"],
        "company_name": normalized["company"],
        "company_url": normalized["company_url"],
        "company_logo_url": normalized["company_logo_url"],
        "job_url": normalized["job_url"],
        "normalized_job_url": normalized_url,
        "location": normalized["location"],
        "seniority_level": normalized["seniority_level"],
        "employment_type": normalized["employment_type"],
        "job_function": normalized["job_function"],
        "industries": normalize_list_field(raw_row.get("industries")),
        "description": normalized["description"],
        "posted_text": normalized["posted_text"],
        "exact_posted_text": normalized["exact_posted_text"],
        "applicants_text": normalized["applicants_text"],
        # Pass the raw dict, NOT a pre-dumped JSON string — this record is
        # inserted via a reflected Table object (see run_upsert), whose
        # JSONB column type serializes Python objects itself. Handing it an
        # already-serialized string would double-encode it (a JSON string
        # containing escaped JSON, not a JSON object).
        "raw_payload": raw_row,
    }


def _read_csv(path: str) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def run_preview(csv_path: str) -> None:
    rows = _read_csv(csv_path)
    print(f"[preview] {csv_path}: {len(rows)} row(s) — no Postgres connection made.")
    seen_keys = set()
    for r in rows:
        rec = _build_all_jobs_record(r)
        seen_keys.add(rec["canonical_job_key"])
    print(f"[preview] {len(seen_keys)} distinct canonical_job_key value(s) among {len(rows)} row(s).")
    print("[preview] Run with --allow-write (+ ALLOW_SUPABASE_APP_MIGRATION=true) to actually upsert.")


def run_upsert(csv_path: str, batch_size: int = 200) -> dict[str, int]:
    rows = _read_csv(csv_path)
    if not rows:
        print(f"[upsert] {csv_path}: no rows found.")
        return {"received": 0, "inserted": 0, "updated": 0}

    now = datetime.now(timezone.utc)
    records = []
    for r in rows:
        rec = _build_all_jobs_record(r)
        rec["last_scraped_at"] = now
        records.append(rec)

    # De-dupe within this one CSV by canonical_job_key (last occurrence wins)
    # — Postgres rejects two rows in the same statement targeting the same
    # ON CONFLICT key (same reasoning as linkedin_job_repository.py).
    by_key: dict[str, dict] = {}
    for r in records:
        by_key[r["canonical_job_key"]] = r
    deduped = list(by_key.values())
    skipped = len(records) - len(deduped)

    inserted = updated = 0
    with get_pg_session() as session:
        metadata = MetaData()
        table = Table("all_jobs", metadata, autoload_with=session.get_bind(), schema="public")
        excluded_cols = {c: getattr(pg_insert(table).excluded, c) for c in _ALL_JOBS_COLUMNS + ("last_scraped_at",)}

        for i in range(0, len(deduped), batch_size):
            batch = deduped[i: i + batch_size]
            stmt = pg_insert(table).values(batch)
            set_ = {
                col: excluded_cols[col]
                for col in _ALL_JOBS_COLUMNS + ("last_scraped_at",)
                if col not in _NEVER_UPDATED
            }
            set_["last_seen_at"] = text("now()")
            set_["updated_at"] = text("now()")
            stmt = stmt.on_conflict_do_update(
                index_elements=["source", "canonical_job_key"],
                set_=set_,
            ).returning(text("(xmax = 0) AS was_insert"))
            result = session.execute(stmt)
            for row in result:
                if row[0]:
                    inserted += 1
                else:
                    updated += 1
        session.commit()

    print(f"[upsert] {csv_path}: received={len(records)} skipped_dupes={skipped} "
          f"inserted={inserted} updated={updated}")
    return {"received": len(records), "inserted": inserted, "updated": updated, "skipped": skipped}


def main():
    parser = argparse.ArgumentParser(description="Upsert a LinkedIn scraper CSV into public.all_jobs.")
    parser.add_argument("--csv", required=True, help="Path to the CSV produced by linkedin_israel_jobs.py")
    parser.add_argument("--allow-write", action="store_true",
                         help="Required (together with ALLOW_SUPABASE_APP_MIGRATION=true) to actually write.")
    parser.add_argument("--batch-size", type=int, default=200)
    args = parser.parse_args()

    if not args.allow_write:
        run_preview(args.csv)
        return

    _guard_write(args)
    run_upsert(args.csv, batch_size=args.batch_size)


if __name__ == "__main__":
    main()
