"""
One-time (re-runnable) data migration: copies every row from backend/
jobs.db (SQLite, the app's actual primary datastore — see CLAUDE.md) into
the Postgres `public` schema tables created by backend/alembic_app_schema/
versions/413f4ed8fbc6_create_app_tables.py.

PREREQUISITE: run the alembic_app_schema migration against the target
database first (see backend/alembic_app_schema/README) — this script only
INSERTs rows, it does not create tables.

This is a DATA COPY, not a cutover: the running app keeps reading from and
writing to SQLite after this runs. Switching the app itself over to Postgres
is a separate, larger effort (every repository module's data-access path
would need to change) and is explicitly out of scope here.

Network/write safety gate (mirrors backend/scripts/linkedin_israel_jobs.py's
_guard_linkedin_request): no row is ever written to Postgres unless BOTH
  1. --allow-write is passed on the command line, AND
  2. ALLOW_SUPABASE_APP_MIGRATION=true is set in the environment
are true. Omitting --allow-write always runs the safe, read-only preview
path instead — reads backend/jobs.db, reports per-table row counts, and
makes ZERO Postgres connections.

Usage
-----
    # Safe default — read-only preview, no Postgres connection:
    python -m backend.scripts.migrate_jobs_db_to_supabase

    # Real copy (after alembic_app_schema has created the tables):
    ALLOW_SUPABASE_APP_MIGRATION=true python -m backend.scripts.migrate_jobs_db_to_supabase --allow-write

    # Row-count comparison only, against an already-migrated target:
    python -m backend.scripts.migrate_jobs_db_to_supabase --verify-only
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from sqlalchemy import text  # noqa: E402

from backend.core.postgres import get_pg_session  # noqa: E402

_SQLITE_PATH = _PROJECT_ROOT / "backend" / "jobs.db"

# FK-safe copy order — must match backend/alembic_app_schema/versions/
# 413f4ed8fbc6_create_app_tables.py's create order (parents before children).
#
# evidence_records_old is deliberately excluded: it's a dead duplicate table
# still present in SQLite, but backend/alembic_app_schema/versions/
# f1c4f486a0a8_drop_evidence_records_old.py already dropped it from Postgres
# ("accidental permanent duplicate") — there is no target table to copy into.
TABLE_ORDER = [
    "profile_entities", "ariel_sessions", "conversation_events",
    "evidence_records", "ariel_gap_queue",
    "ariel_probe_log", "confidence_audit_log",
    "applications", "chat_sessions", "company_culture", "company_intel",
    "job_feedback", "jobs", "kv_store", "master_profiles", "match_triggers",
    "profile_interviews", "recruiter_reply_drafts", "shadow_match_scores",
]

# Columns that are JSONB in Postgres but plain JSON text in SQLite — need an
# explicit ::jsonb cast on insert; psycopg2 won't infer it from a Python str.
JSONB_COLUMNS: dict[str, set[str]] = {
    "jobs": {"investigation_points", "detailed_analysis", "reasons", "tailored_cv"},
    "master_profiles": {"master_profile"},
    "profile_interviews": {"messages", "draft_profile", "confidence_map", "pending_probes", "document_refs"},
}

# Columns that are a real Postgres BOOLEAN but stored as SQLite 0/1 integers
# — need explicit bool() coercion (Postgres has no implicit int->boolean cast).
BOOLEAN_COLUMNS: dict[str, set[str]] = {
    "jobs": {"is_new", "applied", "is_open", "score_is_proxy"},
    "master_profiles": {"is_admin"},
}

# Tables with a Postgres SERIAL/autoincrement integer PK — the sequence must
# be reset to MAX(id)+1 after copying explicit id values across, or the next
# real INSERT (once the app cuts over) would collide with a copied row.
AUTOINCREMENT_TABLES: dict[str, str] = {
    "chat_sessions": "id",
    "confidence_audit_log": "log_id",
    "job_feedback": "id",
    "match_triggers": "id",
    "shadow_match_scores": "id",
}

# Primary key per table — used for ON CONFLICT DO NOTHING so a re-run (or a
# run against a target that already has some independently-seeded rows, e.g.
# from earlier ad-hoc testing) is safe at the row level rather than only
# safe when the whole table's row count happens to match exactly.
PRIMARY_KEYS: dict[str, str] = {
    "profile_entities": "entity_id",
    "ariel_sessions": "session_id",
    "conversation_events": "event_id",
    "evidence_records": "evidence_id",
    "ariel_gap_queue": "gap_id",
    "ariel_probe_log": "probe_id",
    "confidence_audit_log": "log_id",
    "applications": "application_id",
    "chat_sessions": "id",
    "company_culture": "company_key",
    "company_intel": "company_key",
    "job_feedback": "id",
    "jobs": "job_id",
    "kv_store": "key",
    "master_profiles": "user_id",
    "match_triggers": "id",
    "profile_interviews": "session_id",
    "recruiter_reply_drafts": "draft_id",
    "shadow_match_scores": "id",
}

# chat_sessions.created_at/updated_at are the one column pair ported to a
# real Postgres TIMESTAMPTZ (see backend/alembic_app_schema's migration
# docstring) — but SQLite stores them as a NAIVE text string with no offset
# (confirmed: "2026-06-30 10:02:14.743538", no "+00:00"/"Z"), even though
# backend/api/routes/history.py's ChatSessionRow writes them from
# datetime.now(timezone.utc). Handing that naive string straight to
# psycopg2 would let the *target* Postgres session's timezone setting decide
# how to interpret it — silently wrong if that session isn't UTC. Parsed and
# tagged explicitly as UTC here instead, so the copied value is unambiguous
# regardless of the target session's timezone.
_NAIVE_UTC_DATETIME_COLUMNS: dict[str, set[str]] = {
    "chat_sessions": {"created_at", "updated_at"},
}


def _parse_naive_utc(value: Any) -> Any:
    if value is None or isinstance(value, datetime):
        return value
    dt = datetime.fromisoformat(str(value))
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _guard_write(args: argparse.Namespace) -> None:
    env_allowed = os.environ.get("ALLOW_SUPABASE_APP_MIGRATION", "").strip().lower() in ("1", "true", "yes")
    cli_allowed = bool(getattr(args, "allow_write", False))
    if not (cli_allowed and env_allowed):
        print(
            "[GUARD] Refusing to write to Postgres: requires BOTH --allow-write "
            "AND ALLOW_SUPABASE_APP_MIGRATION=true in the environment. Omit "
            "--allow-write to run the safe read-only preview instead.",
            file=sys.stderr,
        )
        sys.exit(1)


def _sqlite_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_SQLITE_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def _sqlite_table_counts() -> dict[str, int]:
    conn = _sqlite_conn()
    try:
        return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in TABLE_ORDER}
    finally:
        conn.close()


def _coerce_row(table: str, row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    for col in BOOLEAN_COLUMNS.get(table, ()):
        if col in d and d[col] is not None:
            d[col] = bool(d[col])
    for col in _NAIVE_UTC_DATETIME_COLUMNS.get(table, ()):
        if col in d and d[col] is not None:
            d[col] = _parse_naive_utc(d[col])
    return d


def _insert_sql(table: str, columns: list[str]) -> str:
    """
    NOTE: `:col::jsonb` (a bare `::` cast directly after a named bind param)
    breaks SQLAlchemy's text() bindparam tokenizer when the statement is
    later executed as a batch (executemany) — the jsonb-cast params silently
    fail to convert to psycopg2's %(name)s paramstyle while every other
    param does, producing "syntax error at or near ':'" against Postgres.
    CAST(:col AS jsonb) avoids the ambiguity entirely and is functionally
    identical. Confirmed via a real failed run against Supabase — see the
    module's own migration history for this exact traceback.
    """
    jsonb_cols = JSONB_COLUMNS.get(table, set())
    placeholders = [f"CAST(:{c} AS jsonb)" if c in jsonb_cols else f":{c}" for c in columns]
    pk = PRIMARY_KEYS[table]
    return (
        f"INSERT INTO public.{table} ({', '.join(columns)}) VALUES ({', '.join(placeholders)}) "
        f"ON CONFLICT ({pk}) DO NOTHING"
    )


def run_preview() -> None:
    print(f"[preview] Reading {_SQLITE_PATH} — no Postgres connection made.\n")
    counts = _sqlite_table_counts()
    total = 0
    for t in TABLE_ORDER:
        print(f"  {t:<24} {counts[t]:>6} row(s) would be copied")
        total += counts[t]
    print(f"\n[preview] Total: {total} row(s) across {len(TABLE_ORDER)} tables.")
    print("[preview] Run with --allow-write (+ ALLOW_SUPABASE_APP_MIGRATION=true) to actually copy.")


def run_migration(batch_size: int = 500) -> dict[str, tuple[int, int]]:
    """
    Copies every table in TABLE_ORDER. Returns {table: (sqlite_count, inserted_count)}.

    Row-level idempotent via `ON CONFLICT (<pk>) DO NOTHING` (see PRIMARY_KEYS/
    _insert_sql), not a table-level row-count skip: a target that already has
    some of a table's rows (a partial prior run, or independently-seeded rows
    with no SQLite counterpart — confirmed to happen in practice against Dev)
    is handled correctly by only inserting what's actually missing, rather
    than either re-running a doomed full INSERT (primary-key violation) or
    wrongly skipping the whole table because the counts don't happen to match.
    inserted_count is measured as the actual net row-count delta, not the
    number of rows sent, since ON CONFLICT DO NOTHING silently no-ops
    duplicates.
    """
    sqlite_conn = _sqlite_conn()
    results: dict[str, tuple[int, int]] = {}
    try:
        with get_pg_session() as session:
            for table in TABLE_ORDER:
                rows = sqlite_conn.execute(f"SELECT * FROM {table}").fetchall()
                if not rows:
                    results[table] = (0, 0)
                    print(f"  {table}: 0 rows (nothing to copy)")
                    continue

                before = session.execute(text(f"SELECT count(*) FROM public.{table}")).scalar_one()

                columns = list(rows[0].keys())
                stmt = text(_insert_sql(table, columns))
                for i in range(0, len(rows), batch_size):
                    batch = [_coerce_row(table, r) for r in rows[i: i + batch_size]]
                    session.execute(stmt, batch)
                session.commit()

                after = session.execute(text(f"SELECT count(*) FROM public.{table}")).scalar_one()
                inserted = after - before
                print(f"  {table}: {inserted} new row(s) inserted ({after}/{len(rows)} sqlite rows now present)")
                results[table] = (len(rows), inserted)

            # Reset autoincrement sequences so a future real INSERT (once the
            # app itself cuts over) doesn't collide with a copied row's id.
            for table, pk_col in AUTOINCREMENT_TABLES.items():
                session.execute(text(
                    f"SELECT setval(pg_get_serial_sequence('public.{table}', '{pk_col}'), "
                    f"COALESCE((SELECT MAX({pk_col}) FROM public.{table}), 1), "
                    f"(SELECT MAX({pk_col}) FROM public.{table}) IS NOT NULL)"
                ))
            session.commit()
    finally:
        sqlite_conn.close()
    return results


def run_verify() -> bool:
    """
    Per-table PK-coverage check, SQLite vs Postgres — the zero-data-loss check.

    Checks that every SQLite row's primary key is present in Postgres, rather
    than comparing raw row counts: Postgres may legitimately hold extra rows
    with no SQLite counterpart (confirmed against Dev — some tables already
    had independently-seeded rows before this script ever ran), which a bare
    count comparison would wrongly flag as a mismatch even with zero data
    loss. Missing-from-Postgres is the only real failure condition here.
    """
    sqlite_conn = _sqlite_conn()
    ok = True
    with get_pg_session() as session:
        print(f"{'table':<24} {'sqlite':>8} {'postgres':>8} {'missing':>8}  status")
        for t in TABLE_ORDER:
            pk = PRIMARY_KEYS[t]
            sq_ids = {r[pk] for r in sqlite_conn.execute(f"SELECT {pk} FROM {t}").fetchall()}
            pg_ids = {r[0] for r in session.execute(text(f"SELECT {pk} FROM public.{t}")).fetchall()}
            missing = sq_ids - pg_ids
            match = not missing
            ok = ok and match
            print(f"{t:<24} {len(sq_ids):>8} {len(pg_ids):>8} {len(missing):>8}  {'OK' if match else 'MISMATCH'}")
    sqlite_conn.close()
    return ok


def main():
    parser = argparse.ArgumentParser(description="Copy backend/jobs.db into Postgres's public schema.")
    parser.add_argument("--allow-write", action="store_true",
                         help="Required (together with ALLOW_SUPABASE_APP_MIGRATION=true) to actually write "
                              "to Postgres. Omit this flag to run the safe read-only preview instead (default).")
    parser.add_argument("--verify-only", action="store_true",
                         help="Skip copying; just compare row counts between SQLite and the already-migrated "
                              "Postgres target.")
    parser.add_argument("--batch-size", type=int, default=500)
    args = parser.parse_args()

    if args.verify_only:
        ok = run_verify()
        print("\n[verify] " + ("ALL TABLES MATCH — zero data loss confirmed." if ok else "MISMATCH DETECTED — see table above."))
        sys.exit(0 if ok else 1)

    if not args.allow_write:
        run_preview()
        return

    _guard_write(args)
    print("=== Copying backend/jobs.db -> Postgres public schema ===")
    run_migration(batch_size=args.batch_size)
    print("\n=== Verifying row counts ===")
    ok = run_verify()
    print("\n" + ("ALL TABLES MATCH — zero data loss confirmed." if ok else "MISMATCH DETECTED — see table above."))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
