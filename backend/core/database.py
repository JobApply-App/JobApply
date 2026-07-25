"""
Database engine and declarative base.

Extracted from the former backend/services/db.py during the repo restructure
(backend/models/* now holds the ORM classes; backend/core/migrations.py holds
the migration functions). This module is intentionally minimal: engine setup,
the SQLite connect-time pragma, and the shared declarative Base every ORM
class in backend/models/ imports from.
"""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase

# Place jobs.db next to main.py inside the backend/ directory
_DB_PATH = Path(__file__).resolve().parent.parent / "jobs.db"
ENGINE   = create_engine(
    f"sqlite:///{_DB_PATH}",
    connect_args={"check_same_thread": False},
)


@event.listens_for(ENGINE, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA encoding = 'UTF-8'")
    cursor.close()


class Base(DeclarativeBase):
    pass
