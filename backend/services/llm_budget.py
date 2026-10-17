"""
Per-user daily budget for BACKGROUND LLM work, and the provider-outage gate.

Why this exists
----------------
The enrichment loop (every 30s) and the discovery loop (every 5 min) used to
send every unscored job to the LLM with no ceiling. That was harmless while
the pipeline served one user. The day it opened to ten, the all_jobs bridge
added ~2,400 matches and the loops tried to score all of them — ~4 LLM calls
each — until the Gemini quota and the Anthropic credit balance were both
gone. From then on every AI feature failed for every user, including the
ones a user is actively waiting on (Ariel, CV upload).

Two controls:
- A daily per-user budget (config.ENRICH_DAILY_BUDGET_PER_USER) on jobs the
  background loops may send to the LLM. The counter lives in the kv table so
  a deploy/restart does not reset it.
- An outage gate (llm_client.providers_unavailable): while both providers are
  failing for billing/quota reasons, background loops skip the LLM entirely
  instead of retrying every job every cycle, and do not count those failures
  against the job (which would permanently retire it after 3).

User-initiated calls are deliberately not budgeted here.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def _key(user_id: str) -> str:
    return f"llm_enrich_budget:{user_id}:{datetime.now(timezone.utc).date().isoformat()}"


def _used(user_id: str) -> int:
    from backend.repositories import kv_repository
    entry = kv_repository.get(_key(user_id))
    try:
        return int(entry.value) if entry else 0
    except (TypeError, ValueError):
        return 0


def remaining(user_id: str) -> int:
    """Jobs this user may still send to the LLM from background loops today."""
    from backend.config import ENRICH_DAILY_BUDGET_PER_USER
    return max(0, ENRICH_DAILY_BUDGET_PER_USER - _used(user_id))


def consume(user_id: str) -> bool:
    """
    Reserve one job's worth of budget. Returns False (and reserves nothing)
    when today's budget is spent. Called BEFORE the LLM work, because the
    cost is incurred by the attempt, not by its success.
    """
    from backend.config import ENRICH_DAILY_BUDGET_PER_USER
    from backend.repositories import kv_repository
    used = _used(user_id)
    if used >= ENRICH_DAILY_BUDGET_PER_USER:
        return False
    kv_repository.upsert(_key(user_id), str(used + 1))
    return True


def background_llm_allowed(user_id: str) -> bool:
    """Cheap pre-check for loops: providers up and budget left."""
    from backend.services.llm_client import providers_unavailable
    if providers_unavailable():
        return False
    return remaining(user_id) > 0
