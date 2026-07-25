"""
Tenant registry — the multi-tenant replacement for the single-slot active_user.

Background pipelines (discovery, enrichment) must run once PER USER, each cycle
strictly inside that user's context. This module answers exactly one question:
"which user_ids should the pipeline fan out over right now?"

Selection rule:
  • Every master_profiles row with onboarding_status='complete' — these users
    have unlocked the matching/tailoring pipeline (see ariel_tools
    finalize_onboarding, the sole writer of that flag).
  • Plus the 'default' legacy tenant, ONLY while un-migrated legacy job rows
    still exist (pre-auth local development / pre-migration state). Once
    /api/auth/migrate-legacy-data has reassigned them, 'default' drops out
    automatically.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def list_pipeline_user_ids() -> list[str]:
    """
    Return the user_ids the background pipeline should fan out over.

    Never raises — on any DB error it falls back to ['default'] so the
    pipeline keeps functioning in a broken-config dev environment.
    """
    from sqlalchemy import text as _text
    from backend.core.database import ENGINE

    try:
        with ENGINE.connect() as conn:
            rows = conn.execute(_text(
                "SELECT user_id FROM master_profiles WHERE onboarding_status = 'complete'"
            )).fetchall()
            user_ids = [str(r[0]) for r in rows if str(r[0]).strip()]

            has_legacy = conn.execute(_text(
                "SELECT EXISTS(SELECT 1 FROM jobs WHERE user_id = 'default')"
            )).scalar()
            if has_legacy and "default" not in user_ids:
                user_ids.append("default")

        return user_ids or ["default"]
    except Exception as exc:
        logger.warning("[tenant_registry] could not list users (%s) — falling back to ['default']", exc)
        return ["default"]
