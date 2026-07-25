"""
dev_run_flush.py — one-shot dev utility

Clears all stale JD text and score state for a target user, then runs the full
s2 enrichment pipeline (hydrate → LLM score) against the newly emptied rows.

Usage:
    cd /Users/ronmorim/Projects/JobApply_Venture
    venv/bin/python dev_run_flush.py

Remove this file when no longer needed.
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

# ── Path setup ────────────────────────────────────────────────────────────────
# Must run from the project root so 'backend', 'models', etc. resolve correctly.
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

# ── Load .env before any backend imports touch os.getenv ─────────────────────
_env_path = ROOT / "backend" / ".env"
if _env_path.exists():
    with open(_env_path) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _, _v = _line.partition("=")
                os.environ.setdefault(_k.strip(), _v.strip())

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("dev_flush")

# ── Target user ───────────────────────────────────────────────────────────────
USER_ID = "e2472fa3-db25-4e53-9d0b-2aed67bcfe0e"


async def main() -> None:
    from backend.repositories import job_repository as job_store
    from backend.services import feed_service

    # ── Phase 1: Flush ────────────────────────────────────────────────────────
    all_jobs = job_store.get_feed(user_id=USER_ID)
    total = len(all_jobs)
    logger.info("Phase 1 — flushing %d jobs for user %s", total, USER_ID)

    for i, job in enumerate(all_jobs, 1):
        job_store.reset_job_for_enrichment(job.job_id)   # match_score=0, why_ron=None
        job_store.update_jd_text(job.job_id, "")          # empty → _is_thin() → True
        if i % 50 == 0 or i == total:
            logger.info("  flushed %d/%d", i, total)

    logger.info("Phase 1 complete — %d jobs cleared.\n", total)

    # ── Phase 2: Hydrate + LLM enrich ────────────────────────────────────────
    logger.info("Phase 2 — running refresh_user_scores (hydrate → LLM score) …")
    enriched = await feed_service.refresh_user_scores(USER_ID)
    logger.info("Phase 2 complete — %d jobs enriched.\n", enriched)

    # ── Summary ───────────────────────────────────────────────────────────────
    logger.info("═" * 60)
    logger.info("DONE  flushed=%d  enriched=%d  user=%s", total, enriched, USER_ID)
    logger.info("═" * 60)


if __name__ == "__main__":
    asyncio.run(main())
