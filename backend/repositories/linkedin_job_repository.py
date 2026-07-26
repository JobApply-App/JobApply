"""
Bulk upsert repository for backend/models/linkedin_job.py (`linkedin.jobs`).

Function-based, takes an optional trailing `session: Optional[Session] = None`
— same convention as backend/repositories/job_repository.py and
kv_repository.py — except the default session factory is
backend.core.postgres.get_pg_session() (the dedicated Postgres engine), not
Session(ENGINE) (the app's SQLite engine); this table lives nowhere else.

Upsert semantics (see linkedin_israel_jobs.py's CLI docstring for the full
spec this implements):
  - New job            -> insert; insertion_time/first_seen_at/last_seen_at/
                          scraped_at/updated_at all = now (scraped_at = the
                          run's scraped_at).
  - Existing, same hash -> only last_seen_at/scraped_at move; insertion_time,
                          first_seen_at, updated_at, and every business field
                          stay exactly as they were.
  - Existing, new hash  -> business fields + data_hash + updated_at + last_seen_at
                          + scraped_at all move; insertion_time/first_seen_at
                          stay exactly as they were.

Implemented as ONE `INSERT ... ON CONFLICT DO UPDATE` per batch (per
conflict-target partition — see _split_by_conflict_target()), with the
same/changed-hash branching expressed as SQL `CASE` expressions evaluated
against the *server-side* current row at conflict time (`jobs.data_hash` vs
`excluded.data_hash`) — not decided in Python beforehand — so it's race-safe
under concurrent writers and touches the DB exactly once per batch, no
per-row SELECT/INSERT (no N+1). A single bulk SELECT of existing hashes
*is* still done, but only to produce accurate inserted/updated/unchanged
*statistics* to return to the caller — it plays no role in the upsert's
correctness, which is entirely enforced by the CASE expressions below.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import case, func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from backend.core.postgres import get_pg_session
from backend.models.linkedin_job import LinkedInJobRow

logger = logging.getLogger(__name__)

_TABLE = LinkedInJobRow.__table__

# Columns that must NEVER be touched by an ON CONFLICT DO UPDATE — set only
# at insert time. Deliberately excluded from every SET clause below, not
# just left out "by omission" — see the module docstring's upsert semantics.
_NEVER_UPDATED = {"id", "insertion_time", "first_seen_at"}

# Business fields whose SET expression is conditional on data_hash having
# changed (see _conditional_set_clauses()). Everything else in the table is
# handled explicitly (timestamps, data_hash, linkedin_job_id/job_url_normalized
# — the latter two are part of the conflict target itself so re-asserting
# them is harmless and keeps the statement simple).
_CONDITIONAL_FIELDS = (
    "title", "company", "location", "posted_text", "job_url", "company_url",
    "description", "exact_posted_text", "applicants_text", "seniority_level",
    "employment_type", "job_function", "industries", "company_logo_url",
    "linkedin_status", "is_active", "linkedin_job_id", "job_url_normalized",
    "data_hash",
)

DEFAULT_BATCH_SIZE = 200

# GET /api/linkedin/jobs pagination defaults/cap — see get_paginated_jobs().
DEFAULT_PAGE_SIZE = 25
MAX_PAGE_SIZE = 100

# List-view columns only — deliberately excludes `description` (large text,
# never shown in a list row per the route's spec), `company_url`/`data_hash`
# (internal, not displayed), and `scraped_at` (not part of the requested
# display fields). Selecting exactly these columns (not `select(_TABLE)`)
# keeps the list query itself cheap, not just the Python-side response.
_LIST_VIEW_COLUMNS = (
    "id", "linkedin_job_id", "title", "company", "location", "job_url",
    "posted_text", "exact_posted_text", "applicants_text", "seniority_level",
    "employment_type", "job_function", "industries", "company_logo_url",
    "linkedin_status", "is_active", "insertion_time", "first_seen_at",
    "last_seen_at", "updated_at",
)


@dataclass
class UpsertStats:
    jobs_received: int = 0
    jobs_normalized: int = 0
    jobs_inserted: int = 0
    jobs_updated: int = 0
    jobs_unchanged: int = 0
    jobs_skipped: int = 0
    jobs_invalid: int = 0
    active_jobs: int = 0
    inactive_jobs: int = 0
    unknown_status_jobs: int = 0
    database_failures: int = 0

    def __iadd__(self, other: "UpsertStats") -> "UpsertStats":
        for f in self.__dataclass_fields__:
            setattr(self, f, getattr(self, f) + getattr(other, f))
        return self


def _conditional_set_clauses(excluded) -> dict[str, Any]:
    """
    One SET clause per business field: keep the existing value if
    data_hash is unchanged, else take the newly-submitted value. Expressed
    with the table's own `data_hash` column compared against
    `excluded.data_hash` (the row Postgres would insert) — this is
    evaluated server-side, per conflicting row, at statement execution
    time, not decided in Python beforehand.
    """
    unchanged = _TABLE.c.data_hash == excluded.data_hash
    return {
        field: case((unchanged, _TABLE.c[field]), else_=getattr(excluded, field))
        for field in _CONDITIONAL_FIELDS
    }


def _build_upsert_stmt(rows: list[dict], *, index_elements: list[str], index_where=None):
    stmt = pg_insert(_TABLE).values(rows)
    excluded = stmt.excluded

    set_ = _conditional_set_clauses(excluded)
    # Always move forward regardless of whether content changed — this is
    # exactly what tells us "still present in the latest sample".
    set_["last_seen_at"] = excluded.last_seen_at
    set_["scraped_at"] = excluded.scraped_at
    unchanged = _TABLE.c.data_hash == excluded.data_hash
    set_["updated_at"] = case((unchanged, _TABLE.c.updated_at), else_=excluded.updated_at)
    assert not (_NEVER_UPDATED & set_.keys()), "insertion_time/first_seen_at/id must never be in SET"

    kwargs: dict[str, Any] = {"index_elements": index_elements, "set_": set_}
    if index_where is not None:
        kwargs["index_where"] = index_where

    return stmt.on_conflict_do_update(**kwargs).returning(
        _TABLE.c.linkedin_job_id, _TABLE.c.job_url_normalized, _TABLE.c.data_hash,
        text("(xmax = 0) AS was_insert"),
    )


def _split_by_conflict_target(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    """linkedin_job_id present -> conflict on that partial unique index;
    absent (rare — see linkedin_job_normalize.extract_linkedin_job_id) ->
    conflict on the always-present job_url_normalized unique index. Postgres
    requires one fixed conflict target per statement, so rows needing
    different targets can't share a single INSERT."""
    with_id = [r for r in rows if r.get("linkedin_job_id")]
    without_id = [r for r in rows if not r.get("linkedin_job_id")]
    return with_id, without_id


def _existing_hashes(session: Session, rows: list[dict]) -> dict[str, str]:
    """
    One bulk SELECT for the whole batch (not per row — see module
    docstring) to classify inserted/updated/unchanged for the returned
    stats. Keyed by whichever business key each row actually has.
    """
    ids = [r["linkedin_job_id"] for r in rows if r.get("linkedin_job_id")]
    urls = [r["job_url_normalized"] for r in rows if not r.get("linkedin_job_id")]

    existing: dict[str, str] = {}
    if ids:
        q = select(_TABLE.c.linkedin_job_id, _TABLE.c.data_hash).where(
            _TABLE.c.linkedin_job_id.in_(ids)
        )
        existing.update({row.linkedin_job_id: row.data_hash for row in session.execute(q)})
    if urls:
        q = select(_TABLE.c.job_url_normalized, _TABLE.c.data_hash).where(
            _TABLE.c.job_url_normalized.in_(urls)
        )
        existing.update({row.job_url_normalized: row.data_hash for row in session.execute(q)})
    return existing


def _classify(rows: list[dict], existing_hashes: dict[str, str]) -> tuple[int, int, int]:
    inserted = updated = unchanged = 0
    for r in rows:
        key = r.get("linkedin_job_id") or r["job_url_normalized"]
        prior_hash = existing_hashes.get(key)
        if prior_hash is None:
            inserted += 1
        elif prior_hash == r["data_hash"]:
            unchanged += 1
        else:
            updated += 1
    return inserted, updated, unchanged


def _upsert_batch(session: Session, rows: list[dict]) -> tuple[int, int, int]:
    """One batch -> at most two INSERT statements (with/without linkedin_job_id
    conflict target). Returns (inserted, updated, unchanged) for this batch."""
    if not rows:
        return 0, 0, 0

    existing_hashes = _existing_hashes(session, rows)
    inserted = updated = unchanged = 0

    with_id, without_id = _split_by_conflict_target(rows)

    if with_id:
        stmt = _build_upsert_stmt(
            with_id,
            index_elements=["linkedin_job_id"],
            index_where=text("linkedin_job_id IS NOT NULL"),
        )
        session.execute(stmt)
        i, u, n = _classify(with_id, existing_hashes)
        inserted += i; updated += u; unchanged += n

    if without_id:
        stmt = _build_upsert_stmt(without_id, index_elements=["job_url_normalized"])
        session.execute(stmt)
        i, u, n = _classify(without_id, existing_hashes)
        inserted += i; updated += u; unchanged += n

    return inserted, updated, unchanged


def _dedupe_by_business_key(records: list[dict]) -> tuple[list[dict], int]:
    """
    Postgres rejects `ON CONFLICT DO UPDATE` outright if two rows in the
    *same* INSERT statement target the same conflict key
    ("CardinalityViolation: ON CONFLICT DO UPDATE command cannot affect row
    a second time") — confirmed experimentally. A single scrape/import run
    could plausibly observe the same job twice (e.g. pagination overlap),
    so collapse same-business-key rows to the last occurrence before they
    ever reach a batch, rather than letting it surface as a batch failure.
    Returns (deduped, skipped_count).
    """
    by_key: dict[str, dict] = {}
    for r in records:
        key = r.get("linkedin_job_id") or r["job_url_normalized"]
        by_key[key] = r  # last occurrence wins
    return list(by_key.values()), len(records) - len(by_key)


def bulk_upsert_jobs(
    records: list[dict],
    *,
    batch_size: int = DEFAULT_BATCH_SIZE,
    session: Optional[Session] = None,
) -> UpsertStats:
    """
    records: fully-normalized dicts, one per job, each already containing
    linkedin_job_id/job_url_normalized/industries/linkedin_status/is_active
    (backend.services.linkedin_job_normalize.build_normalized_job()),
    data_hash (compute_data_hash()), and scraped_at (a datetime — the
    caller decides the run's scrape timestamp; see linkedin_israel_jobs.py).

    Rolls back a batch's transaction on database failure (no partial-batch
    commits) and moves on to the next batch rather than aborting the whole
    run — recorded in stats.database_failures so the caller can tell
    partial failure from full success.
    """
    stats = UpsertStats(jobs_received=len(records))
    records, skipped = _dedupe_by_business_key(records)
    stats.jobs_skipped += skipped
    owns_session = session is None
    session = session or get_pg_session()

    try:
        now = datetime.now(timezone.utc)
        for i in range(0, len(records), batch_size):
            chunk = records[i : i + batch_size]

            # Raw Core insert (not the ORM) needs an explicit id/first_seen_at/
            # insertion_time/updated_at/last_seen_at for NEW rows — the
            # ON CONFLICT DO UPDATE SET clauses above override every one of
            # these for a row that already exists (id and first_seen_at are
            # never in the SET clause at all; insertion_time likewise;
            # updated_at/last_seen_at are conditionally/unconditionally
            # overridden — see _build_upsert_stmt), so supplying "as if new"
            # values here is always safe regardless of insert-vs-update.
            prepared = []
            for r in chunk:
                row = dict(r)
                row["id"] = uuid.uuid4()
                row["first_seen_at"] = now
                row["insertion_time"] = now
                row["updated_at"] = now
                row["last_seen_at"] = now
                # scraped_at comes from the caller per-record; default to now
                # if somehow missing rather than raising mid-batch.
                row.setdefault("scraped_at", now)
                prepared.append(row)

            try:
                inserted, updated, unchanged = _upsert_batch(session, prepared)
                session.commit()
            except Exception:
                session.rollback()
                stats.database_failures += len(chunk)
                logger.exception(
                    "[linkedin_job_repository] batch upsert failed (rows %d-%d) — rolled back",
                    i, i + len(chunk) - 1,
                )
                continue

            stats.jobs_inserted += inserted
            stats.jobs_updated += updated
            stats.jobs_unchanged += unchanged

        for r in records:
            if r.get("is_active") is True:
                stats.active_jobs += 1
            elif r.get("is_active") is False:
                stats.inactive_jobs += 1
            else:
                stats.unknown_status_jobs += 1
    finally:
        if owns_session:
            session.close()

    return stats


@dataclass
class PaginatedJobs:
    items: list[dict]
    total_items: int


def get_paginated_jobs(
    *,
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
    session: Optional[Session] = None,
) -> PaginatedJobs:
    """
    One query for the common case: `COUNT(*) OVER()` rides alongside the
    page's own row data, so total_items comes back in the same round trip
    as the rows themselves — no separate count query, and LIMIT/OFFSET (not
    "load everything, slice in Python") is what bounds how much the DB
    sends back.

    Falls back to a second, plain `COUNT(*)` query ONLY when the requested
    page returns zero rows (page beyond the last page, or the table itself
    is empty) — a window function computed over an empty final result set
    carries no value to read, since LIMIT/OFFSET trims rows after the
    window function already ran. This still means totally-empty results
    take 2 queries, never more, and are the only case that does.

    Ordered `insertion_time DESC, id DESC` — the composite index
    ix_linkedin_jobs_insertion_time_id_desc exists specifically for this —
    with `id` (the primary key) as the mandatory tie-breaker so two rows
    with an identical insertion_time (bulk-imported in the same batch)
    never reorder between page 1 and page 2.

    `page`/`page_size` are trusted to already be validated (page >= 1,
    1 <= page_size <= MAX_PAGE_SIZE) by the caller — see
    backend/api/routes/linkedin_jobs.py's `Query(...)` constraints, which
    reject bad values with a 422 before this is ever called. Still clamped
    defensively here so a direct/non-HTTP caller can't construct a
    nonsensical OFFSET.
    """
    page = max(page, 1)
    page_size = min(max(page_size, 1), MAX_PAGE_SIZE)
    offset = (page - 1) * page_size

    columns = [_TABLE.c[name] for name in _LIST_VIEW_COLUMNS]
    total_count_col = func.count().over().label("total_count")

    stmt = (
        select(*columns, total_count_col)
        .order_by(_TABLE.c.insertion_time.desc(), _TABLE.c.id.desc())
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

    return PaginatedJobs(items=items, total_items=total_items)
