"""Repository for the master_profiles table.

Consolidates the "get row, or create one with defaults if absent" pattern
that was independently re-implemented across master_profile_service.py,
ariel_tools.py, feedback_service.py, profile_baseline_service.py, and
several inline route blocks in profile.py/chat.py — each a slightly
divergent copy of the same logic.

get_or_create() takes an already-open Session (mirroring the shared-session
pattern from application_repository.upsert_submitted) so callers can combine
the row creation with further mutations in one atomic commit, and an
explicit `now` string so each caller keeps using its own timestamp
formatting exactly as before (some callers use a truncated-seconds ISO
format, others full isoformat() with microseconds — unifying that was out
of scope for a behavior-preserving move).
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from backend.core.database import ENGINE
from backend.models.profile import MasterProfileRow


def get_or_create(
    session: Session,
    user_id: str,
    *,
    now: str,
) -> tuple[MasterProfileRow, bool]:
    """
    Return the MasterProfileRow for user_id, creating it (with an empty
    master_profile dict) if absent.

    The caller is responsible for committing the session. Returns
    (row, created) — created=True only when a brand new row was added.
    """
    row = session.get(MasterProfileRow, user_id)
    if row is not None:
        return row, False

    row = MasterProfileRow(
        user_id           = user_id,
        onboarding_status = "incomplete",
        master_profile    = {},
        created_at        = now,
        updated_at        = now,
    )
    session.add(row)
    return row, True


def get(user_id: str, engine: Optional[Engine] = None) -> Optional[MasterProfileRow]:
    """Standalone read-only fetch, own session. Row is detached on return."""
    eng = engine or ENGINE
    with Session(eng) as session:
        return session.get(MasterProfileRow, user_id)


def get_profile_json(user_id: str, engine: Optional[Engine] = None) -> dict:
    """Return the master_profile JSON dict for user_id, or {} if absent."""
    row = get(user_id, engine=engine)
    return dict(row.master_profile or {}) if row else {}
