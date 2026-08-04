"""
Unit tests — GET /api/chat/history AUTOCOMMIT fix.

Confirms the AUTOCOMMIT-scoped read session (backend/api/routes/history.py's
_get_read_db(), used by list_sessions()/get_session()) preserves exact
output vs. the engine's default (transactional) mode — AUTOCOMMIT only
removes the implicit rollback-on-close cost, it must never change what's
returned. upsert_session() is untouched (still uses _get_db(), the default
transactional session, since it commits a write).

Runs against the real Postgres DB (db_available fixture) — the QA account
below has 14 real chat sessions (~728KB total messages_json).
"""
from __future__ import annotations

from sqlalchemy.orm import Session

_QA_USER_A = "e2472fa3-db25-4e53-9d0b-2aed67bcfe0e"   # real account with 14 chat sessions


def test_list_sessions_matches_default_mode(db_available):
    from backend.api.deps import CurrentUser
    from backend.api.routes.history import list_sessions, MAIN_ENGINE

    user = CurrentUser(user_id=_QA_USER_A, email="qa@test.com", name="QA")

    with Session(MAIN_ENGINE) as db:
        expected = list_sessions(user=user, db=db)

    with MAIN_ENGINE.connect().execution_options(isolation_level="AUTOCOMMIT") as conn, \
            Session(bind=conn) as db:
        got = list_sessions(user=user, db=db)

    assert [s.session_id for s in got] == [s.session_id for s in expected]
    assert [s.message_count for s in got] == [s.message_count for s in expected]
    assert [s.preview for s in got] == [s.preview for s in expected]
