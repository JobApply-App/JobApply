"""Repository for the ariel_sessions table.

Consolidates the raw ENGINE.begin()/text() CRUD for Ariel conversation
sessions, previously split between the raw-SQL transcript read/write in
backend/api/routes/ariel.py and the session lifecycle helpers
(open_session/close_session) in backend/services/profile_update_service.py.

Every function accepts an optional `engine` override (falling back to the
shared ENGINE, resolved at call time) so ProfileUpdateService — which is
constructed with an injectable engine for testability — can route session
lifecycle writes through its own `self._engine` instead of always hitting
the production database.
"""
from __future__ import annotations

import json
from typing import Optional

from sqlalchemy import text
from sqlalchemy.engine import Engine

from backend.core.database import ENGINE


def create_session(
    *,
    session_id: str,
    user_id: str,
    session_type: str,
    started_at: str,
    target_job_id: Optional[str] = None,
    target_entities: Optional[list[str]] = None,
    ariel_goal: Optional[str] = None,
    engine: Optional[Engine] = None,
) -> None:
    eng = engine or ENGINE
    with eng.begin() as conn:
        conn.execute(
            text("""
                INSERT INTO ariel_sessions
                    (session_id, user_id, session_type,
                     target_job_id, target_entities, ariel_goal,
                     status, started_at)
                VALUES
                    (:sid, :uid, :stype,
                     :jid, :ents, :goal,
                     'active', :now)
            """),
            {
                "sid":   session_id,
                "uid":   user_id,
                "stype": session_type,
                "jid":   target_job_id,
                "ents":  json.dumps(target_entities or []),
                "goal":  ariel_goal,
                "now":   started_at,
            },
        )


def update_status(
    session_id: str,
    status: str,
    ended_at: str,
    engine: Optional[Engine] = None,
) -> None:
    eng = engine or ENGINE
    with eng.begin() as conn:
        conn.execute(
            text("""
                UPDATE ariel_sessions
                SET    status = :status, ended_at = :now
                WHERE  session_id = :sid
            """),
            {"status": status, "now": ended_at, "sid": session_id},
        )


def append_turn(
    session_id: str,
    user_id: str,
    turn: int,
    answer: str,
    engine: Optional[Engine] = None,
) -> Optional[dict]:
    """
    Atomically merge one turn's answer into the session's transcript_json and
    return the resulting transcript, or None if no such session exists for
    this user (scoped to user_id, so a mismatch is indistinguishable from
    "not found").

    Uses a single UPDATE ... RETURNING statement with SQLite's json_set() to
    perform the read, merge, and write as one atomic operation — there is no
    separate SELECT-then-UPDATE window for a concurrent call on the same
    session_id to race into, so two overlapping calls (e.g. a client retry)
    can never silently drop one turn's answer the way a fetch-mutate-save
    round trip would.
    """
    eng = engine or ENGINE
    path = f"$.turn_{int(turn)}"
    with eng.begin() as conn:
        row = conn.execute(
            text("""
                UPDATE ariel_sessions
                SET    transcript_json = json_set(COALESCE(transcript_json, '{}'), :path, :answer)
                WHERE  session_id = :sid AND user_id = :uid
                RETURNING transcript_json
            """),
            {"path": path, "answer": answer, "sid": session_id, "uid": user_id},
        ).fetchone()
        if row is None:
            return None
        return json.loads(row[0] or "{}")
