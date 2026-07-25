"""
Unit tests — Phase 35: autonomous update_profile_base tool
============================================================

Coverage for ariel_tools._handle_update_profile_base() / execute_tool():
  - summary-only update persists professional_summary
  - target_title-only update replaces career_goals.target_roles
  - both fields together in a single call
  - empty input is a no-op (no DB row created/mutated)
  - a brand-new user_id gets a row created (upsert path)

Runs against an isolated in-memory SQLite database built from the real ORM
metadata, so the live jobs.db is never touched.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

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


def _uid() -> str:
    return str(uuid.uuid4())


class TestUpdateProfileBaseHandler:

    def test_summary_only_update_persists(self):
        from backend.agents.ariel_tools import execute_tool
        from backend.models.profile import MasterProfileRow

        uid = "summary-" + _uid()
        with Session(_TEST_ENGINE) as session:
            msg = execute_tool(
                "update_profile_base",
                {"summary": "Senior PM with 8 years shipping B2C fintech."},
                uid,
                session,
            )
            assert "summary" in msg

            row = session.get(MasterProfileRow, uid)
            assert row is not None
            assert row.master_profile["professional_summary"] == (
                "Senior PM with 8 years shipping B2C fintech."
            )

    def test_target_title_only_replaces_target_roles(self):
        from backend.agents.ariel_tools import execute_tool
        from backend.models.profile import MasterProfileRow

        uid = "title-" + _uid()
        with Session(_TEST_ENGINE) as session:
            msg = execute_tool(
                "update_profile_base",
                {"target_title": "Head of Product"},
                uid,
                session,
            )
            assert "target_title" in msg

            row = session.get(MasterProfileRow, uid)
            assert row.master_profile["career_goals"]["target_roles"] == ["Head of Product"]

    def test_both_fields_together(self):
        from backend.agents.ariel_tools import execute_tool
        from backend.models.profile import MasterProfileRow

        uid = "both-" + _uid()
        with Session(_TEST_ENGINE) as session:
            msg = execute_tool(
                "update_profile_base",
                {"summary": "Growth-focused PM.", "target_title": "VP Product"},
                uid,
                session,
            )
            assert "summary" in msg and "target_title" in msg

            row = session.get(MasterProfileRow, uid)
            assert row.master_profile["professional_summary"] == "Growth-focused PM."
            assert row.master_profile["career_goals"]["target_roles"] == ["VP Product"]

    def test_empty_input_is_a_noop(self):
        from backend.agents.ariel_tools import execute_tool
        from backend.models.profile import MasterProfileRow

        uid = "empty-" + _uid()
        with Session(_TEST_ENGINE) as session:
            msg = execute_tool("update_profile_base", {}, uid, session)
            assert "No summary or target_title" in msg

            row = session.get(MasterProfileRow, uid)
            assert row is None

    def test_existing_profile_fields_are_preserved(self):
        """A partial update must not clobber unrelated master_profile fields."""
        from backend.agents.ariel_tools import execute_tool
        from backend.models.profile import MasterProfileRow

        uid = "preserve-" + _uid()
        with Session(_TEST_ENGINE) as session:
            row = MasterProfileRow(
                user_id=uid,
                onboarding_status="complete",
                master_profile={
                    "professional_summary": "Old summary.",
                    "experience": [{"company": "Acme", "role": "PM", "start": "2020", "end": "2023", "bullets": ["Shipped X"]}],
                    "skills": ["SQL"],
                    "education": [],
                    "career_goals": {
                        "target_roles": ["Old Title"],
                        "preferred_locations": ["Tel Aviv"],
                        "work_environment": "remote",
                        "notes": "keep me",
                    },
                },
            )
            session.add(row)
            session.commit()

            execute_tool("update_profile_base", {"target_title": "New Title"}, uid, session)

            refreshed = session.get(MasterProfileRow, uid)
            assert refreshed.master_profile["professional_summary"] == "Old summary."
            assert refreshed.master_profile["skills"] == ["SQL"]
            assert refreshed.master_profile["career_goals"]["target_roles"] == ["New Title"]
            assert refreshed.master_profile["career_goals"]["preferred_locations"] == ["Tel Aviv"]
            assert refreshed.master_profile["career_goals"]["notes"] == "keep me"
