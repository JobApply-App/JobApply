"""Repository for the profile_entities table.

Consolidates the read-only single-entity and per-user-list lookups that were
inlined across backend/api/routes/ariel.py (probe start/respond/audit) and
backend/api/routes/profile.py (trust-score endpoint, manual-verify start).

Does NOT cover profile_update_service.py's writes — those mutate entity rows
as part of larger, atomic multi-table evidence-ingestion transactions and stay
where they are (repository-consumer pattern), nor force_recalculate's entity
mutation loop in profile.py, which needs live ORM rows attached to its own
session to update-then-commit in place.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sqlalchemy.orm import Session

from backend.core.database import ENGINE
from backend.models.profile import ProfileEntityRow


@dataclass(frozen=True)
class ProfileEntity:
    entity_id: str
    user_id: str
    entity_type: str
    name: str
    normalized_name: str
    confidence_score: float
    verification_status: str
    manual_review_required: bool
    skill_tier: Optional[str]
    proficiency_level: Optional[str]
    architecture_confidence: float
    syntax_confidence: float
    verification_level: str


def _to_entry(row: ProfileEntityRow) -> ProfileEntity:
    return ProfileEntity(
        entity_id               = row.entity_id,
        user_id                 = row.user_id,
        entity_type             = row.entity_type,
        name                    = row.name,
        normalized_name         = row.normalized_name,
        confidence_score        = row.confidence_score,
        verification_status     = row.verification_status,
        manual_review_required  = bool(row.manual_review_required),
        skill_tier              = row.skill_tier,
        proficiency_level       = row.proficiency_level,
        architecture_confidence = row.architecture_confidence,
        syntax_confidence       = row.syntax_confidence,
        verification_level      = row.verification_level,
    )


def get_by_id(entity_id: str) -> Optional[ProfileEntity]:
    with Session(ENGINE) as session:
        row = session.get(ProfileEntityRow, entity_id)
        return _to_entry(row) if row else None


def get_for_user(entity_id: str, user_id: str) -> Optional[ProfileEntity]:
    """Like get_by_id, but scoped to user_id — returns None on any mismatch."""
    with Session(ENGINE) as session:
        row = (
            session.query(ProfileEntityRow)
            .filter(
                ProfileEntityRow.entity_id == entity_id,
                ProfileEntityRow.user_id   == user_id,
            )
            .first()
        )
        return _to_entry(row) if row else None


def get_all_for_user(user_id: str, session: Optional[Session] = None) -> list[ProfileEntity]:
    """
    All entities for user_id, ordered by confidence_score descending.

    Accepts an optional already-open Session so a caller that also needs to
    read/write other tables in the same request (e.g. profile.py's
    trust-score endpoint, which then queries evidence per entity) can share
    one session/connection for a consistent read snapshot.
    """
    if session is not None:
        return _query(session, user_id)
    with Session(ENGINE) as owned_session:
        return _query(owned_session, user_id)


def _query(session: Session, user_id: str) -> list[ProfileEntity]:
    rows = (
        session.query(ProfileEntityRow)
        .filter(ProfileEntityRow.user_id == user_id)
        .order_by(ProfileEntityRow.confidence_score.desc())
        .all()
    )
    return [_to_entry(r) for r in rows]


def reassign_user(old_user_id: str, new_user_id: str, session: Session) -> int:
    """
    Re-point every ProfileEntityRow owned by old_user_id to new_user_id.

    Takes an already-open Session so the caller (account-linking/migration
    flows in auth.py) can combine this with reassignments on other tables
    in one atomic commit.
    """
    return (
        session.query(ProfileEntityRow)
        .filter(ProfileEntityRow.user_id == old_user_id)
        .update({"user_id": new_user_id}, synchronize_session="fetch")
    )
