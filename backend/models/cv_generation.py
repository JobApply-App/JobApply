"""ORM model for the CV generation audit log — backs the daily per-user cap.

One row per successful POST /tailor call (initial generation AND
force=true regenerate — both are a real LLM generation, both should count).
Deliberately NOT an in-memory counter: the existing llm_rate_limit
(backend/api/deps.py) is a per-minute burst guard that resets on process
restart, which is fine for its purpose but wrong for a daily cap — Render's
free-tier instance sleeps and restarts through the day (see config.py's
DISCOVERY_INTERVAL_SECONDS comment), so an in-memory daily count would reset
itself for free multiple times a day. A DB row survives restarts and gives
an honest, queryable count.
"""
from __future__ import annotations

from sqlalchemy import Column, Index, String

from backend.core.database import Base
from backend.models.application import UUID_FK


class CvGenerationRow(Base):
    """One row per POST /tailor call that actually produced a CV."""
    __tablename__ = "cv_generations"

    id         = Column(String, primary_key=True)
    user_id    = Column(UUID_FK, nullable=False, index=True)
    job_id     = Column(String, nullable=False)
    created_at = Column(String, nullable=False)   # ISO-8601 UTC

    __table_args__ = (
        # The daily-cap check is "count rows for user_id where created_at
        # falls in today" — this composite index is exactly that query's
        # access path, not a generic user_id lookup alone.
        Index("ix_cv_generations_user_created", "user_id", "created_at"),
    )
