"""
GET /api/all-jobs/company-logos and the logo filter behind it.

The database lookup is stubbed: the route's own job is passing the names
through and shaping the answer, and usable_logo() is pure. No database runs.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.api.deps import CurrentUser, get_current_user
from backend.api.routes import all_jobs as route
from backend.main import app
from backend.repositories.all_jobs_repository import usable_logo


@pytest.fixture()
def client():
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(user_id="test-user", email="test@example.com")
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_returns_logos_keyed_by_the_names_sent(client, monkeypatch):
    seen = {}

    def fake(names):
        seen["names"] = names
        return {"monday.com": "https://media.licdn.com/dms/image/v2/x/company-logo_100_100/x"}

    monkeypatch.setattr(route, "get_company_logos", fake)
    resp = client.get("/api/all-jobs/company-logos", params=[("name", "monday.com"), ("name", "Unknown Ltd")])
    assert resp.status_code == 200
    assert seen["names"] == ["monday.com", "Unknown Ltd"]
    assert resp.json() == {"logos": {"monday.com": "https://media.licdn.com/dms/image/v2/x/company-logo_100_100/x"}}


def test_too_many_names_is_rejected(client):
    resp = client.get("/api/all-jobs/company-logos", params=[("name", f"c{i}") for i in range(101)])
    assert resp.status_code == 422


def test_placeholder_and_insecure_logos_are_dropped():
    assert usable_logo("https://static.licdn.com/aero-v1/sc/h/1kxd9keftj1y0os0evez0vt9u") is None
    assert usable_logo("http://media.licdn.com/x") is None
    assert usable_logo(None) is None
    assert usable_logo("https://media.licdn.com/dms/image/v2/x/company-logo_100_100/x") is not None
