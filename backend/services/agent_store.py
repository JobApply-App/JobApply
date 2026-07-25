"""
Per-user in-memory agent status store.

Architecture
------------
The four pipeline agents (Scraper, Sourcing Specialist, Content Strategist,
Quality Guard) represent a single shared background pipeline — not independent
per-user processes.  However, every authenticated user deserves their own
initialised view of those agents so the UI never shows empty/dead cards.

  _USER_STORES : dict[user_id, dict[agent_id, AgentStatus]]

When a user first hits GET /api/agents/ their personal store is seeded from
the global default templates (all four agents, state=idle).  Background tasks
call the module-level write helpers (set_active, set_idle, etc.) which update
ALL seeded user stores simultaneously, so every user sees the same running
state in real time.

In production: replace the in-memory dicts with Redis hashes or a DB-backed
table keyed by (user_id, agent_id).
"""
from __future__ import annotations

import logging
from copy import deepcopy
from typing import Any, Optional

from backend.schemas.agent import AgentStatus, AgentStats

logger = logging.getLogger(__name__)

# Maximum number of spark values kept per agent
_SPARK_MAX = 10

# ── Default agent templates ────────────────────────────────────────────────────

def _build_defaults() -> dict[str, AgentStatus]:
    """Return a fresh set of four agents in their initial idle state."""
    return {
        "s1": AgentStatus(
            id="s1",
            name="Scraper",
            role="Fetches raw job data from LinkedIn, Drushim, AllJobs, and other boards",
            state="idle",
            stats=AgentStats(today=0, queue=0, spark=[2, 3, 5, 4, 6, 5, 7]),
        ),
        "s2": AgentStatus(
            id="s2",
            name="Sourcing Specialist",
            role="Performs deep gap analysis: maps job requirements to USER_PROFILE facts",
            state="idle",
            stats=AgentStats(today=0, queue=0, spark=[1, 2, 3, 2, 4, 3, 5]),
        ),
        "s3": AgentStatus(
            id="s3",
            name="Content Strategist",
            role="Generates 'Why Ron?' recruiter brief grounded in USER_PROFILE evidence",
            state="idle",
            stats=AgentStats(today=0, queue=0, spark=[1, 1, 2, 2, 3, 2, 3]),
        ),
        "s4": AgentStatus(
            id="s4",
            name="Quality Guard",
            role="Truth Guard: verifies every claim is grounded in USER_PROFILE — no invented facts",
            state="idle",
            stats=AgentStats(today=0, queue=0, spark=[1, 1, 1, 2, 2, 1, 2]),
        ),
    }


# ── Per-user registry ─────────────────────────────────────────────────────────
#
# Outer key = user_id (Supabase UUID or "default" for legacy/background tasks)
# Inner key = agent_id ("s1" … "s4")

_USER_STORES: dict[str, dict[str, AgentStatus]] = {}


def ensure_user_seeded(user_id: str) -> None:
    """
    Initialise a personal agent registry for *user_id* if one does not exist yet.

    Idempotent — safe to call on every request.  The very first call creates
    the four default-idle agents; subsequent calls are a no-op.
    """
    if user_id not in _USER_STORES:
        _USER_STORES[user_id] = _build_defaults()
        logger.info("[agent_store] Seeded agent rows for user_id=%r", user_id)


# ── Read ──────────────────────────────────────────────────────────────────────

def get_for_user(user_id: str) -> list[AgentStatus]:
    """
    Return all four agents for *user_id*, seeding defaults on first access.
    The returned list order matches the agent IDs (s1 → s4).
    """
    ensure_user_seeded(user_id)
    return list(_USER_STORES[user_id].values())


def get_by_id_for_user(user_id: str, agent_id: str) -> Optional[AgentStatus]:
    """Return a single agent for *user_id*, or None if agent_id is unknown."""
    ensure_user_seeded(user_id)
    return _USER_STORES[user_id].get(agent_id)


# ── Backward-compat aliases (used by the LangGraph orchestrator) ──────────────

def get_all() -> list[AgentStatus]:
    """Return agents for the legacy 'default' scope (LangGraph orchestrator)."""
    return get_for_user("default")


def get_by_id(agent_id: str) -> Optional[AgentStatus]:
    """Return a single agent from the legacy 'default' scope."""
    return get_by_id_for_user("default", agent_id)


# ── Write helpers ─────────────────────────────────────────────────────────────
#
# All write operations apply to EVERY seeded user store so the shared pipeline
# state is reflected consistently for all logged-in users.

def _patch_all(agent_id: str, **kwargs: Any) -> None:
    """Apply keyword-argument updates to *agent_id* in every seeded user store."""
    for uid, store in _USER_STORES.items():
        if agent_id in store:
            store[agent_id] = store[agent_id].model_copy(update=kwargs)


# ── Per-user write helpers (multi-tenant — preferred) ─────────────────────────
#
# A pipeline run for user X must never mutate user Y's agent status. The
# broadcast helpers below (set_active / set_idle / set_queued) survive ONLY
# for the legacy shared background pipeline; per-user pipeline runs must use
# these scoped variants.

def set_active_for_user(user_id: str, agent_id: str, task: str) -> None:
    ensure_user_seeded(user_id)
    store = _USER_STORES[user_id]
    if agent_id in store:
        agent = store[agent_id]
        store[agent_id] = agent.model_copy(update={
            "state":        "active",
            "current_task": task,
            "error_msg":    None,
            "stats":        agent.stats.model_copy(
                update={"queue": max(0, agent.stats.queue - 1)}
            ),
        })


def set_idle_for_user(user_id: str, agent_id: str) -> None:
    ensure_user_seeded(user_id)
    store = _USER_STORES[user_id]
    if agent_id in store:
        agent  = store[agent_id]
        today  = agent.stats.today + 1
        spark  = (agent.stats.spark + [today])[-_SPARK_MAX:]
        store[agent_id] = agent.model_copy(update={
            "state":        "idle",
            "current_task": None,
            "stats":        AgentStats(today=today, queue=agent.stats.queue, spark=spark),
        })


def set_active(agent_id: str, task: str) -> None:
    ensure_user_seeded("default")   # guarantee at least the legacy store exists
    for uid, store in _USER_STORES.items():
        if agent_id in store:
            agent = store[agent_id]
            store[agent_id] = agent.model_copy(update={
                "state":        "active",
                "current_task": task,
                "error_msg":    None,
                "stats":        agent.stats.model_copy(
                    update={"queue": max(0, agent.stats.queue - 1)}
                ),
            })


def set_idle(agent_id: str) -> None:
    ensure_user_seeded("default")
    for uid, store in _USER_STORES.items():
        if agent_id in store:
            agent  = store[agent_id]
            today  = agent.stats.today + 1
            spark  = (agent.stats.spark + [today])[-_SPARK_MAX:]
            store[agent_id] = agent.model_copy(update={
                "state":        "idle",
                "current_task": None,
                "stats":        AgentStats(today=today, queue=agent.stats.queue, spark=spark),
            })


def set_queued(agent_id: str, msg: str) -> None:
    ensure_user_seeded("default")
    for uid, store in _USER_STORES.items():
        if agent_id in store:
            agent = store[agent_id]
            store[agent_id] = agent.model_copy(update={
                "state":     "queued",
                "queue_msg": msg,
                "stats":     agent.stats.model_copy(
                    update={"queue": agent.stats.queue + 1}
                ),
            })


def pipeline_reset(agent_id: str, msg: str) -> None:
    """
    Hard-reset an agent to a clean queued state for a fresh pipeline run.

    Unlike set_queued(), this function explicitly clears EVERY field that
    could carry stale text from a previous run:

        current_task — set by set_active(); survives crashes because the
                       finally block that calls set_idle() may not run on
                       SIGKILL or dev-reload.  If not cleared here, the
                       ghost string reappears the moment the next run calls
                       set_active() and the frontend polls mid-transition.

        error_msg    — left behind by set_error(); would make an agent
                       card flash a previous failure banner while the new
                       run is still in its queued phase.

        queue_msg    — replaced with the caller-supplied initialising
                       message so all four cards show a uniform status.

    stats.queue is set to exactly 1 (not incremented) — there is precisely
    one thing queued: the master pipeline run.  Stacking increments from
    partial prior runs would inflate the counter and confuse the UI.

    Called synchronously in sync_pipeline() before asyncio.create_task(),
    so the in-memory state is clean before the first HTTP response leaves
    the server.  _run_full_pipeline() calls it again at coroutine start as
    a second safety net for any state drift that occurs between the endpoint
    returning and the event loop scheduling the task.
    """
    ensure_user_seeded("default")
    for uid, agents in _USER_STORES.items():
        if agent_id in agents:
            agent = agents[agent_id]
            agents[agent_id] = agent.model_copy(update={
                "state":        "queued",
                "queue_msg":    msg,
                "current_task": None,
                "error_msg":    None,
                "stats":        agent.stats.model_copy(update={"queue": 1}),
            })


def set_error(agent_id: str, msg: str) -> None:
    ensure_user_seeded("default")
    _patch_all(agent_id, state="error", error_msg=msg, current_task=None)


def set_paused(agent_id: str) -> None:
    ensure_user_seeded("default")
    _patch_all(agent_id, state="paused", current_task=None)


def set_resumed(agent_id: str) -> None:
    ensure_user_seeded("default")
    _patch_all(agent_id, state="idle", current_task=None)


def set_paused_for_user(user_id: str, agent_id: str) -> None:
    ensure_user_seeded(user_id)
    store = _USER_STORES[user_id]
    if agent_id in store:
        agent = store[agent_id]
        store[agent_id] = agent.model_copy(update={
            "state":        "paused",
            "current_task": None,
        })


def set_resumed_for_user(user_id: str, agent_id: str) -> None:
    ensure_user_seeded(user_id)
    store = _USER_STORES[user_id]
    if agent_id in store:
        agent = store[agent_id]
        store[agent_id] = agent.model_copy(update={
            "state":        "idle",
            "current_task": None,
        })
