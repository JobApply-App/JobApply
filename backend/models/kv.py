"""ORM model for the process-level key-value store.

Extracted from the former backend/services/db.py.
"""
from __future__ import annotations

from sqlalchemy import Column, String, Text

from backend.core.database import Base


class KVRow(Base):
    """
    Lightweight key-value store for ephemeral system state.

    Used for transient values that don't justify a dedicated table:
      • gmail_verification_code — 9-digit code intercepted from Google's
        forwarding confirmation email; read by the frontend modal poller
        and discarded after 30 minutes.

    Schema is intentionally minimal: key is always a short ASCII string,
    value is text, updated_at is an ISO-8601 UTC string for TTL checks.
    """
    __tablename__ = "kv_store"

    key        = Column(String, primary_key=True)
    value      = Column(Text,   nullable=False, default="")
    updated_at = Column(String, nullable=False, default="")
