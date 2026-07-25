"""Repository for the conversation_events table.

The only writer is profile_update_service.py's ingest_conversation_event(),
which inserts a conversation_events row inside a larger atomic transaction
that also writes evidence_records, profile_entities, confidence_audit_log,
and ariel_sessions. insert() therefore takes the caller's already-open
Connection rather than opening its own, to preserve that all-or-nothing
commit exactly.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import text
from sqlalchemy.engine import Connection


def insert(
    conn: Connection,
    *,
    event_id: str,
    session_id: str,
    user_id: str,
    star_situation: Optional[str],
    star_task: Optional[str],
    star_action: Optional[str],
    star_result: Optional[str],
    extracted_entity_ids_json: str,
    extraction_confidence: float,
    analyzed_at: str,
    raw_quote: str,
) -> None:
    conn.execute(
        text("""
            INSERT INTO conversation_events
                (event_id, session_id, user_id,
                 star_situation, star_task, star_action, star_result,
                 extracted_entity_ids, extraction_confidence,
                 analyzed_at, raw_quote)
            VALUES
                (:evid, :sid, :uid,
                 :sit, :task, :act, :res,
                 :eids, :conf,
                 :now, :quote)
        """),
        {
            "evid":  event_id,
            "sid":   session_id,
            "uid":   user_id,
            "sit":   star_situation,
            "task":  star_task,
            "act":   star_action,
            "res":   star_result,
            "eids":  extracted_entity_ids_json,
            "conf":  extraction_confidence,
            "now":   analyzed_at,
            "quote": raw_quote,
        },
    )
