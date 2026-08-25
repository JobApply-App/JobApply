"""Schema migrations and startup table initialisation.

Extracted from the former backend/services/db.py during the repo restructure
(backend/models/* now holds the ORM classes; backend/core/database.py holds
the engine/Base). init_db() remains the single public entry point main.py
calls at startup.

Every migration function in this file (_migrate, _migrate_confidence_matrix,
_migrate_tenant_id) is built entirely on SQLite-only introspection
(`PRAGMA table_info`, `sqlite_master`, `PRAGMA foreign_keys`/`wal_checkpoint`)
— none of it has a Postgres equivalent, and none of it needs one: when
backend/core/database.py's ENGINE points at Postgres, the schema is already
fully created and versioned by backend/alembic_app_schema/ (run explicitly as
a deploy step, `alembic -c alembic_app_schema.ini upgrade head` — never from
here). init_db() therefore only runs this file's migration logic on SQLite;
on Postgres it just confirms connectivity and logs the target.
"""
from __future__ import annotations

import logging

from sqlalchemy import text

from backend.core.database import Base, ENGINE

logger = logging.getLogger(__name__)

# Importing the model modules registers every ORM class on Base.metadata so
# that Base.metadata.create_all() below creates all tables, not just the ones
# some other import happened to touch first.
from backend.models import application, ariel, chat_message_log, cv_generation, kv, matching, profile  # noqa: F401


def _migrate() -> None:
    """Add columns introduced after the initial schema without dropping data."""

    # ── profile_interviews — add user_id (v2) + intent (v3) ─────────────────
    with ENGINE.connect() as conn:
        existing_pi = {row[1] for row in conn.execute(text("PRAGMA table_info(profile_interviews)"))}
        if "user_id" not in existing_pi:
            conn.execute(text(
                "ALTER TABLE profile_interviews ADD COLUMN user_id TEXT NOT NULL DEFAULT 'default'"
            ))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_profile_interviews_user_id "
                "ON profile_interviews (user_id)"
            ))
            conn.commit()
        if "intent" not in existing_pi:
            conn.execute(text(
                "ALTER TABLE profile_interviews ADD COLUMN intent TEXT"
            ))
            conn.commit()

    # ── applications — add user_id (v2) ──────────────────────────────────────
    with ENGINE.connect() as conn:
        existing_app = {row[1] for row in conn.execute(text("PRAGMA table_info(applications)"))}
        if "user_id" not in existing_app:
            conn.execute(text(
                "ALTER TABLE applications ADD COLUMN user_id TEXT NOT NULL DEFAULT 'default'"
            ))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_applications_user_id "
                "ON applications (user_id)"
            ))
            conn.commit()

    # ── JOB-6: indexes on applications filter+sort columns ───────────────────
    # CREATE INDEX IF NOT EXISTS is idempotent — safe to run on every startup
    # against an existing populated DB, no data migration required.
    # (The matching `jobs` table indexes/columns were removed along with
    # JobRow — see TENANT_SCOPED_TABLES comment above.)
    with ENGINE.connect() as conn:
        for stmt in (
            "CREATE INDEX IF NOT EXISTS ix_applications_job_id       ON applications (job_id)",
            "CREATE INDEX IF NOT EXISTS ix_applications_status       ON applications (status)",
            "CREATE INDEX IF NOT EXISTS ix_applications_submitted_at ON applications (submitted_at)",
            "CREATE INDEX IF NOT EXISTS ix_applications_user_status  ON applications (user_id, status)",
        ):
            conn.execute(text(stmt))
        conn.commit()


def _migrate_confidence_matrix(conn) -> None:
    """
    Idempotent migration for the Active Confidence Matrix tables (migration 001).
    Creates each table only if it doesn't already exist.
    Matches the SQL in backend/migrations/001_confidence_matrix.sql.
    """
    tables = {
        row[0]
        for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
    }

    # All six tables are created by Base.metadata.create_all() above if the DB
    # is fresh.  For existing DBs the tables won't be in the ORM metadata yet,
    # so we run the raw CREATE TABLE IF NOT EXISTS statements here.
    # NOTE on the "CREATE TABLE IF NOT EXISTS" fallbacks below (profile_entities,
    # ariel_sessions, conversation_events, evidence_records, confidence_audit_log,
    # ariel_gap_queue): every one of these tables also has an ORM class earlier in
    # this file, so Base.metadata.create_all() (called before this function, in
    # init_db()) already creates the FULL, current-schema table on any DB where
    # "tables" is captured fresh — these raw strings only run for legacy DBs that
    # predate the ORM class. Kept in sync with their ORM class column-for-column
    # (JOB-91) so that IF a raw-DDL branch or the rename/recreate dance below ever
    # does execute, it produces the exact schema the ORM (and the rest of this
    # migration function) expects — a drift here previously caused
    # sqlite3.OperationalError on fresh deployments (see evidence_records below).
    if "profile_entities" not in tables:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS profile_entities (
                entity_id               TEXT PRIMARY KEY,
                user_id                 TEXT NOT NULL,
                entity_type             TEXT NOT NULL,
                name                    TEXT NOT NULL,
                normalized_name         TEXT NOT NULL,
                confidence_score        REAL NOT NULL DEFAULT 0.0,
                verification_status     TEXT NOT NULL DEFAULT 'unverified',
                manual_review_required  INTEGER NOT NULL DEFAULT 0,
                skill_tier              TEXT,
                architecture_confidence REAL NOT NULL DEFAULT 0.0,
                syntax_confidence       REAL NOT NULL DEFAULT 0.0,
                verification_level      TEXT NOT NULL DEFAULT 'UNVERIFIED',
                last_evidence_at        TEXT,
                proficiency_level       TEXT,
                created_at              TEXT NOT NULL,
                updated_at              TEXT NOT NULL,
                UNIQUE (user_id, normalized_name, entity_type)
            )
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_pe_user ON profile_entities (user_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_pe_user_score ON profile_entities (user_id, confidence_score DESC)"))

    if "ariel_sessions" not in tables:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS ariel_sessions (
                session_id              TEXT PRIMARY KEY,
                user_id                 TEXT NOT NULL,
                session_type            TEXT NOT NULL,
                target_job_id           TEXT,
                target_entities         TEXT,
                ariel_goal              TEXT,
                status                  TEXT NOT NULL DEFAULT 'active',
                transcript_json         TEXT,
                confidence_delta_total  REAL NOT NULL DEFAULT 0.0,
                started_at              TEXT NOT NULL,
                ended_at                TEXT
            )
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_as_user ON ariel_sessions (user_id, started_at DESC)"))

    if "conversation_events" not in tables:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS conversation_events (
                event_id                TEXT PRIMARY KEY,
                session_id              TEXT NOT NULL REFERENCES ariel_sessions (session_id),
                user_id                 TEXT NOT NULL,
                star_situation          TEXT,
                star_task               TEXT,
                star_action             TEXT,
                star_result             TEXT,
                extracted_entity_ids    TEXT NOT NULL,
                extraction_confidence   REAL NOT NULL,
                raw_quote               TEXT,
                analyzed_at             TEXT NOT NULL,
                -- Probe events share this table since migration 32d536527e9a:
                -- a probe and a STAR extraction are both events inside one
                -- ariel_session. star_extraction rows leave the probe columns
                -- NULL and vice versa.
                event_kind              TEXT NOT NULL DEFAULT 'star_extraction',
                probe_outcome           TEXT,
                entity_id               TEXT REFERENCES profile_entities (entity_id)
            )
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_ce_session ON conversation_events (session_id)"))
        # Backs the probe-cooldown LEFT JOIN in ariel_probe_service.
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_ce_probe_cooldown "
            "ON conversation_events (user_id, entity_id, analyzed_at DESC)"
        ))

    # Full CREATE DDL for evidence_records — includes all source_type values.
    # base_weight is REAL (not constrained to positive) so negative_flag rows
    # can store negative weights.
    #
    # JOB-91: this string previously had 11 columns while EvidenceRecordRow
    # (the ORM class) has 13 — missing tenant_id and is_ai_assisted. On a
    # fresh deployment, Base.metadata.create_all() already builds the full
    # 13-column table from the ORM class BEFORE this function runs, so
    # "evidence_records" is already in `tables` and this CREATE TABLE string
    # is skipped — but the ORM never emits a CHECK constraint, so the
    # freshly-created table's sqlite_master SQL never contains the literal
    # text "negative_flag". Migration 003 below used that substring as its
    # "is this schema stale?" test, so it always misfired on a brand-new DB,
    # rebuilding the table via this (drifted, 11-column) DDL and then
    # crashing on `INSERT INTO evidence_records SELECT * FROM
    # evidence_records_old` (13 columns selected, 11-column target) with
    # sqlite3.OperationalError. Keeping this DDL column-for-column identical
    # to EvidenceRecordRow removes that mismatch.
    _EVIDENCE_RECORDS_DDL = """
        CREATE TABLE evidence_records (
            evidence_id     TEXT PRIMARY KEY,
            entity_id       TEXT NOT NULL REFERENCES profile_entities (entity_id),
            user_id         TEXT NOT NULL,
            source_type     TEXT NOT NULL
                                CHECK (source_type IN (
                                    'cv_parse', 'self_assertion',
                                    'contextual_reinforcement',
                                    'certification', 'portfolio',
                                    'conversation_star',
                                    'manual_assessment',
                                    'negative_flag'
                                )),
            base_weight     REAL NOT NULL,
            raw_content     TEXT,
            verified_at     TEXT NOT NULL,
            hard_expires_at TEXT,
            session_id      TEXT REFERENCES ariel_sessions (session_id),
            event_id        TEXT REFERENCES conversation_events (event_id),
            extra_metadata  TEXT,
            is_ai_assisted  INTEGER NOT NULL DEFAULT 0
        )
    """

    if "evidence_records" not in tables:
        conn.execute(text(_EVIDENCE_RECORDS_DDL))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_er_entity ON evidence_records (entity_id, verified_at DESC)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_er_user   ON evidence_records (user_id, source_type)"))
    else:
        # ── Migration 003: widen source_type CHECK to include new types ────────
        # Detect a stale constraint by checking whether 'negative_flag' is
        # already present in the CREATE TABLE statement stored in sqlite_master.
        schema_row = conn.execute(
            text("SELECT sql FROM sqlite_master WHERE type='table' AND name='evidence_records'")
        ).fetchone()
        if schema_row and "negative_flag" not in schema_row[0]:
        # Recreate the table with the updated CHECK constraint.
        # SQLite requires a 3-step rename-create-copy-drop dance.
            conn.execute(text("PRAGMA foreign_keys=OFF"))
            conn.execute(text("ALTER TABLE evidence_records RENAME TO evidence_records_old"))
            conn.execute(text(_EVIDENCE_RECORDS_DDL))
            conn.execute(text("""
                INSERT INTO evidence_records
                    (evidence_id, entity_id, user_id, source_type, base_weight,
                     raw_content, verified_at, hard_expires_at, session_id,
                     event_id, extra_metadata, is_ai_assisted)
                SELECT evidence_id, entity_id, user_id, source_type, base_weight,
                       raw_content, verified_at, hard_expires_at, session_id,
                       event_id, extra_metadata, is_ai_assisted
                FROM evidence_records_old
            """))
            conn.execute(text("DROP TABLE evidence_records_old"))
            conn.execute(text("PRAGMA foreign_keys=ON"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_er_entity ON evidence_records (entity_id, verified_at DESC)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_er_user   ON evidence_records (user_id, source_type)"))

        # ── Migration 004: rename metadata → extra_metadata ───────────────
        # SQLite doesn't support ALTER TABLE RENAME COLUMN before 3.25.0, so
        # we detect the stale column name and do the rename-copy-drop dance.
        schema_row = conn.execute(
            text("SELECT sql FROM sqlite_master WHERE type='table' AND name='evidence_records'")
        ).fetchone()
        if schema_row and "extra_metadata" not in schema_row[0]:
            conn.execute(text("PRAGMA foreign_keys=OFF"))
            conn.execute(text("ALTER TABLE evidence_records RENAME TO evidence_records_old"))
            conn.execute(text(_EVIDENCE_RECORDS_DDL))
            conn.execute(text("""
                INSERT INTO evidence_records
                    (evidence_id, entity_id, user_id, source_type, base_weight,
                     raw_content, verified_at, hard_expires_at, session_id,
                     event_id, extra_metadata)
                SELECT evidence_id, entity_id, user_id, source_type, base_weight,
                       raw_content, verified_at, hard_expires_at, session_id,
                       event_id, metadata
                FROM evidence_records_old
            """))
            conn.execute(text("DROP TABLE evidence_records_old"))
            conn.execute(text("PRAGMA foreign_keys=ON"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_er_entity ON evidence_records (entity_id, verified_at DESC)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_er_user   ON evidence_records (user_id, source_type)"))

        # ── Migration 005: add is_ai_assisted to evidence_records ─────────────
        er_cols = [r[1] for r in conn.execute(
            text("PRAGMA table_info(evidence_records)")
        ).fetchall()]
        if "is_ai_assisted" not in er_cols:
            conn.execute(text(
                "ALTER TABLE evidence_records ADD COLUMN is_ai_assisted INTEGER NOT NULL DEFAULT 0"
            ))

        # ── Migration 006: add skill_tier to profile_entities ─────────────────
        pe_cols = [r[1] for r in conn.execute(
            text("PRAGMA table_info(profile_entities)")
        ).fetchall()]
        if "skill_tier" not in pe_cols:
            conn.execute(text(
                "ALTER TABLE profile_entities ADD COLUMN skill_tier TEXT"
            ))

        # ── Migration 007: add decoupled score columns ────────────────────────
        # Re-read cols in case Migration 006 just added one
        pe_cols = [r[1] for r in conn.execute(
            text("PRAGMA table_info(profile_entities)")
        ).fetchall()]
        if "architecture_confidence" not in pe_cols:
            conn.execute(text(
                "ALTER TABLE profile_entities "
                "ADD COLUMN architecture_confidence REAL NOT NULL DEFAULT 0.0"
            ))
        if "syntax_confidence" not in pe_cols:
            conn.execute(text(
                "ALTER TABLE profile_entities "
                "ADD COLUMN syntax_confidence REAL NOT NULL DEFAULT 0.0"
            ))
        if "verification_level" not in pe_cols:
            conn.execute(text(
                "ALTER TABLE profile_entities "
                "ADD COLUMN verification_level TEXT NOT NULL DEFAULT 'UNVERIFIED'"
            ))

        # ── Migration 008: expand evidence_records CHECK for manual_assessment ─
        er_schema = conn.execute(
            text("SELECT sql FROM sqlite_master WHERE type='table' AND name='evidence_records'")
        ).fetchone()
        if er_schema and "manual_assessment" not in er_schema[0]:
            conn.execute(text("PRAGMA foreign_keys=OFF"))
            conn.execute(text("ALTER TABLE evidence_records RENAME TO evidence_records_old"))
            conn.execute(text(_EVIDENCE_RECORDS_DDL))
            conn.execute(text("""
                INSERT INTO evidence_records
                    (evidence_id, entity_id, user_id, source_type, base_weight,
                     raw_content, verified_at, hard_expires_at, session_id,
                     event_id, extra_metadata, is_ai_assisted)
                SELECT evidence_id, entity_id, user_id, source_type, base_weight,
                       raw_content, verified_at, hard_expires_at, session_id,
                       event_id, extra_metadata, is_ai_assisted
                FROM evidence_records_old
            """))
            conn.execute(text("DROP TABLE evidence_records_old"))
            conn.execute(text("PRAGMA foreign_keys=ON"))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_er_entity "
                "ON evidence_records (entity_id, verified_at DESC)"
            ))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_er_user "
                "ON evidence_records (user_id, source_type)"
            ))

        # ── Migration 009: add proficiency_level to profile_entities ──────────
        pe_cols = [r[1] for r in conn.execute(
            text("PRAGMA table_info(profile_entities)")
        ).fetchall()]
        if "proficiency_level" not in pe_cols:
            conn.execute(text(
                "ALTER TABLE profile_entities ADD COLUMN proficiency_level TEXT"
            ))

    if "confidence_audit_log" not in tables:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS confidence_audit_log (
                log_id          INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_id       TEXT NOT NULL REFERENCES profile_entities (entity_id),
                user_id         TEXT NOT NULL,
                old_score       REAL NOT NULL,
                new_score       REAL NOT NULL,
                delta           REAL NOT NULL,
                trigger_source  TEXT NOT NULL,
                evidence_id     TEXT REFERENCES evidence_records (evidence_id),
                session_id      TEXT REFERENCES ariel_sessions (session_id),
                changed_at      TEXT NOT NULL,
                note            TEXT
            )
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_cal_entity ON confidence_audit_log (entity_id, changed_at DESC)"))

    if "ariel_gap_queue" not in tables:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS ariel_gap_queue (
                gap_id              TEXT PRIMARY KEY,
                user_id             TEXT NOT NULL,
                entity_id           TEXT NOT NULL REFERENCES profile_entities (entity_id),
                job_id              TEXT,
                current_confidence  REAL NOT NULL,
                required_confidence REAL NOT NULL,
                gap_severity        TEXT NOT NULL,
                status              TEXT NOT NULL DEFAULT 'pending',
                session_id          TEXT REFERENCES ariel_sessions (session_id),
                detected_at         TEXT NOT NULL,
                resolved_at         TEXT
            )
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_agq_user ON ariel_gap_queue (user_id, gap_severity, status)"))

    # Migration 004 (ariel_probe_log) intentionally removed: probe events
    # moved into conversation_events with event_kind='probe'
    # (migration 32d536527e9a). The columns and the cooldown index are
    # created with that table above.

    # ── Migration 002: add manual_review_required to profile_entities ─────────
    # ALTER TABLE to add the column if the table already exists from migration 001.
    # SQLite supports ADD COLUMN on existing tables; the DEFAULT 0 backfills safely.
    if "profile_entities" in tables:
        existing_pe_cols = {
            row[1]
            for row in conn.execute(text("PRAGMA table_info(profile_entities)"))
        }
        if "manual_review_required" not in existing_pe_cols:
            conn.execute(text(
                "ALTER TABLE profile_entities "
                "ADD COLUMN manual_review_required INTEGER NOT NULL DEFAULT 0"
            ))

    conn.commit()


# ── Multi-tenant scoping inventory ────────────────────────────────────────────
#
# Every table listed here already carries `user_id` as its isolation key —
# see docs/multi-tenant-erd.md for the full table-by-table classification.
# `tenant_id` (added by _migrate_tenant_id below) is forward-compatible only:
# it is NOT yet consumed by any query filter, because there is no tenant
# concept above `user_id` in CurrentUser (backend/api/deps.py) yet — one
# account is one tenant for now. When an org/workspace concept lands,
# query-layer filtering composes alongside the existing user_id filter at
# each call site (mechanical, not a redesign — every call site already takes
# user_id as an explicit parameter, never a global).
#
# This list drives the SQLite-only tenant_id backfill, so membership tracks
# what still exists ON SQLITE — which is not the same as what exists in
# Postgres. The deciding question for each table is whether an ORM model still
# creates it via create_all(), not whether Postgres still has it:
#
#   jobs             dropped in Postgres (migration 3a6b5cab3433) AND JobRow
#                     deleted (backend/models/job.py) — never created anywhere
#                     now. REMOVED.
#   master_profiles  dropped AND MasterProfileRow deleted — never created
#                    anywhere now. REMOVED.
#   match_triggers   folded into user_job_matches (3542b0021d6b) and their ORM
#   job_feedback     models deleted with them. REMOVED.
#
# The loop below skips a missing table silently, so a stale entry costs nothing
# at runtime — but an entry missing for a table that DOES exist silently skips
# a real migration, which is the failure mode above.
TENANT_SCOPED_TABLES: tuple[str, ...] = (
    "profile_interviews", "applications", "recruiter_reply_drafts",
    "profile_entities", "evidence_records", "shadow_match_scores",
    "ariel_sessions", "conversation_events", "confidence_audit_log",
    "ariel_gap_queue",
)

# Intentionally global / shared across all tenants — never add tenant_id here
# without a deliberate product decision (see docs/multi-tenant-erd.md):
#   kv_store        — process-level operational flags, not user data.
#   company_intel   — company research cache; identical regardless of viewer.
#   company_culture — company culture-fit cache; identical regardless of viewer.
GLOBAL_TABLES: tuple[str, ...] = ("kv_store", "company_intel", "company_culture")


def _migrate_tenant_id(conn) -> None:
    """
    Additive, idempotent migration: add a nullable `tenant_id` column to every
    table in TENANT_SCOPED_TABLES that doesn't already have one, backfill it
    from that table's own `user_id` (one account == one tenant, today), and
    index it.

    Safe to run on every startup against a live, populated DB — every step is
    guarded by an existence check, matching the pattern already used
    throughout this file's _migrate()/_migrate_confidence_matrix().

    WAL/-shm note: SQLite's WAL mode allows ALTER TABLE ADD COLUMN as a normal
    write transaction, but a schema change while a large, un-checkpointed WAL
    file is outstanding can make the change slower to become visible to other
    connections and inflates -wal file growth. We checkpoint before starting
    (flush any prior writers' backlog so we're altering a clean base file) and
    again after committing (so the new schema + backfill land in jobs.db
    itself immediately, not left pending in -wal for an indeterminate time).
    """
    conn.execute(text("PRAGMA wal_checkpoint(TRUNCATE)"))

    existing_tables = {
        row[0] for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
    }

    for table in TENANT_SCOPED_TABLES:
        if table not in existing_tables:
            # Table doesn't exist yet on this DB (e.g. fresh install where
            # create_all()/a later migration will create it already carrying
            # tenant_id via the ORM model) — nothing to backfill.
            continue

        cols = {row[1] for row in conn.execute(text(f"PRAGMA table_info({table})"))}
        if "tenant_id" not in cols:
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN tenant_id TEXT"))

        # Backfill is safe to re-run: only touches rows where tenant_id is
        # still NULL, so partially-migrated or re-run states converge safely.
        if "user_id" in cols:
            conn.execute(text(
                f"UPDATE {table} SET tenant_id = user_id WHERE tenant_id IS NULL AND user_id IS NOT NULL"
            ))

        conn.execute(text(
            f"CREATE INDEX IF NOT EXISTS ix_{table}_tenant_id ON {table} (tenant_id)"
        ))
        # Composite index for the highest-traffic table — mirrors the
        # (user_id, applied) composite the JOB-6 indexing pass already added.
        if table == "applications":
            conn.execute(text(
                f"CREATE INDEX IF NOT EXISTS ix_{table}_tenant_user "
                f"ON {table} (tenant_id, user_id)"
            ))

    conn.commit()
    conn.execute(text("PRAGMA wal_checkpoint(TRUNCATE)"))
    conn.commit()


def _rollback_tenant_id(conn) -> None:
    """
    Rollback for _migrate_tenant_id(): drops the `tenant_id` column (and its
    indexes, which SQLite drops automatically with the column) from every
    table in TENANT_SCOPED_TABLES that has one.

    Requires SQLite >= 3.35 (native ALTER TABLE ... DROP COLUMN, shipped
    2021). Verified present in this environment (3.43.2). On an older SQLite
    this raises rather than silently corrupting data — the manual fallback is
    the same rename/recreate/copy/drop dance already used elsewhere in this
    file for evidence_records (see migration 003/004/008 above), applied to
    each affected table with tenant_id omitted from the recreated schema.

    Not wired into init_db() / _migrate() — this is an explicit, manually
    invoked escape hatch, never run automatically.
    """
    import sqlite3
    if sqlite3.sqlite_version_info < (3, 35, 0):
        raise RuntimeError(
            f"_rollback_tenant_id requires SQLite >= 3.35 for native DROP COLUMN "
            f"(found {sqlite3.sqlite_version}). Use the manual rename/recreate "
            f"procedure documented in this function's docstring instead."
        )

    conn.execute(text("PRAGMA wal_checkpoint(TRUNCATE)"))

    existing_tables = {
        row[0] for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
    }
    for table in TENANT_SCOPED_TABLES:
        if table not in existing_tables:
            continue
        cols = {row[1] for row in conn.execute(text(f"PRAGMA table_info({table})"))}
        if "tenant_id" in cols:
            # Indexes referencing tenant_id must be dropped explicitly first —
            # SQLite's DROP COLUMN does not implicitly drop them and errors
            # ("error in index ... after drop column") if they're left in place.
            conn.execute(text(f"DROP INDEX IF EXISTS ix_{table}_tenant_id"))
            if table == "applications":
                conn.execute(text(f"DROP INDEX IF EXISTS ix_{table}_tenant_user"))
            conn.execute(text(f"ALTER TABLE {table} DROP COLUMN tenant_id"))

    conn.commit()
    conn.execute(text("PRAGMA wal_checkpoint(TRUNCATE)"))
    conn.commit()


def init_db() -> None:
    """
    On SQLite: create all tables if they don't already exist, then apply any
    pending migrations (unchanged behavior).

    On Postgres: the schema is already created and versioned by
    backend/alembic_app_schema/ as an explicit deploy step, so there is
    nothing here to run — just confirm the app can actually reach the
    configured database before serving traffic.
    """
    if ENGINE.dialect.name != "sqlite":
        with ENGINE.connect() as conn:
            conn.execute(text("SELECT 1"))
        logger.info(
            "Database initialised (Postgres, host=%s) — schema managed by "
            "backend/alembic_app_schema/, not by this module.",
            ENGINE.url.host,
        )
        return

    Base.metadata.create_all(ENGINE)
    _migrate()
    # profile_interviews table is created by create_all() on first run;
    # no ALTER TABLE migrations needed since it's a new table.
    with ENGINE.connect() as conn:
        _migrate_confidence_matrix(conn)
        _migrate_tenant_id(conn)
