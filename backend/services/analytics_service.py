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
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.core.database import ENGINE

logger = logging.getLogger(__name__)


def compute_overview(user_id: str, session: Optional[Session] = None) -> dict:
    """
    Return the daily Overview KPI values for `user_id` (and only `user_id`).

    Accepts an optional already-open Session so a caller loading several
    Overview-page datasets in one request (backend/api/routes/dashboard.py)
    can share one session/connection instead of this opening its own — same
    optional-session pattern as kv_repository/profile_entity_repository/
    evidence_repository.
    """
    midnight_utc = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    def _run(db: Session) -> dict:
        # All three KPIs in one round trip via conditional aggregation
        # (SUM/AVG of a CASE WHEN) instead of three separate SELECT count()/
        # avg() queries against the same table — same filters, same date
        # boundary, one query instead of three. SUM/AVG over zero matching
        # rows returns NULL (unlike COUNT(*), which returns 0), so the `or 0`
        # / `or 0.0` fallbacks below reproduce the original per-query
        # zero-rows behavior exactly.
        row = db.execute(
            text("""
                SELECT
                    SUM(CASE WHEN created_at >= :midnight THEN 1 ELSE 0 END) AS jobs_scanned_today,
                    SUM(CASE WHEN applied = true AND applied_at >= :midnight THEN 1 ELSE 0 END) AS actions_taken_today,
                    AVG(CASE WHEN match_score > 0 THEN match_score END) AS avg_match_score
                FROM public.user_job_matches
                WHERE user_id = CAST(:uid AS uuid)
            """),
            {"uid": user_id, "midnight": midnight_utc},
        ).one()
        return {
            "jobs_scanned_today":  int(row.jobs_scanned_today or 0),
            "actions_taken_today": int(row.actions_taken_today or 0),
            "average_match_score": round(float(row.avg_match_score), 1) if row.avg_match_score else 0.0,
        }

    if session is not None:
        kpis = _run(session)
    else:
        with Session(ENGINE) as db:
            kpis = _run(db)

    jobs_scanned_today  = kpis["jobs_scanned_today"]
    actions_taken_today = kpis["actions_taken_today"]
    average_match_score = kpis["average_match_score"]

    logger.info(
        "[analytics] overview user=%s scanned_today=%d actions_today=%d avg_match=%.1f",
        user_id, jobs_scanned_today, actions_taken_today, average_match_score,
    )

    return {
        "jobs_scanned_today":  jobs_scanned_today,
        "actions_taken_today": actions_taken_today,
        "average_match_score": average_match_score,
    }
