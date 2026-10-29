"""
Regression: every finished Ariel STAR probe returned HTTP 500.

The ORM column is `evidence_records.extra_metadata` ('metadata' is reserved by
SQLAlchemy, migration 004 renamed it), but four raw INSERTs in
ProfileUpdateService still named the old `metadata` column. Postgres answered
`column "metadata" of relation "evidence_records" does not exist`, so both
probe outcomes — a positive STAR event and a shallow-answer flag — crashed
before anything was saved.

These tests run each write path against a schema built from the real ORM
metadata, so the INSERT column list is checked against the same columns
production has.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

_ENGINE = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)


def _setup_schema() -> None:
    from backend.core.database import Base
    from backend.models import application, ariel, kv, matching, profile  # noqa: F401
    Base.metadata.create_all(_ENGINE)


_setup_schema()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _svc():
    from backend.services.profile_update_service import ProfileUpdateService
    return ProfileUpdateService(_ENGINE)


def _entity(user_id: str, name: str, score: float = 50.0) -> str:
    eid = str(uuid.uuid4())
    with _ENGINE.begin() as conn:
        conn.execute(
            text("""
                INSERT INTO profile_entities
                    (entity_id, user_id, entity_type, name, normalized_name,
                     confidence_score, verification_status, manual_review_required,
                     architecture_confidence, syntax_confidence, verification_level,
                     created_at, updated_at)
                VALUES (:eid, :uid, 'skill', :name, :norm, :score, 'unverified', 0,
                        0.0, 0.0, 'UNVERIFIED', :now, :now)
            """),
            {"eid": eid, "uid": user_id, "name": name,
             "norm": name.lower().replace(".", "_"), "score": score, "now": _now()},
        )
    return eid


def _session(user_id: str) -> str:
    return _svc().open_session(
        user_id=user_id, session_type="behavioral_interview",
        target_entities=[], ariel_goal="test",
    )


def _metadata_of(evidence_source: str, entity_id: str) -> dict:
    with _ENGINE.connect() as conn:
        raw = conn.execute(
            text("SELECT extra_metadata FROM evidence_records "
                 "WHERE entity_id = :e AND source_type = :s"),
            {"e": entity_id, "s": evidence_source},
        ).scalar_one()
    return json.loads(raw)


def test_shallow_star_flag_is_recorded():
    uid = str(uuid.uuid4())
    eid = _entity(uid, "Node.js")
    sid = _session(uid)

    _svc().ingest_negative_flag(
        user_id=uid, entity_id=eid, session_id=sid,
        flag_type="shallow_star", raw_content="{}",
        flag_reason="no measurable result",
    )

    meta = _metadata_of("negative_flag", eid)
    assert meta["flag_type"] == "shallow_star"


def test_positive_star_event_is_recorded():
    uid = str(uuid.uuid4())
    eid = _entity(uid, "Node.js")
    sid = _session(uid)

    result = _svc().ingest_conversation_event(
        user_id=uid, session_id=sid,
        event={"extracted_entity_ids": [eid], "extraction_confidence": 0.9,
               "star_action": "built the API", "star_result": "latency -40%"},
    )

    assert eid in result
    assert _metadata_of("conversation_star", eid)["extraction_confidence"] == 0.9


def test_certification_is_recorded():
    uid = str(uuid.uuid4())
    eid = _svc().ingest_certification(
        user_id=uid, entity_name="AWS SAA",
        cert_metadata={"issuer": "AWS"},
    )
    assert _metadata_of("certification", eid)["issuer"] == "AWS"


# The last probe answer runs record_probe_outcome as a whole: evidence write
# plus the conversation_events cooldown row. Sapir's shallow answer took the
# negative path and got a 500 on the final question (production, 2026-10-28).
def _probe_outcome(flag_type: str, conf: float) -> str:
    from backend.services.ariel_probe_service import ArielProbeService
    uid = str(uuid.uuid4())
    eid = _entity(uid, "Node.js")
    sid = _session(uid)
    ArielProbeService(_ENGINE, _svc()).record_probe_outcome(
        uid, {"entity_id": eid, "entity_type": "skill"}, sid,
        {"flag_type": flag_type, "extraction_confidence": conf, "probe_method": "star",
         "star_components": {"situation": "s", "task": "t", "action": "a", "result": "r"}},
    )
    with _ENGINE.connect() as conn:
        return conn.execute(
            text("SELECT probe_outcome FROM conversation_events "
                 "WHERE entity_id = :e AND event_kind = 'probe'"),
            {"e": eid},
        ).scalar_one()


def test_full_probe_outcome_shallow_answer():
    assert _probe_outcome("shallow_star", 0.40) == "shallow_star"


def test_full_probe_outcome_good_answer():
    assert _probe_outcome("none", 0.8) == "positive_star"
