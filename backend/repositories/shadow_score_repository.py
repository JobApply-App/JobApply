"""Repository for the shadow_match_scores table.

Consolidates the append-only insert previously inlined in
backend/services/match_score_service.py's _persist_score_audit.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from backend.core.database import ENGINE
from backend.models.matching import ShadowScoreRow


def insert(
    *,
    user_id: str,
    job_title: str,
    company: str,
    existing_score: float,
    ats_score: float,
    breakdown_json: str,
    created_at: str,
    engine: Optional[Engine] = None,
) -> None:
    eng = engine or ENGINE
    with Session(eng) as session:
        session.add(ShadowScoreRow(
            user_id        = user_id,
            job_title      = job_title,
            company        = company,
            existing_score = existing_score,
            ats_score      = ats_score,
            breakdown_json = breakdown_json,
            created_at     = created_at,
        ))
        session.commit()


def first_answer(
    user_id: str, prompt_hash: str, engine: Optional[Engine] = None,
) -> Optional[tuple[str, str]]:
    """
    (answer, model) from the oldest row recording this scorer prompt_hash for
    user_id, or None. The match scorer reuses it so the same input keeps the
    score it got the first time (match_score_service._first_answer).
    """
    import json

    from sqlalchemy import select

    eng = engine or ENGINE
    with Session(eng) as session:
        rows = session.execute(
            select(ShadowScoreRow.breakdown_json)
            .where(ShadowScoreRow.user_id == user_id)
            .where(ShadowScoreRow.breakdown_json.contains(f'"prompt_hash": "{prompt_hash}"'))
            .order_by(ShadowScoreRow.id)
            .limit(1)
        ).scalars().all()
    for blob in rows:
        data = json.loads(blob)
        if data.get("prompt_hash") == prompt_hash and data.get("answer"):
            return data["answer"], data.get("model") or "unknown"
    return None
