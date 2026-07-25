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
