"""
backfill_entity_scores.py

Recomputes confidence_score + verification_status for every profile_entity
that has evidence but still shows confidence_score=0.0 (or any entity,
with --force).

This fixes the gap created when the seed script inserts entities and evidence
but skips the ProfileUpdateService._recompute_and_persist() call.

Usage
-----
    # Dry-run (print what would change, touch nothing)
    venv/bin/python -m backend.scripts.backfill_entity_scores --dry-run

    # Apply for a specific user
    venv/bin/python -m backend.scripts.backfill_entity_scores --user-id e2472fa3-...

    # Apply for all users in the DB
    venv/bin/python -m backend.scripts.backfill_entity_scores

    # Recompute every entity even if score != 0
    venv/bin/python -m backend.scripts.backfill_entity_scores --force
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sqlalchemy import text

from backend.services.confidence_math import (
    EvidenceRow,
    compute_decoupled_score,
    compute_confidence_score,
    verification_status,
)
from backend.core.database import ENGINE

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("backfill")


def _parse_dt(value) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        dt = datetime.fromisoformat(str(value))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return datetime.now(timezone.utc)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def backfill(user_id: Optional[str], dry_run: bool, force: bool) -> None:
    now = _now()

    with ENGINE.connect() as conn:
        # ── 1. Load target entities ───────────────────────────────────────────
        if user_id:
            entity_rows = conn.execute(
                text("""
                    SELECT entity_id, user_id, name, confidence_score
                    FROM   profile_entities
                    WHERE  user_id = :uid
                    ORDER  BY name
                """),
                {"uid": user_id},
            ).fetchall()
        else:
            entity_rows = conn.execute(
                text("""
                    SELECT entity_id, user_id, name, confidence_score
                    FROM   profile_entities
                    ORDER  BY user_id, name
                """)
            ).fetchall()

        logger.info("Loaded %d entities (force=%s, dry_run=%s)", len(entity_rows), force, dry_run)

        updated = skipped = 0

        for (entity_id, uid, name, stored_score) in entity_rows:
            # Skip entities that already have a score unless --force
            if stored_score and stored_score > 0.0 and not force:
                skipped += 1
                continue

            # ── 2. Fetch evidence for this entity ─────────────────────────────
            ev_rows = conn.execute(
                text("""
                    SELECT source_type, base_weight, verified_at, is_ai_assisted
                    FROM   evidence_records
                    WHERE  entity_id = :eid
                      AND  (hard_expires_at IS NULL OR hard_expires_at > :now)
                """),
                {"eid": entity_id, "now": now},
            ).fetchall()

            if not ev_rows:
                logger.debug("  SKIP  %-40s  no evidence", name)
                skipped += 1
                continue

            # ── 3. Build EvidenceRow list and compute ─────────────────────────
            evidence: list[EvidenceRow] = [
                {
                    "source_type":    r[0],
                    "base_weight":    float(r[1]),
                    "verified_at":    _parse_dt(r[2]),
                    "is_ai_assisted": bool(r[3]) if r[3] is not None else False,
                }
                for r in ev_rows
            ]

            dscore     = compute_decoupled_score(evidence)
            new_score  = dscore.final_score
            new_status = verification_status(new_score)

            # Infer skill_tier: Core_Mastery unless ALL positive evidence is ai_assisted
            pos_ev = [e for e in evidence if e["base_weight"] >= 0]
            new_tier = ("System_Orchestration" if pos_ev and all(e["is_ai_assisted"] for e in pos_ev)
                        else "Core_Mastery" if pos_ev else None)

            logger.info(
                "  [DEBUG] Entity %-42s  ev=%d  arch=%.1f  syntax=%.1f"
                "  final=%.1f  vl=%s  tier=%s",
                repr(name),
                len(evidence),
                dscore.architecture_confidence,
                dscore.syntax_confidence,
                new_score,
                dscore.verification_level,
                new_tier,
            )

            if dry_run:
                updated += 1
                continue

            # ── 4. Write back ─────────────────────────────────────────────────
            conn.execute(
                text("""
                    UPDATE profile_entities
                    SET    confidence_score         = :score,
                           verification_status      = :status,
                           skill_tier               = :tier,
                           architecture_confidence  = :arch,
                           syntax_confidence        = :syntax,
                           verification_level       = :vl,
                           last_evidence_at         = :now,
                           updated_at               = :now
                    WHERE  entity_id = :eid
                """),
                {
                    "score":  new_score,
                    "status": new_status,
                    "tier":   new_tier,
                    "arch":   dscore.architecture_confidence,
                    "syntax": dscore.syntax_confidence,
                    "vl":     dscore.verification_level,
                    "now":    now,
                    "eid":    entity_id,
                },
            )
            updated += 1

        if not dry_run:
            conn.commit()

    verb = "Would update" if dry_run else "Updated"
    logger.info("%s %d entities, skipped %d", verb, updated, skipped)


def main() -> None:
    p = argparse.ArgumentParser(description="Back-fill confidence scores from evidence.")
    p.add_argument("--user-id", default=None)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--force",   action="store_true", help="Recompute even when score > 0")
    args = p.parse_args()
    backfill(args.user_id, args.dry_run, args.force)


if __name__ == "__main__":
    main()
