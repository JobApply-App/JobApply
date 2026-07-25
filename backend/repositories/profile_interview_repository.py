"""Repository for the profile_interviews table.

Consolidates CRUD previously inlined across backend/agents/profile_interviewer.py
(session create / read / turn-persist / resume-persist) and the document-
verification confidence_map update in backend/api/routes/profile.py.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from backend.core.database import ENGINE
from backend.models.profile import ProfileInterviewRow


def create(
    *,
    session_id: str,
    user_id: str,
    messages: list,
    status: str,
    intent: Optional[str],
    now: str,
) -> None:
    with Session(ENGINE) as session:
        session.add(ProfileInterviewRow(
            session_id     = session_id,
            user_id        = user_id,
            messages       = messages,
            draft_profile  = None,
            confidence_map = {},
            pending_probes = [],
            document_refs  = [],
            status         = status,
            intent         = intent,
            created_at     = now,
            updated_at     = now,
        ))
        session.commit()


def get(session_id: str) -> Optional[dict]:
    """Return a plain-dict snapshot of the session, or None if not found."""
    with Session(ENGINE) as session:
        row = session.get(ProfileInterviewRow, session_id)
        if row is None:
            return None
        return {
            "session_id":     row.session_id,
            "user_id":        row.user_id,
            "messages":       row.messages or [],
            "draft_profile":  row.draft_profile,
            "confidence_map": row.confidence_map or {},
            "pending_probes": row.pending_probes or [],
            "document_refs":  row.document_refs or [],
            "status":         row.status,
            "intent":         row.intent,
        }


def update_full(
    session_id: str,
    *,
    messages: list,
    draft_profile: Optional[dict],
    confidence_map: dict,
    pending_probes: list,
    now: str,
) -> bool:
    """Persist a full processed turn. Returns False if the session no longer exists."""
    with Session(ENGINE) as session:
        row = session.get(ProfileInterviewRow, session_id)
        if row is None:
            return False
        row.messages       = messages
        row.draft_profile  = draft_profile
        row.confidence_map = confidence_map
        row.pending_probes = pending_probes
        row.updated_at     = now
        session.commit()
        return True


def update_messages(session_id: str, *, messages: list, now: str) -> bool:
    """Persist only the message history (used by resume_session). Returns False if absent."""
    with Session(ENGINE) as session:
        row = session.get(ProfileInterviewRow, session_id)
        if row is None:
            return False
        row.messages   = messages
        row.updated_at = now
        session.commit()
        return True


def update_confidence_and_docs(
    session_id: str,
    *,
    confidence_map: dict,
    document_refs: list,
) -> bool:
    """Persist a document-verification result. Returns False if the session doesn't exist."""
    with Session(ENGINE) as session:
        row = session.get(ProfileInterviewRow, session_id)
        if row is None:
            return False
        row.confidence_map = confidence_map
        row.document_refs  = document_refs
        session.commit()
        return True


def count_for_user(user_id: str, session: Optional[Session] = None) -> int:
    """Number of ProfileInterviewRow rows owned by user_id."""
    if session is not None:
        return session.query(ProfileInterviewRow).filter(ProfileInterviewRow.user_id == user_id).count()
    with Session(ENGINE) as owned_session:
        return owned_session.query(ProfileInterviewRow).filter(ProfileInterviewRow.user_id == user_id).count()


def reassign_user(old_user_id: str, new_user_id: str, session: Session) -> int:
    """
    Re-point every ProfileInterviewRow owned by old_user_id to new_user_id.

    Takes an already-open Session so the caller (account-linking/migration
    flows in auth.py) can combine this with reassignments on other tables
    in one atomic commit.
    """
    return (
        session.query(ProfileInterviewRow)
        .filter(ProfileInterviewRow.user_id == old_user_id)
        .update({"user_id": new_user_id}, synchronize_session="fetch")
    )
