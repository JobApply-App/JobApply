"""ORM models for the profile / confidence-matrix cluster.

Extracted from the former backend/services/db.py.
"""
from __future__ import annotations

from sqlalchemy import Column, DateTime, Float, Integer, Numeric, String, Text, text
from sqlalchemy.types import JSON

from sqlalchemy.dialects import postgresql

from backend.core.database import Base

# Shared tenancy-key type — see the UUID_FK comment on any user_id column below.
UUID_FK = String().with_variant(postgresql.UUID(as_uuid=False), "postgresql")


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
    # UUID_FK: a real UUID column in Postgres (FK to profiles.id, migration
    # 00eab53e0f00), plain String on SQLite. The variant matters: this codebase
    # mixes raw text() INSERTs with ORM reads, and a uniform Uuid type would
    # normalise the ORM side to hex-32 while raw SQL wrote a dashed string —
    # they would silently stop matching on SQLite. Python always sees a str.
    # See docs/db-architecture-spec.md principle 1.
    user_id        = Column(UUID_FK, nullable=False, index=True)
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


## MasterProfileRow (master_profiles table) removed — Phase 3/4 of the
## relational schema redesign (docs/db-redesign-proposal.md) repointed every
## read/write path at backend/repositories/profile_repository.py (profiles/
## user_preferences/profile_answers/cv_documents/cv_claims) and the
## master_profiles table itself was dropped (Alembic revision 3a6b5cab3433).


# ── Active Confidence Matrix ORM models ──────────────────────────────────────
# These six tables form the knowledge-graph backbone for the Ariel agent.
# ProfileUpdateService is the only writer; never UPDATE confidence_score directly.

class ProfileEntityRow(Base):
    """Knowledge graph node: one skill / trait / domain / experience per row."""
    __tablename__ = "profile_entities"

    entity_id              = Column(String,  primary_key=True)
    # UUID_FK: a real UUID column in Postgres (FK to profiles.id, migration
    # 00eab53e0f00), plain String on SQLite. The variant matters: this codebase
    # mixes raw text() INSERTs with ORM reads, and a uniform Uuid type would
    # normalise the ORM side to hex-32 while raw SQL wrote a dashed string —
    # they would silently stop matching on SQLite. Python always sees a str.
    # See docs/db-architecture-spec.md principle 1.
    user_id                = Column(UUID_FK, nullable=False, index=True)
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
    # ── CV-claim merge (migration fa884910ef1d) ───────────────────────────────
    # A skill used to exist twice: as a raw cv_claims row and as a scored entity
    # here, unlinked. These three columns absorbed the cv_claims side.
    #   content            — the rich claim payload from cv_claims.content
    #   source_document_id — the cv_document this capability is CURRENTLY claimed
    #                        on; NULL when it isn't. profile_repository sets and
    #                        clears it, and get_profile() filters on it, so the
    #                        profile document still returns only CV-claimed
    #                        skills rather than the whole Confidence Matrix.
    #                        Removing a skill clears this instead of deleting the
    #                        row — evidence_records/confidence_audit_log point at
    #                        entity_id and are append-only.
    #   origin             — cv_parse | self_assertion | conversation | inferred
    content                = Column(JSON,    nullable=True)
    source_document_id     = Column(String,  nullable=True, index=True)
    origin                 = Column(String,  nullable=False, default="self_assertion",
                                    server_default="self_assertion")
    # ── Global skills taxonomy (migration 90b20294d1d3) ───────────────────────
    # skill_id: FK to skills_taxonomy.id — NULL for non-'skill' entity_types
    # (trait/domain/experience aren't in scope for the taxonomy) and for any
    # skill row a canonicalization pass hasn't reached yet. ON DELETE SET NULL:
    # deleting/merging a taxonomy row must never cascade into deleting a
    # user's entity (evidence_records/confidence_audit_log point at entity_id
    # and are append-only, same rationale as source_document_id above).
    # raw_text: the original extracted phrase verbatim, for auditability —
    # `name` is the canonical display form once resolved, `raw_text` is what
    # the CV/chat actually said (may be the same string if not yet resolved).
    skill_id                = Column(UUID_FK, nullable=True, index=True)
    raw_text                = Column(Text,    nullable=True)
    years_of_experience     = Column(Numeric(4, 1), nullable=True)
    last_used_year          = Column(Integer, nullable=True)
    created_at             = Column(String,  nullable=False)
    updated_at             = Column(String,  nullable=False)


class SkillsTaxonomyRow(Base):
    """
    Global, cross-tenant reference table — one row per canonical skill
    concept. No user_id: identical for every viewer, same category as
    company_intel/job_postings (see docs/db-architecture-spec.md's
    GLOBAL_TABLES note in backend/core/migrations.py).

    canonical_name is the single source of truth for a skill's display form
    across the whole platform (always English, per the taxonomy design) —
    profile_entities.skill_id points here so two accounts' differently-phrased
    or differently-languaged mentions of the same skill ("React"/"ReactJS"/
    "ריאקט") resolve to one row instead of three unrelated entities.
    """
    __tablename__ = "skills_taxonomy"

    # UUID_FK here is just the dialect-variant String/UUID type (see the
    # comment on the type definition above) — not literally a foreign key,
    # this table has none. Reused for the same reason: a real UUID column in
    # Postgres, plain text on SQLite, Python always sees a str.
    #
    # No server_default here even though Postgres has one (gen_random_uuid(),
    # set by the migration directly via raw DDL) — that function doesn't
    # exist on SQLite, and this repo's existing convention (see entity_id on
    # ProfileEntityRow above, always supplied explicitly by the caller via
    # _uid()) is to generate IDs in application code, not rely on the DB.
    id             = Column(UUID_FK, primary_key=True)
    canonical_name = Column(Text, nullable=False, unique=True)
    category       = Column(Text, nullable=False, default="Uncategorized",
                             server_default="Uncategorized")
    # Real Postgres TEXT[]; JSON (stored as text) on SQLite — same
    # .with_variant() escape hatch as UUID_FK, needed because raw
    # postgresql.ARRAY has no SQLite equivalent and would break create_all().
    synonyms       = Column(
        postgresql.ARRAY(Text).with_variant(JSON(), "sqlite"),
        nullable=False, default=list, server_default="{}",
    )
    created_at     = Column(DateTime(timezone=True), nullable=True)


class EvidenceRecordRow(Base):
    """Immutable evidence ledger — append-only, never UPDATE or DELETE."""
    __tablename__ = "evidence_records"

    evidence_id     = Column(String,  primary_key=True)
    entity_id       = Column(String,  nullable=False, index=True)
    # UUID_FK: a real UUID column in Postgres (FK to profiles.id, migration
    # 00eab53e0f00), plain String on SQLite. The variant matters: this codebase
    # mixes raw text() INSERTs with ORM reads, and a uniform Uuid type would
    # normalise the ORM side to hex-32 while raw SQL wrote a dashed string —
    # they would silently stop matching on SQLite. Python always sees a str.
    # See docs/db-architecture-spec.md principle 1.
    user_id         = Column(UUID_FK, nullable=False, index=True)
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
    # UUID_FK: a real UUID column in Postgres (FK to profiles.id, migration
    # 00eab53e0f00), plain String on SQLite. The variant matters: this codebase
    # mixes raw text() INSERTs with ORM reads, and a uniform Uuid type would
    # normalise the ORM side to hex-32 while raw SQL wrote a dashed string —
    # they would silently stop matching on SQLite. Python always sees a str.
    # See docs/db-architecture-spec.md principle 1.
    user_id        = Column(UUID_FK, nullable=False, index=True)
    old_score      = Column(Float,   nullable=False)
    new_score      = Column(Float,   nullable=False)
    delta          = Column(Float,   nullable=False)
    trigger_source = Column(String,  nullable=False)
    evidence_id    = Column(String,  nullable=True)
    session_id     = Column(String,  nullable=True)
    changed_at     = Column(String,  nullable=False)
    note           = Column(Text,    nullable=True)
