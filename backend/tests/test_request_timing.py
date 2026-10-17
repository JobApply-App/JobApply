"""
Every API request logs its duration, grouped by route template.

Testers reported slow responses and nothing recorded how long any request
took (no duration in uvicorn's access log, no request logs on the Render
plan). These pin that the timing line exists, uses the route template rather
than the concrete URL, and stays out of non-API paths like /health.
"""
import logging

from fastapi.testclient import TestClient


def test_api_request_is_timed_by_route_template(caplog):
    from backend.main import app

    with caplog.at_level(logging.INFO, logger="backend.main"):
        # Unauthenticated, so it 401s — the timing line must still be written.
        TestClient(app).get("/api/resumes/tailor/status/abc123")

    lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("[timing]")]
    assert lines, "no [timing] line was logged"
    assert "/api/resumes/tailor/status/{task_id}" in lines[-1]
    assert "abc123" not in lines[-1]


def test_health_is_not_timed(caplog):
    from backend.main import app

    with caplog.at_level(logging.INFO, logger="backend.main"):
        TestClient(app).get("/health")
    assert not [r for r in caplog.records if r.getMessage().startswith("[timing]")]
