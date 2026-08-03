"""
`linkedin.jobs` — PostgreSQL-only table for the LinkedIn Israel jobs scraper
(backend/scripts/linkedin_israel_jobs.py).

Lives on the dedicated Postgres engine in backend/core/postgres.py, NOT the
app's primary SQLite ENGINE (backend/core/database.py) — see that module's
docstring for why. Uses real Postgres types (schema, TIMESTAMPTZ, JSONB,
UUID) rather than this repo's usual String/JSON/String-timestamp house style
(backend/models/application.py etc.), because those SQLite-compatible types can't
express what this table needs (see the project's Postgres migration request:
native `INSERT ... ON CONFLICT DO UPDATE`, a non-default schema, JSONB).

Business-key note (see backend/services/linkedin_job_normalize.py): the
LinkedIn guest scraper never returns an official job ID field, so
`linkedin_job_id` is extracted from `job_url`'s trailing numeric segment.
It's nullable because that extraction can theoretically fail on an
unexpected URL shape — `job_url_normalized` is the non-nullable fallback
unique key for that case (see the two partial/unique indexes below).
"""
from __future__ import annotations

import uuid

from sqlalchemy import Boolean, Column, DateTime, Index, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from backend.core.postgres import LinkedInBase


class LinkedInJobRow(LinkedInBase):
    __tablename__ = "jobs"
    __table_args__ = (
        # Primary business-key uniqueness — only enforced for rows where
        # extraction succeeded (see module docstring). A plain UNIQUE
        # constraint can't be partial, so this is a partial unique INDEX
        # instead, matching the project's explicit request to prefer
        # UNIQUE(linkedin_job_id) without allowing NULLs to collide (Postgres
        # normally treats every NULL as distinct anyway, but being explicit
        # here documents the intent rather than relying on that default).
        Index(
            "ix_linkedin_jobs_linkedin_job_id_unique",
            "linkedin_job_id",
            unique=True,
            postgresql_where=text("linkedin_job_id IS NOT NULL"),
        ),
        # Fallback uniqueness for the (expected-rare) case where
        # linkedin_job_id extraction fails — always present, so a plain
        # (non-partial) unique index.
        Index("ix_linkedin_jobs_job_url_normalized_unique", "job_url_normalized", unique=True),
        # Requested explicitly alongside job_url_normalized's unique index
        # above — this one is plain (non-unique) since job_url is the raw,
        # pre-normalization value (e.g. may still carry tracking params).
        Index("ix_linkedin_jobs_job_url", "job_url"),
        Index("ix_linkedin_jobs_company", "company"),
        Index("ix_linkedin_jobs_location", "location"),
        Index("ix_linkedin_jobs_is_active", "is_active"),
        Index("ix_linkedin_jobs_linkedin_status", "linkedin_status"),
        Index("ix_linkedin_jobs_insertion_time", "insertion_time"),
        Index("ix_linkedin_jobs_last_seen_at", "last_seen_at"),
        Index("ix_linkedin_jobs_updated_at", "updated_at"),
        Index("ix_linkedin_jobs_scraped_at", "scraped_at"),
        # Supports GET /api/linkedin/jobs's deterministic pagination sort
        # (ORDER BY insertion_time DESC, id DESC) — DESC/DESC matches the
        # query exactly so Postgres can walk the index directly with no
        # extra sort step. Created via raw SQL in the Alembic migration
        # (op.create_index doesn't express per-column sort direction as
        # cleanly), so this Index() is metadata-only bookkeeping to keep
        # the model in sync with the real DDL — SQLAlchemy won't try to
        # re-create it since there's no create_all() path for this schema
        # (see backend/core/postgres.py's docstring).
        Index("ix_linkedin_jobs_insertion_time_id_desc", "insertion_time", "id"),
        {"schema": "linkedin"},
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Business key (see module docstring).
    linkedin_job_id = Column(String, nullable=True)
    job_url_normalized = Column(String, nullable=False)

    title = Column(String, nullable=False)
    company = Column(String, nullable=False)
    location = Column(String, nullable=True)
    posted_text = Column(String, nullable=True)
    job_url = Column(Text, nullable=False)
    company_url = Column(Text, nullable=True)
    description = Column(Text, nullable=True)
    exact_posted_text = Column(String, nullable=True)
    applicants_text = Column(String, nullable=True)
    seniority_level = Column(String, nullable=True)
    employment_type = Column(String, nullable=True)
    job_function = Column(String, nullable=True)
    industries = Column(JSONB, nullable=True)  # list[str] — see normalize module
    company_logo_url = Column(Text, nullable=True)

    # See backend/services/linkedin_job_normalize.py's map_linkedin_status()
    # docstring for why this is UNKNOWN/NULL as of this task, and what source
    # a future change would need to derive it from.
    linkedin_status = Column(String, nullable=False, default="UNKNOWN")
    is_active = Column(Boolean, nullable=True)

    # All TIMESTAMPTZ / UTC — see linkedin_israel_jobs.py's CLI docstring for
    # the exact semantics of each (insertion_time never updates after
    # creation; first_seen_at rarely changes; last_seen_at/scraped_at update
    # on every re-sighting; updated_at only moves when data_hash changes).
    first_seen_at = Column(DateTime(timezone=True), nullable=False)
    last_seen_at = Column(DateTime(timezone=True), nullable=False)
    insertion_time = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)
    scraped_at = Column(DateTime(timezone=True), nullable=False)

    data_hash = Column(String, nullable=False)
