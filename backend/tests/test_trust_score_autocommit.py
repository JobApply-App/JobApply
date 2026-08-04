"""
Unit tests — GET /api/profile/{user_id}/trust-score AUTOCOMMIT fix.

Confirms the AUTOCOMMIT-scoped connection (backend/api/routes/profile.py's
get_trust_score()) preserves exact output vs. the engine's default
(transactional) mode — AUTOCOMMIT only removes the implicit rollback-on-close
cost, it must never change what's returned.

Runs against the real Postgres DB (db_available fixture) — the QA account
below has 160 profile entities, a real N+1-sensitive shape.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import event

_QA_USER_A = "e2472fa3-db25-4e53-9d0b-2aed67bcfe0e"   # real account with 160 entities


def test_trust_score_issues_exactly_two_queries(db_available):
    from backend.api.deps import CurrentUser
    from backend.api.routes.profile import get_trust_score
    from backend.core.database import ENGINE

    query_count = 0

    def _count(*a, **kw):
        nonlocal query_count
        query_count += 1

    event.listen(ENGINE, "before_cursor_execute", _count)
    try:
        user = CurrentUser(user_id=_QA_USER_A, email="qa@test.com", name="QA")
        get_trust_score(user_id=_QA_USER_A, sort_by="score_desc", top_n=0, user=user)
    finally:
        event.remove(ENGINE, "before_cursor_execute", _count)

    assert query_count == 2, f"expected exactly 2 queries (entities + batched evidence), got {query_count}"


def test_trust_score_matches_default_mode(db_available):
    from sqlalchemy.orm import Session
    from backend.api.deps import CurrentUser
    from backend.api.routes.profile import get_trust_score, build_trust_score_response
    from backend.core.database import ENGINE
    from backend.repositories import profile_entity_repository, evidence_repository

    user = CurrentUser(user_id=_QA_USER_A, email="qa@test.com", name="QA")
    got = get_trust_score(user_id=_QA_USER_A, sort_by="score_desc", top_n=0, user=user)

    now_iso = datetime.now(timezone.utc).isoformat()
    with Session(ENGINE) as db:
        entity_rows = profile_entity_repository.get_all_for_user(_QA_USER_A, session=db)
        entity_ids = [e.entity_id for e in entity_rows]
        evidence_by_entity = evidence_repository.get_active_for_entities(entity_ids, now_iso, session=db)
    expected = build_trust_score_response(_QA_USER_A, entity_rows, evidence_by_entity, now_iso)

    assert got["overall_trust_score"] == expected["overall_trust_score"]
    assert [e["entity_id"] for e in got["entities"]] == [e["entity_id"] for e in expected["entities"]]
