"""
Repository for `public.all_jobs` (backend/models/all_jobs.py) — both the
read side (get_paginated_all_jobs, for GET /api/all-jobs) and the write
side (bulk_upsert_all_jobs). Callers pass in-memory records (e.g.
backend/scripts/linkedin_israel_jobs.py's scraped JobListing dicts, or
backend/scripts/upsert_linkedin_csv_to_all_jobs.py's CSV rows for manual
backfill) — this module never touches a file itself, so a live scrape can
write straight to Supabase with no CSV round-trip in between.

Pagination mirrors backend/repositories/linkedin_job_repository.py's
get_paginated_jobs() — single-query COUNT(*) OVER() alongside the page's
own rows, falling back to a second, plain COUNT(*) only when the requested
page returns zero rows. The upsert mirrors that same module's
bulk_upsert_jobs() — one INSERT ... ON CONFLICT DO UPDATE per batch.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import MetaData, Table, func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from backend.core.postgres import get_pg_session
from backend.models.all_jobs import AllJobRow
from backend.services.linkedin_job_normalize import (
    build_normalized_job,
    normalize_list_field,
)

_TABLE = AllJobRow.__table__

DEFAULT_PAGE_SIZE = 25
MAX_PAGE_SIZE = 100

# ── Write side ────────────────────────────────────────────────────────────────

_WRITABLE_COLUMNS = (
    "source", "source_job_id", "canonical_job_key",
    "job_title", "company_name", "company_url", "company_logo_url",
    "job_url", "normalized_job_url", "location", "seniority_level",
    "employment_type", "job_function", "industries", "description",
    "posted_text", "exact_posted_text", "applicants_text", "raw_payload",
    "last_scraped_at",
)

# Never updated once a row exists — set only at insert time.
_NEVER_UPDATED = {"canonical_job_key", "source", "source_job_id",
                  "first_seen_at", "insertion_time", "created_at"}


@dataclass
class AllJobsUpsertStats:
    received: int = 0
    skipped_dupes: int = 0
    inserted: int = 0
    updated: int = 0


def build_all_jobs_record(raw_row: dict, *, source: str = "linkedin") -> dict[str, Any]:
    """
    A provider's raw scraped-job dict (currently only LinkedIn's JobListing
    shape — see backend/services/linkedin_job_normalize.py's
    build_normalized_job()) -> a public.all_jobs-shaped record. Reuses the
    exact same normalization already tested against `linkedin.jobs`, so a
    job's canonical_job_key here is derived identically to its
    linkedin_job_id/job_url_normalized there.

    Identity/dedup: canonical_job_key = extracted provider job id when
    available, else normalized_job_url — same two-tier fallback as
    backend/models/linkedin_job.py. Upsert target: UNIQUE(source, canonical_job_key).
    """
    normalized = build_normalized_job(raw_row)
    provider_job_id = normalized["linkedin_job_id"]
    normalized_url = normalized["job_url_normalized"]
    canonical_job_key = provider_job_id or normalized_url

    return {
        "source": source,
        "source_job_id": provider_job_id,
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
        # Raw dict, NOT a pre-dumped JSON string — inserted via a reflected
        # Table object whose JSONB column type serializes Python objects
        # itself; handing it an already-serialized string would double-encode it.
        "raw_payload": raw_row,
    }


def bulk_upsert_all_jobs(
    raw_rows: list[dict],
    *,
    source: str = "linkedin",
    batch_size: int = 200,
    session: Optional[Session] = None,
) -> AllJobsUpsertStats:
    """
    Normalizes and upserts a batch of raw provider rows into `all_jobs` in
    one INSERT ... ON CONFLICT DO UPDATE per batch.

    Idempotent semantics:
      - New job      -> insert; first_seen_at/insertion_time/created_at = now(),
                        last_seen_at/last_scraped_at/updated_at = now() too
                        (server-side defaults handle the former three; this
                        function only ever sets the latter three explicitly).
      - Existing job -> only last_seen_at/updated_at/last_scraped_at and the
                        mutable job fields + raw_payload move; first_seen_at/
                        insertion_time/created_at are NEVER touched.
    """
    stats = AllJobsUpsertStats(received=len(raw_rows))
    if not raw_rows:
        return stats

    now = datetime.now(timezone.utc)
    records = []
    for raw in raw_rows:
        rec = build_all_jobs_record(raw, source=source)
        rec["last_scraped_at"] = now
        records.append(rec)

    # De-dupe within this one batch by canonical_job_key (last occurrence
    # wins) — Postgres rejects two rows in the same statement targeting the
    # same ON CONFLICT key ("cannot affect row a second time").
    by_key: dict[str, dict] = {}
    for r in records:
        by_key[r["canonical_job_key"]] = r
    deduped = list(by_key.values())
    stats.skipped_dupes = len(records) - len(deduped)

    owns_session = session is None
    session = session or get_pg_session()
    try:
        metadata = MetaData()
        table = Table("all_jobs", metadata, autoload_with=session.get_bind(), schema="public")
        excluded = pg_insert(table).excluded
        excluded_cols = {c: getattr(excluded, c) for c in _WRITABLE_COLUMNS}

        for i in range(0, len(deduped), batch_size):
            batch = deduped[i: i + batch_size]
            stmt = pg_insert(table).values(batch)
            set_ = {col: excluded_cols[col] for col in _WRITABLE_COLUMNS if col not in _NEVER_UPDATED}
            set_["last_seen_at"] = text("now()")
            set_["updated_at"] = text("now()")
            stmt = stmt.on_conflict_do_update(
                index_elements=["source", "canonical_job_key"],
                set_=set_,
            ).returning(text("(xmax = 0) AS was_insert"))
            result = session.execute(stmt)
            for row in result:
                if row[0]:
                    stats.inserted += 1
                else:
                    stats.updated += 1
        session.commit()
    finally:
        if owns_session:
            session.close()

    return stats


# ── Read side ─────────────────────────────────────────────────────────────────

# List-view columns only — excludes `description` (large text, never shown
# in a list row) and `raw_payload` (internal, not displayed), same
# convention as linkedin_job_repository.py's _LIST_VIEW_COLUMNS.
_LIST_VIEW_COLUMNS = (
    "id", "source", "source_job_id", "canonical_job_key",
    "job_title", "company_name", "company_url", "company_logo_url",
    "job_url", "normalized_job_url", "location", "seniority_level",
    "employment_type", "job_function", "industries",
    "posted_text", "exact_posted_text", "applicants_text",
    "is_active", "first_seen_at", "last_seen_at", "insertion_time",
    "updated_at", "last_scraped_at",
)


@dataclass
class PaginatedAllJobs:
    items: list[dict]
    total_items: int


def get_paginated_all_jobs(
    *,
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
    session: Optional[Session] = None,
) -> PaginatedAllJobs:
    """
    Ordered `last_seen_at DESC, id DESC` — the former rides the existing
    ix_all_jobs_last_seen_at_desc index (most-recently-seen job first, so a
    fresh scrape run surfaces at the top); `id` (the primary key) is the
    mandatory tie-breaker so two rows re-touched in the same batch upsert
    (identical last_seen_at) never reorder between page 1 and page 2.

    page/page_size are trusted to already be validated by the caller (see
    backend/api/routes/all_jobs.py's Query(...) constraints) but are still
    clamped defensively here for any direct/non-HTTP caller.
    """
    page = max(page, 1)
    page_size = min(max(page_size, 1), MAX_PAGE_SIZE)
    offset = (page - 1) * page_size

    columns = [_TABLE.c[name] for name in _LIST_VIEW_COLUMNS]
    total_count_col = func.count().over().label("total_count")

    stmt = (
        select(*columns, total_count_col)
        .order_by(_TABLE.c.last_seen_at.desc(), _TABLE.c.id.desc())
        .limit(page_size)
        .offset(offset)
    )

    owns_session = session is None
    session = session or get_pg_session()
    try:
        rows = session.execute(stmt).all()
        if rows:
            total_items = rows[0].total_count
            items = [
                {col: getattr(row, col) for col in _LIST_VIEW_COLUMNS}
                for row in rows
            ]
        else:
            total_items = session.execute(
                select(func.count()).select_from(_TABLE)
            ).scalar_one()
            items = []
    finally:
        if owns_session:
            session.close()

    return PaginatedAllJobs(items=items, total_items=total_items)
