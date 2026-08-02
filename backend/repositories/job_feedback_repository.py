"""
Persistence for per-job user feedback (thumbs up/down + reason).

Backed by columns on user_job_matches rather than a table of its own since
migration 3542b0021d6b: feedback is 1:1 with the (user, job) match it is about
— the old job_feedback table enforced that with a UNIQUE (user_id, job_id)
index and its writer was already an upsert ("latest opinion wins") — so it is
state on that row, not a separate entity. The partial index ix_ujm_feedback
keeps "what has this user rated" as cheap as the dedicated table was.

feedback_snapshot is kept as a real column rather than being derived on read.
It looks like the same denormalisation the trigger payload was, but is not:
build_job_snapshot() records culture_axis / operational_pace / work_model from
the company_intel culture cache, none of which live on user_job_matches, and
the preference-learning path reads snapshot["culture_axis"] directly. Freezing
it at rating time is also the more correct semantics — the learning signal
should reflect what the job looked like when the user judged it, not what a
re-researched culture profile says today.

Consolidates the CRUD previously inlined in feedback_service.py's
_upsert_feedback_row/fetch_feedback_rows.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import text
from sqlalchemy.engine import Engine

from backend.core.database import ENGINE


def upsert(
    *,
    user_id: str,
    job_id: str,
    feedback_type: str,
    reason: Optional[str],
    snapshot_json: str,
    now: str,
    engine: Optional[Engine] = None,
) -> None:
    """
    Latest opinion wins — one feedback state per (user_id, job_id).

    A no-op when the user has no match row for that job: feedback is a property
    of a match, and there is nothing to attach it to otherwise. The old table
    would have accepted such a row and orphaned it.
    """
    eng = engine or ENGINE
    with eng.begin() as conn:
        conn.execute(
            text("""
                UPDATE public.user_job_matches
                SET feedback_type     = :ftype,
                    feedback_reason   = :reason,
                    feedback_snapshot = CAST(NULLIF(:snapshot, '') AS jsonb),
                    feedback_at       = COALESCE(CAST(NULLIF(:now, '') AS timestamptz), now())
                WHERE job_id = :job_id AND user_id = CAST(:uid AS uuid)
            """),
            {
                "ftype": feedback_type, "reason": reason, "snapshot": snapshot_json,
                "now": now, "job_id": job_id, "uid": user_id,
            },
        )


def fetch_for_user(user_id: str, engine: Optional[Engine] = None) -> list[dict]:
    """Every job this user has rated, newest first."""
    eng = engine or ENGINE
    with eng.connect() as conn:
        rows = conn.execute(
            text("""
                SELECT job_id, feedback_type, feedback_reason, feedback_snapshot, feedback_at
                FROM public.user_job_matches
                WHERE user_id = CAST(:uid AS uuid) AND feedback_type IS NOT NULL
                ORDER BY feedback_at DESC NULLS LAST
            """),
            {"uid": user_id},
        ).fetchall()

    return [
        {
            "job_id":        r.job_id,
            "feedback_type": r.feedback_type,
            "reason":        r.feedback_reason,
            # jsonb comes back already deserialised; the old column was TEXT
            # and callers expect a dict either way.
            "snapshot":      r.feedback_snapshot or {},
            "updated_at":    r.feedback_at.isoformat() if r.feedback_at else "",
        }
        for r in rows
    ]
