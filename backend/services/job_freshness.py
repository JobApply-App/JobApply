"""
One definition of "this job is too old to show", shared by every query that
lists jobs to a user.

Jobs posted more than config.JOB_MAX_AGE_DAYS ago (30) are almost certainly
closed, yet the job boards and feeds kept showing them. They are hidden, not
deleted: each listing query filters them out, and the rows stay in the
database until open/closed detection can decide for real.

The posting date is the job's own posted_at when known, else the first time
we saw it (first_seen_at / created_at). A job with no date at all is kept.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, or_


def cutoff(now: datetime | None = None) -> datetime:
    from backend.config import JOB_MAX_AGE_DAYS
    return (now or datetime.now(timezone.utc)) - timedelta(days=JOB_MAX_AGE_DAYS)


def fresh_condition(posted_col, fallback_col):
    """SQL: the job's date (posted, else first seen) is within the window, or unknown."""
    date = func.coalesce(posted_col, fallback_col)
    return or_(date.is_(None), date >= cutoff())
