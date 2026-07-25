"""
Per-user profile store — replaces the single global master_profile.json.

Storage layout
--------------
    backend/data/
      users/
        {user_id}/
          profile.json   ← structured master profile (metrics, personal, etc.)

Backward compatibility
----------------------
user_id='default' still falls back to the legacy data/master_profile.json
path so the existing single-user deployment continues to work without any
data migration.  New real users get their own isolated subdirectory from
first write onward.

Public API
----------
    load(user_id)                   -> dict
    save(user_id, profile)          -> None   (atomic)
    get_cached_answer(user_id, qid) -> str | None
    merge_answers(user_id, answers) -> int
    profile_path(user_id)           -> Path
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

# Project root is three levels up from backend/services/user_profile_store.py
_PROJECT_ROOT   = Path(__file__).resolve().parents[2]
_USERS_DIR      = _PROJECT_ROOT / "backend" / "data" / "users"
# Legacy single-user fallback file was never scoped into the backend/data/
# move — it still lives at repo-root data/master_profile.json.
_LEGACY_PROFILE = _PROJECT_ROOT / "data" / "master_profile.json"


# ── Path helpers ──────────────────────────────────────────────────────────────

def profile_path(user_id: str) -> Path:
    """Return the profile.json path for a given user_id."""
    if user_id == "default":
        return _LEGACY_PROFILE
    return _USERS_DIR / user_id / "profile.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def _empty_profile(user_id: str) -> dict:
    """
    Return a fresh profile scaffold.

    For user_id='default', seed personal fields from USER_PROFILE so the
    legacy single-user experience is preserved.  All other users start blank.
    """
    personal: dict = {
        "full_name": "", "email": "", "phone": "",
        "linkedin_url": "", "location": "",
    }

    if user_id == "default":
        try:
            from backend.services.user_profile import USER_PROFILE
            p = USER_PROFILE.get("personal", {})
            personal = {
                "full_name":    p.get("name",     ""),
                "email":        p.get("email",    ""),
                "phone":        p.get("phone",    ""),
                "linkedin_url": p.get("linkedin", ""),
                "location":     p.get("location", ""),
            }
        except Exception:
            pass

    return {
        "version":          1,
        "last_updated":     _now_iso(),
        "personal":         personal,
        "metrics":          {},
        "role_preferences": {
            "target_titles":       [],
            "preferred_locations": [],
            "work_type":           "any",
            "salary_min_usd":      None,
        },
        "enriched_entities": {},
        # Claims extracted from uploaded CVs — treated as unverified by Jonathan
        "cv_claims": {
            "skills":      [],
            "experiences": [],
            "education":   [],
            "summary":     "",
        },
    }


# ── Core persistence ──────────────────────────────────────────────────────────

def load(user_id: str) -> dict:
    """
    Load the profile for user_id from disk.

    Returns a fresh scaffold (and creates the file) if the profile is missing
    or corrupt.  Never raises.
    """
    path = profile_path(user_id)

    if path.exists():
        try:
            profile = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(profile, dict) and profile.get("version"):
                return profile
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning(
                "[user_profile_store] Could not load %s for user=%s (%s) — starting fresh",
                path, user_id, exc,
            )

    profile = _empty_profile(user_id)
    try:
        save(user_id, profile)
        logger.info(
            "[user_profile_store] Created new profile at %s for user=%s", path, user_id
        )
    except Exception as exc:
        logger.warning(
            "[user_profile_store] Could not write new profile for user=%s: %s", user_id, exc
        )
    return profile


def save(user_id: str, profile: dict) -> None:
    """
    Atomically write the profile to disk (tempfile → os.replace).
    Creates the user's directory if it does not exist.
    """
    path = profile_path(user_id)
    path.parent.mkdir(parents=True, exist_ok=True)

    profile["last_updated"] = _now_iso()

    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".json.tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(profile, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ── Answer cache ──────────────────────────────────────────────────────────────

def get_cached_answer(user_id: str, question_id: str) -> str | None:
    """Return the stored answer for question_id, or None if not present."""
    if not question_id:
        return None
    try:
        profile = load(user_id)
        entry   = profile.get("metrics", {}).get(question_id)
        if entry and isinstance(entry, dict):
            value = str(entry.get("value", "")).strip()
            if value:
                return value
    except Exception as exc:
        logger.warning(
            "[user_profile_store] get_cached_answer failed for user=%s qid=%s: %s",
            user_id, question_id, exc,
        )
    return None


def merge_answers(user_id: str, answers: dict[str, str]) -> int:
    """
    Write new question_id → answer pairs into the user's profile["metrics"].
    Returns the count of newly written entries.  Never raises.
    """
    if not answers:
        return 0

    newly_written = 0
    try:
        profile = load(user_id)
        metrics = profile.setdefault("metrics", {})
        now     = _now_iso()

        for qid, raw_answer in answers.items():
            answer = str(raw_answer or "").strip()
            if not answer:
                continue
            if qid in metrics:
                metrics[qid]["value"]      = answer
                metrics[qid]["updated_at"] = now
                metrics[qid]["confidence"] = "high"
            else:
                metrics[qid] = {
                    "value":      answer,
                    "source":     "supplemental",
                    "confidence": "high",
                    "created_at": now,
                    "updated_at": now,
                }
                newly_written += 1

        save(user_id, profile)
        logger.info(
            "[user_profile_store] merge_answers user=%s: %d new / %d updated",
            user_id, newly_written, len(answers) - newly_written,
        )
    except Exception as exc:
        logger.error(
            "[user_profile_store] merge_answers failed for user=%s: %s", user_id, exc
        )
    return newly_written
