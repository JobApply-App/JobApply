"""
Regression test for the cross-tenant webhook bug (2026-08-20).

find_updatable_by_company() used to search every user's applications with
no tenant filter at all — an inbound email whose company name substring-
matched ANY user's most-recently-submitted application would return (and
the caller would then mutate) that unrelated user's row.

Runs against an isolated in-memory SQLite engine (same StaticPool pattern as
test_kv_repository.py) — no live Postgres needed, so this actually executes
in CI rather than joining the tests gated behind db_available.
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.core.database import Base
from backend.models.application import ApplicationRow
from backend.repositories.application_repository import find_updatable_by_company

_UPDATABLE = frozenset({"submitted", "phone screen", "technical", "interview"})

_TEST_ENGINE = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
Base.metadata.create_all(_TEST_ENGINE, tables=[ApplicationRow.__table__])


def _seed(session: Session, *, app_id: str, user_id: str, company: str, status: str, submitted_at: str) -> None:
    session.add(ApplicationRow(
        application_id=app_id, user_id=user_id, job_id=f"job-{app_id}",
        title="Product Manager", company=company, ats="Direct",
        status=status, submitted_at=submitted_at, last_update=submitted_at, score=0.0,
    ))


@pytest.fixture()
def session():
    with Session(_TEST_ENGINE) as s:
        yield s
        # Isolate each test — StaticPool shares the one in-memory DB across
        # the whole file, so a leftover row from one test would corrupt the
        # next test's assumptions about who's "most recent."
        s.query(ApplicationRow).delete()
        s.commit()


def test_never_returns_another_users_application(session):
    # User B's row is more recent than user A's — under the old unscoped
    # query (ORDER BY submitted_at DESC, first match wins), searching as
    # user A would have returned user B's row. That is the exact bug.
    _seed(session, app_id="a1", user_id="user-a", company="Wix", status="submitted", submitted_at="2026-08-01")
    _seed(session, app_id="b1", user_id="user-b", company="Wix", status="submitted", submitted_at="2026-08-20")

    result = find_updatable_by_company(session, "user-a", "Wix Engineering", _UPDATABLE)

    assert result is not None
    assert result.application_id == "a1"
    assert result.user_id == "user-a"


def test_returns_none_rather_than_a_different_users_match(session):
    # user-a has no application at this company at all; user-b does. The
    # function must return None for user-a, never fall back to user-b's row.
    _seed(session, app_id="b1", user_id="user-b", company="Notion", status="submitted", submitted_at="2026-08-20")

    result = find_updatable_by_company(session, "user-a", "Notion", _UPDATABLE)

    assert result is None


def test_fuzzy_company_match_still_works_within_one_users_scope(session):
    _seed(session, app_id="a1", user_id="user-a", company="Google Inc.", status="submitted", submitted_at="2026-08-01")

    result = find_updatable_by_company(session, "user-a", "Google", _UPDATABLE)

    assert result is not None
    assert result.application_id == "a1"


def test_ignores_non_updatable_statuses(session):
    _seed(session, app_id="a1", user_id="user-a", company="Wix", status="offer", submitted_at="2026-08-01")

    result = find_updatable_by_company(session, "user-a", "Wix", _UPDATABLE)

    assert result is None
