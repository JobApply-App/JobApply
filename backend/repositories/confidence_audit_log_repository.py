"""Repository for the confidence_audit_log table.

Consolidates the raw-SQL read used by backend/api/routes/ariel.py's
GET /api/ariel/audit/{entity_id} endpoint.

Does NOT cover profile_update_service.py's audit-log writes (_recompute_and_
persist's INSERT) — those are append-only inserts inside larger, atomic
multi-table transactions and stay where they are (repository-consumer
pattern).
"""
from __future__ import annotations

from sqlalchemy import text

from backend.core.database import ENGINE


def get_recent_for_entity(entity_id: str, limit: int = 50) -> list[dict]:
    """Most recent confidence_audit_log rows for entity_id, newest first."""
    with ENGINE.connect() as conn:
        rows = conn.execute(
            text("""
                SELECT
                    log_id, old_score, new_score, delta,
                    trigger_source, changed_at, note
                FROM confidence_audit_log
                WHERE entity_id = :eid
                ORDER BY changed_at DESC
                LIMIT :lim
            """),
            {"eid": entity_id, "lim": limit},
        ).fetchall()

    return [
        {
            "log_id":         r[0],
            "old_score":      r[1],
            "new_score":      r[2],
            "delta":          r[3],
            "trigger_source": r[4],
            "changed_at":     r[5],
            "note":           r[6],
        }
        for r in rows
    ]
