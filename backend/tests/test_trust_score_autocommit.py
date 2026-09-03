"""
Unit tests — GET /api/profile/{user_id}/trust-score AUTOCOMMIT fix.

Confirms the AUTOCOMMIT-scoped connection (backend/api/routes/profile.py's
get_trust_score()) preserves exact output vs. the engine's default
(transactional) mode — AUTOCOMMIT only removes the implicit rollback-on-close
cost, it must never change what's returned.

Runs against Postgres (db_available fixture).

The N+1 assertion below is only meaningful when the account actually has
entities: with none, get_trust_score() correctly skips the evidence fetch
and issues one query, so `== 2` fails for a reason that says nothing about
batching. This module used to rely on one shared QA account happening to
hold 160 rows, which made it pass only against that particular database —
and it was skipped everywhere else, so nobody noticed. The fixture below
seeds its own entities and removes them afterwards, so the test asserts
what it claims to on any Postgres.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import event

_QA_USER_A = "e2472fa3-db25-4e53-9d0b-2aed67bcfe0e"


@pytest.fixture()
def seeded_entities(db_available):
    """
    Give _QA_USER_A a few profile entities for the duration of one test.

    Three is enough: batching means the query count is independent of how
    many entities there are, which is the property under test. Rows are
    deleted on teardown so the shared account is left as it was found.
    """
    from sqlalchemy import text as _text
    from backend.core.database import ENGINE

    now = datetime.now(timezone.utc).isoformat()
    ids = [f"tsa-test-{uuid.uuid4()}" for _ in range(3)]
    with ENGINE.begin() as conn:
        for i, eid in enumerate(ids):
            conn.execute(_text("""
                INSERT INTO profile_entities
                    (entity_id, user_id, entity_type, name, normalized_name,
                     confidence_score, verification_status, created_at, updated_at)
                VALUES
                    (:eid, :uid, 'skill', :name, :norm,
                     :score, 'unverified', :now, :now)
            """), {"eid": eid, "uid": _QA_USER_A, "name": f"TSA Skill {i}",
                   "norm": f"tsa skill {i}", "score": 50.0 + i, "now": now})
    try:
        yield ids
    finally:
        with ENGINE.begin() as conn:
            conn.execute(
                _text("DELETE FROM profile_entities WHERE entity_id = ANY(:ids)"),
                {"ids": ids},
            )


def test_trust_score_issues_exactly_two_queries(db_available, seeded_entities):
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
