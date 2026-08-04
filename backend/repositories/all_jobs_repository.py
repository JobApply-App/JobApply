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
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import Integer, MetaData, Table, and_, func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from backend.core.postgres import get_pg_session
from backend.models.all_jobs import AllJobRow
from backend.services.linkedin_job_normalize import (
    _INDUSTRY_KNOWN_TERMS,
    _JOB_FUNCTION_KNOWN_TERMS,
    build_normalized_job,
    normalize_company_key,
    normalize_list_field,
    parse_applicants,
    parse_location,
    parse_posted_at,
)

_TABLE = AllJobRow.__table__

DEFAULT_PAGE_SIZE = 25
MAX_PAGE_SIZE = 100

# ── Write side ────────────────────────────────────────────────────────────────

_WRITABLE_COLUMNS = (
    "source", "source_job_id", "canonical_job_key",
    "job_title", "company_name", "company_name_normalized", "company_url", "company_logo_url",
    "job_url", "normalized_job_url", "location", "seniority_level",
    "employment_type", "job_function", "industries", "description",
    "posted_text", "exact_posted_text", "posted_at", "applicants", "raw_payload",
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


def build_all_jobs_record(
    raw_row: dict, *, source: str = "linkedin", reference_time: Optional[datetime] = None,
) -> dict[str, Any]:
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

    reference_time anchors parse_posted_at()'s "N units ago" -> absolute
    datetime conversion — defaults to now() for any caller that doesn't
    pass one (e.g. a manual CSV backfill run standalone), but
    bulk_upsert_all_jobs() below passes the same `now` it also writes to
    last_scraped_at, so both reflect the same scrape-run moment.
    """
    normalized = build_normalized_job(raw_row)
    provider_job_id = normalized["linkedin_job_id"]
    normalized_url = normalized["job_url_normalized"]
    canonical_job_key = provider_job_id or normalized_url
    reference_time = reference_time or datetime.now(timezone.utc)

    return {
        "source": source,
        "source_job_id": provider_job_id,
        "canonical_job_key": canonical_job_key,
        "job_title": normalized["title"],
        "company_name": normalized["company"],
        "company_name_normalized": normalize_company_key(normalized["company"]),
        "company_url": normalized["company_url"],
        "company_logo_url": normalized["company_logo_url"],
        "job_url": normalized["job_url"],
        "normalized_job_url": normalized_url,
        "location": parse_location(normalized["location"]),
        "seniority_level": normalized["seniority_level"],
        "employment_type": normalized["employment_type"],
        "job_function": normalize_list_field(normalized["job_function"], known_terms=_JOB_FUNCTION_KNOWN_TERMS),
        "industries": normalize_list_field(raw_row.get("industries"), known_terms=_INDUSTRY_KNOWN_TERMS),
        "description": normalized["description"],
        "posted_text": normalized["posted_text"],
        "exact_posted_text": normalized["exact_posted_text"],
        "posted_at": parse_posted_at(normalized["posted_text"], reference_time),
        "applicants": parse_applicants(normalized["applicants_text"]),
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
        rec = build_all_jobs_record(raw, source=source, reference_time=now)
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

# List-view columns — excludes only `raw_payload` (internal, never
# displayed). `description` IS included despite being large text: the
# frontend renders it behind a per-row expand/collapse toggle rather than
# inline, so it's hidden by default without needing a second per-row
# network round-trip to fetch it on expand.
_LIST_VIEW_COLUMNS = (
    "id", "source", "source_job_id", "canonical_job_key",
    "job_title", "company_name", "company_name_normalized", "company_url", "company_logo_url",
    "job_url", "normalized_job_url", "location", "seniority_level",
    "employment_type", "job_function", "industries", "description",
    "posted_text", "exact_posted_text", "posted_at", "applicants",
    "first_seen_at", "last_seen_at", "insertion_time",
    "updated_at", "last_scraped_at",
)


@dataclass
class PaginatedAllJobs:
    items: list[dict]
    total_items: int


@dataclass
class AllJobsFilters:
    """
    Every field is optional/AND-combined — only fields the caller actually
    sets narrow the query. source/seniority_level/employment_type/
    job_function/industry take a LIST of values, OR'd together within the
    field (e.g. seniority_level=["Entry level", "Associate"] matches
    either) — each is exact-match against real distinct values already in
    the table (see get_all_jobs_filter_options()), not free text, so a
    filter can never silently return zero rows due to a typo.
    company/title are case-insensitive substring search instead, since
    those columns are open-ended (no fixed vocabulary to pick from).
    """
    source: Optional[list[str]] = None
    seniority_level: Optional[list[str]] = None
    employment_type: Optional[list[str]] = None
    job_function: Optional[list[str]] = None
    industry: Optional[list[str]] = None
    company: Optional[str] = None
    title: Optional[str] = None
    min_applicants: Optional[int] = None
    max_applicants: Optional[int] = None
    posted_within_hours: Optional[int] = None


def _build_filter_conditions(filters: AllJobsFilters) -> list:
    conditions = []
    if filters.source:
        conditions.append(_TABLE.c.source.in_(filters.source))
    if filters.seniority_level:
        conditions.append(_TABLE.c.seniority_level.in_(filters.seniority_level))
    if filters.employment_type:
        conditions.append(_TABLE.c.employment_type.in_(filters.employment_type))
    if filters.job_function:
        # ARRAY overlap (&&), same as industries below — job_function is
        # also a text[] now, not a single exact-match string.
        conditions.append(_TABLE.c.job_function.overlap(filters.job_function))
    if filters.industry:
        # ARRAY overlap (&&) — matches rows whose `industries` array shares
        # at least one element with the selected list (OR semantics across
        # the selected industries, same as every other multi-select field).
        conditions.append(_TABLE.c.industries.overlap(filters.industry))
    if filters.company:
        conditions.append(_TABLE.c.company_name_normalized.ilike(f"%{filters.company.strip().lower()}%"))
    if filters.title:
        conditions.append(_TABLE.c.job_title.ilike(f"%{filters.title.strip()}%"))
    if filters.min_applicants is not None:
        conditions.append(_TABLE.c.applicants["value"].astext.cast(Integer) >= filters.min_applicants)
    if filters.max_applicants is not None:
        conditions.append(_TABLE.c.applicants["value"].astext.cast(Integer) <= filters.max_applicants)
    if filters.posted_within_hours is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=filters.posted_within_hours)
        conditions.append(_TABLE.c.posted_at >= cutoff)
    return conditions


# `id DESC` is always the final tie-breaker — every option, so two rows
# with an identical sort value never reorder between page 1 and page 2.
_SORT_OPTIONS = {
    # Most-recently-scraped first — rides the existing
    # ix_all_jobs_last_seen_at_desc index. The default: matches what a
    # fresh scrape run surfaces without the user picking anything.
    "recent": (_TABLE.c.last_seen_at.desc(),),
    # Most-recently-posted first (by the job's own posted_at, not scrape
    # time) — the most meaningful default for a job-seeker once they've
    # applied any filter narrowing the list down, since "posted_within_hours"
    # and "newest posted" are the same mental model.
    "posted": (_TABLE.c.posted_at.desc().nulls_last(),),
    "applicants_desc": (_TABLE.c.applicants["value"].astext.cast(Integer).desc().nulls_last(),),
    "applicants_asc": (_TABLE.c.applicants["value"].astext.cast(Integer).asc().nulls_last(),),
    "company": (_TABLE.c.company_name_normalized.asc().nulls_last(),),
}
DEFAULT_SORT_BY = "recent"


def get_paginated_all_jobs(
    *,
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
    filters: Optional[AllJobsFilters] = None,
    sort_by: str = DEFAULT_SORT_BY,
    session: Optional[Session] = None,
) -> PaginatedAllJobs:
    """
    sort_by picks from _SORT_OPTIONS above (falls back to the default for
    anything unrecognized, so a bad/stale value from a client can never
    500 — see backend/api/routes/all_jobs.py's Query(...) for the
    user-facing option list). `id DESC` is always appended as the final
    tie-breaker regardless of sort_by, so two rows sharing an identical
    sort value never reorder between page 1 and page 2.

    page/page_size are trusted to already be validated by the caller (see
    backend/api/routes/all_jobs.py's Query(...) constraints) but are still
    clamped defensively here for any direct/non-HTTP caller.
    """
    page = max(page, 1)
    page_size = min(max(page_size, 1), MAX_PAGE_SIZE)
    offset = (page - 1) * page_size

    conditions = _build_filter_conditions(filters) if filters else []
    order_clauses = _SORT_OPTIONS.get(sort_by, _SORT_OPTIONS[DEFAULT_SORT_BY])

    columns = [_TABLE.c[name] for name in _LIST_VIEW_COLUMNS]
    total_count_col = func.count().over().label("total_count")

    stmt = select(*columns, total_count_col)
    if conditions:
        stmt = stmt.where(and_(*conditions))
    stmt = (
        stmt
        .order_by(*order_clauses, _TABLE.c.id.desc())
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
            count_stmt = select(func.count()).select_from(_TABLE)
            if conditions:
                count_stmt = count_stmt.where(and_(*conditions))
            total_items = session.execute(count_stmt).scalar_one()
            items = []
    finally:
        if owns_session:
            session.close()

    return PaginatedAllJobs(items=items, total_items=total_items)


@dataclass
class AllJobsFilterOptions:
    sources: list[str]
    seniority_levels: list[str]
    employment_types: list[str]
    job_functions: list[str]
    industries: list[str]


_FILTER_OPTIONS_SQL = text("""
    SELECT
      ARRAY(SELECT DISTINCT source FROM public.all_jobs
            WHERE source IS NOT NULL ORDER BY source)                       AS sources,
      ARRAY(SELECT DISTINCT seniority_level FROM public.all_jobs
            WHERE seniority_level IS NOT NULL ORDER BY seniority_level)     AS seniority_levels,
      ARRAY(SELECT DISTINCT employment_type FROM public.all_jobs
            WHERE employment_type IS NOT NULL ORDER BY employment_type)    AS employment_types,
      ARRAY(SELECT DISTINCT x FROM public.all_jobs, unnest(job_function) x
            WHERE job_function IS NOT NULL ORDER BY x)                     AS job_functions,
      ARRAY(SELECT DISTINCT x FROM public.all_jobs, unnest(industries) x
            WHERE industries IS NOT NULL ORDER BY x)                       AS industries
""")


def get_all_jobs_filter_options(*, session: Optional[Session] = None) -> AllJobsFilterOptions:
    """
    Distinct, sorted values actually present in `all_jobs` right now — the
    frontend's filter dropdowns are populated from this rather than a
    hardcoded list, so a filter option can never be offered that would
    return zero results.

    One round trip via 5 independent ARRAY(SELECT DISTINCT ...) subqueries,
    rather than 5 separate SELECTs — measured byte-for-byte identical output
    to the old 5-query version, ~50% faster (1758ms -> 876ms mean, 6/6
    interleaved A/B wins against the real DB; per-query cost is dominated by
    network round-trip time, not query execution, since `all_jobs` is small).
    """
    owns_session = session is None
    session = session or get_pg_session()
    try:
        row = session.execute(_FILTER_OPTIONS_SQL).one()
        return AllJobsFilterOptions(
            sources=list(row.sources),
            seniority_levels=list(row.seniority_levels),
            employment_types=list(row.employment_types),
            job_functions=list(row.job_functions),
            industries=list(row.industries),
        )
    finally:
        if owns_session:
            session.close()
