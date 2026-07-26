"""
Tests for GET /api/linkedin/jobs (backend/api/routes/linkedin_jobs.py) and
its repository method (backend/repositories/linkedin_job_repository.py's
get_paginated_jobs()).

Uses the real local/test PostgreSQL instance (see conftest.py's
db_available/clean_jobs_table fixtures) — skipped, not failed, if
unreachable. Auth is stubbed via FastAPI's dependency_overrides (this route
requires Depends(get_current_user) like every other GET route in this app;
no real Supabase JWT is needed to test the route's own behavior).
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from backend.api.deps import CurrentUser, get_current_user
from backend.main import app
from backend.repositories.linkedin_job_repository import bulk_upsert_jobs
from backend.services.linkedin_job_normalize import build_normalized_job, compute_data_hash


@pytest.fixture()
def client():
    """
    Per-test override, set up and torn down around each test — NOT a
    module-level assignment. Several other test files (test_skills_gap_
    route.py, test_outreach_service.py, test_profile_trust.py, test_
    interview_routes.py) set/pop the same `get_current_user` key on the
    same shared `app.dependency_overrides` dict; a module-level override
    that's never popped gets silently wiped by whichever of those files'
    per-test teardown happens to run afterward in the same session,
    breaking these tests only when the full suite runs (confirmed —
    passed standalone, failed under `pytest backend/tests/`).
    """
    def _override_user():
        return CurrentUser(user_id="test-user", email="test@example.com")

    app.dependency_overrides[get_current_user] = _override_user
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def _seed_jobs(n: int, *, session=None):
    """Insert `n` distinct jobs, each with a strictly increasing
    insertion_time so ordering is unambiguous to assert on. bulk_upsert_jobs
    always stamps insertion_time as "now" for a new row (see that
    function's docstring), so distinct rows are inserted one call at a time
    a millisecond apart to guarantee a strict order — a single batched call
    would give every row in it the same insertion_time timestamp."""
    import time
    for i in range(n):
        raw = {
            "title": f"Job {i}",
            "company": f"Company {i}",
            "location": "Israel",
            "posted_text": "1 hour ago",
            "job_url": f"https://il.linkedin.com/jobs/view/job-{i}-at-company-{i}-{1000000000 + i}",
            "company_url": None,
            "description": f"Description for job {i}",
            "exact_posted_text": "1 hour ago",
            "applicants_text": "< 25",
            "seniority_level": "Entry level",
            "employment_type": "Full-time",
            "job_function": "Engineering",
            "industries": "Software Development",
            "company_logo_url": None,
        }
        normalized = build_normalized_job(raw)
        normalized["data_hash"] = compute_data_hash(normalized)
        normalized["scraped_at"] = datetime.now(timezone.utc)
        bulk_upsert_jobs([normalized], session=session)
        time.sleep(0.01)


# ── 1-4. page / page_size behavior ───────────────────────────────────────────

def test_default_page_and_page_size(client, clean_jobs_table):
    _seed_jobs(3)
    resp = client.get("/api/linkedin/jobs")
    assert resp.status_code == 200
    body = resp.json()
    assert body["pagination"]["page"] == 1
    assert body["pagination"]["page_size"] == 25
    assert len(body["items"]) == 3


def test_first_page(client, clean_jobs_table):
    _seed_jobs(5)
    resp = client.get("/api/linkedin/jobs?page=1&page_size=2")
    body = resp.json()
    assert len(body["items"]) == 2
    assert body["pagination"] == {
        "page": 1, "page_size": 2, "total_items": 5,
        "total_pages": 3, "has_next": True, "has_previous": False,
    }


def test_middle_page(client, clean_jobs_table):
    _seed_jobs(5)
    resp = client.get("/api/linkedin/jobs?page=2&page_size=2")
    body = resp.json()
    assert len(body["items"]) == 2
    assert body["pagination"]["page"] == 2
    assert body["pagination"]["has_next"] is True
    assert body["pagination"]["has_previous"] is True


def test_last_page_partial(client, clean_jobs_table):
    _seed_jobs(5)
    resp = client.get("/api/linkedin/jobs?page=3&page_size=2")
    body = resp.json()
    assert len(body["items"]) == 1  # 5 items, page_size 2 -> last page has 1
    assert body["pagination"]["total_pages"] == 3
    assert body["pagination"]["has_next"] is False
    assert body["pagination"]["has_previous"] is True


# ── 5. Page beyond range ─────────────────────────────────────────────────────

def test_page_beyond_range_returns_empty_items_but_correct_total(client, clean_jobs_table):
    _seed_jobs(3)
    resp = client.get("/api/linkedin/jobs?page=100&page_size=10")
    assert resp.status_code == 200
    body = resp.json()
    assert body["items"] == []
    assert body["pagination"]["total_items"] == 3
    assert body["pagination"]["total_pages"] == 1
    assert body["pagination"]["has_next"] is False


# ── 6. Empty table ───────────────────────────────────────────────────────────

def test_empty_table(client, clean_jobs_table):
    resp = client.get("/api/linkedin/jobs")
    body = resp.json()
    assert body["items"] == []
    assert body["pagination"]["total_items"] == 0
    assert body["pagination"]["total_pages"] == 0
    assert body["pagination"]["has_next"] is False
    assert body["pagination"]["has_previous"] is False


# ── 7-9. Input validation ─────────────────────────────────────────────────────

def test_page_zero_is_rejected(client, clean_jobs_table):
    resp = client.get("/api/linkedin/jobs?page=0")
    assert resp.status_code == 422


def test_negative_page_size_is_rejected(client, clean_jobs_table):
    resp = client.get("/api/linkedin/jobs?page_size=-1")
    assert resp.status_code == 422


def test_page_size_over_maximum_is_rejected(client, clean_jobs_table):
    resp = client.get("/api/linkedin/jobs?page_size=101")
    assert resp.status_code == 422


def test_page_size_at_maximum_is_accepted(client, clean_jobs_table):
    resp = client.get("/api/linkedin/jobs?page_size=100")
    assert resp.status_code == 200


# ── 10-12. Pagination metadata correctness ───────────────────────────────────

def test_total_pages_calculation(client, clean_jobs_table):
    _seed_jobs(7)
    resp = client.get("/api/linkedin/jobs?page=1&page_size=3")
    assert resp.json()["pagination"]["total_pages"] == 3  # ceil(7/3)


def test_has_next_true_when_more_pages_remain(client, clean_jobs_table):
    _seed_jobs(5)
    resp = client.get("/api/linkedin/jobs?page=1&page_size=2")
    assert resp.json()["pagination"]["has_next"] is True


def test_has_previous_false_on_first_page(client, clean_jobs_table):
    _seed_jobs(5)
    resp = client.get("/api/linkedin/jobs?page=1&page_size=2")
    assert resp.json()["pagination"]["has_previous"] is False


# ── 13. Deterministic order across pages ─────────────────────────────────────

def test_deterministic_order_no_gaps_or_duplicates_across_pages(client, clean_jobs_table):
    _seed_jobs(6)
    page1 = client.get("/api/linkedin/jobs?page=1&page_size=4").json()["items"]
    page2 = client.get("/api/linkedin/jobs?page=2&page_size=4").json()["items"]

    ids_page1 = [item["id"] for item in page1]
    ids_page2 = [item["id"] for item in page2]
    assert len(ids_page1) == 4
    assert len(ids_page2) == 2
    assert set(ids_page1).isdisjoint(ids_page2)  # no row appears on both pages

    # Newest-inserted-first: page 1 must be "Job 5".."Job 2", page 2 "Job 1","Job 0"
    all_titles = [item["title"] for item in page1] + [item["title"] for item in page2]
    assert all_titles == ["Job 5", "Job 4", "Job 3", "Job 2", "Job 1", "Job 0"]


# ── 14-15. Query efficiency (only the requested page fetched, no full scan) ──

def test_repository_returns_only_requested_page_size(clean_jobs_table):
    from backend.repositories.linkedin_job_repository import get_paginated_jobs
    _seed_jobs(50)
    result = get_paginated_jobs(page=1, page_size=5)
    assert len(result.items) == 5          # not all 50
    assert result.total_items == 50        # but total is still accurate


def test_repository_uses_limit_offset_not_full_table_load(clean_jobs_table, monkeypatch):
    """Asserts the actual SQL statement executed carries a LIMIT/OFFSET
    clause, rather than just trusting the returned row count — a stronger
    guarantee that the DB itself bounds the result set."""
    import backend.repositories.linkedin_job_repository as repo_module

    _seed_jobs(10)
    captured_statements = []
    real_execute = repo_module.Session.execute

    def spy_execute(self, statement, *args, **kwargs):
        captured_statements.append(str(statement))
        return real_execute(self, statement, *args, **kwargs)

    monkeypatch.setattr(repo_module.Session, "execute", spy_execute)
    repo_module.get_paginated_jobs(page=2, page_size=3)

    main_query = captured_statements[0]
    assert "LIMIT" in main_query and "OFFSET" in main_query


# ── Response field shape (list-view fields present, description excluded) ───

def test_response_items_include_expected_fields_and_exclude_description(client, clean_jobs_table):
    _seed_jobs(1)
    body = client.get("/api/linkedin/jobs").json()
    item = body["items"][0]
    for field in (
        "id", "linkedin_job_id", "title", "company", "location", "job_url",
        "posted_text", "exact_posted_text", "applicants_text", "seniority_level",
        "employment_type", "job_function", "industries", "company_logo_url",
        "linkedin_status", "is_active", "insertion_time", "first_seen_at",
        "last_seen_at", "updated_at",
    ):
        assert field in item, f"missing field: {field}"
    assert "description" not in item
    assert "company_url" not in item
    assert "data_hash" not in item


def test_route_requires_authentication_without_override():
    """With no override active at all (this test deliberately does NOT
    request the `client` fixture), the route 401s — confirming the auth
    dependency is real, not accidentally bypassed globally."""
    assert get_current_user not in app.dependency_overrides
    anon_client = TestClient(app)
    resp = anon_client.get("/api/linkedin/jobs")
    assert resp.status_code == 401
