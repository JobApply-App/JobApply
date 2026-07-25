"""Repository for the ariel_gap_queue table.

profile_update_service.py's enqueue_gap() reads profile_entities and
ariel_gap_queue together in one transaction (the entity's current confidence
feeds the idempotency check and severity calc), so find_open_gap()/insert()
take the caller's already-open Connection rather than opening their own —
splitting that transaction would change its atomicity. resolve_gap() is a
genuinely standalone, single-table write, so resolve() opens its own
transaction (mirrors ariel_session_repository.update_status's pattern).
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from backend.core.database import ENGINE


def find_open_gap(
    conn: Connection,
    user_id: str,
    entity_id: str,
    job_id: Optional[str],
) -> Optional[str]:
    """Return the gap_id of an existing pending/in_session gap for this triple, or None."""
    row = conn.execute(
        text("""
            SELECT gap_id FROM ariel_gap_queue
            WHERE  user_id = :uid
              AND  entity_id = :eid
              AND  (job_id = :jid OR (:jid IS NULL AND job_id IS NULL))
              AND  status IN ('pending', 'in_session')
        """),
        {"uid": user_id, "eid": entity_id, "jid": job_id},
    ).fetchone()
    return row[0] if row else None


def insert(
    conn: Connection,
    *,
    gap_id: str,
    user_id: str,
    entity_id: str,
    job_id: Optional[str],
    current_confidence: float,
    required_confidence: float,
    gap_severity: str,
    detected_at: str,
) -> None:
    conn.execute(
        text("""
            INSERT INTO ariel_gap_queue
                (gap_id, user_id, entity_id, job_id,
                 current_confidence, required_confidence, gap_severity,
                 status, detected_at)
            VALUES
                (:gid, :uid, :eid, :jid,
                 :cur, :req, :sev,
                 'pending', :now)
        """),
        {
            "gid": gap_id, "uid": user_id, "eid": entity_id, "jid": job_id,
            "cur": current_confidence, "req": required_confidence, "sev": gap_severity,
            "now": detected_at,
        },
    )


def resolve(gap_id: str, resolved_at: str, engine: Optional[Engine] = None) -> None:
    """Mark a gap as resolved (entity score now meets threshold)."""
    eng = engine or ENGINE
    with eng.begin() as conn:
        conn.execute(
            text("""
                UPDATE ariel_gap_queue
                SET    status = 'resolved', resolved_at = :now
                WHERE  gap_id = :gid
            """),
            {"now": resolved_at, "gid": gap_id},
        )
