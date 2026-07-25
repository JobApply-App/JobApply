"""ORM models for the Ariel conversational agent.

Extracted from the former backend/services/db.py.
"""
from __future__ import annotations

from sqlalchemy import Column, Float, String, Text

from backend.core.database import Base


class ArielSessionRow(Base):
    """One purposeful Ariel conversation session."""
    __tablename__ = "ariel_sessions"

    session_id             = Column(String, primary_key=True)
    user_id                = Column(String, nullable=False, index=True)
    tenant_id              = Column(String, nullable=True, index=True)   # see JobRow.tenant_id docstring
    session_type           = Column(String, nullable=False)
    target_job_id          = Column(String, nullable=True, index=True)
    target_entities        = Column(Text,   nullable=True)    # JSON array
    ariel_goal             = Column(Text,   nullable=True)
    status                 = Column(String, nullable=False, default="active")
    transcript_json        = Column(Text,   nullable=True)
    confidence_delta_total = Column(Float,  nullable=False, default=0.0)
    started_at             = Column(String, nullable=False)
    ended_at               = Column(String, nullable=True)


class ConversationEventRow(Base):
    """One STAR behavioral event extracted by the LLM from a session transcript."""
    __tablename__ = "conversation_events"

    event_id              = Column(String, primary_key=True)
    session_id            = Column(String, nullable=False, index=True)
    user_id               = Column(String, nullable=False, index=True)
    tenant_id             = Column(String, nullable=True, index=True)   # see JobRow.tenant_id docstring
    star_situation        = Column(Text,   nullable=True)
    star_task             = Column(Text,   nullable=True)
    star_action           = Column(Text,   nullable=True)
    star_result           = Column(Text,   nullable=True)
    extracted_entity_ids  = Column(Text,   nullable=False)   # JSON array
    extraction_confidence = Column(Float,  nullable=False)
    raw_quote             = Column(Text,   nullable=True)
    analyzed_at           = Column(String, nullable=False)


class ArielGapQueueRow(Base):
    """Ariel's work queue: skills/traits that need evidence for priority jobs."""
    __tablename__ = "ariel_gap_queue"

    gap_id              = Column(String, primary_key=True)
    user_id             = Column(String, nullable=False, index=True)
    tenant_id           = Column(String, nullable=True, index=True)   # see JobRow.tenant_id docstring
    entity_id           = Column(String, nullable=False)
    job_id              = Column(String, nullable=True,  index=True)
    current_confidence  = Column(Float,  nullable=False)
    required_confidence = Column(Float,  nullable=False)
    gap_severity        = Column(String, nullable=False)
    status              = Column(String, nullable=False, default="pending")
    session_id          = Column(String, nullable=True)
    detected_at         = Column(String, nullable=False)
    resolved_at         = Column(String, nullable=True)
