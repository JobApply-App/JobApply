"""
seed_ron_entities.py — Load Ron's profile_entities + evidence_records from seed JSON.

Usage (from project root):
    python -m backend.scripts.seed_ron_entities [--user-id <id>] [--dry-run]

If --user-id is omitted, it reads AUTH_USER_ID from .env or falls back to
the first user_id found in the profile_entities table.  If the table is
empty, the script aborts with instructions.

Safe to re-run: existing entities are upserted (updated), evidence is only
inserted when the evidence_id does not already exist (append-only).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

# Allow running as `python -m backend.scripts.seed_ron_entities` from project root
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from dotenv import load_dotenv
from sqlalchemy import text

from backend.core.database import ENGINE

load_dotenv(Path(__file__).resolve().parents[2] / "backend" / ".env")
load_dotenv(Path(__file__).resolve().parents[2] / ".env")

SEED_FILE = Path(__file__).resolve().parent.parent / "data" / "ron_entities_seed.json"


def _resolve_user_id(override: str | None) -> str:
    if override:
        return override
    uid = os.getenv("AUTH_USER_ID") or os.getenv("SEED_USER_ID")
    if uid:
        return uid
    with ENGINE.connect() as conn:
        row = conn.execute(text("SELECT user_id FROM profile_entities LIMIT 1")).fetchone()
        if row:
            return row[0]
    sys.exit(
        "Cannot determine user_id. Pass --user-id <id>, or set AUTH_USER_ID in .env, "
        "or ensure at least one row exists in profile_entities."
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def seed(user_id: str, dry_run: bool) -> None:
    data = json.loads(SEED_FILE.read_text())
    entities = data["entities"]
    seed_entity_ids = [e["entity_id"] for e in entities]

    upserted = 0
    migrated = 0
    evidence_inserted = 0

    with ENGINE.connect() as conn:
        # ── Pre-flight: show what's currently in the DB for this user ──────────
        current = conn.execute(
            text("SELECT user_id, COUNT(*) FROM profile_entities GROUP BY user_id")
        ).fetchall()
        print("Current profile_entities counts before seed:")
        for row in current:
            marker = " ← TARGET" if row[0] == user_id else ""
            print(f"  {row[0]}  →  {row[1]} rows{marker}")

        # ── Migrate any seed entities owned by a foreign user_id ───────────────
        # This fixes the case where entity_ids were previously inserted under a
        # different UUID (e.g. the stale 'fede' context) and the upsert loop
        # would silently skip them thinking they already "exist".
        if not dry_run:
            placeholders = ",".join(f":eid{i}" for i in range(len(seed_entity_ids)))
            params = {f"eid{i}": eid for i, eid in enumerate(seed_entity_ids)}
            params["uid"] = user_id
            migrated_count = conn.execute(
                text(f"""
                    UPDATE profile_entities
                    SET user_id = :uid
                    WHERE entity_id IN ({placeholders})
                      AND user_id != :uid
                """),
                params,
            ).rowcount
            if migrated_count:
                migrated = migrated_count
                print(f"Migrated {migrated_count} entity row(s) to user_id={user_id} "
                      f"(previously owned by a different UUID)")
            conn.commit()

        # ── Upsert loop — scoped to this user_id ──────────────────────────────
        for ent in entities:
            entity_id = ent["entity_id"]
            now = _now()

            # Existence check is now user_id-scoped so cross-user rows don't
            # shadow inserts for the target user.
            existing = conn.execute(
                text("SELECT entity_id FROM profile_entities "
                     "WHERE entity_id = :eid AND user_id = :uid"),
                {"eid": entity_id, "uid": user_id},
            ).fetchone()

            if not dry_run:
                if existing:
                    # Update metadata — preserve confidence_score / verification_status
                    # that have been built up through live probe sessions.
                    conn.execute(
                        text("""
                            UPDATE profile_entities
                            SET name            = :name,
                                entity_type     = :entity_type,
                                normalized_name = :normalized_name,
                                updated_at      = :updated_at
                            WHERE entity_id = :entity_id AND user_id = :user_id
                        """),
                        {
                            "name":             ent["name"],
                            "entity_type":      ent["entity_type"],
                            "normalized_name":  ent["normalized_name"],
                            "updated_at":       now,
                            "entity_id":        entity_id,
                            "user_id":          user_id,
                        },
                    )
                else:
                    conn.execute(
                        text("""
                            INSERT INTO profile_entities
                              (entity_id, user_id, entity_type, name, normalized_name,
                               confidence_score, verification_status,
                               manual_review_required, created_at, updated_at)
                            VALUES
                              (:entity_id, :user_id, :entity_type, :name, :normalized_name,
                               0.0, 'unverified', 0, :created_at, :updated_at)
                        """),
                        {
                            "entity_id":        entity_id,
                            "user_id":          user_id,
                            "entity_type":      ent["entity_type"],
                            "name":             ent["name"],
                            "normalized_name":  ent["normalized_name"],
                            "created_at":       now,
                            "updated_at":       now,
                        },
                    )
            upserted += 1

            for ev in ent.get("evidence", []):
                ev_id = f"ev_{entity_id}_{ev['source_type']}"
                existing_ev = conn.execute(
                    text("SELECT evidence_id FROM evidence_records WHERE evidence_id = :eid"),
                    {"eid": ev_id},
                ).fetchone()

                if not existing_ev and not dry_run:
                    conn.execute(
                        text("""
                            INSERT INTO evidence_records
                              (evidence_id, entity_id, user_id, source_type,
                               base_weight, raw_content, verified_at)
                            VALUES
                              (:evidence_id, :entity_id, :user_id, :source_type,
                               :base_weight, :raw_content, :verified_at)
                        """),
                        {
                            "evidence_id":  ev_id,
                            "entity_id":    entity_id,
                            "user_id":      user_id,
                            "source_type":  ev["source_type"],
                            "base_weight":  ev["base_weight"],
                            "raw_content":  ev.get("raw_content", ""),
                            "verified_at":  ev["verified_at"],
                        },
                    )
                    evidence_inserted += 1
                elif not existing_ev:
                    evidence_inserted += 1  # would insert in non-dry run

        if not dry_run:
            conn.commit()

        # ── Post-seed verification: confirm row count for this user ───────────
        final_count = conn.execute(
            text("SELECT COUNT(*) FROM profile_entities WHERE user_id = :uid"),
            {"uid": user_id},
        ).scalar()

    action = "[DRY RUN] Would insert/update" if dry_run else "Seeded"
    print(f"{action}: {upserted} entities, {evidence_inserted} evidence records → user_id={user_id}")
    if not dry_run:
        status = "✓ CORRECT" if final_count == len(entities) else "✗ MISMATCH"
        print(f"Post-seed row count for {user_id}: {final_count}/{len(entities)}  {status}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed Ron's profile entities into the DB.")
    parser.add_argument("--user-id", default=None, help="Target user_id (uuid string)")
    parser.add_argument("--dry-run", action="store_true", help="Print what would happen without writing")
    args = parser.parse_args()

    user_id = _resolve_user_id(args.user_id)
    print(f"Target user_id: {user_id}")
    seed(user_id, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
