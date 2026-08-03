"""
Unit tests — profile_entity_repository.get_all_with_evidence_for_user()

Verifies the single-LEFT-JOIN combined loader (entities + evidence in one
round trip) produces byte-for-byte identical output to the original
two-query path (get_all_for_user + evidence_repository.get_active_for_entities),
on the real 160-entity/253-evidence-row QA account.

Runs against the real Postgres DB (db_available fixture) — profile_entities
has a hard FK to auth.users, same constraint as other repository tests.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

_QA_USER_A = "e2472fa3-db25-4e53-9d0b-2aed67bcfe0e"   # the 160-entity test account


def test_combined_loader_matches_two_query_path(db_available):
    from backend.core.database import ENGINE
    from backend.repositories import evidence_repository, profile_entity_repository

    now_iso = datetime.now(timezone.utc).isoformat()

    with Session(ENGINE) as db:
        expected_entities = profile_entity_repository.get_all_for_user(_QA_USER_A, session=db)
        entity_ids = [e.entity_id for e in expected_entities]
        expected_evidence = evidence_repository.get_active_for_entities(entity_ids, now_iso, session=db)

    with Session(ENGINE) as db:
        got_entities, got_evidence = profile_entity_repository.get_all_with_evidence_for_user(
            _QA_USER_A, now_iso, session=db
        )

    # Entity order and content must match exactly — both queries now share
    # the same (confidence_score DESC, entity_id ASC) tiebreaker, so ties
    # (common in real data — this account has 82 entities tied at the same
    # confidence_score) resolve identically regardless of query shape.
    assert got_entities == expected_entities

    # Evidence must match per-entity, in the same (verified_at DESC,
    # evidence_id ASC) order.
    assert set(got_evidence.keys()) == set(expected_evidence.keys())
    for eid in expected_evidence:
        assert got_evidence[eid] == expected_evidence[eid], f"evidence mismatch for entity {eid}"


def test_combined_loader_issues_exactly_one_query(db_available):
    from sqlalchemy import event
    from backend.core.database import ENGINE
    from backend.repositories import profile_entity_repository

    now_iso = datetime.now(timezone.utc).isoformat()
    query_count = 0

    def _count(*a, **kw):
        nonlocal query_count
        query_count += 1

    event.listen(ENGINE, "before_cursor_execute", _count)
    try:
        with Session(ENGINE) as db:
            profile_entity_repository.get_all_with_evidence_for_user(_QA_USER_A, now_iso, session=db)
    finally:
        event.remove(ENGINE, "before_cursor_execute", _count)

    assert query_count == 1, f"expected 1 query (one JOIN), got {query_count}"


def test_combined_loader_empty_profile():
    from backend.core.database import ENGINE
    from backend.repositories import profile_entity_repository
    import uuid

    now_iso = datetime.now(timezone.utc).isoformat()
    with Session(ENGINE) as db:
        entities, evidence = profile_entity_repository.get_all_with_evidence_for_user(
            str(uuid.uuid4()), now_iso, session=db
        )
    assert entities == []
    assert evidence == {}
