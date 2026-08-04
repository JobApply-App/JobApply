"""
Unit/integration tests — GET /api/dashboard/overview (NDJSON stream)

The aggregated Overview-page endpoint streams 4 sections (overview,
scraper_status, confidence_matrix, trust_score) as newline-delimited JSON,
each the instant its own computation finishes, from one shared AUTOCOMMIT
connection with profile_entities/evidence loaded exactly once via a single
LEFT JOIN — see profile_entity_repository.get_all_with_evidence_for_user().

Correctness-first design: there is NO server-side cache in front of this
endpoint. Every call recomputes from the current committed database state —
see test_dashboard_overview_always_reads_live_data below, which asserts this
directly (every call issues its full query set, never zero).

Runs against the real Postgres DB (db_available fixture) rather than an
in-memory SQLite engine — user_job_matches (needed by the KPI query) has a
hard FK to auth.users and Postgres-only `uuid`/CAST syntax, same constraint
documented in test_job_postings_isolation.py/test_analytics_service.py.
"""
from __future__ import annotations

import json

from sqlalchemy import event

_QA_USER_A = "2631c93b-93bb-4313-a2c2-79dbb786d199"

_ALL_SECTIONS = {"overview", "scraper_status", "confidence_matrix", "trust_score"}


def _collect(chunks) -> dict:
    """NDJSON chunks -> {section_name: parsed_json_line}."""
    result = {}
    for chunk in chunks:
        obj = json.loads(chunk)
        result[obj["section"]] = obj
    return result


def test_stream_emits_all_four_sections_without_error(db_available):
    from backend.api.routes.dashboard import _stream_dashboard_overview

    sections = _collect(_stream_dashboard_overview(_QA_USER_A))

    assert set(sections.keys()) == _ALL_SECTIONS
    for name, obj in sections.items():
        assert "error" not in obj, f"section {name} unexpectedly errored: {obj.get('error')}"
        assert "data" in obj


def test_stream_matches_individual_endpoints(db_available):
    """
    The streamed trust_score/confidence_matrix sections must be identical to
    calling the existing standalone functions with a fresh, independent
    load — proves the shared-load reuse in dashboard.py doesn't change any
    computed value, only how many times the data is fetched and how it's
    delivered.
    """
    from backend.api.routes.dashboard import _stream_dashboard_overview
    from backend.services.analytics_service import compute_overview
    from backend.services.confidence_matrix_service import get_confidence_matrix_and_breakdown
    from backend.core.database import ENGINE
    from backend.api.routes import profile as profile_module
    from backend.repositories import profile_entity_repository, evidence_repository
    from datetime import datetime, timezone

    sections = _collect(_stream_dashboard_overview(_QA_USER_A))
    result = {name: obj["data"] for name, obj in sections.items()}

    expected_overview = compute_overview(_QA_USER_A)
    assert result["overview"] == expected_overview

    expected_radar, expected_breakdown = get_confidence_matrix_and_breakdown(_QA_USER_A, ENGINE)
    assert result["confidence_matrix"]["radar_data"] == expected_radar
    got_breakdown = {b["entity_id"]: b for b in result["confidence_matrix"]["entity_breakdown"]}
    exp_breakdown = {b["entity_id"]: b for b in expected_breakdown}
    assert got_breakdown == exp_breakdown

    now_iso = datetime.now(timezone.utc).isoformat()
    from sqlalchemy.orm import Session
    with Session(ENGINE) as db:
        entity_rows = profile_entity_repository.get_all_for_user(_QA_USER_A, session=db)
        entity_ids = [e.entity_id for e in entity_rows]
        evidence_by_entity = evidence_repository.get_active_for_entities(entity_ids, now_iso, session=db)
    expected_trust = profile_module.build_trust_score_response(_QA_USER_A, entity_rows, evidence_by_entity, now_iso)

    assert result["trust_score"]["overall_trust_score"] == expected_trust["overall_trust_score"]
    assert result["trust_score"]["category_averages"] == expected_trust["category_averages"]
    got_entities = {e["entity_id"]: e for e in result["trust_score"]["entities"]}
    exp_entities = {e["entity_id"]: e for e in expected_trust["entities"]}
    assert got_entities == exp_entities


def test_stream_loads_entities_and_evidence_exactly_once(db_available):
    """
    The whole point of the aggregated endpoint: profile_entities + evidence
    are loaded ONCE (a single LEFT JOIN) and reused for both trust_score and
    confidence_matrix, not loaded independently by each, and not as two
    separate queries either.
    """
    from backend.api.routes.dashboard import _stream_dashboard_overview
    from backend.repositories import profile_entity_repository

    load_calls = []
    original = profile_entity_repository.get_all_with_evidence_for_user

    def _counting(*args, **kwargs):
        load_calls.append(1)
        return original(*args, **kwargs)

    profile_entity_repository.get_all_with_evidence_for_user = _counting
    try:
        list(_stream_dashboard_overview(_QA_USER_A))
    finally:
        profile_entity_repository.get_all_with_evidence_for_user = original

    assert len(load_calls) == 1, f"expected 1 combined entity+evidence load, got {len(load_calls)}"


def test_stream_sections_arrive_in_fastest_first_order(db_available):
    """
    overview and scraper_status (one query each) must arrive before
    confidence_matrix/trust_score (which wait on the entities+evidence
    JOIN) — this is the entire point of streaming instead of buffering: the
    page can render KPIs and the scraper banner before the heavier section
    resolves.
    """
    from backend.api.routes.dashboard import _stream_dashboard_overview

    order = [json.loads(chunk)["section"] for chunk in _stream_dashboard_overview(_QA_USER_A)]

    assert order.index("overview") < order.index("confidence_matrix")
    assert order.index("scraper_status") < order.index("confidence_matrix")
    assert order.index("overview") < order.index("trust_score")
    assert order.index("scraper_status") < order.index("trust_score")


def test_stream_one_section_failure_does_not_abort_others(db_available):
    """
    Per-widget error handling: if scraper_status's computation raises, the
    other 3 sections must still stream through successfully with their real
    data, and scraper_status's line reports an error instead of silently
    vanishing or taking down the whole response.
    """
    from backend.api.routes import dashboard as dashboard_module

    original = dashboard_module.build_scraper_status

    def _boom(*a, **kw):
        raise RuntimeError("simulated scraper-status failure")

    dashboard_module.build_scraper_status = _boom
    try:
        sections = _collect(dashboard_module._stream_dashboard_overview(_QA_USER_A))
    finally:
        dashboard_module.build_scraper_status = original

    assert set(sections.keys()) == _ALL_SECTIONS
    assert "error" in sections["scraper_status"]
    for name in ("overview", "confidence_matrix", "trust_score"):
        assert "error" not in sections[name], f"{name} should not have failed"
        assert "data" in sections[name]


def test_stream_entity_load_failure_reports_errors_for_dependent_sections_only(db_available):
    """
    If the entities+evidence JOIN itself fails, overview and scraper_status
    (independent of it) must still have already succeeded, while
    confidence_matrix and trust_score (which depend on that load) report
    errors rather than the whole request failing.
    """
    from backend.api.routes import dashboard as dashboard_module
    from backend.repositories import profile_entity_repository

    original = profile_entity_repository.get_all_with_evidence_for_user

    def _boom(*a, **kw):
        raise RuntimeError("simulated DB failure")

    profile_entity_repository.get_all_with_evidence_for_user = _boom
    try:
        sections = _collect(dashboard_module._stream_dashboard_overview(_QA_USER_A))
    finally:
        profile_entity_repository.get_all_with_evidence_for_user = original

    assert set(sections.keys()) == _ALL_SECTIONS
    assert "error" not in sections["overview"]
    assert "error" not in sections["scraper_status"]
    assert "error" in sections["confidence_matrix"]
    assert "error" in sections["trust_score"]


def test_stream_http_endpoint(db_available):
    """Full HTTP round trip via TestClient, auth dependency overridden."""
    from fastapi.testclient import TestClient
    from backend.main import app
    from backend.api.deps import CurrentUser, get_current_user

    def _override():
        return CurrentUser(user_id=_QA_USER_A, email="qa@test.com", name="QA")

    app.dependency_overrides[get_current_user] = _override
    try:
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/api/dashboard/overview")
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    assert resp.headers["content-type"].startswith("application/x-ndjson")

    lines = [line for line in resp.text.strip().split("\n") if line]
    sections = {json.loads(line)["section"]: json.loads(line) for line in lines}
    assert set(sections.keys()) == _ALL_SECTIONS
    assert sections["trust_score"]["data"]["user_id"] == _QA_USER_A
    assert sections["confidence_matrix"]["data"]["user_id"] == _QA_USER_A


def test_stream_has_no_cache_header(db_available):
    """
    Correctness-first design: this endpoint has no server-side cache, so
    there is no X-Dashboard-Cache (or any other cache-status) header on the
    response — its presence would imply a cache layer exists to report on.
    """
    from fastapi.testclient import TestClient
    from backend.main import app
    from backend.api.deps import CurrentUser, get_current_user

    def _override():
        return CurrentUser(user_id=_QA_USER_A, email="qa@test.com", name="QA")

    app.dependency_overrides[get_current_user] = _override
    try:
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/api/dashboard/overview")
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert resp.status_code == 200
    assert "X-Dashboard-Cache" not in resp.headers
    assert "ETag" not in resp.headers
    assert "no-store" in resp.headers.get("Cache-Control", "").lower()


def test_stream_always_reads_live_data(db_available):
    """
    The whole point of removing the server-side cache: back-to-back calls
    for the SAME user must each independently issue their full query set —
    a second call must never short-circuit to a cached value with zero
    queries. This is what "the database remains the single source of truth"
    means, verified directly rather than assumed.
    """
    from backend.api.routes.dashboard import _stream_dashboard_overview
    from backend.core.database import ENGINE

    def _count_queries(fn):
        count = 0

        def _tick(*a, **kw):
            nonlocal count
            count += 1
        event.listen(ENGINE, "before_cursor_execute", _tick)
        try:
            fn()
        finally:
            event.remove(ENGINE, "before_cursor_execute", _tick)
        return count

    first_call_queries = _count_queries(lambda: list(_stream_dashboard_overview(_QA_USER_A)))
    second_call_queries = _count_queries(lambda: list(_stream_dashboard_overview(_QA_USER_A)))

    assert first_call_queries > 0, "first call must hit the database"
    assert second_call_queries > 0, "second call must ALSO hit the database — no cache short-circuit"
    assert second_call_queries == first_call_queries, (
        "an uncached endpoint should issue the same query set every time it's called"
    )


def test_stream_reflects_a_write_immediately(db_available):
    """
    End-to-end proof that the database is the single source of truth: a
    write followed immediately by a GET must reflect that write — there is
    no cache layer that could still be serving a pre-write snapshot.
    """
    import uuid
    from datetime import datetime, timezone

    from backend.api.routes.dashboard import _stream_dashboard_overview
    from backend.core.postgres import PG_ENGINE
    from backend.repositories import job_repository as job_store
    from backend.schemas.job import DetailedAnalysis, JobMatch

    before = _collect(_stream_dashboard_overview(_QA_USER_A))
    before_count = before["overview"]["data"]["jobs_scanned_today"]

    jid = f"live-read-proof-{uuid.uuid4()}"
    job = JobMatch(
        job_id=jid, title="Live-read proof", company="Acme", location="Remote",
        score=80.0, confidence_score=50, culture_fit_score=50,
        trajectory_alignment="", company_dna_inference="",
        detailed_analysis=DetailedAnalysis(strengths=[], critical_gaps=[], strategic_advice=[]),
        investigation_points=[], reasons=[],
        user_id=_QA_USER_A, match_score=42.0, status="new",
        is_new=True, posted_at="", source="automatic", is_open=True,
        source_type="other", score_is_proxy=False,
        created_at=datetime.now(timezone.utc).isoformat(),
        apply_url=f"https://example.com/{jid}",
    )
    try:
        job_store.save_with_source_priority(job)
        after = _collect(_stream_dashboard_overview(_QA_USER_A))
        after_count = after["overview"]["data"]["jobs_scanned_today"]
        assert after_count == before_count + 1, (
            "a GET immediately after a write must reflect that write — "
            "a cached response would still show the pre-write count"
        )
    finally:
        with PG_ENGINE.begin() as conn:
            from sqlalchemy import text as _text
            postings = conn.execute(_text(
                "SELECT job_posting_id FROM public.user_job_matches WHERE job_id = :jid"
            ), {"jid": jid}).fetchall()
            conn.execute(_text("DELETE FROM public.user_job_matches WHERE job_id = :jid"), {"jid": jid})
            for (pid,) in postings:
                conn.execute(_text("DELETE FROM public.job_postings WHERE id = :pid"), {"pid": pid})


def test_stream_query_count_bound(db_available):
    """
    Sanity bound on total SQL queries for the whole streamed response —
    catches a future regression that reintroduces per-item round trips.
    Current shape: 1 (overview KPI) + 1 (scraper-status) + 1 (entities+
    evidence, single JOIN) = 3, all pure-Python from there (confidence_matrix
    and trust_score need no further queries). The <=8 bound here is a loose
    regression guard, not a tight pin to the current count.
    """
    from backend.api.routes.dashboard import _stream_dashboard_overview
    from backend.core.database import ENGINE

    query_count = 0

    def _count(*a, **kw):
        nonlocal query_count
        query_count += 1

    event.listen(ENGINE, "before_cursor_execute", _count)
    try:
        list(_stream_dashboard_overview(_QA_USER_A))
    finally:
        event.remove(ENGINE, "before_cursor_execute", _count)

    assert query_count <= 8, f"expected <=8 total queries, got {query_count}"
