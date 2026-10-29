"""
Per-user profile store — personal fields, supplemental answers (metrics),
role preferences and enriched entities.

Backed by the database (the profile document's "metrics_doc" key, via
master_profile_service). It used to be a JSON file per user under
backend/data/users/, on the server's local disk — which Render wipes on every
deploy and restart, so anything written only here (a phone number edited in
the profile, supplemental answers, a LinkedIn URL) silently disappeared on
the next release.

The API is unchanged so call sites need no edits. A file still on disk from
before the move is imported once on first load and renamed, so nothing written
since the last deploy is lost.

The CV itself is not kept here: it lives in the profile's cv_data
(profile_repository). A "cv_claims" key passed to save() is dropped.

Public API
----------
    load(user_id)                   -> dict
    save(user_id, profile)          -> None
    get_cached_answer(user_id, qid) -> str | None
    merge_answers(user_id, answers) -> int
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Where the old file store lived; read only to import leftovers.
_LEGACY_USERS_DIR = Path(__file__).resolve().parents[2] / "backend" / "data" / "users"


def _import_legacy_file(user_id: str, doc: dict) -> bool:
    """
    Fill keys missing from doc with the user's old on-disk profile.json, then
    rename the file so it is imported only once. Returns True when doc changed.
    """
    path = _LEGACY_USERS_DIR / user_id / "profile.json"
    if not path.is_file():
        return False
    try:
        legacy = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("[user_profile_store] unreadable legacy file for user=%s: %s", user_id, exc)
        return False
    changed = False
    if isinstance(legacy, dict):
        for key in ("personal", "metrics", "role_preferences", "enriched_entities"):
            old, new = legacy.get(key), doc.get(key)
            if not isinstance(old, dict) or not old:
                continue
            merged = {**old, **{k: v for k, v in (new or {}).items() if v not in ("", None, [], {})}}
            if merged != new:
                doc[key] = merged
                changed = True
    try:
        path.rename(path.with_suffix(".json.imported"))
    except OSError:
        pass
    if changed:
        logger.info("[user_profile_store] imported legacy file store for user=%s", user_id)
    return changed


def load(user_id: str) -> dict:
    """
    The user's store document; a fresh scaffold when they have none.

    Raises on a database error rather than returning an empty document: most
    callers edit what they load and save it back, and an empty stand-in would
    overwrite the user's real data.
    """
    from backend.services import master_profile_service

    doc = master_profile_service.load(user_id, strict=True)
    try:
        if _import_legacy_file(user_id, doc):
            master_profile_service.save(doc, user_id)
    except Exception as exc:
        logger.warning("[user_profile_store] legacy import failed for user=%s: %s", user_id, exc)
    return doc


def save(user_id: str, profile: dict) -> None:
    """Persist the store document for user_id."""
    from backend.services import master_profile_service

    doc = {k: v for k, v in profile.items() if k != "cv_claims"}
    master_profile_service.save(doc, user_id)


def get_cached_answer(user_id: str, question_id: str) -> str | None:
    """Return the stored answer for question_id, or None if not present."""
    from backend.services import master_profile_service
    return master_profile_service.get_cached_answer(question_id, user_id)


def merge_answers(user_id: str, answers: dict[str, str]) -> int:
    """Write question_id → answer pairs into profile["metrics"]; returns the count of new ones."""
    from backend.services import master_profile_service
    return master_profile_service.merge_answers(answers, user_id)
