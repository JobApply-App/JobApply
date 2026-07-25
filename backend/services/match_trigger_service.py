"""
Match Trigger Service — High-Match Detection & Event Emission (JOB-43)
======================================================================

Watches newly-computed match scores and emits a one-time trigger event when a
job crosses the high-match threshold, so downstream notification channels
(in-app bell, push/SMS, WhatsApp, CV Adaptation Flow) can react without each
re-implementing detection.

Design invariants
-----------------
1. CONFIGURABLE THRESHOLD — HIGH_MATCH_THRESHOLD env var (backend/config.py),
   default 85.0. Never hardcode the number at a call site.

2. EXACTLY-ONCE PER (user, job) — dedup is enforced by the database, not by
   in-process state: match_triggers has UNIQUE(user_id, job_id), so a re-score
   (same/higher/lower value) conflicts on INSERT and no duplicate event exists
   even across process restarts or concurrent scorers.

3. THIN-JD SAFE (CLAUDE.md Principle 4) — a trigger requires
   llm_validated=True AND semantic_score > 0. The thin-JD fallback path in
   compute_match_score_async() returns llm_validated=False with
   semantic=management=0, so un-hydrated jobs can never fire, regardless of
   how the local proxy scores their title.

4. NON-BLOCKING — schedule_match_trigger() is the pipeline-facing entry point:
   it fire-and-forgets an asyncio task and swallows every failure into a log
   line. Scoring must never slow down or crash because trigger persistence
   had a bad day.
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# Strong references to in-flight fire-and-forget tasks — asyncio only keeps
# weak refs, so without this a scheduled trigger could be garbage-collected
# mid-write.
_background_tasks: set["asyncio.Task"] = set()


def _default_threshold() -> float:
    from backend.config import HIGH_MATCH_THRESHOLD
    return HIGH_MATCH_THRESHOLD


# ── Decision layer (pure, deterministic) ─────────────────────────────────────

@dataclass(frozen=True)
class TriggerDecision:
    fired:  bool
    reason: str


def should_trigger(score_data: dict, threshold: Optional[float] = None) -> TriggerDecision:
    """
    Pure decision function: does this score qualify as a high-match trigger?

    Qualifies iff ALL of:
      • llm_validated is True   — excludes the thin-JD fallback and every
        run_llm_validation=False fast path (Principle 4: a Phase-1-only or
        local-proxy score is never trustworthy enough to interrupt the user).
      • semantic_score > 0      — belt-and-braces on the same principle; the
        thin-JD path zeroes this by contract.
      • total >= threshold      — boundary is inclusive: a score exactly at
        the threshold fires.

    `score_data` is MatchScoreResult.as_dict() (or a compatible dict).
    """
    th = _default_threshold() if threshold is None else float(threshold)
    total = float(score_data.get("total", 0.0))

    if not score_data.get("llm_validated", False):
        return TriggerDecision(False, "not_llm_validated")
    if float(score_data.get("semantic_score", 0.0)) <= 0.0:
        return TriggerDecision(False, "no_semantic_signal")
    if total < th:
        return TriggerDecision(False, f"below_threshold ({total:.1f} < {th:.1f})")
    return TriggerDecision(True, f"qualified ({total:.1f} >= {th:.1f})")


# ── Persistence layer ─────────────────────────────────────────────────────────

def _insert_trigger_row(
    job_id: str,
    user_id: str,
    score_data: dict,
    threshold: float,
    payload: dict,
    engine,
) -> bool:
    """
    Synchronous INSERT of the trigger row. Returns True if this call created
    the event, False if the (user, job) pair already fired (UNIQUE conflict).

    Runs inside asyncio.to_thread() — must stay free of event-loop touching.
    """
    from backend.repositories import match_trigger_repository

    return match_trigger_repository.insert(
        job_id       = job_id,
        user_id      = user_id,
        score        = round(float(score_data.get("total", 0.0)), 1),
        threshold    = round(float(threshold), 1),
        payload_json = json.dumps(payload, ensure_ascii=False),
        created_at   = datetime.now(timezone.utc).isoformat(),
        engine       = engine,
    )


# ── Async trigger evaluation ──────────────────────────────────────────────────

async def evaluate_match_trigger(
    job_id: str,
    user_id: str,
    score_data: dict,
    *,
    job_title: str = "",
    company_name: str = "",
    threshold: Optional[float] = None,
    engine=None,
) -> bool:
    """
    Evaluate a freshly-computed score and persist a trigger event if it
    qualifies. Returns True only when THIS call created the event (i.e. the
    job newly crossed the threshold for this user).

    The DB insert runs in a worker thread so the event loop — and therefore
    the scoring pipeline sharing it — is never blocked on SQLite I/O.

    Parameters mirror the scoring context: `score_data` is
    MatchScoreResult.as_dict(); `engine` defaults to the shared db.ENGINE
    (injectable for tests).
    """
    th = _default_threshold() if threshold is None else float(threshold)

    decision = should_trigger(score_data, th)
    if not decision.fired:
        logger.debug(
            "[match-trigger] no-fire job=%s user=%s: %s",
            job_id, user_id, decision.reason,
        )
        return False

    if engine is None:
        from backend.core.database import ENGINE
        engine = ENGINE

    # Compact payload for the notification channels — enough to render an
    # alert without a join back to the jobs table.
    payload = {
        "job_id":  job_id,
        "title":   job_title,
        "company": company_name,
        "score":   round(float(score_data.get("total", 0.0)), 1),
        "why_ron": (score_data.get("why_ron") or "")[:250],
    }

    inserted = await asyncio.to_thread(
        _insert_trigger_row, job_id, user_id, score_data, th, payload, engine
    )
    if inserted:
        # Structured single-line event — grep-able anchor for ops/debugging.
        logger.info(
            "[match-trigger] HIGH_MATCH_TRIGGER fired user=%s job=%s score=%.1f "
            "threshold=%.1f title=%r company=%r",
            user_id, job_id, payload["score"], th, job_title, company_name,
        )
    else:
        logger.debug(
            "[match-trigger] duplicate suppressed job=%s user=%s (already fired)",
            job_id, user_id,
        )
    return inserted


def schedule_match_trigger(
    job_id: str,
    user_id: str,
    score_data: dict,
    *,
    job_title: str = "",
    company_name: str = "",
    threshold: Optional[float] = None,
    engine=None,
) -> Optional["asyncio.Task"]:
    """
    Fire-and-forget entry point for the scoring pipeline.

    Schedules evaluate_match_trigger() on the running event loop and returns
    immediately — the scorer never awaits trigger persistence. Failures are
    logged by the done-callback, never raised into the caller. Returns the
    Task (mainly for tests), or None when no event loop is running (pure-sync
    caller) — in that context there is no pipeline to avoid blocking, and the
    sync paths are run_llm_validation=False anyway, which can never qualify.
    """
    try:
        task = asyncio.get_running_loop().create_task(
            evaluate_match_trigger(
                job_id, user_id, score_data,
                job_title    = job_title,
                company_name = company_name,
                threshold    = threshold,
                engine       = engine,
            )
        )
    except RuntimeError:
        logger.debug(
            "[match-trigger] no running event loop — skipping trigger for job=%s",
            job_id,
        )
        return None

    _background_tasks.add(task)
    task.add_done_callback(_on_trigger_done)
    return task


def _on_trigger_done(task: "asyncio.Task") -> None:
    _background_tasks.discard(task)
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.warning("[match-trigger] background trigger failed (non-fatal): %s", exc)


# ── Consumer API (UI Notifications, Mobile, WhatsApp, CV Adaptation) ─────────

def fetch_pending_triggers(user_id: str, engine=None, limit: int = 50) -> list[dict]:
    """
    Return the user's un-consumed trigger events, newest first, each as
    {id, job_id, score, created_at, **payload}. Consumers acknowledge with
    mark_triggers_consumed() — never by deleting rows (the row is the dedup
    record).
    """
    from backend.repositories import match_trigger_repository

    return match_trigger_repository.fetch_pending(user_id, limit=limit, engine=engine)


def mark_triggers_consumed(trigger_ids: list[int], engine=None) -> int:
    """Acknowledge delivered triggers. Returns the number of rows updated."""
    if not trigger_ids:
        return 0
    from backend.repositories import match_trigger_repository

    return match_trigger_repository.mark_consumed(
        trigger_ids,
        consumed_at = datetime.now(timezone.utc).isoformat(),
        engine      = engine,
    )
