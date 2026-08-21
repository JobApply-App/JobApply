"""Repository for cv_generations — backs the daily per-user generation cap.

See backend/models/cv_generation.py for why this is a DB table rather than
an in-memory counter.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.core.database import ENGINE
from backend.models.cv_generation import CvGenerationRow


def _today_start_utc() -> str:
    """
    ISO-8601 UTC midnight for 'today'. String comparison against created_at
    (also ISO-8601 UTC) works correctly because ISO-8601's lexicographic
    order matches chronological order — no date-parsing needed on either
    side, and it's dialect-portable (SQLite has no native DATE type).

    UTC, not the user's local day: a hard boundary has to pick one clock,
    and UTC is what every other created_at/updated_at string in this
    codebase already uses (see ApplicationRow, KVRow) — consistent with the
    rest of the schema rather than introducing a per-feature timezone.
    """
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT00:00:00")


def count_today(user_id: str) -> int:
    """How many CVs user_id has generated since UTC midnight today."""
    with Session(ENGINE) as session:
        return (
            session.query(func.count(CvGenerationRow.id))
            .filter(
                CvGenerationRow.user_id == user_id,
                CvGenerationRow.created_at >= _today_start_utc(),
            )
            .scalar()
        ) or 0


def record(user_id: str, job_id: str) -> None:
    """Log one successful generation. Called AFTER the CV is actually built —
    a failed generation must not count against the user's daily cap."""
    with Session(ENGINE) as session:
        session.add(CvGenerationRow(
            id=uuid.uuid4().hex,
            user_id=user_id,
            job_id=job_id,
            created_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
        ))
        session.commit()
