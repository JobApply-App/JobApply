"""ORM models for the matching/culture cluster.

Extracted from the former backend/services/db.py.
"""
from __future__ import annotations

from sqlalchemy import Column, Float, Integer, String, Text, UniqueConstraint

from backend.core.database import Base


class ShadowScoreRow(Base):
    """
    Shadow-mode calibration log for the ATS Match Engine.

    One row per scored job: the production composite the user actually saw,
    alongside the new engine's score and full component breakdown. Append-only;
    consumed later by the weight-calibration analysis. Safe to truncate after
    calibration.
    """
    __tablename__ = "shadow_match_scores"

    id             = Column(Integer, primary_key=True, autoincrement=True)
    user_id        = Column(String,  nullable=False, index=True)
    tenant_id      = Column(String,  nullable=True, index=True)   # see JobRow.tenant_id docstring
    job_title      = Column(String,  nullable=True)
    company        = Column(String,  nullable=True)
    existing_score = Column(Float,   nullable=False)   # what the frontend received
    ats_score      = Column(Float,   nullable=False)   # new engine's final_score
    breakdown_json = Column(Text,    nullable=False, default="{}")  # AtsMatchResult dump
    created_at     = Column(String,  nullable=False)


class MatchTriggerRow(Base):
    """
    High-match trigger events (JOB-43).

    One row per (user, job) pair whose LLM-validated composite score crossed
    HIGH_MATCH_THRESHOLD. The UNIQUE(user_id, job_id) constraint is the
    exactly-once guarantee: re-scoring the same job — same, higher, or lower —
    can never emit a second trigger, because the INSERT simply conflicts.

    `status` lifecycle: 'pending' → 'consumed'. Downstream channels
    (UI Notifications bell, Mobile push/SMS, WhatsApp, CV Adaptation Flow)
    read pending rows via match_trigger_service.fetch_pending_triggers() and
    acknowledge via mark_triggers_consumed() — they must NOT delete rows,
    since the row itself is the dedup record.
    """
    __tablename__ = "match_triggers"

    id           = Column(Integer, primary_key=True, autoincrement=True)
    user_id      = Column(String,  nullable=False, index=True)
    tenant_id    = Column(String,  nullable=True, index=True)   # see JobRow.tenant_id docstring
    job_id       = Column(String,  nullable=False)
    score        = Column(Float,   nullable=False)               # 1-decimal composite at trigger time
    threshold    = Column(Float,   nullable=False)               # threshold in force when fired
    payload_json = Column(Text,    nullable=False, default="{}") # title/company/why_ron for notifications
    status       = Column(String,  nullable=False, default="pending", index=True)
    created_at   = Column(String,  nullable=False)
    consumed_at  = Column(String,  nullable=True)

    __table_args__ = (
        UniqueConstraint("user_id", "job_id", name="uq_match_trigger_user_job"),
    )


class CompanyIntelRow(Base):
    """
    Cached CompanyProfile from the Company Intelligence Agent.

    One row per normalized company name. Profiles older than the service's
    staleness window (30 days) are served stale-while-revalidate: returned
    immediately while a background refresh re-researches recent news
    (layoffs, acquisitions, pivots).
    """
    __tablename__ = "company_intel"

    company_key   = Column(String, primary_key=True)              # normalized lowercase name
    display_name  = Column(String, nullable=False)
    profile_json  = Column(Text,   nullable=False, default="{}")  # CompanyProfile dump
    researched_at = Column(String, nullable=False)                # ISO 8601 UTC


class CompanyCultureRow(Base):
    """
    Cached CompanyCultureProfile from the Company Culture Agent (JOB-19).

    One row per normalized company name — most companies post multiple roles,
    so repeat postings from the same employer reuse the cached profile instead
    of re-running research. Distinct from company_intel (financial vibe for CV
    tailoring): this table holds the culture/persona dimension consumed by the
    Dynamic Matching Score (JOB-20).
    """
    __tablename__ = "company_culture"

    company_key   = Column(String, primary_key=True)              # normalized lowercase name
    display_name  = Column(String, nullable=False)
    profile_json  = Column(Text,   nullable=False, default="{}")  # CompanyCultureProfile dump
    researched_at = Column(String, nullable=False)                # ISO 8601 UTC
