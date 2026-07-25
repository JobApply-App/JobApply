"""
sync_trust_scores.py
=====================
One-off backfill: sync every user's existing master_profile JSON
(experience + skills) into the Active Confidence Matrix via
ProfileUpdateService.ingest_self_assertion().

Why this is needed
-------------------
Ariel's update_experience/update_skills tools call
ProfileUpdateService.ingest_self_assertion() as a side effect, but only at
the moment the user asserts a fact in chat. Users whose experience/skills
were already present in master_profile *before* that sync path existed (or
whose data the agent declined to re-touch because it looked unchanged)
never got a corresponding profile_entities / evidence_records row, so their
Confidence Score stayed at 0 despite having a populated profile.

Safety
------
This script only *adds* self_assertion evidence rows (ingest_self_assertion
is append-only and upserts entities) — it never deletes or overwrites
existing data. It is idempotent at the entity level (upsert by normalized
name) but NOT idempotent at the evidence level: re-running it will append a
duplicate self_assertion evidence row per item. Run once.

Usage
-----
    python3 -m backend.scripts.sync_trust_scores
"""
from __future__ import annotations

import logging

from sqlalchemy import text

from backend.core.database import ENGINE
from backend.services.profile_update_service import ProfileUpdateService

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def _experience_name_and_content(item: dict) -> tuple[str, str]:
    role = (item.get("role") or "").strip()
    company = (item.get("company") or "").strip()
    if role and company:
        name = f"{role} at {company}"
    else:
        name = role or company or "Unknown role"
    bullets = item.get("bullets") or []
    raw_content = " ".join(str(b) for b in bullets)
    return name, raw_content


def backfill_trust_scores() -> None:
    service = ProfileUpdateService(ENGINE)

    with ENGINE.connect() as conn:
        users = conn.execute(
            text("SELECT user_id, master_profile FROM master_profiles")
        ).fetchall()

    logger.info("sync_trust_scores: found %d user(s) to process", len(users))

    total_experience = 0
    total_skills = 0
    failed_users = 0

    for user_id, master_profile in users:
        profile = master_profile or {}
        if isinstance(profile, str):
            import json
            try:
                profile = json.loads(profile)
            except (TypeError, ValueError):
                profile = {}

        try:
            for item in profile.get("experience") or []:
                name, raw_content = _experience_name_and_content(item)
                service.ingest_self_assertion(user_id, "experience", name, raw_content)
                total_experience += 1

            for skill in profile.get("skills") or []:
                skill_name = str(skill).strip()
                if not skill_name:
                    continue
                service.ingest_self_assertion(user_id, "skill", skill_name, "")
                total_skills += 1

        except Exception:
            failed_users += 1
            logger.exception("sync_trust_scores: failed to process user=%s", user_id)

    logger.info(
        "sync_trust_scores: complete — %d experience item(s), %d skill(s) ingested "
        "across %d user(s), %d user(s) failed",
        total_experience, total_skills, len(users), failed_users,
    )


if __name__ == "__main__":
    backfill_trust_scores()
