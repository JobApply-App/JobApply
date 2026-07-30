"""
Multi-tenant isolation + handler-level tests for the Phase 3 profile schema
(profiles/user_preferences/profile_answers/cv_documents/cv_claims via
backend/repositories/profile_repository.py).

Deliberately a SEPARATE file from test_tenant_isolation.py /
test_ariel_profile_base_tool.py / test_proficiency_update.py: those files'
autouse/manual ENGINE-patching points ariel_tools and master_profile_service
at an isolated in-memory SQLite engine, but profile_repository.py is
Postgres-only (CAST(... AS uuid), jsonb casts, `public.` schema-qualified
tables) and profiles.id has a hard FK to auth.users(id) — arbitrary
"user-a-<uuid>" test strings that worked against a synthetic SQLite
MasterProfileRow table can't be written here. Every test uses the
`db_available` fixture (backend/tests/conftest.py) to skip gracefully when
Postgres isn't reachable, against two stable, pre-existing Supabase QA
accounts reused as test tenants (same convention as
test_job_postings_isolation.py).

Covers the three test classes that broke when ariel_tools.py /
master_profile_service.py were repointed at profile_repository.py:
  - TestMasterProfileIsolation      (was in test_tenant_isolation.py)
  - TestUpdateProfileBaseHandler    (was test_ariel_profile_base_tool.py)
  - TestUpdateSkillsHandlerUpdateAction (was in test_proficiency_update.py)

Running
-------
    backend/.venv/bin/pytest backend/tests/test_profile_isolation.py -v
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

_QA_USER_A = "2631c93b-93bb-4313-a2c2-79dbb786d199"   # qa.test2.jobapply.claude@gmail.com
_QA_USER_B = "b0dbf35a-929c-4db3-a04a-24fbe3a3d59d"   # qa-test-linkedin-tab@example.com


def _uid() -> str:
    return str(uuid.uuid4())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clear_profile_data(user_id: str) -> None:
    """Blank a QA account's profile document back to {} / incomplete, own transaction."""
    from backend.core.database import ENGINE
    with Session(ENGINE) as s:
        s.execute(text("DELETE FROM public.cv_documents WHERE user_id = CAST(:u AS uuid)"), {"u": user_id})
        s.execute(text("DELETE FROM public.profile_answers WHERE user_id = CAST(:u AS uuid)"), {"u": user_id})
        s.execute(text("DELETE FROM public.user_preferences WHERE user_id = CAST(:u AS uuid)"), {"u": user_id})
        s.execute(
            text("""
                UPDATE public.profiles SET
                    onboarding_status = 'incomplete', full_name = NULL, phone = NULL,
                    linkedin_url = NULL, location = NULL
                WHERE id = CAST(:u AS uuid)
            """),
            {"u": user_id},
        )
        s.commit()


def _insert_skill_entity(*, user_id: str, name: str, confidence_score: float,
                          verification_status: str = "unverified") -> str:
    """Insert a skill row into profile_entities (real Postgres) and return its entity_id."""
    from backend.core.database import ENGINE
    entity_id = _uid()
    now = _now()
    with ENGINE.begin() as conn:
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
                "eid": entity_id, "uid": user_id, "name": name,
                "norm": name.strip().lower().replace(" ", "_").replace("-", "_"),
                "score": confidence_score, "status": verification_status, "now": now,
            },
        )
    return entity_id


def _fetch_entity(entity_id: str) -> dict:
    from backend.core.database import ENGINE
    with ENGINE.connect() as conn:
        row = conn.execute(
            text("SELECT confidence_score, proficiency_level, verification_status "
                 "FROM profile_entities WHERE entity_id = :eid"),
            {"eid": entity_id},
        ).fetchone()
    return {"confidence_score": float(row[0]), "proficiency_level": row[1], "verification_status": row[2]}


def _cleanup_entities(entity_ids: list[str]) -> None:
    from backend.core.database import ENGINE
    with ENGINE.begin() as conn:
        conn.execute(text("DELETE FROM confidence_audit_log WHERE entity_id = ANY(:ids)"), {"ids": entity_ids})
        conn.execute(text("DELETE FROM profile_entities WHERE entity_id = ANY(:ids)"), {"ids": entity_ids})


# ═══════════════════════════════════════════════════════════════════════════
# Master Profile isolation
# ═══════════════════════════════════════════════════════════════════════════

class TestMasterProfileIsolation:
    @pytest.fixture(autouse=True)
    def _cleanup(self, db_available):
        yield
        _clear_profile_data(_QA_USER_A)
        _clear_profile_data(_QA_USER_B)

    def test_two_users_cannot_read_each_others_profile(self, db_available):
        """User B's load() must never return User A's saved data, and vice versa."""
        from backend.services import master_profile_service as mp

        profile_a = {"version": 1, "professional_summary": "A's secret summary"}
        profile_b = {"version": 1, "professional_summary": "B's secret summary"}

        mp.save(profile_a, user_id=_QA_USER_A)
        mp.save(profile_b, user_id=_QA_USER_B)

        loaded_a = mp.load(_QA_USER_A)
        loaded_b = mp.load(_QA_USER_B)

        assert loaded_a["professional_summary"] == "A's secret summary"
        assert loaded_b["professional_summary"] == "B's secret summary"
        assert loaded_a["professional_summary"] != loaded_b["professional_summary"]

    def test_save_for_user_a_does_not_overwrite_user_b_row(self, db_available):
        """Writing A's profile after B's must leave B's row untouched."""
        from backend.services import master_profile_service as mp

        mp.save({"version": 1, "professional_summary": "B original"}, user_id=_QA_USER_B)
        mp.save({"version": 1, "professional_summary": "A original"}, user_id=_QA_USER_A)
        mp.save({"version": 1, "professional_summary": "A updated"}, user_id=_QA_USER_A)

        assert mp.load(_QA_USER_B)["professional_summary"] == "B original"
        assert mp.load(_QA_USER_A)["professional_summary"] == "A updated"

    def test_profile_row_count_matches_distinct_users(self, db_available):
        """Structural check: profiles.id is the primary key — each user gets exactly one row."""
        from backend.core.database import ENGINE
        from backend.services import master_profile_service as mp

        mp.save({"version": 1, "professional_summary": "for A"}, user_id=_QA_USER_A)
        mp.save({"version": 1, "professional_summary": "for B"}, user_id=_QA_USER_B)

        with ENGINE.connect() as conn:
            count = conn.execute(
                text("SELECT count(*) FROM public.profiles WHERE id = ANY(CAST(:ids AS uuid[]))"),
                {"ids": [_QA_USER_A, _QA_USER_B]},
            ).scalar()
        assert count == 2


# ═══════════════════════════════════════════════════════════════════════════
# ariel_tools._handle_update_profile_base via execute_tool
# ═══════════════════════════════════════════════════════════════════════════

class TestUpdateProfileBaseHandler:
    @pytest.fixture(autouse=True)
    def _cleanup(self, db_available):
        _clear_profile_data(_QA_USER_A)
        yield
        _clear_profile_data(_QA_USER_A)

    def test_summary_only_update_persists(self, db_available):
        from backend.agents.ariel_tools import execute_tool
        from backend.core.database import ENGINE
        from backend.repositories import profile_repository

        with Session(ENGINE) as session:
            msg = execute_tool(
                "update_profile_base",
                {"summary": "Senior PM with 8 years shipping B2C fintech."},
                _QA_USER_A,
                session,
            )
        assert "summary" in msg

        row = profile_repository.get(_QA_USER_A)
        assert row is not None
        assert row.master_profile["professional_summary"] == "Senior PM with 8 years shipping B2C fintech."

    def test_target_title_only_replaces_target_roles(self, db_available):
        from backend.agents.ariel_tools import execute_tool
        from backend.core.database import ENGINE
        from backend.repositories import profile_repository

        with Session(ENGINE) as session:
            msg = execute_tool("update_profile_base", {"target_title": "Head of Product"}, _QA_USER_A, session)
        assert "target_title" in msg

        row = profile_repository.get(_QA_USER_A)
        assert row.master_profile["career_goals"]["target_roles"] == ["Head of Product"]

    def test_both_fields_together(self, db_available):
        from backend.agents.ariel_tools import execute_tool
        from backend.core.database import ENGINE
        from backend.repositories import profile_repository

        with Session(ENGINE) as session:
            msg = execute_tool(
                "update_profile_base",
                {"summary": "Growth-focused PM.", "target_title": "VP Product"},
                _QA_USER_A,
                session,
            )
        assert "summary" in msg and "target_title" in msg

        row = profile_repository.get(_QA_USER_A)
        assert row.master_profile["professional_summary"] == "Growth-focused PM."
        assert row.master_profile["career_goals"]["target_roles"] == ["VP Product"]

    def test_existing_profile_fields_are_preserved(self, db_available):
        """A partial update must not clobber unrelated master_profile fields."""
        from backend.agents.ariel_tools import execute_tool
        from backend.core.database import ENGINE
        from backend.repositories import profile_repository

        with Session(ENGINE) as session:
            row, _created = profile_repository.get_or_create(session, _QA_USER_A, now=_now())
            row.onboarding_status = "complete"
            row.master_profile = {
                "professional_summary": "Old summary.",
                "experience": [{"company": "Acme", "role": "PM", "start": "2020", "end": "2023", "bullets": ["Shipped X"]}],
                "skills": ["SQL"],
                "education": [],
                "career_goals": {
                    "target_roles": ["Old Title"], "preferred_locations": ["Tel Aviv"],
                    "work_environment": "remote", "notes": "keep me",
                },
            }
            profile_repository.save(session, row)
            session.commit()

            execute_tool("update_profile_base", {"target_title": "New Title"}, _QA_USER_A, session)

        refreshed = profile_repository.get(_QA_USER_A)
        assert refreshed.master_profile["professional_summary"] == "Old summary."
        assert refreshed.master_profile["skills"] == ["SQL"]
        assert refreshed.master_profile["career_goals"]["target_roles"] == ["New Title"]
        assert refreshed.master_profile["career_goals"]["preferred_locations"] == ["Tel Aviv"]
        assert refreshed.master_profile["career_goals"]["notes"] == "keep me"


# ═══════════════════════════════════════════════════════════════════════════
# ariel_tools._handle_update_skills UPDATE action (Confidence Matrix)
# ═══════════════════════════════════════════════════════════════════════════

class TestUpdateSkillsHandlerUpdateAction:
    @pytest.fixture(autouse=True)
    def _cleanup(self, db_available):
        yield
        _clear_profile_data(_QA_USER_A)

    def test_update_action_lowers_existing_skill_in_place(self, db_available):
        from backend.agents.ariel_tools import _handle_update_skills
        from backend.core.database import ENGINE

        eid = _insert_skill_entity(user_id=_QA_USER_A, name="Python", confidence_score=51.7)
        try:
            with Session(ENGINE) as session:
                msg = _handle_update_skills(
                    {"update": [{"skill": "Python", "proficiency_level": "beginner"}]}, _QA_USER_A, session,
                )
            assert "Updated" in msg
            ent = _fetch_entity(eid)
            assert ent["confidence_score"] == pytest.approx(30.0, abs=0.1)
            assert ent["proficiency_level"] == "beginner"
            assert ent["verification_status"] == "verified"
        finally:
            _cleanup_entities([eid])

    def test_update_missing_skill_reports_failure(self, db_available):
        from backend.agents.ariel_tools import _handle_update_skills
        from backend.core.database import ENGINE

        with Session(ENGINE) as session:
            msg = _handle_update_skills(
                {"update": [{"skill": "Fortran", "proficiency_level": "beginner"}]}, _QA_USER_A, session,
            )
        assert "Could not update" in msg

    def test_add_remove_update_compose_in_one_call(self, db_available):
        from backend.agents.ariel_tools import _handle_update_skills
        from backend.core.database import ENGINE

        eid = _insert_skill_entity(user_id=_QA_USER_A, name="Django", confidence_score=80.0)
        try:
            with Session(ENGINE) as session:
                msg = _handle_update_skills(
                    {"add": ["Kubernetes"], "update": [{"skill": "Django", "new_confidence": 45.0}]},
                    _QA_USER_A, session,
                )
            assert "Added" in msg and "Updated" in msg
            assert _fetch_entity(eid)["confidence_score"] == pytest.approx(45.0, abs=0.1)
        finally:
            _cleanup_entities([eid])
