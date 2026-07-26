"""
LinkedIn "Israel jobs" scraper - no login required - with dual persistence
to PostgreSQL (`linkedin.jobs`, see backend/models/linkedin_job.py) and a
timestamped CSV export.

Uses LinkedIn's public guest jobs API:
    https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search

This endpoint returns the same job cards you'd see browsing LinkedIn
jobs while logged out. It supports:
    - keywords
    - location
    - f_TPR   (time posted range, in seconds -> r86400 = last 24 hours)
    - start   (pagination offset, 25 results per "page")

The script pulls results in BATCHES of `batch_size` pages (default 1 page
= 25 jobs per request), with a delay between each request and a longer
delay between batches, to stay polite and reduce the chance of getting
rate-limited or blocked. Individual page/detail fetches also retry with
exponential backoff on 429/5xx before giving up on that one page/job.

Network safety gate
--------------------
No code path in this script contacts LinkedIn unless BOTH:
  1. --allow-linkedin-request is passed on the command line, AND
  2. ALLOW_LINKEDIN_SCRAPE=true is set in the environment
are true (see _guard_linkedin_request()). Requiring both makes an
accidental live run a two-step deliberate action, not a one-flag slip.
Use --import-file to exercise the normalize -> hash -> upsert -> CSV
pipeline against an existing CSV with zero network calls, e.g. to verify
the DB connection and dedup logic before ever spending a real request.

Dual persistence
-----------------
Every job (live-scraped or --import-file'd) is normalized identically
(backend/services/linkedin_job_normalize.py) and upserted into
`linkedin.jobs` via backend/repositories/linkedin_job_repository.py's
bulk_upsert_jobs() (INSERT ... ON CONFLICT DO UPDATE, deduped on
linkedin_job_id / job_url_normalized — see that module's docstring for the
exact insert/update/unchanged semantics). A live scrape additionally writes
a timestamped CSV snapshot to backend/data/exports/ (or --export-dir) —
the DB is the durable/deduplicated store of record; the CSV is a
point-in-time audit copy of that specific run.

IMPORTANT:
- No LinkedIn account / cookies needed for this endpoint.
- LinkedIn still applies anti-bot / rate-limit measures to this endpoint,
  even without login. Keep delays reasonable; don't hammer it.
- This is unofficial use of a public endpoint, not an official API.
  It may break if LinkedIn changes their markup, and heavy/automated use
  may be against LinkedIn's Terms of Service - use responsibly and at
  your own risk.
- Optional proxy rotation: set PROXY_LIST (comma-separated proxy URLs,
  e.g. "http://user:pass@host:1,http://user:pass@host:2") to round-robin
  requests across a proxy pool. Without it, requests go out directly, same
  as before. (backend/scrapers/proxy_manager.py's ProxyManager is httpx/
  async and built for the agentic scrapers under backend/scrapers/ — this
  script stays on sync `requests` to keep its CLI/threading model simple,
  so proxy rotation is reimplemented minimally here rather than pulled in,
  but intentionally reuses the same PROXY_LIST env var name for consistency.)

Usage:
    # Dry-run the DB/CSV pipeline with zero network calls:
    python -m backend.scripts.linkedin_israel_jobs --import-file path/to/jobs.csv

    # Daily Israel pull, last 24 hours (requires the two-step opt-in above):
    ALLOW_LINKEDIN_SCRAPE=true python -m backend.scripts.linkedin_israel_jobs \\
        --allow-linkedin-request --hours 24

    python -m backend.scripts.linkedin_israel_jobs --allow-linkedin-request \\
        --keywords "Python Developer" --hours 3
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests
from bs4 import BeautifulSoup

# Allow `python backend/scripts/linkedin_israel_jobs.py` (direct execution,
# not just `-m`) to resolve the `backend.*` package, matching the other
# scripts in this directory (e.g. ingest_linkedin_postgres_to_feed.py).
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from backend.repositories.linkedin_job_repository import (  # noqa: E402
    DEFAULT_BATCH_SIZE,
    UpsertStats,
    bulk_upsert_jobs,
)
from backend.services.linkedin_job_normalize import (  # noqa: E402
    build_normalized_job,
    compute_data_hash,
)

BASE_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
RESULTS_PER_PAGE = 25  # LinkedIn's guest API pages in chunks of 25

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

DEFAULT_EXPORT_DIR = _PROJECT_ROOT / "backend" / "data" / "exports"

# 429/5xx are transient — worth a couple of retries with backoff before
# treating the page/job as unfetchable for this run.
MAX_FETCH_RETRIES = 3
BASE_BACKOFF_SECONDS = 3.0


@dataclass
class JobListing:
    title: str
    company: str
    location: str
    posted_text: Optional[str]
    job_url: str
    company_url: Optional[str]
    description: Optional[str] = None
    exact_posted_text: Optional[str] = None
    applicants_text: Optional[str] = None
    seniority_level: Optional[str] = None
    employment_type: Optional[str] = None
    job_function: Optional[str] = None
    industries: Optional[str] = None
    company_logo_url: Optional[str] = None


class RateLimitTracker:
    """Thread-safe counter for 429s hit during a run (fetch_job_details runs
    across a ThreadPoolExecutor, fetch_page runs sequentially) — surfaced in
    the final run summary per Phase 3's reporting requirement."""

    def __init__(self) -> None:
        self._count = 0
        self._lock = threading.Lock()

    def bump(self) -> None:
        with self._lock:
            self._count += 1

    @property
    def count(self) -> int:
        with self._lock:
            return self._count


# ── Optional proxy rotation (PROXY_LIST env var) ────────────────────────────

def _load_proxy_pool() -> list[str]:
    raw = os.environ.get("PROXY_LIST", "")
    return [p.strip() for p in raw.split(",") if p.strip()]


class _ProxyRotator:
    def __init__(self, pool: list[str]) -> None:
        self._pool = pool
        self._i = 0
        self._lock = threading.Lock()

    def next(self) -> Optional[dict[str, str]]:
        if not self._pool:
            return None
        with self._lock:
            proxy = self._pool[self._i % len(self._pool)]
            self._i += 1
        return {"http": proxy, "https": proxy}


_PROXY_ROTATOR = _ProxyRotator(_load_proxy_pool())


# ── Network guard ────────────────────────────────────────────────────────────

def _guard_linkedin_request(args: argparse.Namespace) -> None:
    """
    Hard stop before any network call to LinkedIn. Requires BOTH the
    --allow-linkedin-request CLI flag AND the ALLOW_LINKEDIN_SCRAPE=true
    env var — a single flag alone is one accidental invocation away from a
    real scrape; requiring both makes an unintended run take two
    independent, deliberate opt-ins. Use --import-file instead to exercise
    the DB/CSV pipeline with zero network calls.
    """
    env_allowed = os.environ.get("ALLOW_LINKEDIN_SCRAPE", "").strip().lower() in ("1", "true", "yes")
    cli_allowed = bool(getattr(args, "allow_linkedin_request", False))
    if not (cli_allowed and env_allowed):
        print(
            "[GUARD] Refusing to contact LinkedIn: requires BOTH "
            "--allow-linkedin-request AND ALLOW_LINKEDIN_SCRAPE=true in the "
            "environment. Use --import-file to test the DB/CSV pipeline "
            "without any network call.",
            file=sys.stderr,
        )
        sys.exit(1)


def clean_applicants(text: Optional[str]) -> Optional[str]:
    if not text:
        return text
    text = text.strip()
    # Check if it represents less than 25 applicants (either English or Hebrew versions)
    if "first 25" in text.lower() or "25 הראשונים" in text:
        return "< 25"
    # Find any numeric value
    match = re.search(r'(\d+)', text)
    if match:
        return match.group(1)
    return text


def fetch_job_details(
    session: requests.Session,
    job: JobListing,
    delay: float = 2.0,
    rate_tracker: Optional[RateLimitTracker] = None,
) -> None:
    """Fetch job details from the job_url and populate description, exact_posted_text, applicants_text, criteria, and logo."""
    # Force www instead of il subdomain to ensure English responses
    target_url = job.job_url.replace("il.linkedin.com", "www.linkedin.com")
    print(f"Fetching details for: {job.title} @ {job.company}...")

    for attempt in range(MAX_FETCH_RETRIES):
        try:
            resp = session.get(
                target_url, headers=HEADERS, timeout=15,
                proxies=_PROXY_ROTATOR.next(),
            )
        except requests.RequestException as e:
            print(f"    [!] Network error (attempt {attempt + 1}): {e}")
            time.sleep(BASE_BACKOFF_SECONDS * (2 ** attempt))
            continue

        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "html.parser")

            # 1. Parse description
            desc_el = soup.select_one(".show-more-less-html__markup")
            if desc_el:
                job.description = desc_el.get_text(separator="\n", strip=True)

            # 2. Parse exact posted time text
            posted_el = soup.select_one(".posted-time-ago__text")
            if posted_el:
                job.exact_posted_text = posted_el.get_text(strip=True)

            # 3. Parse applicants count
            applicants_el = soup.select_one(".num-applicants__figure, .num-applicants__caption")
            if applicants_el:
                job.applicants_text = clean_applicants(applicants_el.get_text(strip=True))

            # 4. Parse job criteria (Seniority, Employment type, Function, Industries)
            criteria_items = soup.select(".description__job-criteria-item")
            for item in criteria_items:
                subheader = item.select_one(".description__job-criteria-subheader")
                val_el = item.select_one(".description__job-criteria-text")
                if subheader and val_el:
                    sh_txt = subheader.get_text(strip=True).lower()
                    val_txt = val_el.get_text(strip=True)
                    if "seniority" in sh_txt:
                        job.seniority_level = val_txt
                    elif "employment" in sh_txt:
                        job.employment_type = val_txt
                    elif "function" in sh_txt:
                        job.job_function = val_txt
                    elif "industries" in sh_txt:
                        job.industries = val_txt

            # 5. Parse company logo image URL
            logo_el = soup.select_one(".contextual-sign-in-modal__img")
            if logo_el:
                job.company_logo_url = logo_el.get("src") or logo_el.get("data-delayed-url")
            else:
                for img in soup.find_all("img"):
                    src = img.get("src") or img.get("data-delayed-url") or ""
                    classes = img.get("class", [])
                    classes_str = " ".join(classes) if classes else ""
                    if "company-logo" in src or "company-logo" in classes_str:
                        job.company_logo_url = src
                        break
            break

        elif resp.status_code == 429:
            if rate_tracker:
                rate_tracker.bump()
            wait = BASE_BACKOFF_SECONDS * (2 ** attempt)
            print(f"    [!] Rate limited (429) on details fetch. Backing off {wait:.0f}s "
                  f"(attempt {attempt + 1}/{MAX_FETCH_RETRIES}).")
            time.sleep(wait)
        else:
            print(f"    [!] Failed to fetch details, status code: {resp.status_code}")
            break

    time.sleep(delay)


def build_params(keywords: str, location: str, hours: int, start: int) -> dict:
    """Build query params for the guest jobs API.

    f_TPR uses the format rNNNN where NNNN is seconds. 24 hours = 86400.
    """
    return {
        "keywords": keywords,
        "location": location,
        "f_TPR": f"r{hours * 3600}",
        "start": start,
    }


def fetch_page(
    session: requests.Session, keywords: str, location: str,
    hours: int, start: int, timeout: int = 15,
    rate_tracker: Optional[RateLimitTracker] = None,
) -> Optional[str]:
    """Fetch one page (25 results) of raw HTML from the guest API, retrying
    with exponential backoff on 429/5xx before giving up on this page."""
    params = build_params(keywords, location, hours, start)

    for attempt in range(MAX_FETCH_RETRIES):
        try:
            resp = session.get(
                BASE_URL, params=params, headers=HEADERS, timeout=timeout,
                proxies=_PROXY_ROTATOR.next(),
            )
        except requests.RequestException as e:
            print(f"  [!] Network error at start={start} (attempt {attempt + 1}): {e}")
            time.sleep(BASE_BACKOFF_SECONDS * (2 ** attempt))
            continue

        if resp.status_code == 200:
            return resp.text

        if resp.status_code == 429:
            if rate_tracker:
                rate_tracker.bump()
            wait = BASE_BACKOFF_SECONDS * (2 ** attempt)
            print(f"  [!] Rate limited (429) at start={start}. Backing off {wait:.0f}s "
                  f"(attempt {attempt + 1}/{MAX_FETCH_RETRIES}).")
            time.sleep(wait)
            continue

        if 500 <= resp.status_code < 600:
            wait = BASE_BACKOFF_SECONDS * (2 ** attempt)
            print(f"  [!] Server error {resp.status_code} at start={start}. Retrying in {wait:.0f}s.")
            time.sleep(wait)
            continue

        print(f"  [!] Unexpected status {resp.status_code} at start={start}")
        return None

    print(f"  [!] Giving up on start={start} after {MAX_FETCH_RETRIES} attempts.")
    return None


def parse_jobs(html: str) -> list[JobListing]:
    """Parse a guest-API HTML fragment into JobListing objects."""
    soup = BeautifulSoup(html, "html.parser")
    jobs: list[JobListing] = []

    cards = soup.select("li")
    for card in cards:
        link_el = card.select_one("a.base-card__full-link, a[href*='/jobs/view/']")
        if not link_el:
            continue

        title_el = card.select_one("h3.base-search-card__title, h3")
        company_el = card.select_one("h4.base-search-card__subtitle a, h4 a")
        location_el = card.select_one("span.job-search-card__location")
        time_el = card.select_one("time")

        job_url = link_el.get("href", "").split("?")[0]
        title = title_el.get_text(strip=True) if title_el else "N/A"
        company = company_el.get_text(strip=True) if company_el else "N/A"
        company_url = company_el.get("href") if company_el else None
        location = location_el.get_text(strip=True) if location_el else "N/A"
        posted_text = time_el.get_text(strip=True) if time_el else None

        if job_url:
            jobs.append(JobListing(
                title=title,
                company=company,
                location=location,
                posted_text=posted_text,
                job_url=job_url,
                company_url=company_url,
            ))

    return jobs


def scrape_jobs_in_batches(
    keywords: str, location: str, hours: int,
    max_pages: int, batch_size: int,
    delay_between_requests: float,
    delay_between_batches: float,
    rate_tracker: Optional[RateLimitTracker] = None,
) -> list[JobListing]:
    """
    Pull job pages in batches.

    max_pages: total number of 25-result pages to fetch overall.
    batch_size: how many pages to fetch per batch before the longer pause.
    """
    all_jobs: list[JobListing] = []
    seen_urls = set()

    session = requests.Session()

    for batch_start_page in range(0, max_pages, batch_size):
        batch_pages = range(batch_start_page, min(batch_start_page + batch_size, max_pages))
        print(f"\n--- Batch: pages {batch_start_page}-{batch_start_page + len(list(batch_pages)) - 1} ---")

        empty_page_seen = False
        for page_num in batch_pages:
            start = page_num * RESULTS_PER_PAGE
            print(f"  Fetching page {page_num} (start={start})...")

            html = fetch_page(session, keywords, location, hours, start, rate_tracker=rate_tracker)
            if html is None:
                continue

            page_jobs = parse_jobs(html)
            if not page_jobs:
                print("  No more jobs found on this page - stopping early.")
                empty_page_seen = True
                break

            new_count = 0
            for job in page_jobs:
                if job.job_url not in seen_urls:
                    seen_urls.add(job.job_url)
                    all_jobs.append(job)
                    new_count += 1

            print(f"  Got {len(page_jobs)} jobs ({new_count} new).")
            time.sleep(delay_between_requests)

        if empty_page_seen:
            break

        print(f"--- End of batch. Total collected so far: {len(all_jobs)} ---")
        time.sleep(delay_between_batches)

    return all_jobs


def save_to_csv(jobs: list[JobListing], filepath: Path) -> None:
    if not jobs:
        print("No jobs to save.")
        return
    filepath.parent.mkdir(parents=True, exist_ok=True)
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(asdict(jobs[0]).keys()))
        writer.writeheader()
        for job in jobs:
            writer.writerow(asdict(job))
    print(f"Saved {len(jobs)} jobs to {filepath}")


# ── Dual persistence: DB upsert ─────────────────────────────────────────────

def _persist_to_db(jobs: list[JobListing], scraped_at: datetime, db_batch_size: int) -> UpsertStats:
    """Normalize -> hash -> bulk upsert into linkedin.jobs. Same normalization
    path as --import-file, so a CSV re-imported later hashes identically to
    what was scraped live (see linkedin_job_normalize.py's module docstring)."""
    records = []
    for job in jobs:
        normalized = build_normalized_job(asdict(job))
        normalized["data_hash"] = compute_data_hash(normalized)
        normalized["scraped_at"] = scraped_at
        records.append(normalized)
    return bulk_upsert_jobs(records, batch_size=db_batch_size)


def _run_import_file(path: str, db_batch_size: int = DEFAULT_BATCH_SIZE) -> UpsertStats:
    """
    Load a CSV (this script's own --out format, or any CSV with the same
    JobListing field names) straight into linkedin.jobs via the same
    normalize -> hash -> upsert path the live scrape uses. Makes NO network
    call of any kind — this is the Phase 3 dry-run path for verifying the
    DB connection, upsert/dedup logic, and CSV round-trip without spending
    a single LinkedIn request.
    """
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    if not rows:
        print(f"[import-file] {path}: no rows found.")
        return UpsertStats()

    scraped_at = datetime.now(timezone.utc)
    records = []
    for row in rows:
        normalized = build_normalized_job(row)
        normalized["data_hash"] = compute_data_hash(normalized)
        normalized["scraped_at"] = scraped_at
        records.append(normalized)

    stats = bulk_upsert_jobs(records, batch_size=db_batch_size)
    print(
        f"[import-file] {path}: received={stats.jobs_received} "
        f"inserted={stats.jobs_inserted} updated={stats.jobs_updated} "
        f"unchanged={stats.jobs_unchanged} skipped={stats.jobs_skipped} "
        f"db_failures={stats.database_failures}"
    )
    return stats


def main():
    parser = argparse.ArgumentParser(description="Scrape recent LinkedIn jobs in Israel (no login).")
    parser.add_argument("--keywords", default="", help="Job keywords, e.g. 'Python Developer'")
    parser.add_argument("--location", default="Israel", help="Location filter")
    parser.add_argument("--hours", type=int, default=24, help="Only jobs posted within this many hours")
    parser.add_argument("--max-pages", type=int, default=8, help="Total 25-result pages to fetch (max)")
    parser.add_argument("--batch-size", type=int, default=2, help="Pages per batch before a longer pause")
    parser.add_argument("--request-delay", type=float, default=2.0, help="Seconds between individual requests")
    parser.add_argument("--batch-delay", type=float, default=6.0, help="Seconds between batches")
    parser.add_argument("--out", default=None,
                         help="Output CSV path. Defaults to a timestamped file under --export-dir.")
    parser.add_argument("--export-dir", default=str(DEFAULT_EXPORT_DIR),
                         help="Directory for the timestamped CSV export when --out isn't given.")
    parser.add_argument("--db-batch-size", type=int, default=DEFAULT_BATCH_SIZE,
                         help="Row batch size for the Postgres upsert.")
    parser.add_argument("--skip-db", action="store_true",
                         help="Skip the Postgres upsert; CSV export only.")
    parser.add_argument("--allow-linkedin-request", action="store_true",
                         help="Required (together with ALLOW_LINKEDIN_SCRAPE=true) to actually contact LinkedIn.")
    parser.add_argument("--import-file", default=None,
                         help="Skip scraping entirely; upsert an existing CSV into the DB (no network call).")
    args = parser.parse_args()

    if args.import_file:
        _run_import_file(args.import_file, db_batch_size=args.db_batch_size)
        return

    _guard_linkedin_request(args)

    print(f"Searching '{args.keywords or '(any keywords)'}' in {args.location}, "
          f"posted within the last {args.hours}h, up to {args.max_pages} pages "
          f"in batches of {args.batch_size}...")

    rate_tracker = RateLimitTracker()
    run_started_at = datetime.now(timezone.utc)

    jobs = scrape_jobs_in_batches(
        keywords=args.keywords,
        location=args.location,
        hours=args.hours,
        max_pages=args.max_pages,
        batch_size=args.batch_size,
        delay_between_requests=args.request_delay,
        delay_between_batches=args.batch_delay,
        rate_tracker=rate_tracker,
    )

    if jobs:
        print(f"\n--- Fetching details for {len(jobs)} jobs in parallel (with incremental saving) ---")

        out_path = Path(args.out) if args.out else (
            Path(args.export_dir) /
            f"linkedin_israel_jobs_{run_started_at.strftime('%Y%m%d_%H%M%S')}.csv"
        )
        out_path.parent.mkdir(parents=True, exist_ok=True)

        # Initialize the CSV file with headers
        fieldnames = list(asdict(jobs[0]).keys())
        with open(out_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()

        csv_lock = threading.Lock()

        def process_job(job_obj, index):
            thread_session = requests.Session()
            fetch_job_details(thread_session, job_obj, delay=args.request_delay, rate_tracker=rate_tracker)

            with csv_lock:
                with open(out_path, "a", newline="", encoding="utf-8") as f_append:
                    writer_append = csv.DictWriter(f_append, fieldnames=fieldnames)
                    writer_append.writerow(asdict(job_obj))
            print(f"  [{index}/{len(jobs)}] Saved: {job_obj.title} @ {job_obj.company}")

        # Use ThreadPoolExecutor to request in parallel (max 4 workers to prevent rate limit)
        max_workers = 4
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(process_job, job, idx + 1) for idx, job in enumerate(jobs)]
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as e:
                    print(f"Error in thread execution: {e}")

        db_stats: Optional[UpsertStats] = None
        if not args.skip_db:
            print(f"\n--- Upserting {len(jobs)} jobs into linkedin.jobs ---")
            try:
                db_stats = _persist_to_db(jobs, scraped_at=run_started_at, db_batch_size=args.db_batch_size)
            except Exception as e:
                print(f"[!] DB upsert failed: {e}")

        print(f"\n=== Done. {len(jobs)} unique jobs found in the last {args.hours}h in {args.location}. ===")
        print(f"    CSV export: {out_path}")
        if db_stats is not None:
            print(
                f"    DB upsert:  inserted={db_stats.jobs_inserted} updated={db_stats.jobs_updated} "
                f"unchanged={db_stats.jobs_unchanged} skipped={db_stats.jobs_skipped} "
                f"db_failures={db_stats.database_failures}"
            )
        elif args.skip_db:
            print("    DB upsert:  skipped (--skip-db)")
        print(f"    Rate-limit (429) warnings encountered: {rate_tracker.count}")
        for job in jobs:
            print(f"- {job.title} @ {job.company} | {job.location} | posted: {job.posted_text} / {job.exact_posted_text} | applicants: {job.applicants_text} | {job.job_url}")
    else:
        print(f"\n=== Done. 0 jobs found in the last {args.hours}h in {args.location}. ===")
        print(f"    Rate-limit (429) warnings encountered: {rate_tracker.count}")


if __name__ == "__main__":
    main()
