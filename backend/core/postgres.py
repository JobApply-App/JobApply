"""
Dedicated PostgreSQL engine — separate from backend/core/database.py's SQLite
ENGINE, which remains the app's primary datastore (see CLAUDE.md).

This module exists solely for backend/models/linkedin_job.py (schema
`linkedin`, table `jobs`): the LinkedIn ingestion pipeline needs real
Postgres features the SQLite ENGINE cannot provide — a non-default schema,
JSONB, TIMESTAMPTZ, and native `INSERT ... ON CONFLICT DO UPDATE` bulk
upsert. Nothing else in the codebase should import PG_ENGINE/PGSession;
every other table stays on the SQLite ENGINE until a real, project-wide
Postgres migration is planned.

DATABASE_URL (backend/.env, resolved in backend/config.py — see that
module's "App environment" section) may point at any of Supabase's three
connection types; this module adapts to whichever one it gets:
  - Direct connection      (port 5432, no pgbouncer)
  - Session pooler         (port 5432, pgbouncer session mode)
  - Transaction pooler     (port 6543, pgbouncer transaction mode)
Since every other DB access in this codebase is sync SQLAlchemy
(backend/core/database.py, backend/repositories/*), an async-only
`postgresql+asyncpg://` scheme is normalized to plain `postgresql://`
(psycopg2) rather than introducing the project's first async DB path for
one table.
"""
from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session
from sqlalchemy.pool import NullPool

from backend.config import DATABASE_URL

# Supabase's pgbouncer *transaction* pooler (see module docstring). Detected
# purely by port — Supabase always exposes it on 6543, direct/session
# connections on 5432.
_TRANSACTION_POOLER_PORT = 6543


def _to_sync_dsn(url: str) -> str:
    """postgresql+asyncpg://... -> postgresql://... (psycopg2, sync)."""
    if url.startswith("postgresql+asyncpg://"):
        return "postgresql://" + url[len("postgresql+asyncpg://"):]
    return url


def ensure_sslmode(url: str) -> str:
    """
    Add `sslmode=require` if the DSN doesn't already specify one and isn't
    pointed at localhost/127.0.0.1 — Supabase requires TLS on every
    connection type, while a local/dev-container Postgres often has no TLS
    listener at all, so this is skipped for local hosts. Reused by
    backend/alembic_linkedin/env.py so migrations get the same treatment as
    the app's own runtime engine.
    """
    parts = urlsplit(url)
    if parts.hostname in (None, "localhost", "127.0.0.1"):
        return url
    query = dict(parse_qsl(parts.query))
    query.setdefault("sslmode", "require")
    return urlunsplit(parts._replace(query=urlencode(query)))


def _engine_kwargs_for(url: str) -> dict:
    """
    Supabase's transaction pooler (port 6543) already pools connections
    server-side in pgbouncer transaction mode — stacking SQLAlchemy's own
    QueuePool on top of it risks exhausting pgbouncer's own pool under
    concurrent load and can misbehave with session-scoped state (prepared
    statements, advisory locks) that transaction mode doesn't preserve
    across statements. NullPool (one real connection per checkout, closed
    immediately after) sidesteps both. Direct connections and the session
    pooler (5432) keep the default QueuePool with pool_pre_ping to recycle
    stale connections transparently.
    """
    if urlsplit(url).port == _TRANSACTION_POOLER_PORT:
        return {"poolclass": NullPool}
    return {"pool_pre_ping": True}


class LinkedInBase(DeclarativeBase):
    """Declarative base for the `linkedin` schema only — kept separate from
    backend.core.database.Base (SQLite) so the two metadata sets, and their
    migration mechanisms, never mix."""


PG_ENGINE = (
    create_engine(ensure_sslmode(_to_sync_dsn(DATABASE_URL)), **_engine_kwargs_for(DATABASE_URL))
    if DATABASE_URL else None
)


def get_pg_session() -> Session:
    """
    Raises RuntimeError with a clear setup message if DATABASE_URL isn't
    configured, rather than letting callers hit a cryptic None.create_engine
    AttributeError deep in SQLAlchemy.
    """
    if PG_ENGINE is None:
        raise RuntimeError(
            "DATABASE_URL is not set — add it to backend/.env to use the "
            "LinkedIn Postgres ingestion pipeline."
        )
    return Session(PG_ENGINE)
