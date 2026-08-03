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


## MatchTriggerRow (match_triggers table) removed — folded into
## user_job_matches as trigger_state/trigger_score/trigger_threshold/
## triggered_at/trigger_consumed_at (migration 3542b0021d6b). A trigger is
## 1:1 with the match that fired it — the old table's UNIQUE(user_id,
## job_id) said so — and the partial index ix_ujm_pending_triggers keeps
## the pending scan as cheap as the dedicated table was.


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
