"""
ApplierAgent — finds high-scoring jobs and simulates submitting applications.

apply() logs each attempt, writes an Application record to the DB, and marks
the source JobMatch as applied so it is never processed twice.

Real form-fill logic (Playwright + cover-letter generation) lives in
auto_applier.py and can be wired in later; this agent focuses on the
orchestration layer and persistence contract.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from backend.schemas.application import Application, ApplicationStatus
from backend.schemas.job import JobMatch
from backend.repositories import application_repository as app_store
from backend.repositories import job_repository as job_store

logger = logging.getLogger(__name__)

_APPLY_THRESHOLD = 85.0


def _detect_ats(url: str | None) -> str:
    if not url:
        return "Direct"
    u = url.lower()
    if "greenhouse.io" in u or "greenhouse" in u:
        return "Greenhouse"
    if "lever.co" in u or "/lever" in u:
        return "Lever"
    if "workday" in u:
        return "Workday"
    if "ashbyhq" in u or "ashby" in u:
        return "Ashby"
    if "smartrecruiters" in u:
        return "SmartRecruiters"
    if "jobvite" in u:
        return "Jobvite"
    if "taleo" in u:
        return "Taleo"
    if "linkedin.com/jobs" in u:
        return "LinkedIn"
    return "Direct"


def _format_submitted_at(now: datetime) -> str:
    """Return a human-readable submission timestamp, e.g. 'Today 14:32'."""
    return f"Today {now.strftime('%H:%M')}"


class ApplierAgent:
    """
    Queries the job store for eligible matches and records simulated applications.

    Eligible = score >= threshold AND not yet applied.
    """

    def __init__(self, user_id: str, threshold: float = _APPLY_THRESHOLD) -> None:
        self.user_id   = user_id
        self.threshold = threshold

    def run_cycle(self) -> list[Application]:
        """
        Process all currently eligible jobs.
        Returns the list of Application records created in this cycle.
        """
        eligible = job_store.get_eligible_for_apply(self.threshold, self.user_id)
        if not eligible:
            logger.info("[applier] No eligible jobs above %.1f score threshold.", self.threshold)
            return []

        logger.info(
            "[applier] Starting cycle — %d eligible job(s) above %.1f",
            len(eligible), self.threshold,
        )
        results: list[Application] = []
        for job in eligible:
            app = self._apply(job)
            results.append(app)

        logger.info(
            "[applier] Cycle complete — %d application(s) submitted.", len(results)
        )
        return results

    def apply_single(self, job_id: str) -> Application | None:
        """
        Apply to one specific job by ID. Returns None if not found or already applied.
        """
        jobs = job_store.get_all(self.user_id)
        job  = next((j for j in jobs if j.job_id == job_id), None)
        if job is None:
            logger.warning("[applier] Job %s not found.", job_id)
            return None
        if job.applied:
            logger.info("[applier] Job %s already applied — skipping.", job_id)
            return None
        return self._apply(job)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _apply(self, job: JobMatch) -> Application:
        now          = datetime.now(timezone.utc)
        submitted_at = _format_submitted_at(now)
        app_id       = f"app-{job.job_id}"
        ats          = _detect_ats(job.apply_url)

        logger.info(
            "[applier] Applying — %.1f/100  %s @ %s  (ATS: %s)",
            job.score, job.title, job.company, ats,
        )

        app = Application(
            application_id=app_id,
            job_id=job.job_id,
            title=job.title,
            company=job.company,
            ats=ats,
            status=ApplicationStatus.SUBMITTED,
            submitted_at=submitted_at,
            last_update=submitted_at,
            score=job.score,
        )

        app_store.save(app)
        job_store.mark_applied(job.job_id, submitted_at, self.user_id)

        logger.info(
            "[applier] ✓ Saved application %s — %s @ %s",
            app_id, job.title, job.company,
        )
        return app
