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
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from backend.api.deps import CurrentUser, get_current_user
from backend.repositories.all_jobs_repository import (
    DEFAULT_PAGE_SIZE,
    DEFAULT_SORT_BY,
    MAX_PAGE_SIZE,
    AllJobsFilters,
    get_all_jobs_filter_options,
    get_paginated_all_jobs,
)

SortBy = Literal["recent", "posted", "applicants_desc", "applicants_asc", "company"]

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
    job_function: Optional[list]
    industries: Optional[list]
    description: Optional[str]
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


class AllJobsFilterOptionsResponse(BaseModel):
    sources: List[str]
    seniority_levels: List[str]
    employment_types: List[str]
    job_functions: List[str]
    industries: List[str]


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.get("/filter-options", response_model=AllJobsFilterOptionsResponse)
async def list_all_jobs_filter_options(
    user: CurrentUser = Depends(get_current_user),
) -> AllJobsFilterOptionsResponse:
    """
    Distinct values actually present in `all_jobs` right now, for populating
    the filter dropdowns — guarantees every option offered returns at least
    one result. Registered before "" so it's never shadowed (FastAPI/Starlette
    match by declaration order, and this is a sibling path, not a parameter,
    so no ordering conflict exists either way — kept first for readability).
    """
    opts = get_all_jobs_filter_options()
    return AllJobsFilterOptionsResponse(
        sources=opts.sources,
        seniority_levels=opts.seniority_levels,
        employment_types=opts.employment_types,
        job_functions=opts.job_functions,
        industries=opts.industries,
    )


@router.get("", response_model=AllJobsPage)
async def list_all_jobs(
    page: int = Query(1, ge=1, description="1-indexed page number."),
    page_size: int = Query(
        DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE,
        description=f"Rows per page, 1-{MAX_PAGE_SIZE}.",
    ),
    source: Optional[List[str]] = Query(None, description="One or more exact values from /filter-options (OR'd)."),
    seniority_level: Optional[List[str]] = Query(None, description="One or more exact values from /filter-options (OR'd)."),
    employment_type: Optional[List[str]] = Query(None, description="One or more exact values from /filter-options (OR'd)."),
    job_function: Optional[List[str]] = Query(None, description="One or more exact values from /filter-options (OR'd)."),
    industry: Optional[List[str]] = Query(None, description="One or more industries (OR'd) — matches if the job's industries array contains any of them."),
    company: Optional[str] = Query(None, description="Case-insensitive substring search on company name."),
    title: Optional[str] = Query(None, description="Case-insensitive substring search on job title."),
    min_applicants: Optional[int] = Query(None, ge=0, description="Minimum applicant count (inclusive)."),
    max_applicants: Optional[int] = Query(None, ge=0, description="Maximum applicant count (inclusive)."),
    posted_within_hours: Optional[int] = Query(None, ge=1, description="Only jobs posted within this many hours."),
    sort_by: SortBy = Query(
        DEFAULT_SORT_BY,  # type: ignore[arg-type]
        description=(
            "recent (default, most-recently-scraped first) | posted (most-recently-posted first) | "
            "applicants_desc | applicants_asc | company (A-Z)."
        ),
    ),
    user: CurrentUser = Depends(get_current_user),
) -> AllJobsPage:
    """
    All canonical jobs across every provider (default sort: last_seen_at
    DESC, id DESC — deterministic across pages, see the repository's
    docstring). Not user-scoped: this is a global view of everything
    ingested, same as GET /api/linkedin/jobs.

    All filter params are optional and AND-combined, applied server-side
    in the same query pagination runs against — total_items/total_pages
    below reflect the filtered count, not the whole table, so pagination
    and filtering compose correctly together. sort_by likewise applies to
    that same filtered query, not a client-side reorder of one page.
    """
    filters = AllJobsFilters(
        source=source,
        seniority_level=seniority_level,
        employment_type=employment_type,
        job_function=job_function,
        industry=industry,
        company=company,
        title=title,
        min_applicants=min_applicants,
        max_applicants=max_applicants,
        posted_within_hours=posted_within_hours,
    )
    result = get_paginated_all_jobs(page=page, page_size=page_size, filters=filters, sort_by=sort_by)

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
