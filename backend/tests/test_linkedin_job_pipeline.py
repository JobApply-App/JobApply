"""
Local-only tests for the LinkedIn Israel jobs -> PostgreSQL pipeline.

NEVER makes a network call to LinkedIn — the DB-backed tests below run
against a real local/test PostgreSQL instance (DATABASE_URL in
backend/.env), which must be reachable for the DB-dependent tests to run;
they're skipped (not failed) if it isn't, so this file is still safe to
collect in an environment with no Postgres available.
"""
from __future__ import annotations

import csv
import io
from datetime import datetime, timezone

import pytest
from sqlalchemy import text

from backend.core.postgres import get_pg_session
from backend.repositories.linkedin_job_repository import bulk_upsert_jobs
from backend.services.linkedin_job_normalize import (
    _INDUSTRY_KNOWN_TERMS,
    build_normalized_job,
    compute_data_hash,
    extract_linkedin_job_id,
    map_linkedin_status,
    normalize_list_field,
    normalize_text,
    normalize_url,
)

# The real fixture the user supplied lives outside the repo
# (~/Downloads/israel_jobs_test.csv) — copy its content inline here so this
# test suite is self-contained and doesn't depend on a path outside the
# project. Trimmed to the fields build_normalized_job() actually reads.
_SAMPLE_ROWS = [
    {
        "title": "Verification Team Lead", "company": "HR Home",
        "location": "Haifa, Haifa District, Israel", "posted_text": "2 hours ago",
        "job_url": "https://il.linkedin.com/jobs/view/verification-team-lead-at-hr-home-4443178401",
        "company_url": "https://il.linkedin.com/company/hr-home?trk=public_jobs_jserp-result_job-search-card-subtitle",
        "description": "Design Verification Team Lead...", "exact_posted_text": "2 hours ago",
        "applicants_text": "< 25", "seniority_level": "Not Applicable", "employment_type": "Full-time",
        "job_function": "Engineering",
        "industries": "Computer Hardware Manufacturing and Semiconductor Manufacturing",
        "company_logo_url": "https://static.licdn.com/aero-v1/sc/h/1kxd9keftj1y0os0evez0vt9u",
    },
    {
        "title": "Picker", "company": "Arbex", "location": "Afula, North District, Israel",
        "posted_text": "7 hours ago",
        "job_url": "https://il.linkedin.com/jobs/view/picker-at-arbex-4438800637",
        "company_url": "https://www.linkedin.com/company/arbex?trk=public_jobs_jserp-result_job-search-card-subtitle",
        "description": "Job Description...", "exact_posted_text": "7 hours ago",
        "applicants_text": "29", "seniority_level": "Entry level", "employment_type": "Full-time",
        "job_function": "Management and Manufacturing", "industries": "Manufacturing",
        "company_logo_url": "https://media.licdn.com/dms/image/v2/D4E0BAQF_pywmFu_keg/company-logo_100_100/x?e=2147483647&v=beta&t=abc",
    },
    {
        # Mirrors the fixture's "Bookkeeper\nIsrael" row: embedded newline in
        # title, and the URL slug carries the literal %0A too.
        "title": "Bookkeeper\nIsrael", "company": "WaveBL", "location": "Israel",
        "posted_text": "5 hours ago",
        "job_url": "https://il.linkedin.com/jobs/view/bookkeeper%0Aisrael-at-wavebl-4443917908",
        "company_url": "https://il.linkedin.com/company/wavebl?trk=public_jobs_jserp-result_job-search-card-subtitle",
        "description": "We're a fast-paced startup...", "exact_posted_text": "5 hours ago",
        "applicants_text": "< 25", "seniority_level": "Mid-Senior level", "employment_type": "Full-time",
        "job_function": "Accounting/Auditing and Finance", "industries": "Financial Services",
        "company_logo_url": "https://media.licdn.com/dms/image/v2/x/company-logo_100_100/x?e=2147483647&v=beta&t=xyz",
    },
]


# db_available / clean_jobs_table fixtures now live in conftest.py (shared
# with test_linkedin_jobs_route.py).


def _row(session, business_key: str):
    q = text(
        "SELECT linkedin_job_id, title, applicants_text, description, "
        "insertion_time, first_seen_at, last_seen_at, updated_at, scraped_at, data_hash "
        "FROM linkedin.jobs WHERE linkedin_job_id = :key"
    )
    return session.execute(q, {"key": business_key}).mappings().first()


def _to_records(rows: list[dict], scraped_at: datetime) -> list[dict]:
    records = []
    for r in rows:
        norm = build_normalized_job(r)
        norm["data_hash"] = compute_data_hash(norm)
        norm["scraped_at"] = scraped_at
        records.append(norm)
    return records


# ── 1. linkedin_job_id extraction ───────────────────────────────────────────

def test_extract_linkedin_job_id_from_plain_url():
    url = "https://il.linkedin.com/jobs/view/verification-team-lead-at-hr-home-4443178401"
    assert extract_linkedin_job_id(url) == "4443178401"


def test_extract_linkedin_job_id_from_hebrew_percent_encoded_slug():
    url = ("https://il.linkedin.com/jobs/view/%D7%9E%D7%92%D7%95%D7%95%D7%9F-"
           "%D7%9E%D7%A9%D7%A8%D7%95%D7%AA-4443765113")
    assert extract_linkedin_job_id(url) == "4443765113"


def test_extract_linkedin_job_id_returns_none_when_no_trailing_digits():
    assert extract_linkedin_job_id("https://il.linkedin.com/jobs/view/no-id-here") is None
    assert extract_linkedin_job_id(None) is None
    assert extract_linkedin_job_id("") is None


def test_extract_linkedin_job_id_rejects_short_incidental_numbers():
    # 4-digit trailing number below the 5-digit floor — not a real job ID shape.
    assert extract_linkedin_job_id("https://il.linkedin.com/jobs/view/floor-3-1234") is None


# ── 2. job_url normalization ─────────────────────────────────────────────────

def test_normalize_url_strips_tracking_params():
    url = "https://il.linkedin.com/company/hr-home?trk=public_jobs_jserp-result_job-search-card-subtitle"
    assert normalize_url(url) == "https://il.linkedin.com/company/hr-home"


def test_normalize_url_strips_utm_params_but_keeps_others():
    url = "https://il.linkedin.com/jobs/view/foo-123?utm_source=x&keep=1"
    assert normalize_url(url) == "https://il.linkedin.com/jobs/view/foo-123?keep=1"


def test_normalize_url_lowercases_scheme_and_host_and_drops_trailing_slash():
    assert normalize_url("HTTPS://IL.LinkedIn.COM/jobs/view/foo-123/") == "https://il.linkedin.com/jobs/view/foo-123"


def test_normalize_url_does_not_touch_signed_cdn_query_params():
    # company_logo_url-style signed CDN link — 'e'/'v'/'t' aren't tracking
    # params and must survive normalization or the image link breaks.
    url = "https://media.licdn.com/dms/image/x?e=2147483647&v=beta&t=abc"
    assert normalize_url(url) == url


# ── 3. CSV / raw-data normalization ──────────────────────────────────────────

def test_normalize_text_collapses_embedded_newline():
    assert normalize_text("Bookkeeper\nIsrael") == "Bookkeeper Israel"


def test_normalize_text_empty_and_nan_become_none():
    assert normalize_text("") is None
    assert normalize_text("   ") is None
    assert normalize_text(float("nan")) is None
    assert normalize_text("nan") is None
    assert normalize_text(None) is None


def test_normalize_list_field_splits_and_strips():
    assert normalize_list_field("Manufacturing, Utilities") == ["Manufacturing", "Utilities"]
    assert normalize_list_field("") == []
    assert normalize_list_field(None) == []


def test_normalize_list_field_strips_leading_and_from_every_piece_not_just_the_last():
    """
    Regression test for a real production bug: a raw `industries` value
    confirmed on multiple live all_jobs rows —
    "Appliances, Electrical, and Electronics Manufacturing, Industrial
    Machinery Manufacturing, and Manufacturing" — has the Oxford-comma
    "and" landing on a MID-list piece ("and Electronics Manufacturing"),
    not just the final one. The old code only stripped `pieces[-1]`,
    leaving "and Electronics Manufacturing" / "and Transportation"-style
    fragments as their own garbage filter-dropdown entries.
    """
    result = normalize_list_field(
        "Appliances, Electrical, and Electronics Manufacturing, "
        "Industrial Machinery Manufacturing, and Manufacturing",
        known_terms=_INDUSTRY_KNOWN_TERMS,
    )
    assert result == [
        "Appliances", "Electrical", "Electronics Manufacturing",
        "Industrial Machinery Manufacturing", "Manufacturing",
    ]
    assert not any(p.startswith("and ") for p in result)


def test_build_normalized_job_from_csv_round_trip():
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(_SAMPLE_ROWS[0].keys()))
    writer.writeheader()
    for r in _SAMPLE_ROWS:
        writer.writerow(r)
    buf.seek(0)
    csv_rows = list(csv.DictReader(buf))

    normalized = build_normalized_job(csv_rows[2])  # the embedded-newline row
    assert normalized["title"] == "Bookkeeper Israel"
    assert normalized["linkedin_job_id"] == "4443917908"
    assert normalized["industries"] == ["Financial Services"]


# ── 4. deterministic data_hash ───────────────────────────────────────────────

def test_data_hash_is_deterministic_for_identical_input():
    n1 = build_normalized_job(_SAMPLE_ROWS[0])
    n2 = build_normalized_job(dict(_SAMPLE_ROWS[0]))
    assert compute_data_hash(n1) == compute_data_hash(n2)


def test_data_hash_ignores_industries_order():
    base = build_normalized_job(_SAMPLE_ROWS[1])
    reordered = dict(base)
    reordered["industries"] = list(reversed(base["industries"] + ["Zzz"]))
    base["industries"] = base["industries"] + ["Zzz"]
    assert compute_data_hash(base) == compute_data_hash(reordered)


def test_data_hash_changes_when_business_field_changes():
    n1 = build_normalized_job(_SAMPLE_ROWS[0])
    changed = dict(_SAMPLE_ROWS[0])
    changed["applicants_text"] = "99"
    n2 = build_normalized_job(changed)
    assert compute_data_hash(n1) != compute_data_hash(n2)


def test_data_hash_excludes_timestamp_and_id_fields():
    # data_hash is computed from `normalized` (build_normalized_job's output),
    # which never contains id/insertion_time/first_seen_at/last_seen_at/
    # scraped_at/updated_at at all — asserting that shape directly.
    normalized = build_normalized_job(_SAMPLE_ROWS[0])
    for excluded_field in ("id", "insertion_time", "first_seen_at", "last_seen_at", "scraped_at", "updated_at", "data_hash"):
        assert excluded_field not in normalized


# ── 15. active / inactive / unknown mapping ──────────────────────────────────

@pytest.mark.parametrize("raw,expected_status,expected_active", [
    ("ACTIVE", "ACTIVE", True),
    ("CLOSED", "CLOSED", False),
    ("EXPIRED", "EXPIRED", False),
    ("NO_LONGER_ACCEPTING_APPLICATIONS", "NO_LONGER_ACCEPTING_APPLICATIONS", False),
    ("UNAVAILABLE", "UNAVAILABLE", False),
    ("UNKNOWN", "UNKNOWN", None),
    (None, "UNKNOWN", None),
    ("something-unrecognized", "UNKNOWN", None),
])
def test_map_linkedin_status(raw, expected_status, expected_active):
    status, active = map_linkedin_status(raw)
    assert status == expected_status
    assert active is expected_active


# ── 5-14. Insert / re-import / change-detection semantics (real Postgres) ───

def test_insert_new_job(clean_jobs_table):
    records = _to_records([_SAMPLE_ROWS[0]], datetime.now(timezone.utc))
    stats = bulk_upsert_jobs(records)
    assert stats.jobs_inserted == 1
    assert stats.jobs_updated == 0
    assert stats.jobs_unchanged == 0

    with get_pg_session() as session:
        row = _row(session, "4443178401")
        assert row is not None
        assert row["insertion_time"] == row["first_seen_at"] == row["last_seen_at"] == row["updated_at"]


def test_reimport_identical_job_creates_no_duplicate_and_is_unchanged(clean_jobs_table):
    t1 = datetime.now(timezone.utc)
    bulk_upsert_jobs(_to_records([_SAMPLE_ROWS[0]], t1))

    with get_pg_session() as session:
        before = _row(session, "4443178401")

    t2 = datetime.now(timezone.utc)
    stats = bulk_upsert_jobs(_to_records([_SAMPLE_ROWS[0]], t2))
    assert stats.jobs_inserted == 0
    assert stats.jobs_unchanged == 1
    assert stats.jobs_updated == 0

    with get_pg_session() as session:
        count = session.execute(
            text("SELECT count(*) FROM linkedin.jobs WHERE linkedin_job_id = '4443178401'")
        ).scalar()
        assert count == 1  # no duplicate row (test 7)

        after = _row(session, "4443178401")
        assert after["insertion_time"] == before["insertion_time"]   # test 8
        assert after["first_seen_at"] == before["first_seen_at"]     # test 9
        assert after["last_seen_at"] > before["last_seen_at"]        # test 10
        assert after["updated_at"] == before["updated_at"]           # test 11
        assert after["data_hash"] == before["data_hash"]


def test_content_change_triggers_update_and_moves_updated_at(clean_jobs_table):
    t1 = datetime.now(timezone.utc)
    bulk_upsert_jobs(_to_records([_SAMPLE_ROWS[0]], t1))
    with get_pg_session() as session:
        before = _row(session, "4443178401")

    changed_row = dict(_SAMPLE_ROWS[0])
    changed_row["applicants_text"] = "150"  # test 12: change a business field
    t2 = datetime.now(timezone.utc)
    stats = bulk_upsert_jobs(_to_records([changed_row], t2))

    assert stats.jobs_updated == 1   # test 13
    assert stats.jobs_unchanged == 0

    with get_pg_session() as session:
        after = _row(session, "4443178401")
        assert after["applicants_text"] == "150"
        assert after["updated_at"] > before["updated_at"]  # test 14
        assert after["insertion_time"] == before["insertion_time"]
        assert after["first_seen_at"] == before["first_seen_at"]
        assert after["data_hash"] != before["data_hash"]


# ── 16. bulk upsert of multiple records ──────────────────────────────────────

def test_bulk_upsert_multiple_records_in_one_call(clean_jobs_table):
    records = _to_records(_SAMPLE_ROWS, datetime.now(timezone.utc))
    stats = bulk_upsert_jobs(records, batch_size=2)  # force multiple internal batches
    assert stats.jobs_received == 3
    assert stats.jobs_inserted == 3

    with get_pg_session() as session:
        count = session.execute(text("SELECT count(*) FROM linkedin.jobs")).scalar()
        assert count == 3


def test_bulk_upsert_dedupes_same_business_key_within_one_call(clean_jobs_table):
    # Same job appearing twice in one run (e.g. pagination overlap) must not
    # hit Postgres's "ON CONFLICT DO UPDATE cannot affect row a second time".
    records = _to_records([_SAMPLE_ROWS[0], _SAMPLE_ROWS[0], _SAMPLE_ROWS[1]], datetime.now(timezone.utc))
    stats = bulk_upsert_jobs(records)
    assert stats.database_failures == 0
    assert stats.jobs_skipped == 1
    assert stats.jobs_inserted == 2


# ── 17. rollback on failure ──────────────────────────────────────────────────

def test_batch_failure_rolls_back_and_reports_without_crashing(clean_jobs_table):
    good = _to_records([_SAMPLE_ROWS[0]], datetime.now(timezone.utc))[0]
    bad = _to_records([_SAMPLE_ROWS[1]], datetime.now(timezone.utc))[0]
    bad["title"] = None  # violates the NOT NULL title column -> real DB failure

    stats = bulk_upsert_jobs([good, bad], batch_size=1)  # one batch each -> isolates the failure

    assert stats.database_failures == 1
    assert stats.jobs_inserted == 1  # the good row still went through in its own batch

    with get_pg_session() as session:
        count = session.execute(text("SELECT count(*) FROM linkedin.jobs")).scalar()
        assert count == 1
        # The failed row must not have been partially committed.
        missing = session.execute(
            text("SELECT count(*) FROM linkedin.jobs WHERE linkedin_job_id = '4438800637'")
        ).scalar()
        assert missing == 0


# ── 18 / 19. Network-call guards ─────────────────────────────────────────────

def test_default_cli_refuses_linkedin_network_call(monkeypatch):
    import argparse
    from backend.scripts import linkedin_israel_jobs as script

    monkeypatch.delenv("ALLOW_LINKEDIN_SCRAPE", raising=False)
    with pytest.raises(SystemExit) as exc_info:
        script._guard_linkedin_request(argparse.Namespace(allow_linkedin_request=False))
    assert exc_info.value.code == 1


def test_cli_flag_alone_without_env_var_still_refuses(monkeypatch):
    import argparse
    from backend.scripts import linkedin_israel_jobs as script

    monkeypatch.delenv("ALLOW_LINKEDIN_SCRAPE", raising=False)
    with pytest.raises(SystemExit):
        script._guard_linkedin_request(argparse.Namespace(allow_linkedin_request=True))


def test_both_flag_and_env_var_together_allow_through(monkeypatch):
    import argparse
    from backend.scripts import linkedin_israel_jobs as script

    monkeypatch.setenv("ALLOW_LINKEDIN_SCRAPE", "true")
    script._guard_linkedin_request(argparse.Namespace(allow_linkedin_request=True))  # must not raise


def test_import_file_never_touches_the_network(monkeypatch, clean_jobs_table, tmp_path):
    from backend.scripts import linkedin_israel_jobs as script

    def _boom(*args, **kwargs):
        raise AssertionError("import-file mode must never make a network call")

    monkeypatch.setattr(script.requests.Session, "get", _boom)
    monkeypatch.setattr(script.requests, "get", _boom)

    csv_path = tmp_path / "fixture.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(_SAMPLE_ROWS[0].keys()))
        writer.writeheader()
        for r in _SAMPLE_ROWS:
            writer.writerow(r)

    script._run_import_file(str(csv_path), db_batch_size=200)  # must not raise
