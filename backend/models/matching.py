"""ORM models for the matching/culture cluster.

Extracted from the former backend/services/db.py.
"""
from __future__ import annotations

from sqlalchemy import Column, Float, Integer, String, Text, UniqueConstraint

from sqlalchemy.dialects import postgresql

from backend.core.database import Base

# Shared tenancy-key type — see the UUID_FK comment on any user_id column below.
UUID_FK = String().with_variant(postgresql.UUID(as_uuid=False), "postgresql")


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
    # UUID_FK: a real UUID column in Postgres (FK to profiles.id, migration
    # 00eab53e0f00), plain String on SQLite. The variant matters: this codebase
    # mixes raw text() INSERTs with ORM reads, and a uniform Uuid type would
    # normalise the ORM side to hex-32 while raw SQL wrote a dashed string —
    # they would silently stop matching on SQLite. Python always sees a str.
    # See docs/db-architecture-spec.md principle 1.
    user_id        = Column(UUID_FK, nullable=False, index=True)
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
    # UUID_FK: a real UUID column in Postgres (FK to profiles.id, migration
    # 00eab53e0f00), plain String on SQLite. The variant matters: this codebase
    # mixes raw text() INSERTs with ORM reads, and a uniform Uuid type would
    # normalise the ORM side to hex-32 while raw SQL wrote a dashed string —
    # they would silently stop matching on SQLite. Python always sees a str.
    # See docs/db-architecture-spec.md principle 1.
    user_id      = Column(UUID_FK, nullable=False, index=True)
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
    Cached company research, both dimensions merged into one table
    (docs/db-redesign-proposal.md's cleanup plan): 'intel' (financial vibe/
    tech stack, from the Company Intelligence Agent, for CV tailoring) and
    'culture' (persona/culture-fit, from the Company Culture Agent — JOB-19,
    consumed by the Dynamic Matching Score, JOB-20) previously lived in two
    structurally-identical tables (company_intel/company_culture). Merged
    here with profile_type as a discriminator rather than overloading a
    single company_key row for both, since a company can legitimately have
    both kinds of research cached at once — a bare company_key PK would let
    one silently overwrite the other.

    One row per (normalized company name, profile_type). Profiles older than
    the service's staleness window (30 days) are served stale-while-
    revalidate: returned immediately while a background refresh
    re-researches recent news (layoffs, acquisitions, pivots).
    """
    __tablename__ = "company_intel"

    company_key   = Column(String, primary_key=True)              # normalized lowercase name
    profile_type  = Column(String, primary_key=True, default="intel")  # 'intel' | 'culture'
    display_name  = Column(String, nullable=False)
    profile_json  = Column(Text,   nullable=False, default="{}")  # CompanyProfile/CompanyCultureProfile dump
    researched_at = Column(String, nullable=False)                # ISO 8601 UTC
