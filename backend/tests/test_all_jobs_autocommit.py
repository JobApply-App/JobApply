"""
Unit tests — GET /api/all-jobs and GET /api/all-jobs/filter-options AUTOCOMMIT fix.

Confirms the AUTOCOMMIT-scoped connection (backend/api/routes/all_jobs.py)
preserves exact output vs. the engine's default (transactional) mode —
AUTOCOMMIT only removes the implicit rollback-on-close cost, it must never
change what's returned.

Runs against the real Postgres DB (db_available fixture) — `all_jobs` is a
shared, non-user-scoped table (1052 real rows at the time this was measured).
"""
from __future__ import annotations

import asyncio

from sqlalchemy.orm import Session


def test_list_all_jobs_matches_default_mode(db_available):
    from backend.api.deps import CurrentUser
    from backend.api.routes.all_jobs import list_all_jobs
    from backend.core.postgres import PG_ENGINE
    from backend.repositories.all_jobs_repository import get_paginated_all_jobs

    user = CurrentUser(user_id="00000000-0000-0000-0000-000000000000", email="qa@test.com", name="QA")

    got = asyncio.get_event_loop().run_until_complete(
        list_all_jobs(
            page=1, page_size=25,
            source=None, seniority_level=None, employment_type=None,
            job_function=None, industry=None, company=None, title=None,
            min_applicants=None, max_applicants=None, posted_within_hours=None,
            sort_by="recent",
            user=user,
        )
    )

    with Session(PG_ENGINE) as db:
        expected = get_paginated_all_jobs(page=1, page_size=25, session=db)

    assert got.pagination.total_items == expected.total_items
    assert [item.id for item in got.items] == [item["id"] for item in expected.items]


def test_list_all_jobs_filter_options_matches_default_mode(db_available):
    from backend.api.deps import CurrentUser
    from backend.api.routes.all_jobs import list_all_jobs_filter_options
    from backend.core.postgres import PG_ENGINE
    from backend.repositories.all_jobs_repository import get_all_jobs_filter_options

    user = CurrentUser(user_id="00000000-0000-0000-0000-000000000000", email="qa@test.com", name="QA")

    got = asyncio.get_event_loop().run_until_complete(list_all_jobs_filter_options(user=user))

    with Session(PG_ENGINE) as db:
        expected = get_all_jobs_filter_options(session=db)

    assert got.sources == expected.sources
    assert got.seniority_levels == expected.seniority_levels
    assert got.employment_types == expected.employment_types
    assert got.job_functions == expected.job_functions
    assert got.industries == expected.industries
