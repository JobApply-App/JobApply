"""Repository for chat_messages_log — backs the daily per-user Ariel message cap.

See backend/models/chat_message_log.py for why this is a DB table rather than
an in-memory counter.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.core.database import ENGINE
from backend.models.chat_message_log import ChatMessageLogRow


def _today_start_utc() -> str:
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT00:00:00")


def count_today(user_id: str) -> int:
    """How many Ariel turns (either endpoint) user_id has sent since UTC midnight today."""
    with Session(ENGINE) as session:
        return (
            session.query(func.count(ChatMessageLogRow.id))
            .filter(
                ChatMessageLogRow.user_id == user_id,
                ChatMessageLogRow.created_at >= _today_start_utc(),
            )
            .scalar()
        ) or 0


def record(user_id: str, endpoint: str) -> None:
    """Log one accepted chat turn, right before streaming begins."""
    with Session(ENGINE) as session:
        session.add(ChatMessageLogRow(
            id=uuid.uuid4().hex,
            user_id=user_id,
            endpoint=endpoint,
            created_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
        ))
        session.commit()
