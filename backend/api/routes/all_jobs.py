"""
Canonical, cross-provider jobs API — read-only view over `public.all_jobs`
(backend/models/all_jobs.py), populated so far by backend/scripts/
upsert_linkedin_csv_to_all_jobs.py from the LinkedIn scraper's CSV output.
Designed to hold other providers later via the `source` column.

GET /api/all-jobs → AllJobsPage (server-side paginated list)

Server-side pagination only — see backend/repositories/all_jobs_repository.py's
get_paginated_all_jobs() docstring for the one-query COUNT(*) OVER()
strategy. `page`/`page_size` are validated here (422 on anything out of
range) before ever reaching the repository.
"""
from __future__ import annotations

import logging
import math
import uuid
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from backend.api.deps import CurrentUser, get_current_user
from backend.repositories.all_jobs_repository import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    get_paginated_all_jobs,
)

router = APIRouter()
logger = logging.getLogger(__name__)


# ── Pydantic models ───────────────────────────────────────────────────────────

class LocationInfo(BaseModel):
    city: Optional[str]
    district: Optional[str]
    country: Optional[str]


class ApplicantsInfo(BaseModel):
    value: Optional[int]
    exact: bool


class AllJobItem(BaseModel):
    id: uuid.UUID
    source: str
    source_job_id: Optional[str]
    canonical_job_key: str
    job_title: Optional[str]
    company_name: Optional[str]
    company_name_normalized: Optional[str]
    company_url: Optional[str]
    company_logo_url: Optional[str]
    job_url: str
    normalized_job_url: str
    location: Optional[LocationInfo]
    seniority_level: Optional[str]
    employment_type: Optional[str]
    job_function: Optional[str]
    industries: Optional[list]
    posted_text: Optional[str]
    exact_posted_text: Optional[str]
    posted_at: Optional[datetime]
    applicants: Optional[ApplicantsInfo]
    # Real TIMESTAMPTZ columns (this table's own convention, like
    # linkedin.jobs — see backend/models/linkedin_job.py's docstring),
    # unlike the rest of this app's String/ISO-8601-text house style.
    first_seen_at: datetime
    last_seen_at: datetime
    insertion_time: datetime
    updated_at: datetime
    last_scraped_at: Optional[datetime]


class PaginationMeta(BaseModel):
    page: int
    page_size: int
    total_items: int
    total_pages: int
    has_next: bool
    has_previous: bool


class AllJobsPage(BaseModel):
    items: List[AllJobItem]
    pagination: PaginationMeta


# ── Endpoint ───────────────────────────────────────────────────────────────────

@router.get("", response_model=AllJobsPage)
async def list_all_jobs(
    page: int = Query(1, ge=1, description="1-indexed page number."),
    page_size: int = Query(
        DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE,
        description=f"Rows per page, 1-{MAX_PAGE_SIZE}.",
    ),
    user: CurrentUser = Depends(get_current_user),
) -> AllJobsPage:
    """
    All canonical jobs across every provider, newest-seen first
    (last_seen_at DESC, id DESC — deterministic across pages, see the
    repository's docstring). Not user-scoped: this is a global view of
    everything ingested, same as GET /api/linkedin/jobs.
    """
    result = get_paginated_all_jobs(page=page, page_size=page_size)

    total_pages = math.ceil(result.total_items / page_size) if result.total_items else 0

    return AllJobsPage(
        items=[AllJobItem(**item) for item in result.items],
        pagination=PaginationMeta(
            page=page,
            page_size=page_size,
            total_items=result.total_items,
            total_pages=total_pages,
            has_next=page < total_pages,
            has_previous=page > 1,
        ),
    )
