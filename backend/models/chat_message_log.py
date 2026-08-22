"""ORM model for the Ariel chat audit log — backs the daily per-user message cap.

One row per accepted user turn on either chat surface (POST /chat/stream and
POST /chat/ariel/private — both are presented to the user as "Ariel", and
both bill the same claude-sonnet-4-6 rate). Deliberately NOT an in-memory
counter, same reasoning as backend/models/cv_generation.py: Render's
free-tier instance sleeps and restarts through the day, so an in-memory
daily count would reset itself for free multiple times a day. A DB row
survives restarts and gives an honest, queryable count.

Recorded when the request is accepted and about to stream (not on stream
completion) — a chat turn's cost is already committed once the model starts
generating, unlike a CV generation where a genuinely-failed attempt is
retriable and shouldn't burn the user's daily budget.
"""
from __future__ import annotations

from sqlalchemy import Column, Index, String

from backend.core.database import Base
from backend.models.application import UUID_FK


class ChatMessageLogRow(Base):
    """One row per accepted Ariel chat turn (either /stream or /ariel/private)."""
    __tablename__ = "chat_messages_log"

    id         = Column(String, primary_key=True)
    user_id    = Column(UUID_FK, nullable=False, index=True)
    endpoint   = Column(String, nullable=False)   # "stream" | "ariel_private"
    created_at = Column(String, nullable=False)   # ISO-8601 UTC

    __table_args__ = (
        # Same access path as cv_generations: "count rows for user_id where
        # created_at falls in today," not a plain user_id lookup.
        Index("ix_chat_messages_log_user_created", "user_id", "created_at"),
    )
