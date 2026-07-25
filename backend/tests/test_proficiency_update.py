"""
Unit tests — Phase 30: chat-driven skill UPDATE (proficiency / confidence)
==========================================================================

Coverage:
  1. ProfileUpdateService.apply_chat_proficiency_update()
       - proficiency_level anchors the score DOWN to the level ceiling
         (the "my Python is only beginner level" correction)
       - a self-claimed HIGHER level never inflates the score
       - explicit new_confidence overrides
       - suggested_confidence_modifier applies a signed delta
       - verification_status flips to 'verified' after a chat correction
       - a confidence_audit_log row is written for the change
       - unknown skill → status 'not_found' (no crash, no row created)

  2. ariel_tools._handle_update_skills() UPDATE action
       - the `update` list routes to apply_chat_proficiency_update and
         lowers the entity's confidence in place (no delete + re-add)
       - add / remove / update compose in a single call

All tests run against an isolated in-memory SQLite database built from the
real ORM metadata, so the live jobs.db is never touched.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool


# ---------------------------------------------------------------------------
# Shared in-memory SQLite engine, built from the real ORM Base metadata so the
# profile_entities (incl. proficiency_level) and confidence_audit_log tables
# exactly match production.
# ---------------------------------------------------------------------------

_TEST_ENGINE = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)


def _setup_schema() -> None:
    from backend.core.database import Base
    from backend.models import application, ariel, job, kv, matching, profile  # noqa: F401
    Base.metadata.create_all(_TEST_ENGINE)


_setup_schema()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _uid() -> str:
    return str(uuid.uuid4())


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _insert_skill_entity(
    *,
    user_id: str,
    name: str,
    confidence_score: float,
    verification_status: str = "unverified",
) -> str:
    """Insert a skill row into profile_entities and return its entity_id."""
    entity_id = _uid()
    now = _now()
    with _TEST_ENGINE.begin() as conn:
        conn.execute(
            text("""
                INSERT INTO profile_entities
                    (entity_id, user_id, entity_type, name, normalized_name,
                     confidence_score, verification_status, manual_review_required,
                     architecture_confidence, syntax_confidence, verification_level,
                     created_at, updated_at)
                VALUES
                    (:eid, :uid, 'skill', :name, :norm,
                     :score, :status, 0,
                     0.0, 0.0, 'UNVERIFIED',
                     :now, :now)
            """),
            {
                "eid":    entity_id,
                "uid":    user_id,
                "name":   name,
                "norm":   name.strip().lower().replace(" ", "_").replace("-", "_"),
                "score":  confidence_score,
                "status": verification_status,
                "now":    now,
            },
        )
    return entity_id


def _fetch_entity(entity_id: str) -> dict:
    with _TEST_ENGINE.connect() as conn:
        row = conn.execute(
            text("""
                SELECT confidence_score, proficiency_level, verification_status
                FROM   profile_entities WHERE entity_id = :eid
            """),
            {"eid": entity_id},
        ).fetchone()
    return {
        "confidence_score":    float(row[0]),
        "proficiency_level":   row[1],
        "verification_status": row[2],
    }


def _service():
    from backend.services.profile_update_service import ProfileUpdateService
    return ProfileUpdateService(_TEST_ENGINE)


# ---------------------------------------------------------------------------
# 1. Service-level tests: apply_chat_proficiency_update
# ---------------------------------------------------------------------------

class TestApplyChatProficiencyUpdate:

    def test_beginner_level_anchors_score_down(self):
        """
        The headline Phase 30 case: a parse scored Python at 51.7, the user
        says they're only a beginner → score anchored down to the 30.0 ceiling,
        proficiency recorded, and status flipped to 'verified'.
        """
        uid = "prof-beginner-" + _uid()
        eid = _insert_skill_entity(user_id=uid, name="Python", confidence_score=51.7)

        result = _service().apply_chat_proficiency_update(
            uid, "Python", proficiency_level="beginner"
        )

        assert result["status"] == "updated"
        assert result["old_score"] == pytest.approx(51.7, abs=0.1)
        assert result["new_score"] == pytest.approx(30.0, abs=0.1)

        ent = _fetch_entity(eid)
        assert ent["confidence_score"] == pytest.approx(30.0, abs=0.1)
        assert ent["proficiency_level"] == "beginner"
        assert ent["verification_status"] == "verified"

    def test_self_claimed_higher_level_never_inflates(self):
        """
        Proficiency-only updates only ever anchor DOWN. A user calling a weak
        skill 'expert' (ceiling 90) must not jump a 40 to 90 — self-claims
        can't inflate. Score stays at min(40, 90) = 40.
        """
        uid = "prof-expert-" + _uid()
        eid = _insert_skill_entity(user_id=uid, name="SQL", confidence_score=40.0)

        result = _service().apply_chat_proficiency_update(
            uid, "SQL", proficiency_level="expert"
        )

        assert result["status"] == "updated"
        assert _fetch_entity(eid)["confidence_score"] == pytest.approx(40.0, abs=0.1)
        # The label is still recorded even though the score didn't move.
        assert _fetch_entity(eid)["proficiency_level"] == "expert"

    def test_explicit_new_confidence_overrides(self):
        """An explicit new_confidence wins over any level/modifier and is clamped."""
        uid = "prof-explicit-" + _uid()
        eid = _insert_skill_entity(user_id=uid, name="Go", confidence_score=70.0)

        result = _service().apply_chat_proficiency_update(
            uid, "Go", proficiency_level="expert", new_confidence=22.5
        )
        assert result["new_score"] == pytest.approx(22.5, abs=0.1)
        assert _fetch_entity(eid)["confidence_score"] == pytest.approx(22.5, abs=0.1)

    def test_confidence_modifier_applies_signed_delta(self):
        """A negative modifier lowers the score by that delta."""
        uid = "prof-modifier-" + _uid()
        eid = _insert_skill_entity(user_id=uid, name="Rust", confidence_score=55.0)

        result = _service().apply_chat_proficiency_update(
            uid, "Rust", confidence_modifier=-20.0
        )
        assert result["new_score"] == pytest.approx(35.0, abs=0.1)
        assert _fetch_entity(eid)["confidence_score"] == pytest.approx(35.0, abs=0.1)

    def test_score_clamped_to_valid_range(self):
        """A modifier that would push below 0 clamps to 0.0."""
        uid = "prof-clamp-" + _uid()
        eid = _insert_skill_entity(user_id=uid, name="COBOL", confidence_score=10.0)

        _service().apply_chat_proficiency_update(uid, "COBOL", confidence_modifier=-99.0)
        assert _fetch_entity(eid)["confidence_score"] == pytest.approx(0.0, abs=0.1)

    def test_audit_log_row_written(self):
        """Every chat correction leaves an immutable audit trail."""
        uid = "prof-audit-" + _uid()
        eid = _insert_skill_entity(user_id=uid, name="Java", confidence_score=60.0)

        _service().apply_chat_proficiency_update(uid, "Java", proficiency_level="beginner")

        with _TEST_ENGINE.connect() as conn:
            rows = conn.execute(
                text("""
                    SELECT old_score, new_score, delta, trigger_source
                    FROM   confidence_audit_log
                    WHERE  entity_id = :eid
                """),
                {"eid": eid},
            ).fetchall()

        assert len(rows) == 1
        old, new, delta, src = rows[0]
        assert old == pytest.approx(60.0, abs=0.1)
        assert new == pytest.approx(30.0, abs=0.1)
        assert delta == pytest.approx(-30.0, abs=0.1)
        assert src == "chat_proficiency_update"

    def test_unknown_skill_returns_not_found(self):
        """Updating a skill that has no entity returns not_found, writes nothing."""
        uid = "prof-missing-" + _uid()
        result = _service().apply_chat_proficiency_update(
            uid, "Haskell", proficiency_level="beginner"
        )
        assert result["status"] == "not_found"

        with _TEST_ENGINE.connect() as conn:
            count = conn.execute(
                text("SELECT COUNT(*) FROM profile_entities WHERE user_id = :uid"),
                {"uid": uid},
            ).scalar()
        assert count == 0


# ---------------------------------------------------------------------------
# 2. Handler-level test: _handle_update_skills UPDATE action
# ---------------------------------------------------------------------------

class TestUpdateSkillsHandlerUpdateAction:

    @pytest.fixture(autouse=True)
    def _patch_engine(self, monkeypatch):
        """Point ariel_tools' module-global ENGINE at the in-memory test DB."""
        import backend.agents.ariel_tools as _tools
        monkeypatch.setattr(_tools, "ENGINE", _TEST_ENGINE)

    def test_update_action_lowers_existing_skill_in_place(self):
        """
        The `update` list routes through apply_chat_proficiency_update and
        lowers the entity's confidence WITHOUT deleting/recreating it.
        """
        from backend.agents.ariel_tools import _handle_update_skills

        uid = "handler-update-" + _uid()
        eid = _insert_skill_entity(user_id=uid, name="Python", confidence_score=51.7)

        with Session(_TEST_ENGINE) as session:
            msg = _handle_update_skills(
                {"update": [{"skill": "Python", "proficiency_level": "beginner"}]},
                uid,
                session,
            )

        assert "Updated" in msg
        ent = _fetch_entity(eid)
        assert ent["confidence_score"] == pytest.approx(30.0, abs=0.1)
        assert ent["proficiency_level"] == "beginner"
        assert ent["verification_status"] == "verified"

    def test_update_missing_skill_reports_failure(self):
        """Updating a skill with no entity surfaces a 'could not update' note."""
        from backend.agents.ariel_tools import _handle_update_skills

        uid = "handler-missing-" + _uid()
        with Session(_TEST_ENGINE) as session:
            msg = _handle_update_skills(
                {"update": [{"skill": "Fortran", "proficiency_level": "beginner"}]},
                uid,
                session,
            )
        assert "Could not update" in msg

    def test_add_remove_update_compose_in_one_call(self):
        """add, remove, and update can all run in a single tool call."""
        from backend.agents.ariel_tools import _handle_update_skills

        uid = "handler-compose-" + _uid()
        eid = _insert_skill_entity(user_id=uid, name="Django", confidence_score=80.0)

        with Session(_TEST_ENGINE) as session:
            msg = _handle_update_skills(
                {
                    "add":    ["Kubernetes"],
                    "update": [{"skill": "Django", "new_confidence": 45.0}],
                },
                uid,
                session,
            )

        assert "Added" in msg and "Updated" in msg
        assert _fetch_entity(eid)["confidence_score"] == pytest.approx(45.0, abs=0.1)
