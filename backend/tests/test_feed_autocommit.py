"""
Unit tests — job_repository.get_feed() AUTOCOMMIT fix.

Confirms the AUTOCOMMIT-scoped connection (backend/repositories/job_repository.py's
get_feed()) preserves exact output vs. the engine's default (transactional)
mode — AUTOCOMMIT only removes the implicit rollback-on-close cost, it must
never change what's returned.

Runs against the real Postgres DB (db_available fixture).
"""
from __future__ import annotations

from sqlalchemy.orm import Session

_QA_USER_A = "e2472fa3-db25-4e53-9d0b-2aed67bcfe0e"   # real account with feed data


def test_get_feed_matches_default_mode(db_available):
    from backend.core.database import ENGINE
    from backend.repositories.job_repository import _get_joined, _row_to_jobmatch, get_feed

    got = get_feed(user_id=_QA_USER_A)

    with Session(ENGINE) as session:
        rows = _get_joined(session, user_id=_QA_USER_A, extra_where="ujm.status != 'ignored'")
        expected_ids = sorted(_row_to_jobmatch(r).job_id for r in rows)

    assert sorted(j.job_id for j in got) == expected_ids
