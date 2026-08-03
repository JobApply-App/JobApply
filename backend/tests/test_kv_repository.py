"""
Unit tests — backend.repositories.kv_repository.get_many()

Covers the fix for the N+1 pattern (one session.get() call per key, in a
Python loop) replaced with a single `WHERE key IN (...)` query: same return
shape (dict keyed by key, absent keys simply missing) must hold before and
after.

Runs against an isolated in-memory SQLite engine so the real jobs.db is never
touched — same StaticPool pattern as test_profile_trust.py.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.models.kv import KVRow
from backend.core.database import Base
from backend.repositories import kv_repository

_TEST_ENGINE = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
Base.metadata.create_all(_TEST_ENGINE, tables=[KVRow.__table__])


@pytest.fixture(autouse=True)
def _isolated_engine():
    """Point kv_repository at the in-memory test engine for every test."""
    with patch.object(kv_repository, "ENGINE", _TEST_ENGINE):
        with Session(_TEST_ENGINE) as session:
            session.query(KVRow).delete()
            session.commit()
        yield


def _seed(**kv: str) -> None:
    with Session(_TEST_ENGINE) as session:
        for key, value in kv.items():
            session.add(KVRow(key=key, value=value, updated_at="2026-01-01T00:00:00Z"))
        session.commit()


def test_get_many_returns_all_present_keys():
    _seed(a="1", b="2", c="3")
    result = kv_repository.get_many(["a", "b", "c"])
    assert set(result.keys()) == {"a", "b", "c"}
    assert result["a"].value == "1"
    assert result["b"].value == "2"
    assert result["c"].value == "3"


def test_get_many_omits_missing_keys():
    _seed(a="1")
    result = kv_repository.get_many(["a", "missing_key"])
    assert set(result.keys()) == {"a"}
    assert "missing_key" not in result


def test_get_many_empty_keys_list_returns_empty_dict():
    assert kv_repository.get_many([]) == {}


def test_get_many_no_matching_keys_returns_empty_dict():
    result = kv_repository.get_many(["nonexistent_a", "nonexistent_b"])
    assert result == {}


def test_get_many_issues_exactly_one_query():
    """The whole point of the fix: N keys must cost 1 query, not N."""
    _seed(a="1", b="2", c="3", d="4")
    query_count = 0

    with Session(_TEST_ENGINE) as session:
        original_execute = session.execute

        def _counting_execute(*args, **kwargs):
            nonlocal query_count
            query_count += 1
            return original_execute(*args, **kwargs)

        session.execute = _counting_execute
        result = kv_repository._get_many(session, ["a", "b", "c", "d", "missing"])

    assert set(result.keys()) == {"a", "b", "c", "d"}
    assert query_count == 1, f"expected 1 query for 5 keys, got {query_count}"


def test_get_many_shares_caller_provided_session():
    """When a session is passed in, get_many must not open its own."""
    _seed(a="1")
    with Session(_TEST_ENGINE) as session:
        result = kv_repository.get_many(["a"], session=session)
    assert result["a"].value == "1"
