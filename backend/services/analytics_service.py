"""
Analytics service — daily activity KPIs for one user's Overview dashboard.

compute_overview(user_id) -> dict
  {
    "jobs_scanned_today":  int,    # JobRow created since UTC midnight today
    "actions_taken_today": int,    # applications submitted since UTC midnight today
    "average_match_score": float,  # AVG(JobRow.match_score) across scored jobs, 1dp
  }

The Overview is a *daily snapshot* ("here's what happened overnight"), so the
two activity counters MUST reset to 0 at UTC midnight. Lifetime/static metrics
(top strengths, total tailored-CV count) do not belong here — they live on the
dedicated Analytics page. `average_match_score` is kept as a stable quality
signal, the third KPI in the strip.

Date-filtering strategy — why substr, not a full-ISO `>=` compare
-----------------------------------------------------------------
Timestamp columns are stored as strings in INCONSISTENT formats across the app:
  created_at → "2026-07-02T08:18:33.114244+00:00"   (ISO-8601, 'T', +00:00)
  applied_at → "2026-07-02 08:13 UTC"                (space sep, ' UTC' suffix)
Comparing a whole timestamp string with `>=` against a computed midnight ISO
boundary is therefore fragile: any mismatch in separator, offset, or precision
makes the lexicographic comparison wrong, and the counter silently stops
resetting (the "stuck on 8 for days" bug). Instead we compare only the leading
YYYY-MM-DD date prefix (`substr(col, 1, 10)`) to today's UTC date. Both storage
formats begin with exactly that prefix, and it flips at 00:00 UTC — so the
counters reset every day *by construction*, independent of the rest of the
string's shape.

Tenant isolation
----------------
Every query filters by user_id == user_id. The user_id comes exclusively from
the verified JWT (CurrentUser) at the route layer, never from the client.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.core.database import ENGINE
from backend.models.job import JobRow

logger = logging.getLogger(__name__)


def compute_overview(user_id: str) -> dict:
    """Return the daily Overview KPI values for `user_id` (and only `user_id`)."""
    # UTC calendar date for "today". strftime → "2026-07-07"; this string flips
    # at 00:00 UTC, which is what forces the daily reset of the two counters.
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    with Session(ENGINE) as db:
        def _count(*filters) -> int:
            return int(
                db.query(func.count(JobRow.job_id))
                .filter(JobRow.user_id == user_id, *filters)
                .scalar()
                or 0
            )

        # Jobs the scraper surfaced today — created_at date prefix == today (UTC).
        jobs_scanned_today = _count(
            JobRow.created_at.isnot(None),
            func.substr(JobRow.created_at, 1, 10) == today_str,
        )

        # Concrete user actions today — applications submitted (applied_at date
        # prefix == today, UTC). applied_at is only set when the user applies,
        # so this is the honest "what did I do today" counter.
        actions_taken_today = _count(
            JobRow.applied.is_(True),
            JobRow.applied_at.isnot(None),
            func.substr(JobRow.applied_at, 1, 10) == today_str,
        )

        avg_score_raw = (
            db.query(func.avg(JobRow.match_score))
            .filter(JobRow.user_id == user_id, JobRow.match_score > 0)
            .scalar()
        )
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
