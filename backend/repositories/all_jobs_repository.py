"""
Read repository for `public.all_jobs` (backend/models/all_jobs.py).

Read-only: writes happen via backend/scripts/upsert_linkedin_csv_to_all_jobs.py's
own upsert, not through this module. Pagination mirrors backend/repositories/
linkedin_job_repository.py's get_paginated_jobs() — single-query
COUNT(*) OVER() alongside the page's own rows, falling back to a second,
plain COUNT(*) only when the requested page returns zero rows.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.core.postgres import get_pg_session
from backend.models.all_jobs import AllJobRow

_TABLE = AllJobRow.__table__

DEFAULT_PAGE_SIZE = 25
MAX_PAGE_SIZE = 100

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
