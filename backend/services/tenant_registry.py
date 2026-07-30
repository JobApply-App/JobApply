"""
Tenant registry — the multi-tenant replacement for the single-slot active_user.

Background pipelines (discovery, enrichment) must run once PER USER, each cycle
strictly inside that user's context. This module answers exactly one question:
"which user_ids should the pipeline fan out over right now?"

Selection rule: every master_profiles row with onboarding_status='complete' —
these users have unlocked the matching/tailoring pipeline (see ariel_tools
finalize_onboarding, the sole writer of that flag). No 'default'/legacy
fallback: single-user/pre-auth mode has been retired, so an environment with
no onboarded users simply runs the pipeline for nobody until one exists.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def list_pipeline_user_ids() -> list[str]:
    """
    Return the user_ids the background pipeline should fan out over.

    Never raises — on any DB error it falls back to an empty list so a
    broken-config environment doesn't crash the pipeline, it just runs it
    for nobody until the config is fixed.
    """
    from sqlalchemy import text as _text
    from backend.core.database import ENGINE

    try:
        with ENGINE.connect() as conn:
            rows = conn.execute(_text(
                "SELECT user_id FROM master_profiles WHERE onboarding_status = 'complete'"
            )).fetchall()
            return [str(r[0]) for r in rows if str(r[0]).strip()]
    except Exception as exc:
        logger.warning("[tenant_registry] could not list users (%s) — falling back to []", exc)
        return []
