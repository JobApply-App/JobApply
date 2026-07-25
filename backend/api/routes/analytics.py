"""
Analytics API — aggregated job-seeker metrics.

GET /api/analytics/summary
  Returns KPI cards, pipeline funnel, top companies, and top skill keywords
  drawn live from the application-tracking (CRM) table.

Response shape
--------------
  {
    "total_applications":        int,
    "active_processes":          int,
    "interview_conversion_rate": float,   # (interview + offer) / total × 100
    "funnel_stages":  [{"stage": str, "count": int}],
    "top_companies":  [{"company": str, "count": int}],
    "top_keywords":   [{"keyword": str, "count": int}]
  }

Counting rules
--------------
- total_applications : ApplicationRow rows whose status is NOT in the excluded
  set {new, saved, skipped}.  These are discovery / tracking stages, not real
  pipeline entries.
- active_processes   : rows in {submitted, phone screen, technical, interview}.
- interview_rate     : rows in {interview, offer} / total × 100.
  Offer is included because reaching an offer means the interview was passed —
  it is the best possible interview outcome.

Funnel guarantee
----------------
All six canonical stages are ALWAYS present in funnel_stages, even when their
count is 0, so the frontend can render a complete skeleton without conditional
branching.  Unknown stages found in the live data are appended alphabetically.

top_companies
-------------
Dynamically grouped by ApplicationRow.company (normalised to lower-case for
grouping, but returned as the most-common raw capitalisation form).  Companies
with zero entries are never included.  Sorted by count descending; at most 10
entries returned.
"""
from __future__ import annotations

import logging
from collections import Counter
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.api.deps import CurrentUser, get_current_user, standard_rate_limit
from backend.services.analytics_service import compute_overview
from backend.core.database import ENGINE
from backend.models.job import JobRow
from backend.repositories import application_repository

# Router-level standard_rate_limit (Phase 4 invariant) — covers /summary and
# /overview alike, keyed per authenticated user.
router = APIRouter(dependencies=[Depends(standard_rate_limit)])
logger = logging.getLogger(__name__)

# ── Stage taxonomy ─────────────────────────────────────────────────────────────

# Discovery / tracking stages that do NOT count as real pipeline entries
_EXCLUDED_STAGES: frozenset[str] = frozenset({"new", "saved", "skipped"})

# Canonical pipeline funnel — always returned in this order, even if count = 0
_STAGE_ORDER: list[str] = [
    "submitted",
    "phone screen",
    "technical",
    "interview",
    "offer",
    "rejected",
]

# In-flight stages (application is actively being considered)
_ACTIVE_STAGES: frozenset[str] = frozenset({"submitted", "phone screen", "technical", "interview"})

# Stages that count as having reached the interview stage or beyond
_INTERVIEW_REACHED_STAGES: frozenset[str] = frozenset({"interview", "offer"})

_TOP_COMPANIES_LIMIT = 10
_TOP_KEYWORDS_LIMIT  = 20


def _normalise(raw: str | None) -> str:
    """Lower-case and strip a raw status string; fall back to 'submitted'."""
    return (raw or "submitted").lower().strip()


def _extract_skill_keywords(tailored_cv: Any) -> list[str]:
    """
    Pull flat skill strings out of the nested cv_data skills structure.

      tailored_cv = {"cv_data": {"skills": {"categories": [{"label": …, "items": […]}]}}}
    """
    if not isinstance(tailored_cv, dict):
        return []
    cv_data = tailored_cv.get("cv_data") or {}
    skills  = cv_data.get("skills") or {}
    result: list[str] = []
    for cat in (skills.get("categories") or []):
        for item in (cat.get("items") or []):
            if isinstance(item, str) and item.strip():
                result.append(item.strip())
    return result


def _canonical_company(raw_name: str | None) -> str:
    """Normalise a company name for grouping purposes."""
    return (raw_name or "Unknown").strip()


@router.get("/overview")
async def analytics_overview(user: CurrentUser = Depends(get_current_user)) -> dict:
    """
    Daily Overview KPI values: Jobs Scanned Today, Actions Taken Today
    (applications submitted since UTC midnight), and Average Match Score
    (across scored jobs). The two "today" counters reset at 00:00 UTC.

    Auth-protected; rate-limited at the router level; every underlying query
    is scoped to the verified user.user_id (see services/analytics_service.py).
    """
    return compute_overview(user.user_id)


@router.get("/summary")
async def analytics_summary(user: CurrentUser = Depends(get_current_user)) -> dict:
    """
    Aggregate job-seeker metrics from the CRM (application tracking) table,
    scoped to the authenticated user.

    ApplicationRow drives: total_applications, active_processes,
    interview_conversion_rate, funnel_stages, and top_companies.

    JobRow (applied=True) drives: top_keywords from tailored CV skill data.
    """
    with Session(ENGINE) as db:

        # ── All application rows for this user ────────────────────────────────
        all_apps = application_repository.get_all_rows(user.user_id, session=db)

        # Filter out discovery-only stages to count real pipeline entries
        pipeline_apps = [
            app for app in all_apps
            if _normalise(app.status) not in _EXCLUDED_STAGES
        ]
        total_applications = len(pipeline_apps)

        # ── Stage counters ─────────────────────────────────────────────────────
        stage_counter: Counter[str] = Counter()
        active_processes    = 0
        interview_reached   = 0

        # ── Company counter ────────────────────────────────────────────────────
        # Track raw spellings per lower-cased key so we can return the most
        # common capitalisation form rather than an arbitrary raw value.
        company_count:    Counter[str] = Counter()  # key = canonical name
        company_spellings: dict[str, Counter[str]] = {}  # key → {raw: freq}

        for app in pipeline_apps:
            stage = _normalise(app.status)
            stage_counter[stage] += 1

            if stage in _ACTIVE_STAGES:
                active_processes += 1
            if stage in _INTERVIEW_REACHED_STAGES:
                interview_reached += 1

            canonical = _canonical_company(app.company).lower()
            raw       = _canonical_company(app.company)
            company_count[canonical] += 1
            if canonical not in company_spellings:
                company_spellings[canonical] = Counter()
            company_spellings[canonical][raw] += 1

        interview_conversion_rate = (
            round(interview_reached / total_applications * 100, 1)
            if total_applications > 0 else 0.0
        )

        # ── Funnel — always 6 canonical rows, zero-filled when absent ──────────
        funnel_stages: list[dict] = [
            {"stage": s.title(), "count": stage_counter.get(s, 0)}
            for s in _STAGE_ORDER
        ]
        unknown = sorted(
            s for s in stage_counter
            if s not in _STAGE_ORDER
        )
        funnel_stages += [
            {"stage": s.title(), "count": stage_counter[s]}
            for s in unknown
        ]

        # ── Top companies — sorted desc by count, best spelling as display name ─
        top_companies: list[dict] = []
        for canonical, count in company_count.most_common(_TOP_COMPANIES_LIMIT):
            display_name = company_spellings[canonical].most_common(1)[0][0]
            top_companies.append({"company": display_name, "count": count})

        # ── Top keywords from applied jobs' tailored CVs ───────────────────────
        applied_jobs: list[JobRow] = (
            db.query(JobRow)
            .filter(
                JobRow.user_id     == user.user_id,
                JobRow.applied     == True,           # noqa: E712
                JobRow.tailored_cv.isnot(None),
            )
            .all()
        )
        keyword_counter: Counter[str] = Counter()
        for job in applied_jobs:
            for kw in _extract_skill_keywords(job.tailored_cv):
                keyword_counter[kw] += 1

        top_keywords = [
            {"keyword": kw, "count": cnt}
            for kw, cnt in keyword_counter.most_common(_TOP_KEYWORDS_LIMIT)
        ]

    logger.info(
        "[analytics] summary  total=%d  active=%d  interview_rate=%.1f%%"
        "  companies=%d  keywords=%d",
        total_applications, active_processes,
        interview_conversion_rate, len(top_companies), len(top_keywords),
    )

    return {
        "total_applications":        total_applications,
        "active_processes":          active_processes,
        "interview_conversion_rate": interview_conversion_rate,
        "funnel_stages":             funnel_stages,
        "top_companies":             top_companies,
        "top_keywords":              top_keywords,
    }
