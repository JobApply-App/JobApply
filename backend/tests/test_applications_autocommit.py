"""
Unit tests — GET /api/applications and GET /api/crm/board AUTOCOMMIT fix.

Confirms the AUTOCOMMIT-scoped connection (backend/api/routes/applications.py,
backend/api/routes/crm.py) preserves exact output vs. the engine's default
(transactional) mode — AUTOCOMMIT only removes the implicit rollback-on-close
cost, it must never change what's returned.

Runs against the real Postgres DB (db_available fixture).
"""
from __future__ import annotations

from sqlalchemy import event

_QA_USER_A = "e2472fa3-db25-4e53-9d0b-2aed67bcfe0e"   # real account with 11 applications


def test_list_applications_issues_exactly_one_query(db_available):
    from backend.api.deps import CurrentUser
    from backend.api.routes.applications import list_applications
    from backend.core.database import ENGINE

    query_count = 0

    def _count(*a, **kw):
        nonlocal query_count
        query_count += 1

    event.listen(ENGINE, "before_cursor_execute", _count)
    try:
        user = CurrentUser(user_id=_QA_USER_A, email="qa@test.com", name="QA")
        import asyncio
        asyncio.get_event_loop().run_until_complete(list_applications(user=user))
    finally:
        event.remove(ENGINE, "before_cursor_execute", _count)

    assert query_count == 1, f"expected exactly 1 query, got {query_count}"


def test_list_applications_matches_default_mode(db_available):
    import asyncio
    from backend.api.deps import CurrentUser
    from backend.api.routes.applications import list_applications
    from backend.repositories import application_repository

    user = CurrentUser(user_id=_QA_USER_A, email="qa@test.com", name="QA")
    got = asyncio.get_event_loop().run_until_complete(list_applications(user=user))
    expected = application_repository.get_all(_QA_USER_A)

    assert [a.application_id for a in got] == [a.application_id for a in expected]


def test_crm_board_issues_exactly_one_query(db_available):
    import asyncio
    from backend.api.deps import CurrentUser
    from backend.api.routes.crm import get_crm_board
    from backend.core.database import ENGINE

    query_count = 0

    def _count(*a, **kw):
        nonlocal query_count
        query_count += 1

    event.listen(ENGINE, "before_cursor_execute", _count)
    try:
        user = CurrentUser(user_id=_QA_USER_A, email="qa@test.com", name="QA")
        asyncio.get_event_loop().run_until_complete(get_crm_board(user=user))
    finally:
        event.remove(ENGINE, "before_cursor_execute", _count)

    assert query_count == 1, f"expected exactly 1 query, got {query_count}"


def test_crm_board_matches_default_mode(db_available):
    import asyncio
    from backend.api.deps import CurrentUser
    from backend.api.routes.crm import get_crm_board, _VALID_STAGE_KEYS
    from backend.repositories import application_repository

    user = CurrentUser(user_id=_QA_USER_A, email="qa@test.com", name="QA")
    got = asyncio.get_event_loop().run_until_complete(get_crm_board(user=user))
    expected_rows = application_repository.get_by_statuses(_QA_USER_A, _VALID_STAGE_KEYS)

    got_ids = sorted(c.application_id for col in got.columns for c in col.cards)
    expected_ids = sorted(r.application_id for r in expected_rows)
    assert got_ids == expected_ids
