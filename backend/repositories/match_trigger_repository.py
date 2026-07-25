"""Repository for the match_triggers table.

Consolidates the CRUD previously inlined in
backend/services/match_trigger_service.py (_insert_trigger_row,
fetch_pending_triggers, mark_triggers_consumed). Business logic
(should_trigger, evaluate_match_trigger, schedule_match_trigger) stays in
match_trigger_service.py, which now calls through to this module.

Every function accepts an optional `engine` override (falling back to the
shared ENGINE, resolved at call time) — the service's own functions already
take an injectable `engine` for testability.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.core.database import ENGINE
from backend.models.matching import MatchTriggerRow


def insert(
    *,
    job_id: str,
    user_id: str,
    score: float,
    threshold: float,
    payload_json: str,
    created_at: str,
    engine: Optional[Engine] = None,
) -> bool:
    """
    INSERT the trigger row. Returns True if this call created the event,
    False if the (user, job) pair already fired (UNIQUE conflict).
    """
    eng = engine or ENGINE
    row = MatchTriggerRow(
        user_id      = user_id,
        job_id       = job_id,
        score        = score,
        threshold    = threshold,
        payload_json = payload_json,
        status       = "pending",
        created_at   = created_at,
    )
    with Session(eng) as session:
        session.add(row)
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            return False
    return True


def fetch_pending(user_id: str, limit: int = 50, engine: Optional[Engine] = None) -> list[dict]:
    """Return the user's un-consumed trigger events, newest first."""
    import json

    eng = engine or ENGINE
    with Session(eng) as session:
        rows = (
            session.query(MatchTriggerRow)
            .filter(
                MatchTriggerRow.user_id == user_id,
                MatchTriggerRow.status  == "pending",
            )
            .order_by(MatchTriggerRow.id.desc())
            .limit(limit)
            .all()
        )
        out: list[dict] = []
        for r in rows:
            try:
                payload = json.loads(r.payload_json or "{}")
            except json.JSONDecodeError:
                payload = {}
            out.append({
                "id":         r.id,
                "job_id":     r.job_id,
                "score":      r.score,
                "created_at": r.created_at,
                **payload,
            })
        return out


def mark_consumed(trigger_ids: list[int], consumed_at: str, engine: Optional[Engine] = None) -> int:
    """Mark the given trigger ids as consumed. Returns the number of rows updated."""
    if not trigger_ids:
        return 0
    eng = engine or ENGINE
    with Session(eng) as session:
        updated = (
            session.query(MatchTriggerRow)
            .filter(
                MatchTriggerRow.id.in_(trigger_ids),
                MatchTriggerRow.status == "pending",
            )
            .update(
                {"status": "consumed", "consumed_at": consumed_at},
                synchronize_session=False,
            )
        )
        session.commit()
        return int(updated)
