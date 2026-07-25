"""
LinkedInBulkCsvScraper — ingests a daily jobs.csv export of LinkedIn postings.

JOB-81 (Converge): ports the CSV-parsing logic originally written in
backend/ingestion/csv_ingest.py (deleted 2026-07-13, recovered from git
history at commit fa8ee7a) onto the BaseScraper contract, so bulk-imported
LinkedIn postings land in the same SQLite job_store as every other source
instead of a disconnected Postgres database.

Not registered with SCRAPER_MANAGER — this is a one-shot CLI operation
against a downloaded CSV file, not a continuously-polled company-site
adapter. See backend/scripts/run_linkedin_bulk_ingest.py for the driver.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Optional

import pandas as pd

from backend.schemas.job import JobMatch
from backend.scrapers.base_scraper import BaseScraper, make_job_id, minimal_job_match, now_iso

logger = logging.getLogger(__name__)

# LinkedIn numeric job IDs are 9-10 digits. Matches both
# ".../jobs/view/1234567890/..." and "...currentJobId=1234567890..." forms.
_JOB_ID_RE = re.compile(r"(\d{9,10})")

LINKEDIN_JOB_URL_TEMPLATE = "https://www.linkedin.com/jobs/view/{job_id}/"

# Distinguishes this pipeline's rows from any other LinkedIn-sourced job
# (organic scraper, manual /analyze-job, etc.) so the closure validator
# (linkedin_bulk_validator.py) only ever re-checks jobs it created.
_JOB_ID_PREFIX = "li-bulk"


def extract_linkedin_job_id(job_url: str) -> Optional[str]:
    """Pull the 9-10 digit numeric LinkedIn job ID out of a raw job URL."""
    if not isinstance(job_url, str):
        return None
    match = _JOB_ID_RE.search(job_url)
    return match.group(1) if match else None


def normalize_linkedin_job_url(job_id: str) -> str:
    return LINKEDIN_JOB_URL_TEMPLATE.format(job_id=job_id)


class LinkedInBulkCsvScraper(BaseScraper):
    """
    One instance corresponds to one CSV file. fetch_jobs() reads it, extracts
    the LinkedIn job ID from each row's job_url, and returns a JobMatch per
    parseable row — real metadata, zero AI scores, matching every other
    adapter's contract.

    Expected CSV columns: job_url (required), title, company_name, location,
    description, experience_level, work_type, job_classification,
    applications_count (all optional — missing columns become None).
    """

    def __init__(self, csv_path: str, user_id: str = "default") -> None:
        super().__init__(company_name="LinkedIn Bulk Import", company_url=csv_path)
        self.csv_path = Path(csv_path)
        self.user_id  = user_id

    @property
    def source_type(self) -> str:
        return "linkedin"

    async def fetch_jobs(self) -> list[JobMatch]:
        try:
            df = pd.read_csv(self.csv_path)
        except Exception as exc:
            logger.error("[LinkedInBulkCsvScraper] Failed to read %s: %s", self.csv_path, exc)
            return []

        if "job_url" not in df.columns:
            logger.error(
                "[LinkedInBulkCsvScraper] %s is missing the required 'job_url' column",
                self.csv_path,
            )
            return []

        df["linkedin_job_id"] = df["job_url"].apply(extract_linkedin_job_id)
        dropped = df["linkedin_job_id"].isna().sum()
        if dropped:
            logger.warning(
                "[LinkedInBulkCsvScraper] Dropping %d row(s) with unparseable job_url", dropped,
            )
        df = df.dropna(subset=["linkedin_job_id"]).copy()
        # Duplicate LinkedIn IDs within the same CSV (re-scraped same posting
        # twice) — keep the last occurrence, matching the original ingest logic.
        df = df.drop_duplicates(subset=["linkedin_job_id"], keep="last")

        jobs: list[JobMatch] = []
        for row in df.itertuples(index=False):
            try:
                linkedin_id = str(row.linkedin_job_id)
                apply_url   = normalize_linkedin_job_url(linkedin_id)
                title       = getattr(row, "title", None) or "Unknown Title"
                company     = getattr(row, "company_name", None) or "Unknown Company"
                location    = getattr(row, "location", None) or "Unknown"
                description = getattr(row, "description", None)

                jobs.append(minimal_job_match(
                    job_id      = make_job_id(apply_url, prefix=_JOB_ID_PREFIX),
                    title       = str(title),
                    company     = str(company),
                    location    = str(location),
                    apply_url   = apply_url,
                    jd_text     = str(description) if description else None,
                    posted_at   = now_iso(),
                    source_type = "linkedin",
                    user_id     = self.user_id,
                ))
            except Exception as exc:
                # Never let one bad row abort the whole batch.
                logger.warning("[LinkedInBulkCsvScraper] Skipping unparseable row: %s", exc)
                continue

        logger.info(
            "[LinkedInBulkCsvScraper] Parsed %d job(s) from %s", len(jobs), self.csv_path,
        )
        return jobs
