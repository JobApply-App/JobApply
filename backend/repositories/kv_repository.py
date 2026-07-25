"""Repository for the process-level kv_store table.

Consolidates the raw Session(ENGINE)/KVRow CRUD previously inlined across
backend/api/routes/settings.py, backend/api/routes/webhooks.py, and
backend/scripts/reset_linkedin_scraper.py.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from backend.core.database import ENGINE
from backend.models.kv import KVRow


@dataclass(frozen=True)
class KVEntry:
    key: str
    value: str
    updated_at: str


def get(key: str, session: Optional[Session] = None) -> Optional[KVEntry]:
    """
    Accepts an optional already-open Session so a caller performing several
    KV operations in sequence (e.g. reset_linkedin_scraper.py's multi-key
    pause/resume) can share one session/transaction instead of each call
    committing independently — see kv_session() below.
    """
    if session is not None:
        return _get(session, key)
    with Session(ENGINE) as owned_session:
        return _get(owned_session, key)


def _get(session: Session, key: str) -> Optional[KVEntry]:
    row = session.get(KVRow, key)
    if row is None:
        return None
    return KVEntry(key=row.key, value=row.value, updated_at=row.updated_at)


def get_many(keys: list[str], session: Optional[Session] = None) -> dict[str, KVEntry]:
    """Batch read — one session for all keys, missing keys simply absent from the result."""
    if session is not None:
        return _get_many(session, keys)
    with Session(ENGINE) as owned_session:
        return _get_many(owned_session, keys)


def _get_many(session: Session, keys: list[str]) -> dict[str, KVEntry]:
    result: dict[str, KVEntry] = {}
    for key in keys:
        row = session.get(KVRow, key)
        if row is not None:
            result[key] = KVEntry(key=row.key, value=row.value, updated_at=row.updated_at)
    return result


def upsert(
    key: str,
    value: str,
    updated_at: Optional[str] = None,
    session: Optional[Session] = None,
) -> None:
    ts = updated_at or datetime.now(timezone.utc).isoformat()
    if session is not None:
        _upsert(session, key, value, ts)
        return
    with Session(ENGINE) as owned_session:
        _upsert(owned_session, key, value, ts)
        owned_session.commit()


def _upsert(session: Session, key: str, value: str, ts: str) -> None:
    row = session.get(KVRow, key)
    if row:
        row.value = value
        row.updated_at = ts
    else:
        session.add(KVRow(key=key, value=value, updated_at=ts))


def delete(key: str, session: Optional[Session] = None) -> bool:
    """Return True if a row was deleted, False if the key was already absent."""
    if session is not None:
        return _delete(session, key)
    with Session(ENGINE) as owned_session:
        found = _delete(owned_session, key)
        owned_session.commit()
        return found


def _delete(session: Session, key: str) -> bool:
    row = session.get(KVRow, key)
    if row is None:
        return False
    session.delete(row)
    return True


@contextmanager
def kv_session():
    """
    Context manager yielding a Session for a caller that needs to combine
    several get/upsert/delete calls into one atomic commit (e.g. a
    multi-key delete-then-upsert sequence). Commits on clean exit, rolls
    back (via the Session's own context-manager behavior) on exception.

    Usage:
        with kv_repository.kv_session() as s:
            kv_repository.delete("a", session=s)
            kv_repository.delete("b", session=s)
            kv_repository.upsert("c", "1", session=s)
        # committed here, atomically, as one transaction
    """
    with Session(ENGINE) as session:
        yield session
        session.commit()
