"""Repository for support_messages — Eliya's saved support conversations.

See backend/models/support_message.py. A conversation is identified by the
signed-in user when there is one, otherwise by the browser's session_id.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from backend.core.database import ENGINE
from backend.models.support_message import SupportMessageRow

SUPPORT_RETENTION_DAYS = 90


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")


def _owner_filter(session_id: str, user_id: Optional[str]):
    if user_id:
        return SupportMessageRow.user_id == user_id
    # An anonymous visitor sees only the anonymous rows of their own session,
    # never a signed-in user's rows that share the browser's session_id.
    return (SupportMessageRow.session_id == session_id) & (SupportMessageRow.user_id.is_(None))


def add(session_id: str, user_id: Optional[str], role: str, content: str) -> None:
    with Session(ENGINE) as session:
        session.add(SupportMessageRow(
            id=uuid.uuid4().hex, session_id=session_id, user_id=user_id,
            role=role, content=content, created_at=_now(),
        ))
        session.commit()


def claim_session(session_id: str, user_id: str) -> None:
    """Attach the anonymous rows of session_id to user_id, so a visitor who
    talked to Eliya before signing in keeps that conversation."""
    with Session(ENGINE) as session:
        (session.query(SupportMessageRow)
            .filter(SupportMessageRow.session_id == session_id, SupportMessageRow.user_id.is_(None))
            .update({SupportMessageRow.user_id: user_id}, synchronize_session=False))
        session.commit()


def recent(session_id: str, user_id: Optional[str], limit: int) -> list[dict]:
    """The last `limit` messages of the conversation, oldest first."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=SUPPORT_RETENTION_DAYS)).strftime("%Y-%m-%dT%H:%M:%S")
    with Session(ENGINE) as session:
        rows = (session.query(SupportMessageRow)
                .filter(_owner_filter(session_id, user_id), SupportMessageRow.created_at >= cutoff)
                .order_by(SupportMessageRow.created_at.desc())
                .limit(limit)
                .all())
    return [{"role": r.role, "content": r.content} for r in reversed(rows)]


def clear(session_id: str, user_id: Optional[str]) -> None:
    """Delete the caller's whole conversation (the panel's clear button)."""
    with Session(ENGINE) as session:
        (session.query(SupportMessageRow)
            .filter(_owner_filter(session_id, user_id))
            .delete(synchronize_session=False))
        session.commit()


def purge_expired() -> int:
    """Delete messages older than SUPPORT_RETENTION_DAYS. Returns rows deleted."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=SUPPORT_RETENTION_DAYS)).strftime("%Y-%m-%dT%H:%M:%S")
    with Session(ENGINE) as session:
        n = (session.query(SupportMessageRow)
             .filter(SupportMessageRow.created_at < cutoff)
             .delete(synchronize_session=False))
        session.commit()
    return n
