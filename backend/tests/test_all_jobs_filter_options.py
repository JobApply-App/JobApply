"""
Unit tests — get_all_jobs_filter_options() (backend/repositories/all_jobs_repository.py)

Confirms the single-round-trip rewrite (5 x ARRAY(SELECT DISTINCT ...)
subqueries in one SELECT) preserves exact output vs. the original 5 separate
queries — consolidation only reduces round trips, never changes behavior.

Runs against the real Postgres DB (db_available fixture) — `all_jobs` is a
shared, non-user-scoped table.
"""
from __future__ import annotations

from sqlalchemy import event, text


def test_filter_options_returns_expected_shape(db_available):
    from backend.repositories.all_jobs_repository import get_all_jobs_filter_options

    result = get_all_jobs_filter_options()

    # Note: sort order comes from Postgres's ORDER BY (locale-aware collation),
    # which does not necessarily match Python's sorted() (codepoint order) —
    # e.g. Postgres may order 'a' before 'A'. Ordering itself is verified
    # against the original 5-query implementation in the equivalence test
    # below; here we only check shape and distinctness.
    for field in ("sources", "seniority_levels", "employment_types", "job_functions", "industries"):
        values = getattr(result, field)
        assert isinstance(values, list)
        assert all(isinstance(v, str) for v in values)
        assert len(values) == len(set(values)), f"{field} must be distinct"


def test_filter_options_issues_exactly_one_query(db_available):
    """
    Sanity bound: the old implementation issued 5 separate DISTINCT queries
    (measured ~1993ms). The consolidated version must issue exactly 1.
    """
    from backend.core.postgres import PG_ENGINE
    from backend.repositories.all_jobs_repository import get_all_jobs_filter_options

    query_count = 0

    def _count(*a, **kw):
        nonlocal query_count
        query_count += 1

    event.listen(PG_ENGINE, "before_cursor_execute", _count)
    try:
        get_all_jobs_filter_options()
    finally:
        event.remove(PG_ENGINE, "before_cursor_execute", _count)

    assert query_count == 1, f"expected exactly 1 query, got {query_count}"


def test_filter_options_matches_five_query_original(db_available):
    """
    Byte-for-byte equivalence: the single consolidated query must return the
    exact same distinct/sorted values as the original 5-query implementation.
    """
    from backend.core.postgres import PG_ENGINE, get_pg_session
    from backend.models.all_jobs import AllJobRow
    from backend.repositories.all_jobs_repository import get_all_jobs_filter_options

    got = get_all_jobs_filter_options()

    _TABLE = AllJobRow.__table__
    from sqlalchemy import select

    session = get_pg_session()
    try:
        def _distinct(col):
            stmt = (
                select(_TABLE.c[col])
                .where(_TABLE.c[col].is_not(None))
                .distinct()
                .order_by(_TABLE.c[col])
            )
            return [row[0] for row in session.execute(stmt).all()]

        def _distinct_unnested(col):
            stmt = text(
                f"SELECT DISTINCT x FROM public.all_jobs, unnest({col}) x "
                f"WHERE {col} IS NOT NULL ORDER BY x"
            )
            return [row[0] for row in session.execute(stmt).all()]

        assert got.sources == _distinct("source")
        assert got.seniority_levels == _distinct("seniority_level")
        assert got.employment_types == _distinct("employment_type")
        assert got.job_functions == _distinct_unnested("job_function")
        assert got.industries == _distinct_unnested("industries")
    finally:
        session.close()
