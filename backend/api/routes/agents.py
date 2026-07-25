"""
Agent status and execution routes.

Per-agent work dispatch
-----------------------
Each of the four pipeline agents maps to a distinct backend worker:

  s1  Scraper             run_discovery_cycle() + SCRAPER_MANAGER.run_all()
                          — discovers new jobs from LinkedIn + all board scrapers.
                          run_discovery_cycle manages all four agent states
                          internally via agent_store, so _run_agent_scrape
                          skips the outer set_active / set_idle for s1.

  s2  Sourcing Specialist feed_service.refresh_user_scores(user_id)
                          — computes ATS match_score for every unscored new job.

  s3  Content Strategist  jd_backfill_service.backfill_jd_text(user_id)
                          — fetches full JD text for jobs that only have thin
                            metadata, enabling richer scoring downstream.

  s4  Quality Guard       feed_service.force_rescore_all(user_id)
                          — re-evaluates match scores for ALL existing jobs,
                            picking up profile changes or score-logic updates.

Concurrency model — asyncio.create_task()
-----------------------------------------
FastAPI's BackgroundTasks drains tasks sequentially after the response:
  for task in self.tasks: await task()
This means a second click always waits behind the first — the deadlock.

asyncio.create_task() schedules the coroutine immediately as an independent
Task on the already-running event loop.  The endpoint returns HTTP 200 at
once; multiple agents for the same user, or the same agent for different
users, run fully concurrently and interleave at every await.

Duplicate-run guard
-------------------
_active_runs stores "user_id:agent_id" keys.  Each agent has its own slot,
so s2 can run while s1 is in flight.  The finally block always discards the
key — timeout, crash, or success all release the lock.

Timeout
-------
Each runner is wrapped in asyncio.wait_for(timeout=_PIPELINE_TIMEOUT_S).
On expiry the coroutine is cancelled; its own finally blocks still execute
(Python guarantees this), agents are reset to idle, and the triggering card
surfaces a human-readable error.
"""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException

from backend.api.deps import CurrentUser, get_current_user
from backend.schemas.agent import AgentStatus
import backend.services.agent_store as store

logger = logging.getLogger(__name__)
router = APIRouter()

# ── Per-run state ─────────────────────────────────────────────────────────────
# Key format: "{user_id}:{agent_id}" — each agent slot is independent so
# Sourcing Specialist can run while Scraper is also running, etc.

_active_runs: set[str] = set()

_PIPELINE_TIMEOUT_S = 120.0   # seconds before a hung worker is force-cancelled


# ── Per-agent runners ─────────────────────────────────────────────────────────

async def _run_s1(user_id: str) -> None:
    """
    s1 — Scraper: discover new jobs from all sources.

    Runs board scrapers (Drushim, AllJobs, GotFriends, Dialog, Nisha, Comeet,
    Google Dork) and the LinkedIn discovery cycle in parallel.

    SCRAPER_MANAGER.run_all() does not touch agent_store — it only saves jobs.
    run_discovery_cycle() owns all four agent-state transitions; that is why
    _run_agent_scrape skips the outer set_active/set_idle for s1.
    """
    from backend.scrapers.scraper_manager import SCRAPER_MANAGER
    from backend.services.discovery import run_discovery_cycle
    await asyncio.gather(
        SCRAPER_MANAGER.run_all(user_id=user_id),
        run_discovery_cycle(user_id=user_id),
    )


async def _run_s2(user_id: str) -> None:
    """
    s2 — Sourcing Specialist: score all unscored new jobs against the user's
    Master Profile using ATS keyword analysis.
    """
    from backend.services.feed_service import refresh_user_scores
    await refresh_user_scores(user_id=user_id)


async def _run_s3(user_id: str) -> None:
    """
    s3 — Content Strategist: backfill full JD text for jobs that currently
    hold only thin metadata (title + company line).  Richer descriptions
    produce more accurate ATS scores when s2 / s4 re-run afterward.

    min_score=0.0 ensures every job in the feed is eligible, not just
    high-scorers — quality guard (s4) can re-rank after descriptions land.
    """
    from backend.services.jd_backfill_service import backfill_jd_text
    await backfill_jd_text(user_id=user_id, min_score=0.0)


async def _run_s4(user_id: str) -> None:
    """
    s4 — Quality Guard: force a complete re-evaluation of ATS match scores
    for every job in the user's feed.  Useful after profile edits or when
    new JD text landed via s3 and scores need refreshing.
    """
    from backend.services.feed_service import force_rescore_all
    await force_rescore_all(user_id=user_id)


# Maps agent_id → (runner coroutine, active-state message)
_AGENT_RUNNERS: dict[str, tuple] = {
    "s1": (_run_s1, "Scraping job boards + LinkedIn…"),
    "s2": (_run_s2, "Scoring new jobs against your profile…"),
    "s3": (_run_s3, "Fetching full job descriptions…"),
    "s4": (_run_s4, "Re-evaluating all job scores…"),
}

# s1's runner calls run_discovery_cycle which owns all agent-state transitions.
# Skip the outer set_active / set_idle for this agent.
_SELF_MANAGED_AGENTS = {"s1"}

# Key suffix used when the FULL pipeline is running as a single coordinated task.
# Format: "{user_id}:pipeline"  (no agent_id slot — it spans all four agents)
_PIPELINE_SYNC_KEY = "pipeline"

# Ordered sequence for the master sync — s1 discovers first, then downstream
# agents process the new data in the order that makes semantic sense.
_PIPELINE_SEQUENCE = ("s1", "s2", "s3", "s4")


# ── Full-pipeline sequential runner ──────────────────────────────────────────

async def _run_full_pipeline(user_id: str) -> None:
    """
    Master pipeline task — scheduled via asyncio.create_task() by /sync.

    Runs all four agents sequentially:  s1 → s2 → s3 → s4.

    Each step runs to completion (or hits its own timeout) before the next
    begins, so downstream agents always see the freshest data from upstream.

    A failed step sets that agent's state to error but does NOT abort the
    remaining steps — s2/s3/s4 can still process existing data even if s1
    produced nothing new this cycle.

    The pipeline-level run lock in _active_runs is released in the finally
    block regardless of how the loop exits (success, exception, cancellation).

    State wipe (second pass)
    ------------------------
    sync_pipeline() already calls pipeline_reset() for every agent before
    scheduling this task.  We repeat it here as a safety net: asyncio.create_task()
    schedules the coroutine on the event loop but does not run it synchronously.
    In a loaded process, other callbacks can execute between create_task() and
    the first await inside this coroutine, potentially dirtying agent state
    again.  The second pipeline_reset() at coroutine entry closes that window
    so the very first poll tick after the HTTP response always sees uniform
    "waiting to start" text across all four cards.
    """
    pipeline_key = f"{user_id}:{_PIPELINE_SYNC_KEY}"

    try:
        # ── Second-pass clean slate ───────────────────────────────────────────
        # Wipe any state drift that occurred between create_task() and now.
        _INIT_MSG = "Pipeline initialising — waiting to start…"
        for aid in _PIPELINE_SEQUENCE:
            store.pipeline_reset(aid, _INIT_MSG)

        for agent_id in _PIPELINE_SEQUENCE:
            runner, active_msg = _AGENT_RUNNERS[agent_id]
            self_managed = agent_id in _SELF_MANAGED_AGENTS

            try:
                if not self_managed:
                    store.set_active(agent_id, active_msg)

                await asyncio.wait_for(runner(user_id), timeout=_PIPELINE_TIMEOUT_S)

                if not self_managed:
                    store.set_idle(agent_id)

            except asyncio.TimeoutError:
                logger.warning(
                    "[agents/sync] Step %s timed out after %.0f s (user=%s) — continuing",
                    agent_id, _PIPELINE_TIMEOUT_S, user_id,
                )
                store.set_error(
                    agent_id,
                    f"Timed out after {int(_PIPELINE_TIMEOUT_S)}s — job boards may be slow.",
                )
                # s1 owns all state transitions; reset sibling agents if s1 hung
                if self_managed:
                    for aid in _PIPELINE_SEQUENCE:
                        if aid != agent_id:
                            store.set_idle(aid)

            except Exception as exc:
                logger.exception(
                    "[agents/sync] Step %s failed (user=%s): %s",
                    agent_id, user_id, exc,
                )
                store.set_error(agent_id, f"Step failed: {exc}")
                if self_managed:
                    for aid in _PIPELINE_SEQUENCE:
                        if aid != agent_id:
                            store.set_idle(aid)

        logger.info("[agents/sync] Full pipeline complete — user=%s", user_id)

    finally:
        _active_runs.discard(pipeline_key)
        logger.debug("[agents/sync] Pipeline lock released — user=%s", user_id)


# ── Fire-and-forget task ──────────────────────────────────────────────────────

async def _run_agent_scrape(agent_id: str, user_id: str) -> None:
    """
    Independent async Task scheduled via asyncio.create_task().

    Dispatches to the correct per-agent runner, manages agent state for
    non-self-managed agents, enforces a global timeout, and always releases
    the run-lock in the finally block.
    """
    run_key = f"{user_id}:{agent_id}"
    entry   = _AGENT_RUNNERS.get(agent_id)
    if entry is None:
        logger.error("[agents/run] No runner registered for agent_id=%r", agent_id)
        _active_runs.discard(run_key)
        return

    runner, active_msg = entry
    self_managed = agent_id in _SELF_MANAGED_AGENTS

    try:
        # Non-self-managed agents: stamp active state so UI reacts immediately
        if not self_managed:
            store.set_active(agent_id, active_msg)

        await asyncio.wait_for(runner(user_id), timeout=_PIPELINE_TIMEOUT_S)

        # Successful completion — return to idle
        if not self_managed:
            store.set_idle(agent_id)

    except asyncio.TimeoutError:
        logger.warning(
            "[agents/run] Pipeline timed out after %.0f s (user=%s agent=%s)",
            _PIPELINE_TIMEOUT_S, user_id, agent_id,
        )
        store.set_error(
            agent_id,
            f"Timed out after {int(_PIPELINE_TIMEOUT_S)} s — job boards may be slow. Try again.",
        )
        # s1: discovery_cycle's finally resets s1-s4 to idle, but ensure others
        # are clean in case the cancel happened before that finally ran.
        if self_managed:
            for aid in ("s1", "s2", "s3", "s4"):
                if aid != agent_id:
                    store.set_idle(aid)

    except Exception as exc:
        logger.exception(
            "[agents/run] Runner failed (user=%s agent=%s): %s",
            user_id, agent_id, exc,
        )
        store.set_error(agent_id, f"Run failed: {exc}")
        if self_managed:
            for aid in ("s1", "s2", "s3", "s4"):
                if aid != agent_id:
                    store.set_idle(aid)

    finally:
        _active_runs.discard(run_key)
        logger.debug(
            "[agents/run] Run lock released — user=%s agent=%s", user_id, agent_id
        )


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/", response_model=list[AgentStatus])
async def list_agents(user: CurrentUser = Depends(get_current_user)):
    """
    Return live status for all pipeline agents, scoped to the authenticated user.

    On first call for a new user, their personal agent registry is seeded
    automatically with four default-idle agents — so the UI never shows empty
    or dead cards.
    """
    return store.get_for_user(user.user_id)


@router.post("/sync")
async def sync_pipeline(user: CurrentUser = Depends(get_current_user)):
    """
    Trigger a full sequential pipeline run for the authenticated user:
      s1 (Scraper) → s2 (Sourcing) → s3 (Content) → s4 (Quality Guard)

    Each stage waits for the previous one to finish before starting, so
    downstream agents always score / backfill / rescore the latest data.

    Returns triggered=true if the task was scheduled, triggered=false if a
    pipeline run is already in flight for this user.  The frontend uses this
    flag to avoid showing a false "Running…" state.

    Uses asyncio.create_task() — the endpoint returns HTTP 200 immediately
    while the pipeline coroutine runs concurrently in the background.
    """
    pipeline_key = f"{user.user_id}:{_PIPELINE_SYNC_KEY}"

    if pipeline_key in _active_runs:
        # Stale-lock check: if ALL four agents are at rest (idle / error),
        # the task completed without cleaning up the key.  Hard-reset.
        agent_states = [
            store.get_by_id_for_user(user.user_id, aid)
            for aid in _PIPELINE_SEQUENCE
        ]
        all_at_rest = all(
            a is None or a.state in ("idle", "error", "paused")
            for a in agent_states
        )
        if all_at_rest:
            logger.warning(
                "[agents/sync] Stale pipeline lock for user=%s — force-clearing",
                user.user_id,
            )
            _active_runs.discard(pipeline_key)
            # fall through to schedule a fresh run
        else:
            logger.info(
                "[agents/sync] Pipeline already active for user=%s — skipping duplicate",
                user.user_id,
            )
            return {
                "triggered": False,
                "reason":    "pipeline already running",
            }

    _active_runs.add(pipeline_key)

    # Hard-reset all four agents to a clean queued state BEFORE create_task().
    # pipeline_reset() clears current_task and error_msg — fields that
    # set_queued() leaves untouched — so no stale text from crashed prior runs
    # survives into the new cycle.  This executes synchronously, so the state
    # is already clean before the HTTP 200 response leaves the server and
    # definitely before the frontend's next 5-second poll fires.
    for aid in _PIPELINE_SEQUENCE:
        store.pipeline_reset(aid, "Pipeline queued — waiting to start…")

    asyncio.create_task(
        _run_full_pipeline(user.user_id),
        name=f"pipeline:{user.user_id}",
    )

    logger.info(
        "[agents/sync] Pipeline task created — user=%s timeout_per_step=%.0f s",
        user.user_id, _PIPELINE_TIMEOUT_S,
    )
    return {"triggered": True, "state": "queued"}


@router.get("/{agent_id}", response_model=AgentStatus)
async def get_agent(
    agent_id: str,
    user: CurrentUser = Depends(get_current_user),
):
    """Return status for a single agent, scoped to the authenticated user."""
    agent = store.get_by_id_for_user(user.user_id, agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


@router.post("/{agent_id}/pause")
async def pause_agent(
    agent_id: str,
    user: CurrentUser = Depends(get_current_user),
):
    """Pause a running agent, scoped to the authenticated user's own view."""
    if not store.get_by_id_for_user(user.user_id, agent_id):
        raise HTTPException(status_code=404, detail="Agent not found")
    store.set_paused_for_user(user.user_id, agent_id)
    return {"agent_id": agent_id, "state": "paused"}


@router.post("/{agent_id}/resume")
async def resume_agent(
    agent_id: str,
    user: CurrentUser = Depends(get_current_user),
):
    """Resume a paused agent, scoped to the authenticated user's own view."""
    if not store.get_by_id_for_user(user.user_id, agent_id):
        raise HTTPException(status_code=404, detail="Agent not found")
    store.set_resumed_for_user(user.user_id, agent_id)
    return {"agent_id": agent_id, "state": "idle"}


@router.post("/{agent_id}/run")
async def run_agent(
    agent_id: str,
    user: CurrentUser = Depends(get_current_user),
):
    """
    Trigger an immediate run for a specific pipeline agent.

    Each agent_id maps to its own dedicated worker (see module docstring).
    Agents run independently — clicking s2 while s1 is in flight is valid.

    Returns triggered=true if the task was scheduled, triggered=false if
    that specific agent already has a run in flight for this user.  The
    frontend uses this flag to avoid showing a false "Starting…" state.

    Uses asyncio.create_task() so the endpoint returns HTTP 200 immediately
    and the work runs concurrently without blocking any queue.
    """
    if not store.get_by_id_for_user(user.user_id, agent_id):
        raise HTTPException(status_code=404, detail="Agent not found")

    if agent_id not in _AGENT_RUNNERS:
        raise HTTPException(
            status_code=400,
            detail=f"No runner configured for agent '{agent_id}'. Valid: {list(_AGENT_RUNNERS)}",
        )

    # ── Per-agent duplicate guard ─────────────────────────────────────────────
    run_key = f"{user.user_id}:{agent_id}"
    if run_key in _active_runs:
        # Stale-lock check: if the store already shows idle/error the asyncio
        # task finished but somehow left the key behind (e.g. the process was
        # SIGKILL'd mid-flight, a dev reload swapped the module, etc.).
        # Hard-reset the lock so the user can trigger a fresh run immediately.
        current = store.get_by_id_for_user(user.user_id, agent_id)
        if current and current.state in ("idle", "error"):
            logger.warning(
                "[agents/run] Stale run lock detected "
                "(user=%s agent=%s store_state=%s) — force-clearing lock",
                user.user_id, agent_id, current.state,
            )
            _active_runs.discard(run_key)
            # fall through to schedule a fresh run
        else:
            logger.info(
                "[agents/run] Agent %s genuinely active for user=%s — skipping duplicate",
                agent_id, user.user_id,
            )
            return {
                "agent_id":  agent_id,
                "state":     "queued",
                "triggered": False,
                "reason":    f"agent {agent_id} already running",
            }

    # ── Register, stamp UI, schedule task ────────────────────────────────────
    _active_runs.add(run_key)

    # Stamp queued for non-self-managed agents so the UI reacts before the
    # first poll cycle.  s1 is stamped active by discovery_cycle itself.
    if agent_id not in _SELF_MANAGED_AGENTS:
        store.set_queued(agent_id, "Queued — starting…")

    asyncio.create_task(
        _run_agent_scrape(agent_id, user.user_id),
        name=f"agent-run:{user.user_id}:{agent_id}",
    )

    logger.info(
        "[agents/run] Task created — user=%s agent=%s timeout=%.0f s",
        user.user_id, agent_id, _PIPELINE_TIMEOUT_S,
    )
    return {"agent_id": agent_id, "state": "queued", "triggered": True}
