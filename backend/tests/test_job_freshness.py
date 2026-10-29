"""
Jobs posted more than JOB_MAX_AGE_DAYS (30) ago were still listed on the job
boards and in users' feeds, though they are almost certainly closed. They are
now hidden everywhere a user sees jobs — and kept in the database.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

NOW = datetime.now(timezone.utc)
OLD = NOW - timedelta(days=45)
NEW = NOW - timedelta(days=3)


def test_cutoff_is_thirty_days_by_default():
    from backend.services.job_freshness import cutoff
    assert abs((NOW - cutoff(NOW)) - timedelta(days=30)) < timedelta(seconds=1)


@pytest.fixture()
def catalog(db_available):
    """Three all_jobs rows: posted recently, posted long ago, unknown date but first seen long ago."""
    from backend.core.postgres import PG_ENGINE
    tag = uuid.uuid4().hex[:8]
    rows = {
        "fresh":     (f"Freshness Fresh {tag}", NEW, NEW),
        "old":       (f"Freshness Old {tag}", OLD, NEW),        # posted long ago, re-seen recently
        "old_nodate": (f"Freshness NoDate {tag}", None, OLD),   # no posted_at, first seen long ago
    }
    urls = {}
    with PG_ENGINE.begin() as c:
        for key, (title, posted, first_seen) in rows.items():
            u = f"https://example.com/fresh/{key}-{tag}"
            urls[key] = u
            c.execute(text("""
                INSERT INTO public.all_jobs (id, source, canonical_job_key, first_seen_at, last_seen_at,
                    insertion_time, updated_at, created_at, job_title, company_name, job_url,
                    normalized_job_url, posted_at)
                VALUES (CAST(:id AS uuid), 'linkedin', :k, :fs, :n, :n, :n, :n, :t, 'Acme', :u, :u, :p)
            """), {"id": str(uuid.uuid4()), "k": u, "fs": first_seen, "n": NOW, "t": title, "u": u, "p": posted})
    yield {k: rows[k][0] for k in rows}, urls
    with PG_ENGINE.begin() as c:
        c.execute(text("DELETE FROM public.all_jobs WHERE job_url = ANY(:u)"), {"u": list(urls.values())})


def test_all_jobs_board_hides_old_jobs(catalog):
    from backend.repositories.all_jobs_repository import AllJobsFilters, get_paginated_all_jobs
    titles, urls = catalog
    page = get_paginated_all_jobs(page=1, page_size=100, filters=AllJobsFilters(title="Freshness"))
    shown = {i["job_title"] for i in page.items if i["job_url"] in urls.values()}
    assert shown == {titles["fresh"]}


def test_matching_never_offers_old_jobs(catalog):
    from backend.services import all_jobs_match_service as svc
    titles, _ = catalog
    svc._INDEX_CACHE.update(at=0.0, rows=None)
    indexed = {row[1] for row in svc._catalog_index()}
    svc._INDEX_CACHE.update(at=0.0, rows=None)
    assert titles["fresh"] in indexed
    assert titles["old"] not in indexed and titles["old_nodate"] not in indexed


@pytest.fixture()
def feed_user(db_available):
    """A user with four matches: fresh/new, old/new, old/saved, old/applied."""
    from backend.core.database import ENGINE
    uid = str(uuid.uuid4())
    ready = {"jd_structured": '{"summary": "x"}', "fit": "Fits."}
    with ENGINE.begin() as c:
        c.execute(text("INSERT INTO public.profiles (id, email, onboarding_status) VALUES (CAST(:u AS uuid), :e, 'complete')"),
                  {"u": uid, "e": f"fresh-{uid[:8]}@example.invalid"})
        for key, posted, status, applied in [
            ("fresh_new", NEW, "new", False), ("old_new", OLD, "new", False),
            ("old_saved", OLD, "saved", False), ("old_applied", OLD, "applied", True),
        ]:
            pid = str(uuid.uuid4())
            c.execute(text("""
                INSERT INTO public.job_postings (id, canonical_job_key, title, company, location, posted_at, jd_structured)
                VALUES (CAST(:id AS uuid), :k, :t, 'Acme', 'Tel Aviv', :p, CAST(:js AS jsonb))
            """), {"id": pid, "k": f"{key}-{uid}", "t": key, "p": posted, "js": ready["jd_structured"]})
            c.execute(text("""
                INSERT INTO public.user_job_matches (user_id, job_posting_id, job_id, status, applied,
                    match_score, score_is_proxy, fit_brief)
                VALUES (CAST(:u AS uuid), CAST(:p AS uuid), :j, :s, :a, 70, false, :f)
            """), {"u": uid, "p": pid, "j": f"{key}-{uid[:8]}", "s": status, "a": applied, "f": ready["fit"]})
    yield uid
    with ENGINE.begin() as c:
        c.execute(text("DELETE FROM public.profiles WHERE id = CAST(:u AS uuid)"), {"u": uid})
        c.execute(text("DELETE FROM public.job_postings WHERE canonical_job_key LIKE :k"), {"k": f"%-{uid}"})


def test_feed_hides_old_untouched_jobs_but_keeps_the_users_own(feed_user):
    from backend.repositories import job_repository
    titles = {j.title for j in job_repository.get_feed(feed_user)}
    assert titles == {"fresh_new", "old_saved", "old_applied"}
    ready = {j.title for j in job_repository.get_ready_feed(feed_user)}
    assert ready == {"fresh_new", "old_saved", "old_applied"}
    assert {j.title for j in job_repository.get_feed(feed_user, status_filter="saved")} == {"old_saved"}


def test_old_jobs_are_hidden_not_deleted(feed_user):
    from backend.core.database import ENGINE
    with ENGINE.connect() as c:
        n = c.execute(text("SELECT count(*) FROM public.user_job_matches WHERE user_id = CAST(:u AS uuid)"),
                      {"u": feed_user}).scalar()
    assert n == 4


def test_enrichment_skips_old_untouched_jobs(feed_user):
    from backend.repositories import job_repository
    titles = {r.title for r in job_repository.get_enrichment_candidates(feed_user, 100)}
    assert "old_new" not in titles and "fresh_new" in titles
