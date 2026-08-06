"""
all_jobs_match_service.py — the public.all_jobs -> Matches feed bridge.

Deliberately no DB: every test here monkeypatches the module's own DB-facing
helpers (_existing_job_ids, _candidate_all_jobs_rows, ScraperManager._save_new)
rather than touching real Postgres, so these stay runnable anywhere (CI
included) and isolate the mapping/filtering logic from the actual save path
(which is already covered by the scraper_manager/job_repository tests that
exercise save_with_source_priority directly).
"""
from __future__ import annotations

from types import SimpleNamespace

import backend.services.all_jobs_match_service as svc


# ── _location_to_string ──────────────────────────────────────────────────────

def test_location_to_string_joins_present_parts():
    assert svc._location_to_string({"city": "Tel Aviv", "district": None, "country": "Israel"}) == \
        "Tel Aviv, Israel"


def test_location_to_string_all_parts_present():
    loc = {"city": "Tel Aviv", "district": "Center District", "country": "Israel"}
    assert svc._location_to_string(loc) == "Tel Aviv, Center District, Israel"


def test_location_to_string_none_or_empty_falls_back_to_unknown():
    assert svc._location_to_string(None) == "Unknown"
    assert svc._location_to_string({}) == "Unknown"
    assert svc._location_to_string({"city": None, "district": None, "country": None}) == "Unknown"


def test_location_to_string_strips_whitespace_only_values():
    assert svc._location_to_string({"city": "  ", "district": None, "country": "Israel"}) == "Israel"


# ── _source_type_from_all_jobs_source ────────────────────────────────────────

def test_source_type_maps_linkedin():
    assert svc._source_type_from_all_jobs_source("linkedin") == "linkedin"
    assert svc._source_type_from_all_jobs_source("LinkedIn") == "linkedin"


def test_source_type_maps_company_site_variants():
    for s in ("company_site", "ats", "career_page"):
        assert svc._source_type_from_all_jobs_source(s) == "company_site"


def test_source_type_unrecognized_falls_back_to_other():
    assert svc._source_type_from_all_jobs_source("some_new_board") == "other"
    assert svc._source_type_from_all_jobs_source(None) == "other"
    assert svc._source_type_from_all_jobs_source("") == "other"


# ── _all_jobs_row_to_job_match ───────────────────────────────────────────────

def _row(**overrides):
    defaults = dict(
        job_title="Senior Product Manager",
        company_name="Acme Corp",
        location={"city": "Tel Aviv", "district": None, "country": "Israel"},
        job_url="https://example.com/jobs/12345",
        description="Full JD text here.",
        posted_at=None,
        source="linkedin",
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_row_to_job_match_maps_fields_and_zeroes_scores():
    job = svc._all_jobs_row_to_job_match(_row(), user_id="user-abc")
    assert job.title == "Senior Product Manager"
    assert job.company == "Acme Corp"
    assert job.location == "Tel Aviv, Israel"
    assert job.apply_url == "https://example.com/jobs/12345"
    assert job.jd_text == "Full JD text here."
    assert job.source_type == "linkedin"
    assert job.user_id == "user-abc"
    assert job.score == 0.0
    assert job.match_score == 0.0
    assert job.status == "new"


def test_row_to_job_match_missing_url_returns_none():
    assert svc._all_jobs_row_to_job_match(_row(job_url=""), user_id="user-abc") is None
    assert svc._all_jobs_row_to_job_match(_row(job_url=None), user_id="user-abc") is None


def test_row_to_job_match_job_id_is_deterministic_per_url():
    a = svc._all_jobs_row_to_job_match(_row(), user_id="user-abc")
    b = svc._all_jobs_row_to_job_match(_row(), user_id="user-abc")
    assert a.job_id == b.job_id  # same apply_url -> same job_id, every cycle

    different_url = svc._all_jobs_row_to_job_match(
        _row(job_url="https://example.com/jobs/other"), user_id="user-abc",
    )
    assert different_url.job_id != a.job_id


# ── run_all_jobs_matching_cycle ──────────────────────────────────────────────

def test_cycle_skips_rows_the_user_already_has_a_match_for(monkeypatch):
    """
    The core safety property: a row whose salted job_id is already in the
    user's existing matches must never be re-submitted to _save_new — see
    the module docstring for why re-submitting a zero-score row for an
    already-scored job would silently reset that user's real score to 0.
    """
    from backend.scrapers.base_scraper import make_job_id, make_tenant_job_id

    already_matched_url = "https://example.com/jobs/already-matched"
    new_url = "https://example.com/jobs/brand-new"

    salted_existing = make_tenant_job_id(
        make_job_id(already_matched_url, prefix=svc._JOB_ID_PREFIX), "user-abc",
    )

    monkeypatch.setattr(svc, "_existing_job_ids", lambda user_id: {salted_existing})
    monkeypatch.setattr(
        svc, "_candidate_all_jobs_rows",
        lambda limit: [_row(job_url=already_matched_url), _row(job_url=new_url)],
    )

    captured = {}

    class _FakeScraperManager:
        @staticmethod
        def _save_new(jobs, limit=None, user_id=None):
            captured["jobs"] = jobs
            captured["user_id"] = user_id
            return len(jobs)

    monkeypatch.setattr(
        "backend.scrapers.scraper_manager.ScraperManager", _FakeScraperManager,
    )

    saved = svc.run_all_jobs_matching_cycle("user-abc", limit=10)

    assert saved == 1
    assert len(captured["jobs"]) == 1
    assert captured["jobs"][0].apply_url == new_url
    assert captured["user_id"] == "user-abc"


def test_cycle_respects_limit(monkeypatch):
    urls = [f"https://example.com/jobs/{i}" for i in range(5)]
    monkeypatch.setattr(svc, "_existing_job_ids", lambda user_id: set())
    monkeypatch.setattr(
        svc, "_candidate_all_jobs_rows",
        lambda limit: [_row(job_url=u) for u in urls],
    )

    captured = {}

    class _FakeScraperManager:
        @staticmethod
        def _save_new(jobs, limit=None, user_id=None):
            captured["jobs"] = jobs
            return len(jobs)

    monkeypatch.setattr(
        "backend.scrapers.scraper_manager.ScraperManager", _FakeScraperManager,
    )

    svc.run_all_jobs_matching_cycle("user-abc", limit=2)
    assert len(captured["jobs"]) == 2


def test_cycle_returns_zero_and_skips_save_when_nothing_new(monkeypatch):
    monkeypatch.setattr(svc, "_existing_job_ids", lambda user_id: set())
    monkeypatch.setattr(svc, "_candidate_all_jobs_rows", lambda limit: [])

    def _boom(*a, **k):
        raise AssertionError("_save_new must not be called with nothing to save")

    monkeypatch.setattr(
        "backend.scrapers.scraper_manager.ScraperManager",
        SimpleNamespace(_save_new=_boom),
    )

    assert svc.run_all_jobs_matching_cycle("user-abc") == 0


# ── Live Dev integration: real all_jobs rows, real user_job_matches writes ──
# Uses a disposable_qa_account (see conftest.py) so this never touches a real
# account's data. profiles.id -> user_job_matches.user_id is ON DELETE
# CASCADE, so the fixture's own teardown (deleting the auth.users row) is
# sufficient cleanup here — nothing extra needed in this test.

def test_cycle_against_real_dev_writes_zero_score_matches(disposable_qa_account):
    from sqlalchemy import text as _text

    from backend.core.database import ENGINE

    saved = svc.run_all_jobs_matching_cycle(disposable_qa_account, limit=5)
    assert saved > 0, (
        "Expected at least one candidate from the real Dev all_jobs table — "
        "if this fails, either all_jobs is empty or every candidate title "
        "failed the relevancy gate."
    )

    with ENGINE.connect() as conn:
        rows = conn.execute(
            _text(
                "SELECT ujm.job_id, ujm.score, ujm.match_score, ujm.status, jp.source_type "
                "FROM public.user_job_matches ujm "
                "JOIN public.job_postings jp ON jp.id = ujm.job_posting_id "
                "WHERE ujm.user_id = CAST(:uid AS uuid)"
            ),
            {"uid": disposable_qa_account},
        ).fetchall()

    assert len(rows) == saved
    for row in rows:
        assert row.job_id.startswith(svc._JOB_ID_PREFIX)
        assert row.score == 0.0
        assert row.match_score == 0.0
        assert row.status == "new"
        assert row.source_type in ("linkedin", "company_site", "other")

    # The real risk this module is designed around (see module docstring):
    # re-processing a candidate the user already has a match for must NEVER
    # reset a score the enrichment loop has since written. Simulate that by
    # bumping one just-saved row's score directly (standing in for a real
    # enrichment pass), then re-running a cycle whose candidate pool is
    # forced to contain that exact same all_jobs row again — the pre-check
    # against _existing_job_ids must skip it before it ever reaches
    # _save_new, leaving the score untouched.
    scored_job_id = rows[0].job_id
    with ENGINE.connect() as conn:
        conn.execute(
            _text(
                "UPDATE public.user_job_matches SET score = 91.5, match_score = 87.0 "
                "WHERE job_id = :jid AND user_id = CAST(:uid AS uuid)"
            ),
            {"jid": scored_job_id, "uid": disposable_qa_account},
        )
        conn.commit()

    from backend.models.all_jobs import AllJobRow
    from backend.core.postgres import get_pg_session

    with get_pg_session() as session:
        repeated_row = (
            session.query(AllJobRow)
            .order_by(AllJobRow.last_seen_at.desc())
            .limit(svc._CANDIDATE_POOL_SIZE)
            .all()
        )
    # Isolate exactly the row that produced scored_job_id, forcing the
    # candidate pool to be dominated by the already-matched row so the
    # pre-check (not sheer candidate-pool luck) is what's under test.
    from backend.scrapers.base_scraper import make_job_id, make_tenant_job_id

    target_row = next(
        r for r in repeated_row
        if make_tenant_job_id(make_job_id((r.job_url or "").strip(), prefix=svc._JOB_ID_PREFIX), disposable_qa_account)
        == scored_job_id
    )

    real_candidates_fn = svc._candidate_all_jobs_rows
    svc._candidate_all_jobs_rows = lambda limit: [target_row]
    try:
        saved_repeat = svc.run_all_jobs_matching_cycle(disposable_qa_account, limit=5)
    finally:
        svc._candidate_all_jobs_rows = real_candidates_fn

    assert saved_repeat == 0

    with ENGINE.connect() as conn:
        row = conn.execute(
            _text(
                "SELECT score, match_score FROM public.user_job_matches "
                "WHERE job_id = :jid AND user_id = CAST(:uid AS uuid)"
            ),
            {"jid": scored_job_id, "uid": disposable_qa_account},
        ).fetchone()
    assert row.score == 91.5
    assert row.match_score == 87.0
