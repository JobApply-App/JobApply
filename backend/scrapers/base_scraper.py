"""
Abstract base class for all job-source scrapers.

Each concrete adapter targets one ATS or career-page provider (Comeet,
Greenhouse, Lever, etc.).  All adapters share the same contract:

    fetch_jobs() -> list[JobMatch]

The returned JobMatch objects have real scraped data (title, company,
location, apply_url, jd_text) but zero AI scores (score=0, match_score=0).
Scoring is deferred to feed_service.refresh_user_scores() so that a single
scrape run covering 50+ companies doesn't block on LLM calls.
"""
from __future__ import annotations

import hashlib
import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Optional

from backend.schemas.job import DetailedAnalysis, JobMatch
from backend.scrapers.proxy_manager import ProxyManager
from backend.scrapers.parsing_engine import ParsingEngine

logger = logging.getLogger(__name__)


def make_job_id(url: str, prefix: str = "scraped") -> str:
    """Deterministic, collision-resistant job ID derived from the apply URL."""
    digest = hashlib.sha1(url.encode()).hexdigest()[:10]
    return f"{prefix}-{digest}"


def make_tenant_job_id(job_id: str, user_id: str) -> str:
    """
    Salt a content-derived job_id with its owning user so two different users
    scraping the same posting never collide on the jobs table's job_id PK
    (JOB-92). Deterministic per (job_id, user_id) — safe to recompute on every
    save; the same user re-scraping the same URL always lands on the same row.
    """
    salt = hashlib.sha1(user_id.encode()).hexdigest()[:8]
    return f"{job_id}-{salt}"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def minimal_job_match(
    *,
    job_id:      str,
    title:       str,
    company:     str,
    location:    str,
    apply_url:   Optional[str],
    jd_text:     Optional[str],
    posted_at:   str = "",
    source_type: str = "company_site",
    user_id:     str = "default",
    locale:      Optional[str] = None,
) -> JobMatch:
    """
    Build a JobMatch with real metadata but zeroed AI scores.

    Designed for freshly scraped jobs that haven't been through MatcherAgent
    or compute_match_score_async yet.  Both scoring passes are safe to run
    later because match_score == 0.0 triggers get_unscored_new_jobs().
    """
    return JobMatch(
        job_id              = job_id,
        title               = title,
        company             = company,
        location            = location,
        score               = 0.0,
        confidence_score    = 0,
        culture_fit_score   = 0,
        trajectory_alignment  = "",
        company_dna_inference = "",
        detailed_analysis   = DetailedAnalysis(
            strengths=[], critical_gaps=[], strategic_advice=[],
        ),
        investigation_points = [],
        reasons              = [],
        apply_url            = apply_url,
        is_new               = True,
        posted_at            = posted_at,
        source               = "automatic",
        is_open              = True,
        jd_text              = jd_text,
        # Multi-user / feed fields
        user_id              = user_id,
        source_type          = source_type,   # type: ignore[arg-type]
        status               = "new",
        match_score          = 0.0,
        created_at           = now_iso(),
        locale               = locale,
    )


class BaseScraper(ABC):
    """
    Abstract scraper.  Subclass and implement fetch_jobs().

    Attributes
    ----------
    company_name : str
        Human-readable name used in log messages and as the JobMatch.company
        fallback when the scraped data doesn't supply one.
    company_url : str
        Root careers URL (or API base URL) for this company.  Concrete
        adapters parse this to derive API endpoints.
    """

    def __init__(self, company_name: str, company_url: str) -> None:
        self.company_name = company_name
        self.company_url  = company_url
        self.proxy_manager = ProxyManager()
        self.parser = ParsingEngine()

    @property
    def source_type(self) -> str:
        """Override in subclasses that source from LinkedIn or aggregators."""
        return "company_site"

    @abstractmethod
    async def fetch_jobs(self) -> list[JobMatch]:
        """
        Fetch all currently open positions from this source.

        Returns a list of JobMatch objects with real metadata and zero
        AI scores.  Must never raise — catch and log internally, then
        return an empty list on irrecoverable error.
        """
        ...
