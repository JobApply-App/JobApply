"""Repository for the job_feedback table.

Consolidates the CRUD previously inlined in
backend/services/feedback_service.py's _upsert_feedback_row/fetch_feedback_rows.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from backend.core.database import ENGINE
from backend.models.application import JobFeedbackRow


def upsert(
    *,
    user_id: str,
    job_id: str,
    feedback_type: str,
    reason: Optional[str],
    snapshot_json: str,
    now: str,
    engine: Optional[Engine] = None,
) -> None:
    """Latest opinion wins — one row per (user_id, job_id)."""
    eng = engine or ENGINE
    with Session(eng) as session:
        row = (
            session.query(JobFeedbackRow)
            .filter(JobFeedbackRow.user_id == user_id, JobFeedbackRow.job_id == job_id)
            .one_or_none()
        )
        if row is None:
            row = JobFeedbackRow(user_id=user_id, job_id=job_id, created_at=now)
            session.add(row)
        row.feedback_type = feedback_type
        row.reason        = reason
        row.snapshot_json = snapshot_json
        row.updated_at    = now
        session.commit()


def fetch_for_user(user_id: str, engine: Optional[Engine] = None) -> list[dict]:
    import json

    eng = engine or ENGINE
    with Session(eng) as session:
        rows = (
            session.query(JobFeedbackRow)
            .filter(JobFeedbackRow.user_id == user_id)
            .order_by(JobFeedbackRow.updated_at.desc())
            .all()
        )
        out: list[dict] = []
        for r in rows:
            try:
                snapshot = json.loads(r.snapshot_json or "{}")
            except json.JSONDecodeError:
                snapshot = {}
            out.append({
                "job_id":        r.job_id,
                "feedback_type": r.feedback_type,
                "reason":        r.reason,
                "snapshot":      snapshot,
                "updated_at":    r.updated_at,
            })
        return out
