"""ORM model for the `jobs` table. Extracted from the former backend/services/db.py."""
from __future__ import annotations

from sqlalchemy import Boolean, Column, Float, Integer, String, Text
from sqlalchemy.types import JSON

from backend.core.database import Base


class JobRow(Base):
    """One row = one analyzed JobMatch, fully serialised for SQLite."""
    __tablename__ = "jobs"

    job_id                = Column(String,  primary_key=True)
    title                 = Column(String,  nullable=False)
    company               = Column(String,  nullable=False)
    location              = Column(String,  nullable=False, default="Unknown")
    score                 = Column(Float,   nullable=False, default=0.0)
    confidence_score      = Column(Integer, nullable=False, default=50)
    culture_fit_score     = Column(Integer, nullable=False, default=50)
    trajectory_alignment  = Column(Text,    nullable=False, default="")
    company_dna_inference = Column(Text,    nullable=False, default="")
    # Nested structures stored as JSON
    investigation_points  = Column(JSON, nullable=False, default=list)
    detailed_analysis     = Column(JSON, nullable=False, default=dict)
    reasons               = Column(JSON, nullable=False, default=list)
    # Optional / nullable fields
    apply_url             = Column(String,  nullable=True)
    is_new                = Column(Boolean, nullable=False, default=True)
    posted_at             = Column(String,  nullable=False, default="")
    why_ron               = Column(Text,    nullable=True)
    scoring_rationale     = Column(Text,    nullable=True)
    category              = Column(String,  nullable=True)
    # Cached tailored CV — set by the tailor endpoint after first generation
    # Shape: {"cv_data": {...}, "match_score": {...}}
    tailored_cv           = Column(JSON, nullable=True)
    # Application status
    applied               = Column(Boolean, nullable=False, default=False)
    applied_at            = Column(String,  nullable=True)
    # Origin and liveness
    source                = Column(String,  nullable=False, default='automatic')
    is_open               = Column(Boolean, nullable=False, default=True)
    # Raw JD text — stored so batch scoring never re-scrapes
    jd_text               = Column(Text,    nullable=True)
    # LLM-structured JD stored as JSON string (set by jd_structure_service)
    jd_structured         = Column(Text,    nullable=True)
    # Multi-user & feed columns
    user_id               = Column(String,  nullable=False, default='default', index=True)
    # Forward-compatible tenant scoping (Infra & Multi-Tenant Architecture).
    # Nullable during rollout; backfilled to match user_id (1 account == 1
    # tenant today). Not yet enforced at the query layer — see
    # docs/multi-tenant-erd.md §"What tenant_id does NOT do yet".
    tenant_id              = Column(String,  nullable=True, index=True)
    source_type           = Column(String,  nullable=False, default='other')
    company_website_url   = Column(String,  nullable=True)
    status                = Column(String,  nullable=False, default='new')
    match_score           = Column(Float,   nullable=False, default=0.0)
    score_is_proxy        = Column(Boolean, nullable=False, default=True)
    created_at            = Column(String,  nullable=True)  # ISO-8601 UTC
    # Language hint: 'he' (Hebrew) | 'en' (English) | None (unknown)
    locale                = Column(String,  nullable=True)
    # Cross-board dedup fingerprint: sha1(norm(title)|norm(company)|norm(location))[:16]
    # Shared across multiple boards that post the same role.
    dedup_key             = Column(String,  nullable=True, index=True)
    # Incremented each time s2 LLM enrichment returns a non-substantive result.
    # UI uses this to show a hard-failure state after 3 failed attempts.
    enrichment_failures   = Column(Integer, nullable=False, default=0)
    # Phase 3 — generated hiring-manager outreach message; persists across reloads.
    outreach_text         = Column(Text,    nullable=True)

    # JOB-20: Dynamic culture fit scoring dimensions
    culture_delta         = Column(Float,   nullable=True)
    culture_alignment     = Column(Float,   nullable=True)
    culture_category      = Column(String,  nullable=True)
    culture_note          = Column(String,  nullable=True)
