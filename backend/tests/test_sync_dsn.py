"""
Every engine and both Alembic chains build their URL with `_to_sync_dsn`.

It names psycopg2 explicitly because SQLAlchemy 2.1 changed what a bare
`postgresql://` means (psycopg 3, not installed here); Dependabot's
SQLAlchemy 2.1 bump (PR #201) failed CI at `alembic upgrade` with
"No module named 'psycopg'".
"""
import pytest
from sqlalchemy.engine import make_url

from backend.core.postgres import _to_sync_dsn

DSN = "user:p%40ss@db.example.supabase.co:6543/postgres?sslmode=require"


@pytest.mark.parametrize("scheme", ["postgresql", "postgresql+asyncpg"])
def test_postgres_urls_use_psycopg2(scheme):
    url = _to_sync_dsn(f"{scheme}://{DSN}")
    assert url == f"postgresql+psycopg2://{DSN}"
    assert make_url(url).get_driver_name() == "psycopg2"


@pytest.mark.parametrize("url", [f"postgresql+psycopg2://{DSN}", "sqlite:///backend/jobs.db"])
def test_other_urls_are_left_alone(url):
    assert _to_sync_dsn(url) == url
