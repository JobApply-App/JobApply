"""
Database engine and declarative base.

Extracted from the former backend/services/db.py during the repo restructure
(backend/models/* now holds the ORM classes; backend/core/migrations.py holds
the migration functions). This module is intentionally minimal: engine setup,
the SQLite connect-time pragma, and the shared declarative Base every ORM
class in backend/models/ imports from.

Engine selection: when DATABASE_URL is configured, ENGINE points at that
Postgres database (same resolution/SSL/pooling logic as backend/core/
postgres.py's PG_ENGINE, so both point at the same physical Supabase project
once cut over — schema managed by backend/alembic_app_schema/; the one-time
SQLite-jobs.db-to-Postgres data copy already ran and its script has since
been removed). When DATABASE_URL is unset, ENGINE falls back to the local
SQLite file exactly as before — this keeps offline/local dev and any test
suite that doesn't configure DATABASE_URL working unchanged.
"""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase

from backend.config import DATABASE_URL
from backend.core.postgres import _engine_kwargs_for, _to_sync_dsn, ensure_sslmode

# Place jobs.db next to main.py inside the backend/ directory
_DB_PATH = Path(__file__).resolve().parent.parent / "jobs.db"

if DATABASE_URL:
    ENGINE = create_engine(ensure_sslmode(_to_sync_dsn(DATABASE_URL)), **_engine_kwargs_for(DATABASE_URL))
else:
    ENGINE = create_engine(
        f"sqlite:///{_DB_PATH}",
        connect_args={"check_same_thread": False},
    )


@event.listens_for(ENGINE, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    if ENGINE.dialect.name != "sqlite":
        return
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA encoding = 'UTF-8'")
    cursor.close()


class Base(DeclarativeBase):
    pass
