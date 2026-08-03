"""
Auth utility routes.

POST /api/auth/sync-user
    Called on every login. Links rows across a re-minted Supabase auth
    identity for the same verified email (_relink_rows), or upserts the
    caller's own master_profiles row. See sync_user()'s docstring.

The legacy single-user ('default') migration endpoint has been retired —
single-user/pre-auth mode no longer exists, so there is no more 'default'
data to reassign.
"""
from __future__ import annotations

import logging
import shutil
from pathlib import Path

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session as DBSession

from backend.api.deps import CurrentUser, get_current_user, standard_rate_limit
from backend.core.database import ENGINE
from backend.repositories import application_repository
from backend.repositories import evidence_repository
from backend.repositories import job_repository
from backend.repositories import profile_entity_repository
from backend.repositories import profile_interview_repository
from backend.repositories import profile_repository
from backend.repositories import recruiter_reply_draft_repository

logger = logging.getLogger(__name__)
router = APIRouter(dependencies=[Depends(standard_rate_limit)])

# Paths used by the legacy single-user profile store
_PROJECT_ROOT   = Path(__file__).resolve().parents[3]   # repo root
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


def _profile_is_completed(row: "profile_repository.ProfileHandle | None") -> bool:
    """True when the profile holds real data (CV imported or onboarded)."""
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
    Ensure a profiles row exists for the caller (any auth provider) and link
    data owned by a previous identity with the same verified email.
    """
    from datetime import datetime, timezone

    uid   = user.user_id
    email = (user.email or "").strip().lower()
    now   = datetime.now(timezone.utc).isoformat()

    with DBSession(ENGINE) as db:
        own_row = profile_repository.get_in_session(db, uid)

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
            legacy_row = profile_repository.get_by_email(db, email, exclude_user_id=uid)

        if legacy_row is not None:
            old_uid = legacy_row.user_id
            counts  = _relink_rows(db, old_uid, uid)

            # profiles.id is a real, immutable FK to auth.users(id) — unlike
            # the old free-string MasterProfileRow PK it can't be reassigned
            # in place. Ensure the caller's own row exists, merge the legacy
            # identity's relational data into it field-by-field, and drop the
            # old row (see profile_repository.reassign_user's docstring).
            profile_repository.get_or_create(db, uid, now=now)
            profile_repository.reassign_user(db, old_uid, uid)
            db.execute(
                text("UPDATE public.profiles SET email = :email, updated_at = now() WHERE id = CAST(:uid AS uuid)"),
                {"email": email, "uid": uid},
            )
            db.commit()
            merged = profile_repository.get_in_session(db, uid)

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

            logger.info(
                "[auth/sync] LINKED %s → %s (email=%s): %s",
                old_uid, uid, email, counts,
            )
            return SyncUserResult(
                status            = "linked",
                profile_completed = _profile_is_completed(merged),
                linked_from       = old_uid,
                profile_file      = profile_moved,
                **counts,
            )

        # ── No linking needed: upsert the caller's own row ────────────────────
        # Seed master_profile["personal"]["name"] from the verified JWT's
        # user_metadata (Supabase full_name/name claim — see auth_utils.
        # extract_identity) — never overwrites a name the user has already
        # set some other way (e.g. via a future profile-edit flow).
        name = (user.name or "").strip()

        if own_row is None:
            row, _created = profile_repository.get_or_create(db, uid, now=now)
            row.email = email or None
            if name:
                row.master_profile = {"personal": {"name": name}}
            profile_repository.save(db, row)
            db.commit()
            logger.info("[auth/sync] created profiles row for user=%s", uid)
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
            profile_repository.save(db, own_row)
            db.commit()
        return SyncUserResult(status="ok", profile_completed=_profile_is_completed(own_row))

