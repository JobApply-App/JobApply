"""
pytest configuration for backend/tests/
========================================
Ensures the project root is on sys.path so the canonical `backend.*` package
path resolves when pytest is run from anywhere.

All intra-backend imports use the `backend.` prefix (see main.py). The bare
`api.*` / `services.*` / `config` forms are forbidden: they load the same
file as a second, independent module object, which breaks monkeypatching and
FastAPI dependency_overrides (the override keys on a different function
object than the one the app actually calls).
"""
import os
import sys
import pytest
from pathlib import Path
from sqlalchemy import text

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent   # .../JobApply_Venture

if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

@pytest.fixture(autouse=True)
def mock_env_vars():
    """Mock environment variables for tests."""
    os.environ["ANTHROPIC_API_KEY"] = "test-key-for-ci"


# ── Shared linkedin.jobs Postgres fixtures ───────────────────────────────────
# Used by test_linkedin_job_pipeline.py and test_linkedin_jobs_route.py — this
# table lives on the dedicated Postgres engine in backend/core/postgres.py,
# not the app's primary SQLite ENGINE, so it needs its own reachability
# check/cleanup rather than reusing any SQLite-based test fixture.

@pytest.fixture()
def db_available():
    from backend.core.postgres import PG_ENGINE
    try:
        with PG_ENGINE.connect():
            pass
    except Exception as exc:
        pytest.skip(f"PostgreSQL not reachable for local tests: {exc}")


@pytest.fixture()
def clean_jobs_table(db_available):
    from backend.core.postgres import get_pg_session
    with get_pg_session() as session:
        session.execute(text("TRUNCATE linkedin.jobs"))
        session.commit()
    yield
    with get_pg_session() as session:
        session.execute(text("TRUNCATE linkedin.jobs"))
        session.commit()
