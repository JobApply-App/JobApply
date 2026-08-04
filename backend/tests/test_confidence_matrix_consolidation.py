"""
Unit tests — confidence_matrix_service query consolidation.

Confirms the fix for the duplicate-load bug: get_confidence_matrix() and
get_entity_breakdown(), called independently, used to each open their own
profile_entities + evidence_records query (4 round trips total for the
confidence-matrix route). get_confidence_matrix_and_breakdown() (and the
lower-level load_entities_and_evidence() + compute_radar()/compute_breakdown()
combo the route now uses) must load that data exactly once and still produce
outputs identical to calling the two standalone functions separately.

Runs against an isolated in-memory SQLite engine — same StaticPool pattern as
test_tenant_isolation.py / test_profile_trust.py.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

_TEST_ENGINE = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@pytest.fixture(autouse=True)
def _schema():
    with _TEST_ENGINE.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS profile_entities (
                entity_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                entity_type TEXT,
                name TEXT,
                normalized_name TEXT,
                confidence_score REAL,
                architecture_confidence REAL,
                syntax_confidence REAL,
                skill_tier TEXT,
                verification_level TEXT,
                verification_status TEXT,
                created_at TEXT,
                updated_at TEXT
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS evidence_records (
                evidence_id TEXT PRIMARY KEY,
                entity_id TEXT NOT NULL,
                source_type TEXT,
                base_weight REAL,
                verified_at TEXT,
                hard_expires_at TEXT,
                is_ai_assisted INTEGER
            )
        """))
        conn.execute(text("DELETE FROM profile_entities"))
        conn.execute(text("DELETE FROM evidence_records"))
    yield


def _seed_entity(user_id: str, name: str, entity_type: str = "skill", score: float = 50.0) -> str:
    eid = str(uuid.uuid4())
    with _TEST_ENGINE.begin() as conn:
        conn.execute(text("""
            INSERT INTO profile_entities
                (entity_id, user_id, entity_type, name, normalized_name,
                 confidence_score, architecture_confidence, syntax_confidence,
                 skill_tier, verification_level, verification_status, created_at, updated_at)
            VALUES (:eid, :uid, :etype, :name, :norm, :score, 60.0, 70.0,
                    'mid', 'UNVERIFIED', 'unverified', :now, :now)
        """), {
            "eid": eid, "uid": user_id, "etype": entity_type, "name": name,
            "norm": name.lower(), "score": score, "now": _now(),
        })
    return eid


def _seed_evidence(entity_id: str, source_type: str = "cv_parse", weight: float = 20.0) -> None:
    with _TEST_ENGINE.begin() as conn:
        conn.execute(text("""
            INSERT INTO evidence_records
                (evidence_id, entity_id, source_type, base_weight, verified_at, hard_expires_at, is_ai_assisted)
            VALUES (:eid, :entid, :stype, :weight, :now, NULL, 0)
        """), {
            "eid": str(uuid.uuid4()), "entid": entity_id, "stype": source_type,
            "weight": weight, "now": _now(),
        })


def test_combined_output_matches_separate_calls():
    from backend.services import confidence_matrix_service as cm

    user_id = f"user-{uuid.uuid4()}"
    e1 = _seed_entity(user_id, "Python", "skill", 80.0)
    e2 = _seed_entity(user_id, "Product Management", "skill", 40.0)
    _seed_evidence(e1, "cv_parse", 25.0)
    _seed_evidence(e2, "portfolio", 15.0)

    radar_separate = cm.get_confidence_matrix(user_id, _TEST_ENGINE)
    breakdown_separate = cm.get_entity_breakdown(user_id, _TEST_ENGINE)

    radar_combined, breakdown_combined = cm.get_confidence_matrix_and_breakdown(user_id, _TEST_ENGINE)

    assert radar_combined == radar_separate
    assert breakdown_combined == breakdown_separate


def test_combined_loads_data_exactly_once():
    """The whole point of the fix: one load serves both outputs."""
    from backend.services import confidence_matrix_service as cm

    user_id = f"user-{uuid.uuid4()}"
    e1 = _seed_entity(user_id, "SQL", "skill", 70.0)
    _seed_evidence(e1, "cv_parse", 20.0)

    load_calls = []
    original = cm.load_entities_and_evidence

    def _counting_load(engine, uid):
        load_calls.append(uid)
        return original(engine, uid)

    cm.load_entities_and_evidence = _counting_load
    try:
        cm.get_confidence_matrix_and_breakdown(user_id, _TEST_ENGINE)
    finally:
        cm.load_entities_and_evidence = original

    assert load_calls == [user_id], f"expected exactly 1 load call, got {len(load_calls)}"


def test_empty_profile_both_outputs_empty():
    from backend.services import confidence_matrix_service as cm

    user_id = f"user-{uuid.uuid4()}"
    radar, breakdown = cm.get_confidence_matrix_and_breakdown(user_id, _TEST_ENGINE)

    assert breakdown == []
    assert all(cat["value"] == 0.0 for cat in radar)
    assert {cat["category"] for cat in radar} == set(cm.CATEGORIES)


def test_standalone_functions_still_work_independently():
    """Other call sites (match_score_service, cv_tailor_service, etc.) call
    get_entity_breakdown() alone — it must still work unchanged."""
    from backend.services import confidence_matrix_service as cm

    user_id = f"user-{uuid.uuid4()}"
    _seed_entity(user_id, "Excel", "skill", 55.0)

    breakdown = cm.get_entity_breakdown(user_id, _TEST_ENGINE)
    assert len(breakdown) == 1
    assert breakdown[0]["name"] == "Excel"
