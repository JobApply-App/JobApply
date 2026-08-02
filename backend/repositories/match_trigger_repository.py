"""
Persistence for high-match trigger events (JOB-43).

Backed by columns on user_job_matches rather than a table of its own since
migration 3542b0021d6b: a trigger is 1:1 with the (user, job) match that fired
it — the old match_triggers table enforced exactly that with a UNIQUE
(user_id, job_id) index — so it is state on that row, not a separate entity.
The partial index ix_ujm_pending_triggers keeps "what is pending" as cheap as
it was when the table was dedicated.

Business logic (should_trigger, evaluate_match_trigger, schedule_match_trigger)
stays in backend/services/match_trigger_service.py, which calls through here.

The trigger state remains the DEDUP record: `insert` returns False when this
(user, job) already fired, and consumers acknowledge with mark_consumed rather
than clearing the state, so a job cannot re-notify on every re-score.

Every function accepts an optional `engine` override (falling back to the
shared ENGINE, resolved at call time) — the service's own functions already
take an injectable `engine` for testability.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import text
from sqlalchemy.engine import Engine

from backend.core.database import ENGINE


def insert(
    *,
    job_id: str,
    user_id: str,
    score: float,
    threshold: float,
    payload_json: str,   # accepted for signature compatibility — see below
    created_at: str,
    engine: Optional[Engine] = None,
) -> bool:
    """
    Record the trigger. Returns True if this call created the event, False if
    the (user, job) pair already fired.

    payload_json is deliberately ignored. It used to carry
    title/company/score/fit_brief so a notification could render "without a
    join back to the jobs table"; the state now lives ON that row, so
    fetch_pending reconstructs those fields from the join instead of reading a
    copy frozen at write time (which could go stale after a re-score). The
    parameter stays so match_trigger_service's call site is untouched.
    """
    eng = engine or ENGINE
    with eng.begin() as conn:
        updated = conn.execute(
            text("""
                UPDATE public.user_job_matches
                SET trigger_state     = 'pending',
                    trigger_score     = :score,
                    trigger_threshold = :threshold,
                    triggered_at      = COALESCE(CAST(NULLIF(:created_at, '') AS timestamptz), now())
                WHERE job_id = :job_id
                  AND user_id = CAST(:user_id AS uuid)
                  AND trigger_state IS NULL
            """),
            {
                "score": score, "threshold": threshold, "created_at": created_at,
                "job_id": job_id, "user_id": user_id,
            },
        ).rowcount
    return bool(updated)


def fetch_pending(user_id: str, limit: int = 50, engine: Optional[Engine] = None) -> list[dict]:
    """
    Return the user's un-consumed trigger events, newest first, each shaped
    {id, job_id, score, created_at, title, company, fit_brief} — the same keys
    the old payload_json carried, now read live from the joined posting.

    `id` is the job_id: the fold removed the integer surrogate key, and job_id
    is unique per match, so it is the stable handle to pass to mark_consumed().
    """
    eng = engine or ENGINE
    with eng.connect() as conn:
        rows = conn.execute(
            text("""
                SELECT ujm.job_id, ujm.trigger_score, ujm.triggered_at,
                       ujm.fit_brief, jp.title, jp.company
                FROM public.user_job_matches ujm
                JOIN public.job_postings jp ON jp.id = ujm.job_posting_id
                WHERE ujm.user_id = CAST(:uid AS uuid)
                  AND ujm.trigger_state = 'pending'
                ORDER BY ujm.triggered_at DESC NULLS LAST
                LIMIT :lim
            """),
            {"uid": user_id, "lim": limit},
        ).fetchall()

    return [
        {
            "id":         r.job_id,
            "job_id":     r.job_id,
            "score":      r.trigger_score,
            "created_at": r.triggered_at.isoformat() if r.triggered_at else "",
            "title":      r.title,
            "company":    r.company,
            "fit_brief":  (r.fit_brief or "")[:250],
        }
        for r in rows
    ]


def mark_consumed(job_ids: list[str], consumed_at: str, engine: Optional[Engine] = None) -> int:
    """
    Acknowledge delivered triggers. Returns the number of rows updated.

    Takes job_ids (str), not the integer ids the dedicated table used to hand
    out. Safe to change: the notification worker that would consume these does
    not exist yet, so at the time of the fold fetch_pending/mark_consumed had
    no caller outside the service wrapper.
    """
    if not job_ids:
        return 0
    eng = engine or ENGINE
    with eng.begin() as conn:
        return int(conn.execute(
            text("""
                UPDATE public.user_job_matches
                SET trigger_state       = 'consumed',
                    trigger_consumed_at = COALESCE(CAST(NULLIF(:at, '') AS timestamptz), now())
                WHERE job_id = ANY(:ids) AND trigger_state = 'pending'
            """),
            {"ids": job_ids, "at": consumed_at},
        ).rowcount)
