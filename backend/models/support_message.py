"""ORM model for Eliya's support conversations.

One row per message (the visitor's or Eliya's). A conversation is keyed by the
browser's anonymous session_id; once the visitor is signed in, user_id is set
on every row of that session, so the conversation follows them to any device.
Rows older than SUPPORT_RETENTION_DAYS (90) are deleted — see
backend/repositories/support_message_repository.py.
"""
from __future__ import annotations

from sqlalchemy import Column, Index, String, Text

from backend.core.database import Base
from backend.models.application import UUID_FK


class SupportMessageRow(Base):
    __tablename__ = "support_messages"

    id         = Column(String, primary_key=True)
    session_id = Column(String, nullable=False)
    user_id    = Column(UUID_FK, nullable=True)     # null until the visitor signs in
    role       = Column(String, nullable=False)     # "user" | "assistant"
    content    = Column(Text, nullable=False)
    created_at = Column(String, nullable=False)     # ISO-8601 UTC

    __table_args__ = (
        Index("ix_support_messages_session_created", "session_id", "created_at"),
        Index("ix_support_messages_user_created", "user_id", "created_at"),
    )
