"""Repository for the recruiter_reply_drafts table.

Consolidates the single insert previously inlined in
backend/services/orchestrator.py's draft_recruiter_reply.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from backend.core.database import ENGINE
from backend.models.application import RecruiterReplyDraftRow


def insert(
    *,
    draft_id: str,
    user_id: str,
    job_id: str,
    email_excerpt: str,
    draft_text: str,
    status: str,
    created_at: str,
) -> None:
    with Session(ENGINE) as session:
        session.add(RecruiterReplyDraftRow(
            draft_id      = draft_id,
            user_id       = user_id,
            job_id        = job_id,
            email_excerpt = email_excerpt,
            draft_text    = draft_text,
            status        = status,
            created_at    = created_at,
        ))
        session.commit()


def reassign_user(old_user_id: str, new_user_id: str, session: Session) -> int:
    """
    Re-point every RecruiterReplyDraftRow owned by old_user_id to new_user_id.

    Takes an already-open Session so the caller (account-linking/migration
    flows in auth.py) can combine this with reassignments on other tables
    in one atomic commit.
    """
    return (
        session.query(RecruiterReplyDraftRow)
        .filter(RecruiterReplyDraftRow.user_id == old_user_id)
        .update({"user_id": new_user_id}, synchronize_session="fetch")
    )
