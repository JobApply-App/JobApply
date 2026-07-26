"""
Normalization, business-key extraction, and content-hash calculation for the
LinkedIn Israel jobs pipeline (backend/scripts/linkedin_israel_jobs.py ->
backend/repositories/linkedin_job_repository.py).

Kept as a standalone module (no DB/network imports) so it's trivially unit
testable and reusable from both the live-scrape path and the
`--import-file` CSV path — both must apply IDENTICAL normalization so a
CSV-imported row and a freshly-scraped row for the same job hash the same.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime, timedelta
from typing import Any, Optional
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

# ── Text / value normalization ──────────────────────────────────────────────

# Query params that are pure click-tracking/analytics, not part of a job
# posting's identity — stripped from job_url/company_url only (NOT from
# company_logo_url, whose query string is a signed CDN token; stripping it
# would break the image link).
_TRACKING_PARAM_PREFIXES = ("utm_",)
_TRACKING_PARAM_NAMES = {"trk", "trackingid", "refid", "originalsubdomain", "trkinfo"}


def normalize_text(value: Any) -> Optional[str]:
    """
    Collapse whitespace/newlines to single spaces, strip, turn empty/NaN
    into None. Handles the CSV fixture's literal embedded newline (see
    "Bookkeeper\\nIsrael" in israel_jobs_test.csv) and pandas-style NaN
    floats from a CSV round-trip.
    """
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    text = str(value)
    if text.strip().lower() == "nan":
        return None
    collapsed = " ".join(text.split())
    return collapsed or None


def normalize_company_key(raw: Any) -> Optional[str]:
    """
    company_name -> a lowercased, whitespace-collapsed matching key (e.g.
    "Google Inc", " google inc ", "GOOGLE INC" all normalize to "google
    inc"). Reuses normalize_text()'s whitespace/NaN handling — just adds
    the lowercase fold on top, so the two stay in lockstep if that
    normalization ever changes.
    """
    text = normalize_text(raw)
    return text.lower() if text else None


_LOCATION_SPLIT_RE = re.compile(r"\s*,\s*")


def parse_location(raw: Any) -> dict[str, Any]:
    """
    Split LinkedIn's freeform location string into structured
    `{"city": ..., "district": ..., "country": ...}`.

    The scraper's location text is comma-separated with the country last
    and, going right-to-left, a district before that — LinkedIn's own
    "City, District, Country" convention (e.g. "Ramat Gan, Tel Aviv
    District, Israel"). Verified against every row in production: segment
    count is always 1, 2, or 3, never more —
      1 segment  ("Israel")                         -> country only
      2 segments ("Tel Aviv District, Israel")       -> district + country
      3 segments ("Ramat Gan, Tel Aviv District, Israel") -> city + district + country
    A 4+-segment value (not seen so far) falls back to joining every
    leading segment before the district into `city` with ", " rather than
    silently dropping data.
    """
    text = normalize_text(raw)
    if not text:
        return {"city": None, "district": None, "country": None}
    parts = [p for p in _LOCATION_SPLIT_RE.split(text) if p]
    if len(parts) == 0:
        return {"city": None, "district": None, "country": None}
    if len(parts) == 1:
        return {"city": None, "district": None, "country": parts[0]}
    if len(parts) == 2:
        return {"city": None, "district": parts[0], "country": parts[1]}
    return {"city": ", ".join(parts[:-2]), "district": parts[-2], "country": parts[-1]}


def normalize_url(url: Any) -> str:
    """
    Deterministic URL normalization for `job_url_normalized`: lowercase
    scheme/host, drop fragment, drop tracking query params, drop a single
    trailing slash. Does NOT touch percent-encoding of the path (LinkedIn
    slugs may be percent-encoded Hebrew — re-encoding risks changing the
    string without changing identity).
    """
    text = normalize_text(url) or ""
    parsed = urlparse(text)

    kept_params = [
        (k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True)
        if k.lower() not in _TRACKING_PARAM_NAMES
        and not k.lower().startswith(_TRACKING_PARAM_PREFIXES)
    ]
    path = parsed.path
    if len(path) > 1 and path.endswith("/"):
        path = path[:-1]

    return urlunparse((
        parsed.scheme.lower(),
        parsed.netloc.lower(),
        path,
        parsed.params,
        urlencode(kept_params),
        "",  # fragment dropped
    ))


# Real LinkedIn job postings end their URL path in a long numeric ID
# (observed 10 digits in every sample row; 5+ as a conservative floor to
# avoid false-matching a short incidental number in a slug).
_JOB_ID_RE = re.compile(r"-(\d{5,})/?$")


def extract_linkedin_job_id(job_url: Any) -> Optional[str]:
    """
    Extract LinkedIn's numeric job posting ID from the trailing segment of
    job_url's path, e.g. ".../verification-team-lead-at-hr-home-4443178401"
    -> "4443178401". Returns None if the URL doesn't match this shape
    (business-key tier 2 in the task spec; tier 1 — an official ID field
    from LinkedIn's response — doesn't exist because the guest scraper
    parses HTML search-result cards, not a JSON API that would carry one;
    see linkedin_israel_jobs.py's parse_jobs()).

    Kept as a string (not int) — this is an opaque identifier, not a number
    to do arithmetic on, and could in principle exceed a fixed-width int.
    """
    text = normalize_text(job_url)
    if not text:
        return None
    path = urlparse(text).path
    match = _JOB_ID_RE.search(path)
    return match.group(1) if match else None


_LEADING_AND_RE = re.compile(r"^and\s+", re.IGNORECASE)


def normalize_list_field(value: Any) -> list[str]:
    """
    "Industries", split on comma. LinkedIn's own free-text rendering
    sometimes joins multiple industries into one English list phrase (e.g.
    "Appliances, Electrical, and Electronics Manufacturing, Industrial
    Machinery Manufacturing, and Manufacturing") with no delimiter that
    reliably distinguishes an inter-item comma from an "X, Y, and Z"
    phrasing comma inside one industry name — there's no taxonomy available
    here to disambiguate that losslessly, so this is a best-effort split,
    not a semantically perfect one.

    The naive comma-split leaves a leading "and " on the piece that
    followed the list's Oxford comma — always the last piece, since
    English only ever places that conjunction right before the final item
    (e.g. "..., and Software Development" splits into a last piece
    literally starting with "and "). That's the list conjunction, not part
    of the industry's actual name, so it's stripped from the last piece
    only.
    """
    text = normalize_text(value)
    if not text:
        return []
    pieces = [piece.strip() for piece in re.split(r",\s*", text) if piece.strip()]
    if pieces:
        pieces[-1] = _LEADING_AND_RE.sub("", pieces[-1])
    return pieces


_APPLICANTS_CENSORED_RE = re.compile(r"^<\s*(\d+)$")


def parse_applicants(raw: Any) -> dict[str, Any]:
    """
    "applicants_text" -> {"value": int | None, "exact": bool}.

    Almost every value is a plain integer LinkedIn shows verbatim (e.g.
    "116") — `exact: true`. The remainder is LinkedIn's own privacy
    censoring for low counts, always formatted "< N" (e.g. "< 25") — stored
    as `value: N, exact: false`, i.e. "fewer than N", not N itself; callers
    needing to distinguish real-25 from fewer-than-25 must check `exact`.
    """
    text = normalize_text(raw)
    if not text:
        return {"value": None, "exact": False}
    if text.isdigit():
        return {"value": int(text), "exact": True}
    m = _APPLICANTS_CENSORED_RE.match(text)
    if m:
        return {"value": int(m.group(1)), "exact": False}
    return {"value": None, "exact": False}


_RELATIVE_TIME_RE = re.compile(
    r"^(\d+)\s+(second|minute|hour|day|week|month|year)s?\s+ago$", re.IGNORECASE
)
_UNIT_TO_DAYS = {"month": 30, "year": 365}  # approximate — see docstring


def parse_posted_at(posted_text: Any, reference_time: datetime) -> Optional[datetime]:
    """
    LinkedIn's relative "N units ago" text -> an absolute datetime, by
    subtracting the parsed duration from `reference_time` (the scrape run's
    own timestamp — the same value backend/repositories/
    all_jobs_repository.py's bulk_upsert_all_jobs() writes to
    last_scraped_at, since "ago" is relative to roughly when LinkedIn's
    guest search was queried, not to some other point in time).

    "month"/"year" are only ever approximate (30/365 days) — LinkedIn's
    relative text is itself coarse at that range, so calendar-aware month
    arithmetic would be false precision. Returns None for text that isn't
    exactly this pattern (nothing in the current scraper produces
    anything else, but this must not raise on unexpected input).
    """
    text = normalize_text(posted_text)
    if not text:
        return None
    m = _RELATIVE_TIME_RE.match(text)
    if not m:
        return None
    amount = int(m.group(1))
    unit = m.group(2).lower()
    if unit in _UNIT_TO_DAYS:
        return reference_time - timedelta(days=amount * _UNIT_TO_DAYS[unit])
    return reference_time - timedelta(**{f"{unit}s": amount})


# ── LinkedIn status mapping ──────────────────────────────────────────────────

_STATUS_TO_ACTIVE: dict[str, Optional[bool]] = {
    "ACTIVE": True,
    "CLOSED": False,
    "EXPIRED": False,
    "NO_LONGER_ACCEPTING_APPLICATIONS": False,
    "UNAVAILABLE": False,
    "UNKNOWN": None,
}


def map_linkedin_status(raw_status: Optional[str]) -> tuple[str, Optional[bool]]:
    """
    raw_status -> (linkedin_status, is_active).

    SOURCE, as of this task: none. Neither the guest search-results HTML
    (parse_jobs()) nor the job-detail-page scrape (fetch_job_details()) in
    linkedin_israel_jobs.py currently extracts any open/closed signal — no
    selector for it exists in that code, and verifying one would require a
    live LinkedIn fetch, which this task is explicitly not allowed to make.
    So every call site in this task passes raw_status=None, and every row
    is stored as ("UNKNOWN", None), per the task's own instruction: don't
    guess status, save UNKNOWN/NULL when no reliable indication exists.

    This function still takes an explicit raw_status argument (rather than
    hardcoding UNKNOWN) so a future, live-verified scraper change can
    populate JobListing with a real detected status string and this mapping
    starts working without any other code changing.
    """
    if not raw_status:
        return "UNKNOWN", None
    key = raw_status.strip().upper()
    if key in _STATUS_TO_ACTIVE:
        return key, _STATUS_TO_ACTIVE[key]
    return "UNKNOWN", None


# ── Full normalization ───────────────────────────────────────────────────────

# Keys copied straight through normalize_text() with no other transform.
_PLAIN_TEXT_FIELDS = (
    "title", "company", "location", "posted_text", "description",
    "exact_posted_text", "applicants_text", "seniority_level",
    "employment_type", "job_function", "company_logo_url",
)


def build_normalized_job(raw: dict, *, raw_status: Optional[str] = None) -> dict:
    """
    raw: a dict with the JobListing fields (title, company, location,
    posted_text, job_url, company_url, description, exact_posted_text,
    applicants_text, seniority_level, employment_type, job_function,
    industries, company_logo_url) — works identically whether `raw` came
    from a live JobListing.__dict__ or a csv.DictReader row, which is the
    whole point: both paths must normalize identically so a CSV-imported
    row and a freshly-scraped row for the same job produce the same
    data_hash (see compute_data_hash()).
    """
    normalized = {field: normalize_text(raw.get(field)) for field in _PLAIN_TEXT_FIELDS}

    job_url_raw = normalize_text(raw.get("job_url")) or ""
    normalized["job_url"] = job_url_raw
    normalized["job_url_normalized"] = normalize_url(job_url_raw)
    normalized["linkedin_job_id"] = extract_linkedin_job_id(job_url_raw)

    normalized["company_url"] = (
        normalize_url(raw["company_url"]) if normalize_text(raw.get("company_url")) else None
    )

    normalized["industries"] = normalize_list_field(raw.get("industries"))

    linkedin_status, is_active = map_linkedin_status(raw_status)
    normalized["linkedin_status"] = linkedin_status
    normalized["is_active"] = is_active

    # title/company are NOT NULL in the DB schema — the scraper always
    # produces at least "N/A" for these (see parse_jobs()), but guard here
    # too so a malformed CSV row fails loudly in validation rather than
    # hitting a NOT NULL constraint violation deep in the bulk upsert.
    if not normalized["title"]:
        normalized["title"] = "N/A"
    if not normalized["company"]:
        normalized["company"] = "N/A"

    return normalized


# Fields that describe the job's actual content — everything the task spec
# says to include in data_hash. Explicitly excludes id/insertion_time/
# first_seen_at/last_seen_at/scraped_at/updated_at/data_hash itself.
_HASH_FIELDS = (
    "linkedin_job_id", "title", "company", "location", "posted_text",
    "job_url_normalized", "company_url", "description", "exact_posted_text",
    "applicants_text", "seniority_level", "employment_type", "job_function",
    "industries", "company_logo_url", "linkedin_status", "is_active",
)


def compute_data_hash(normalized: dict) -> str:
    """
    Deterministic SHA-256 over the business fields in `normalized` (as
    produced by build_normalized_job()). Sorted dict keys, sorted list
    values (industries — order carries no meaning there), compact
    separators — same input always produces the same hash, independent of
    dict key insertion order or list ordering.
    """
    canonical: dict[str, Any] = {}
    for field in _HASH_FIELDS:
        value = normalized.get(field)
        canonical[field] = sorted(value) if isinstance(value, list) else value

    payload = json.dumps(canonical, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
