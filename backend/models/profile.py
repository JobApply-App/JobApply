"""ORM models for the profile / confidence-matrix cluster.

Extracted from the former backend/services/db.py.
"""
from __future__ import annotations

from sqlalchemy import Boolean, Column, Float, Integer, String, Text
from sqlalchemy.types import JSON

from backend.core.database import Base


class ProfileInterviewRow(Base):
    """
    Persistent state for a conversational profile-building interview session.

    Each session is a multi-turn dialogue where the agent:
      1. Collects career facts through open-ended questions
      2. Extracts structured data into draft_profile
      3. Assigns confidence scores to every extracted claim
      4. Requests document uploads to upgrade unverified claims to 100%

    draft_profile  — mirrors USER_PROFILE schema; null until first extraction
    confidence_map — flat dict: {claim_id: {score, status, missing, evidence}}
                     claim_id examples: "education.0.degree", "experience.1.role"
    pending_probes — list of targeted follow-up questions still to be asked
    document_refs  — list of {filename, claim_id, status, extracted_text}
    user_id        — owning user; all queries must be scoped to this value
    """
    __tablename__ = "profile_interviews"

    session_id     = Column(String, primary_key=True)
    # Multi-tenant owner — added in v2; existing rows migrated to 'default'
    user_id        = Column(String, nullable=False, default="default", index=True)
    tenant_id      = Column(String, nullable=True, index=True)   # see JobRow.tenant_id docstring
    messages       = Column(JSON, nullable=False, default=list)
    draft_profile  = Column(JSON, nullable=True)
    confidence_map = Column(JSON, nullable=True)
    pending_probes = Column(JSON, nullable=True, default=list)
    document_refs  = Column(JSON, nullable=True, default=list)
    status         = Column(String, nullable=False, default="active")
    # "optimize_gaps" → Jonathan mode; None → Adam (default builder)
    intent         = Column(String, nullable=True)
    created_at     = Column(String, nullable=True)
    updated_at     = Column(String, nullable=True)


class MasterProfileRow(Base):
    """
    Central master profile for each authenticated user.

    Stores the complete, unstructured and structured professional history in a
    single JSON document (master_profile) alongside a lightweight onboarding
    state flag.  All Ariel tool calls that mutate profile data write to this
    table — they never touch the legacy flat JSON files.

    master_profile shape (baseline):
    {
        "professional_summary": str,
        "experience": [
            {
                "company":   str,
                "role":      str,
                "start":     str,   # e.g. "2021-03"
                "end":       str,   # e.g. "2024-01" | "present"
                "bullets":   [str]
            }
        ],
        "skills":       [str],
        "education":    [
            {
                "institution": str,
                "degree":      str,
                "field":       str,
                "year":        str
            }
        ],
        "career_goals": {
            "target_roles":        [str],
            "preferred_locations": [str],
            "work_environment":    str,   # "remote" | "hybrid" | "onsite" | "any"
            "notes":               str
        }
    }

    onboarding_status:
        "incomplete" — default; Ariel is still collecting information
        "complete"   — user confirmed all background has been provided;
                       set exclusively by the finalize_onboarding tool
    """
    __tablename__ = "master_profiles"

    user_id            = Column(String, primary_key=True)
    tenant_id          = Column(String, nullable=True, index=True)   # see JobRow.tenant_id docstring
    # Verified email from the Supabase JWT — lower-cased. Used by
    # POST /api/auth/sync-user to link accounts across auth providers
    # (email login vs Google OAuth) when Supabase issues a different `sub`
    # for the same person.
    email              = Column(String, nullable=True, index=True)
    onboarding_status  = Column(String, nullable=False, default="incomplete")
    master_profile     = Column(JSON,   nullable=False, default=dict)
    # Admin-dashboard foundation (Phase 2) — flipped manually in the DB for
    # now; require_admin (api/deps.py) is the only consumer.
    is_admin           = Column(Boolean, nullable=False, default=False)
    created_at         = Column(String, nullable=True)
    updated_at         = Column(String, nullable=True)


# ── Active Confidence Matrix ORM models ──────────────────────────────────────
# These six tables form the knowledge-graph backbone for the Ariel agent.
# ProfileUpdateService is the only writer; never UPDATE confidence_score directly.

class ProfileEntityRow(Base):
    """Knowledge graph node: one skill / trait / domain / experience per row."""
    __tablename__ = "profile_entities"

    entity_id              = Column(String,  primary_key=True)
    user_id                = Column(String,  nullable=False, index=True)
    tenant_id              = Column(String,  nullable=True, index=True)   # see JobRow.tenant_id docstring
    entity_type            = Column(String,  nullable=False)   # skill|trait|domain|experience
    name                   = Column(String,  nullable=False)
    normalized_name        = Column(String,  nullable=False)
    confidence_score       = Column(Float,   nullable=False, default=0.0)
    verification_status    = Column(String,  nullable=False, default="unverified")
    # Set to 1 by ingest_negative_flag when score < MANUAL_REVIEW_THRESHOLD.
    # Cleared to 0 whenever a positive evidence ingest pushes score back above threshold.
    # Stored as INTEGER (0/1) to avoid SQLite CHECK constraint issues with a new string value.
    # server_default matters: ProfileUpdateService writes with raw SQL INSERTs
    # that omit this column, so a fresh create_all() DB needs an SQL-level
    # DEFAULT (Python-side `default=` is invisible to raw SQL) — otherwise
    # every CV ingest fails with a NOT NULL IntegrityError.
    manual_review_required = Column(Integer, nullable=False, default=0, server_default="0")
    # Hierarchical skill tier — set during evidence ingest by ProfileUpdateService.
    # Core_Mastery:       direct hands-on proficiency, no AI assistance.
    # System_Orchestration: understands architecture; uses AI for boilerplate.
    # NULL until enough evidence is available to classify.
    skill_tier             = Column(String,  nullable=True)
    # Self-reported proficiency level, set when the user states their level in
    # chat (e.g. 'Beginner'/'Intermediate'/'Advanced'/'Expert'). Adjusted by
    # ProfileUpdateService.apply_chat_proficiency_update — NULL until the user
    # explicitly clarifies their level. Independent of skill_tier (which is
    # derived from evidence AI-assistance, not from the user's stated level).
    proficiency_level      = Column(String,  nullable=True)
    # Truth-based decoupled scores — populated by compute_decoupled_score().
    # architecture_confidence: score from portfolio / STAR / CV evidence.
    # syntax_confidence:       score from manual_assessment evidence only.
    # verification_level:      VERIFIED_MANUAL | ORCHESTRATION_ONLY | UNVERIFIED
    architecture_confidence = Column(Float,  nullable=False, default=0.0, server_default="0.0")
    syntax_confidence       = Column(Float,  nullable=False, default=0.0, server_default="0.0")
    verification_level      = Column(String, nullable=False, default="UNVERIFIED", server_default="UNVERIFIED")
    last_evidence_at       = Column(String,  nullable=True)
    created_at             = Column(String,  nullable=False)
    updated_at             = Column(String,  nullable=False)


class EvidenceRecordRow(Base):
    """Immutable evidence ledger — append-only, never UPDATE or DELETE."""
    __tablename__ = "evidence_records"

    evidence_id     = Column(String,  primary_key=True)
    entity_id       = Column(String,  nullable=False, index=True)
    user_id         = Column(String,  nullable=False, index=True)
    tenant_id       = Column(String,  nullable=True, index=True)   # see JobRow.tenant_id docstring
    source_type     = Column(String,  nullable=False)
    base_weight     = Column(Float,   nullable=False)
    raw_content     = Column(Text,    nullable=True)
    verified_at     = Column(String,  nullable=False)
    hard_expires_at = Column(String,  nullable=True)
    session_id      = Column(String,  nullable=True, index=True)
    event_id        = Column(String,  nullable=True)
    extra_metadata  = Column(Text,    nullable=True)   # JSON blob — 'metadata' is reserved by SQLAlchemy
    # True when the candidate used AI to generate boilerplate but understood
    # the architecture.  Triggers AI_AUGMENTATION_PENALTY (×0.6) in scoring.
    # server_default for the same reason as profile_entities: evidence rows are
    # written via raw SQL INSERTs that omit this column.
    is_ai_assisted  = Column(Integer, nullable=False, default=0, server_default="0")


class ConfidenceAuditLogRow(Base):
    """Immutable audit trail — one row per confidence_score change."""
    __tablename__ = "confidence_audit_log"

    log_id         = Column(Integer, primary_key=True, autoincrement=True)
    entity_id      = Column(String,  nullable=False, index=True)
    user_id        = Column(String,  nullable=False, index=True)
    tenant_id      = Column(String,  nullable=True, index=True)   # see JobRow.tenant_id docstring
    old_score      = Column(Float,   nullable=False)
    new_score      = Column(Float,   nullable=False)
    delta          = Column(Float,   nullable=False)
    trigger_source = Column(String,  nullable=False)
    evidence_id    = Column(String,  nullable=True)
    session_id     = Column(String,  nullable=True)
    changed_at     = Column(String,  nullable=False)
    note           = Column(Text,    nullable=True)
