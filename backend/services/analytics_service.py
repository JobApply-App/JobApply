"""
Analytics service — daily activity KPIs for one user's Overview dashboard.

compute_overview(user_id) -> dict
  {
    "jobs_scanned_today":  int,    # user_job_matches created since UTC midnight today
    "actions_taken_today": int,    # applications submitted since UTC midnight today
    "average_match_score": float,  # AVG(user_job_matches.match_score) across scored jobs, 1dp
  }

The Overview is a *daily snapshot* ("here's what happened overnight"), so the
two activity counters MUST reset to 0 at UTC midnight. Lifetime/static metrics
(top strengths, total tailored-CV count) do not belong here — they live on the
dedicated Analytics page. `average_match_score` is kept as a stable quality
signal, the third KPI in the strip.

Date-filtering strategy
-----------------------
user_job_matches.created_at/applied_at are real TIMESTAMPTZ columns (the old
jobs table stored these as strings in inconsistent formats across the app,
which used to need a fragile substr-prefix comparison to work around — that
problem doesn't exist with real timestamp types, so this compares real UTC
midnight directly).

Tenant isolation
----------------
Every query filters by user_id == user_id. The user_id comes exclusively from
the verified JWT (CurrentUser) at the route layer, never from the client.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.core.database import ENGINE

logger = logging.getLogger(__name__)


def compute_overview(user_id: str) -> dict:
    """Return the daily Overview KPI values for `user_id` (and only `user_id`)."""
    midnight_utc = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    with Session(ENGINE) as db:
        # Jobs the scraper surfaced today.
        jobs_scanned_today = db.execute(
            text("""
                SELECT count(*) FROM public.user_job_matches
                WHERE user_id = CAST(:uid AS uuid) AND created_at >= :midnight
            """),
            {"uid": user_id, "midnight": midnight_utc},
        ).scalar_one()

        # Concrete user actions today — applications submitted. applied_at is
        # only set when the user applies, so this is the honest "what did I
        # do today" counter.
        actions_taken_today = db.execute(
            text("""
                SELECT count(*) FROM public.user_job_matches
                WHERE user_id = CAST(:uid AS uuid) AND applied = true AND applied_at >= :midnight
            """),
            {"uid": user_id, "midnight": midnight_utc},
        ).scalar_one()

        avg_score_raw = db.execute(
            text("""
                SELECT avg(match_score) FROM public.user_job_matches
                WHERE user_id = CAST(:uid AS uuid) AND match_score > 0
            """),
            {"uid": user_id},
        ).scalar_one()
        average_match_score = round(float(avg_score_raw), 1) if avg_score_raw else 0.0

    logger.info(
        "[analytics] overview user=%s scanned_today=%d actions_today=%d avg_match=%.1f",
        user_id, jobs_scanned_today, actions_taken_today, average_match_score,
    )

    return {
        "jobs_scanned_today":  jobs_scanned_today,
        "actions_taken_today": actions_taken_today,
        "average_match_score": average_match_score,
    }
