"""
LinkedIn scraped-jobs API — read-only view over `linkedin.jobs`
(backend/models/linkedin_job.py), the table backend/scripts/
linkedin_israel_jobs.py populates.

GET /api/linkedin/jobs → LinkedInJobsPage (server-side paginated list)

Server-side pagination only — see backend/repositories/
linkedin_job_repository.py's get_paginated_jobs() docstring for the
one-query COUNT(*) OVER() strategy (falls back to a second, plain count
query only when a page returns zero rows). `page`/`page_size` are validated
here (422 on anything out of range) before ever reaching the repository.
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
from backend.repositories.linkedin_job_repository import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    get_paginated_jobs,
)

router = APIRouter()
logger = logging.getLogger(__name__)


# ── Pydantic models ───────────────────────────────────────────────────────────

class LinkedInJobItem(BaseModel):
    id: uuid.UUID
    linkedin_job_id: Optional[str]
    title: str
    company: str
    location: Optional[str]
    job_url: str
    posted_text: Optional[str]
    exact_posted_text: Optional[str]
    applicants_text: Optional[str]
    seniority_level: Optional[str]
    employment_type: Optional[str]
    job_function: Optional[str]
    industries: Optional[list]
    company_logo_url: Optional[str]
    linkedin_status: str
    is_active: Optional[bool]
    # Real TIMESTAMPTZ columns (this table's own convention — see
    # backend/models/linkedin_job.py's docstring — unlike the rest of this
    # app's String/ISO-8601-text house style), so these stay `datetime`
    # here too; FastAPI/Pydantic serialize them to ISO-8601 with the UTC
    # offset automatically.
    insertion_time: datetime
    first_seen_at: datetime
    last_seen_at: datetime
    updated_at: datetime


class PaginationMeta(BaseModel):
    page: int
    page_size: int
    total_items: int
    total_pages: int
    has_next: bool
    has_previous: bool


class LinkedInJobsPage(BaseModel):
    items: List[LinkedInJobItem]
    pagination: PaginationMeta


# ── Endpoint ───────────────────────────────────────────────────────────────────

@router.get("/jobs", response_model=LinkedInJobsPage)
async def list_linkedin_jobs(
    page: int = Query(1, ge=1, description="1-indexed page number."),
    page_size: int = Query(
        DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE,
        description=f"Rows per page, 1-{MAX_PAGE_SIZE}.",
    ),
    user: CurrentUser = Depends(get_current_user),
) -> LinkedInJobsPage:
    """
    All scraped LinkedIn jobs, newest-inserted first (insertion_time DESC,
    id DESC — deterministic across pages, see the repository's docstring).
    Not user-scoped: this is a global view of everything the scraper has
    collected, same as every authenticated user sees the same feed.
    """
    result = get_paginated_jobs(page=page, page_size=page_size)

    total_pages = math.ceil(result.total_items / page_size) if result.total_items else 0

    return LinkedInJobsPage(
        items=[LinkedInJobItem(**item) for item in result.items],
        pagination=PaginationMeta(
            page=page,
            page_size=page_size,
            total_items=result.total_items,
            total_pages=total_pages,
            has_next=page < total_pages,
            has_previous=page > 1,
        ),
    )
