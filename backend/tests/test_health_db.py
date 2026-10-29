"""
/health is Render's readiness probe. It must fail (503) when the database is
unreachable — a constant 200 kept routing traffic to an instance that could
not serve a single data-backed request.
"""
from fastapi.testclient import TestClient
from sqlalchemy import create_engine


def test_health_reports_ok_with_a_database(monkeypatch):
    import backend.core.database as database
    from backend.main import app
    monkeypatch.setattr(database, "ENGINE", create_engine("sqlite://"))
    r = TestClient(app).get("/health")
    assert r.status_code == 200 and r.json()["checks"]["database"] == "ok"


def test_health_is_503_when_the_database_is_unreachable(monkeypatch):
    import backend.core.database as database
    from backend.main import app
    monkeypatch.setattr(database, "ENGINE", create_engine("postgresql://u:p@127.0.0.1:1/none"))
    r = TestClient(app).get("/health")
    assert r.status_code == 503
    assert r.json()["checks"]["database"] == "unreachable"
