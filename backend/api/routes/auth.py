"""
Auth utility routes.

POST /api/auth/migrate-legacy-data
    One-time migration: reassigns all SQLite rows and the on-disk profile file
    that were created under user_id='default' (the legacy single-user mode) to
    the calling user's real Supabase user_id.

    Safety rules
    ────────────
    1. Idempotent — if the calling user already owns rows in any table the
       endpoint returns {status: "already_done"} without touching the database.
    2. Exclusive — only rows owned by the literal string 'default' are moved;
       rows belonging to any other real user_id are never touched.
    3. File copy — if data/master_profile.json exists it is copied (not moved)
       to data/users/{user_id}/profile.json.  The legacy file is left in place
       so a server restart doesn't break anything before the next deploy.
    4. Counts — returns the number of rows migrated per table so the frontend
       can decide whether a reload is worthwhile.
"""
from __future__ import annotations

import logging
import shutil
from pathlib import Path

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session as DBSession

from backend.api.deps import CurrentUser, get_current_user, require_admin, standard_rate_limit
from backend.core.database import ENGINE
from backend.models.profile import MasterProfileRow
from backend.repositories import application_repository
from backend.repositories import evidence_repository
from backend.repositories import job_repository
from backend.repositories import profile_entity_repository
from backend.repositories import profile_interview_repository
from backend.repositories import recruiter_reply_draft_repository
from backend.services.active_user import set_active_user_id

logger = logging.getLogger(__name__)
router = APIRouter(dependencies=[Depends(standard_rate_limit)])

# Paths used by the legacy single-user profile store
_PROJECT_ROOT   = Path(__file__).resolve().parents[3]   # repo root
_LEGACY_PROFILE = _PROJECT_ROOT / "backend" / "data" / "master_profile.json"
_USERS_DIR      = _PROJECT_ROOT / "backend" / "data" / "users"


# ══════════════════════════════════════════════════════════════════════════════
# POST /api/auth/sync-user — provider-agnostic identity sync & account linking
# ══════════════════════════════════════════════════════════════════════════════
#
# Why this exists
# ───────────────
# Supabase links a Google OAuth sign-in to an existing email/password user
# automatically ONLY when automatic identity linking applies (same verified
# email). When it instead mints a NEW auth user (a different JWT `sub`), all
# local rows keyed by the old user_id become invisible to the person who owns
# them — they look like a brand-new user.
#
# This endpoint closes that gap on our side. Called by the frontend right
# after every login:
#   1. Upserts the caller's master_profiles row and records their VERIFIED
#      email (lower-cased) from the JWT — never from the request body.
#   2. If the caller owns no data yet but a master_profiles row with the SAME
#      email exists under a DIFFERENT user_id, re-links every table's rows
#      (jobs, applications, interviews, profile entities, evidence, reply
#      drafts) and the on-disk profile file to the caller's user_id.
#
# Security
# ────────
# • The email used for matching comes exclusively from the verified Supabase
#   JWT (get_current_user) — a caller can never supply an arbitrary email to
#   steal another account's data.
# • Standard rate limit applies at the router level.
# • Idempotent: once linked (or when nothing matches), subsequent calls only
#   refresh the email field.

class SyncUserResult(BaseModel):
    status:        str    # "ok" | "linked" | "created"
    # True when the user's master profile already holds real data (CV imported
    # or onboarding finished). The frontend uses this to backfill the
    # profile_completed flag in Supabase user metadata for accounts created
    # before Phase 8.
    profile_completed: bool = False
    linked_from:   str = ""
    jobs:          int = 0
    applications:  int = 0
    interviews:    int = 0
    entities:      int = 0
    evidence:      int = 0
    reply_drafts:  int = 0
    profile_file:  bool = False


def _profile_is_completed(row: "MasterProfileRow | None") -> bool:
    """True when the master profile holds real data (CV imported or onboarded)."""
    if row is None:
        return False
    mp = row.master_profile or {}
    return bool(mp.get("cv_data")) or row.onboarding_status in ("complete", "completed")


def _relink_rows(db: DBSession, old_uid: str, new_uid: str) -> dict:
    """Re-point every user-owned table from old_uid to new_uid."""
    return {
        "jobs":         job_repository.reassign_user(old_uid, new_uid, db),
        "applications": application_repository.reassign_user(old_uid, new_uid, db),
        "interviews":   profile_interview_repository.reassign_user(old_uid, new_uid, db),
        "entities":     profile_entity_repository.reassign_user(old_uid, new_uid, db),
        "evidence":     evidence_repository.reassign_user(old_uid, new_uid, db),
        "reply_drafts": recruiter_reply_draft_repository.reassign_user(old_uid, new_uid, db),
    }


@router.post("/sync-user", response_model=SyncUserResult)
async def sync_user(user: CurrentUser = Depends(get_current_user)) -> SyncUserResult:
    """
    Ensure a master_profiles row exists for the caller (any auth provider) and
    link data owned by a previous identity with the same verified email.
    """
    uid   = user.user_id
    email = (user.email or "").strip().lower()

    with DBSession(ENGINE) as db:
        own_row = db.get(MasterProfileRow, uid)

        # ── Account linking: same verified email, different user_id ──────────
        # Only link INTO a blank identity: either no row yet, or a barebones
        # row a previous sync call created. A caller who already accumulated
        # their own profile data is never overwritten by an email match.
        own_is_blank = own_row is None or (
            not (own_row.master_profile or {})
            and own_row.onboarding_status == "incomplete"
        )
        legacy_row = None
        if email and own_is_blank:
            legacy_row = (
                db.query(MasterProfileRow)
                .filter(
                    MasterProfileRow.email == email,
                    MasterProfileRow.user_id != uid,
                )
                .order_by(MasterProfileRow.updated_at.desc())
                .first()
            )

        if legacy_row is not None:
            old_uid = legacy_row.user_id
            counts  = _relink_rows(db, old_uid, uid)

            # Adopt the old master profile under the new user_id (drop the
            # blank placeholder row first to avoid a primary-key collision).
            if own_row is not None:
                db.delete(own_row)
                db.flush()
            legacy_row.user_id = uid
            legacy_row.email   = email
            db.commit()

            # Move the on-disk profile file to the new identity's directory.
            profile_moved = False
            old_dir = _USERS_DIR / old_uid / "profile.json"
            new_dir = _USERS_DIR / uid / "profile.json"
            if old_dir.exists() and not new_dir.exists():
                try:
                    new_dir.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(old_dir, new_dir)
                    profile_moved = True
                except Exception as exc:
                    logger.warning("[auth/sync] profile file copy failed: %s", exc)

            set_active_user_id(uid)
            logger.info(
                "[auth/sync] LINKED %s → %s (email=%s): %s",
                old_uid, uid, email, counts,
            )
            return SyncUserResult(
                status            = "linked",
                profile_completed = _profile_is_completed(legacy_row),
                linked_from       = old_uid,
                profile_file      = profile_moved,
                **counts,
            )

        # ── No linking needed: upsert the caller's own row ────────────────────
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()

        # Seed master_profile["personal"]["name"] from the verified JWT's
        # user_metadata (Supabase full_name/name claim — see auth_utils.
        # extract_identity) — never overwrites a name the user has already
        # set some other way (e.g. via a future profile-edit flow).
        name = (user.name or "").strip()

        if own_row is None:
            initial_profile = {"personal": {"name": name}} if name else {}
            db.add(MasterProfileRow(
                user_id           = uid,
                email             = email or None,
                onboarding_status = "incomplete",
                master_profile    = initial_profile,
                created_at        = now,
                updated_at        = now,
            ))
            db.commit()
            logger.info("[auth/sync] created master_profiles row for user=%s", uid)
            return SyncUserResult(status="created")

        changed = False
        if email and own_row.email != email:
            own_row.email = email
            changed = True
        if name and not ((own_row.master_profile or {}).get("personal") or {}).get("name"):
            mp = dict(own_row.master_profile or {})
            mp["personal"] = {**mp.get("personal", {}), "name": name}
            own_row.master_profile = mp
            changed = True
        if changed:
            own_row.updated_at = now
            db.commit()
        return SyncUserResult(status="ok", profile_completed=_profile_is_completed(own_row))


# ── Response model ────────────────────────────────────────────────────────────

class MigrationResult(BaseModel):
    status:         str   # "ok" | "already_done" | "nothing_to_migrate"
    jobs:           int = 0
    applications:   int = 0
    interviews:     int = 0
    profile_file:   bool = False
    message:        str = ""


# ── Route ─────────────────────────────────────────────────────────────────────

@router.post("/migrate-legacy-data", response_model=MigrationResult)
async def migrate_legacy_data(
    user: CurrentUser = Depends(require_admin),
) -> MigrationResult:
    """
    Reassign all 'default' user_id rows in every table to the authenticated
    caller's real user_id.  Safe to call multiple times — returns immediately
    if the user already has data or there is nothing to migrate.
    """
    uid = user.user_id

    with DBSession(ENGINE) as db:
        # ── Guard 1: already migrated ────────────────────────────────────────
        # If this user already owns rows in ANY table their data is present and
        # the migration was already performed (or they registered fresh after
        # the multi-tenant rollout).  Don't touch anything.
        already_has_jobs   = job_repository.count_for_user(uid, session=db)
        already_has_apps   = application_repository.count_for_user(uid, session=db)
        already_has_ivws   = profile_interview_repository.count_for_user(uid, session=db)

        if already_has_jobs or already_has_apps or already_has_ivws:
            logger.info(
                "[auth/migrate] user=%s already owns data — skipping "
                "(jobs=%d apps=%d interviews=%d)",
                uid, already_has_jobs, already_has_apps, already_has_ivws,
            )
            # Even on the fast-path: register this user so the next discovery
            # cycle writes new jobs to their feed, not to 'default'.
            set_active_user_id(uid)
            return MigrationResult(
                status  = "already_done",
                message = "User already owns data; no migration needed.",
            )

        # ── Guard 2: nothing to migrate ───────────────────────────────────────
        legacy_jobs  = job_repository.count_for_user("default", session=db)
        legacy_apps  = application_repository.count_for_user("default", session=db)
        legacy_ivws  = profile_interview_repository.count_for_user("default", session=db)

        if not (legacy_jobs or legacy_apps or legacy_ivws):
            logger.info("[auth/migrate] user=%s — no legacy data to migrate", uid)
            # New user: register them so future scrapes write to their feed.
            set_active_user_id(uid)
            return MigrationResult(
                status  = "nothing_to_migrate",
                message = "No legacy data found under user_id='default'.",
            )

        # ── Migrate ───────────────────────────────────────────────────────────
        migrated_jobs = job_repository.reassign_user("default", uid, db)
        migrated_apps = application_repository.reassign_user("default", uid, db)
        migrated_ivws = profile_interview_repository.reassign_user("default", uid, db)
        db.commit()

        logger.info(
            "[auth/migrate] Migrated to user=%s — jobs=%d apps=%d interviews=%d",
            uid, migrated_jobs, migrated_apps, migrated_ivws,
        )

    # ── Register as active user so next scrape cycle writes to this feed ──────
    set_active_user_id(uid)

    # ── Profile file ──────────────────────────────────────────────────────────
    profile_copied = False
    if _LEGACY_PROFILE.exists():
        dest = _USERS_DIR / uid / "profile.json"
        if not dest.exists():
            try:
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(_LEGACY_PROFILE, dest)
                profile_copied = True
                logger.info("[auth/migrate] Copied master_profile.json → %s", dest)
            except Exception as exc:
                logger.warning("[auth/migrate] Profile file copy failed: %s", exc)

    return MigrationResult(
        status        = "ok",
        jobs          = migrated_jobs,
        applications  = migrated_apps,
        interviews    = migrated_ivws,
        profile_file  = profile_copied,
        message       = (
            f"Migrated {migrated_jobs} job(s), {migrated_apps} application(s), "
            f"{migrated_ivws} interview session(s)"
            + (" and profile file" if profile_copied else "")
            + f" to user {uid}."
        ),
    )
