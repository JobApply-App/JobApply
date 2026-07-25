"""
Chat session history — persistence layer for ArielChat Phase 3.

Routes
------
GET  /api/chat/history                  → List[SessionSummary]   (newest first)
GET  /api/chat/history/{session_id}     → SessionDetail
POST /api/chat/history                  → SessionSummary (upsert)

Storage
-------
Sessions are stored in a single SQLite table `chat_sessions` (JSON-column
approach — no per-message rows).  This keeps the schema trivial and makes
the upsert atomic.  If you later need full-text search on history, the migration
path is straightforward: pull messages out of the JSON column into their own table.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import Column, DateTime, Integer, String, Text, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Session

from backend.api.deps import CurrentUser, get_current_user
from backend.core.database import ENGINE as MAIN_ENGINE   # reuse the same DB file

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# ORM
# ─────────────────────────────────────────────────────────────────────────────

class _Base(DeclarativeBase):
    pass


class ChatSessionRow(_Base):
    __tablename__ = "chat_sessions"

    id           = Column(Integer, primary_key=True, autoincrement=True)
    session_id   = Column(String(64),  nullable=False, unique=True, index=True)
    user_id      = Column(String(64),  nullable=False, index=True, default="default")
    messages_json = Column(Text,       nullable=False, default="[]")
    created_at   = Column(DateTime,    nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at   = Column(DateTime,    nullable=False, default=lambda: datetime.now(timezone.utc),
                          onupdate=lambda: datetime.now(timezone.utc))


def _init_history_table() -> None:
    _Base.metadata.create_all(MAIN_ENGINE)


_init_history_table()

# ─────────────────────────────────────────────────────────────────────────────
# Pydantic models (mirror the TypeScript ChatMessage interface)
# ─────────────────────────────────────────────────────────────────────────────

class ImageAttachmentSchema(BaseModel):
    base64:     str   # empty string when stripped; real URL in Phase 4
    mediaType:  str
    previewUrl: str
    name:       str


class ChatMessageSchema(BaseModel):
    id:                 str
    role:               Literal["user", "assistant"]
    content:            str
    isPinned:           Optional[bool] = None
    translatedContent:  Optional[str]  = None
    replyContext:       Optional[str]  = None
    image:              Optional[ImageAttachmentSchema] = None


class ChatSessionUpsert(BaseModel):
    session_id: str
    messages:   List[ChatMessageSchema]


class SessionSummary(BaseModel):
    session_id:    str
    created_at:    str   # ISO-8601
    updated_at:    str
    preview:       str   # first user message, truncated to 80 chars
    message_count: int


class SessionDetail(BaseModel):
    session_id: str
    messages:   List[ChatMessageSchema]
    created_at: str
    updated_at: str


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _to_iso(dt: datetime) -> str:
    """Ensure UTC offset is present before formatting."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _preview(messages: List[ChatMessageSchema]) -> str:
    for m in messages:
        if m.role == "user" and m.content.strip():
            text = m.content.strip().replace("\n", " ")
            return text[:80] + ("…" if len(text) > 80 else "")
    return ""


def _get_db():
    with Session(MAIN_ENGINE) as session:
        yield session


# ─────────────────────────────────────────────────────────────────────────────
# Router
# ─────────────────────────────────────────────────────────────────────────────

router = APIRouter()


@router.get("/history", response_model=List[SessionSummary])
def list_sessions(
    user: CurrentUser = Depends(get_current_user),
    db:   Session     = Depends(_get_db),
):
    """Return all sessions for the authenticated user, newest first."""
    rows = (
        db.execute(
            select(ChatSessionRow)
            .where(ChatSessionRow.user_id == user.user_id)
            .order_by(ChatSessionRow.updated_at.desc())
        )
        .scalars()
        .all()
    )
    result: List[SessionSummary] = []
    for row in rows:
        try:
            messages = [ChatMessageSchema(**m) for m in json.loads(row.messages_json or "[]")]
        except Exception:
            messages = []
        result.append(SessionSummary(
            session_id    = row.session_id,
            created_at    = _to_iso(row.created_at),
            updated_at    = _to_iso(row.updated_at),
            preview       = _preview(messages),
            message_count = len(messages),
        ))
    return result


@router.get("/history/{session_id}", response_model=SessionDetail)
def get_session(
    session_id: str,
    user: CurrentUser = Depends(get_current_user),
    db:   Session     = Depends(_get_db),
):
    """Return the full message list for a session owned by the caller."""
    row = db.execute(
        select(ChatSessionRow).where(
            ChatSessionRow.session_id == session_id,
            ChatSessionRow.user_id    == user.user_id,
        )
    ).scalar_one_or_none()

    # 404 on both absent and not-owned — never leak another user's session existence.
    if row is None:
        raise HTTPException(status_code=404, detail="Session not found")

    try:
        messages = [ChatMessageSchema(**m) for m in json.loads(row.messages_json or "[]")]
    except Exception as exc:
        logger.warning("[history] Failed to parse messages for session %s: %s", session_id, exc)
        messages = []

    return SessionDetail(
        session_id = row.session_id,
        messages   = messages,
        created_at = _to_iso(row.created_at),
        updated_at = _to_iso(row.updated_at),
    )


@router.post("/history", response_model=SessionSummary)
def upsert_session(
    payload: ChatSessionUpsert,
    user: CurrentUser = Depends(get_current_user),
    db:   Session     = Depends(_get_db),
):
    """Create or fully replace a session's message list (upsert by session_id)."""
    now = datetime.now(timezone.utc)

    # session_id is globally unique, so look it up by id then verify ownership.
    # A row that exists under a different user is treated as 404 (don't leak,
    # and don't let one user overwrite another's session).
    row = db.execute(
        select(ChatSessionRow).where(ChatSessionRow.session_id == payload.session_id)
    ).scalar_one_or_none()

    if row is not None and row.user_id != user.user_id:
        raise HTTPException(status_code=404, detail="Session not found")

    serialised = json.dumps(
        [m.model_dump(exclude_none=True) for m in payload.messages],
        ensure_ascii=False,
    )

    if row is None:
        row = ChatSessionRow(
            session_id    = payload.session_id,
            user_id       = user.user_id,
            messages_json = serialised,
            created_at    = now,
            updated_at    = now,
        )
        db.add(row)
    else:
        row.messages_json = serialised
        row.updated_at    = now

    db.commit()
    db.refresh(row)

    logger.info(
        "[history] Upserted session %s for user=%s  messages=%d",
        payload.session_id, user.user_id, len(payload.messages),
    )

    return SessionSummary(
        session_id    = row.session_id,
        created_at    = _to_iso(row.created_at),
        updated_at    = _to_iso(row.updated_at),
        preview       = _preview(payload.messages),
        message_count = len(payload.messages),
    )
