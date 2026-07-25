"""Repository for the evidence_records table.

Consolidates the read-only "active (non hard-expired) evidence for an
entity" query that was inlined (twice, near-identically) in
backend/api/routes/profile.py's trust-score and force-recalculate endpoints.

Does NOT cover profile_update_service.py's evidence_records writes — those
are append-only inserts inside larger, atomic multi-table transactions and
stay where they are (repository-consumer pattern).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from backend.core.database import ENGINE
from backend.models.profile import EvidenceRecordRow


@dataclass(frozen=True)
class Evidence:
    evidence_id: str
    entity_id: str
    source_type: str
    base_weight: float
    raw_content: Optional[str]
    verified_at: str
    hard_expires_at: Optional[str]
    is_ai_assisted: bool


def get_active_for_entity(
    entity_id: str,
    now_iso: str,
    session: Optional[Session] = None,
) -> list[Evidence]:
    """
    Non hard-expired evidence for entity_id, freshest (by verified_at) first.

    "Active" = hard_expires_at is NULL, or in the future relative to now_iso.

    Accepts an optional already-open Session so a caller looping over many
    entities in one request (e.g. profile.py's trust-score and
    force-recalculate endpoints) can share one session/connection for the
    whole loop instead of opening a new one per entity.
    """
    if session is not None:
        return _query(session, entity_id, now_iso)
    with Session(ENGINE) as owned_session:
        return _query(owned_session, entity_id, now_iso)


def _query(session: Session, entity_id: str, now_iso: str) -> list[Evidence]:
    rows = (
        session.query(EvidenceRecordRow)
        .filter(
            EvidenceRecordRow.entity_id == entity_id,
            or_(
                EvidenceRecordRow.hard_expires_at.is_(None),
                EvidenceRecordRow.hard_expires_at > now_iso,
            ),
        )
        .order_by(EvidenceRecordRow.verified_at.desc())
        .all()
    )
    return [
        Evidence(
            evidence_id     = r.evidence_id,
            entity_id       = r.entity_id,
            source_type     = r.source_type,
            base_weight     = r.base_weight,
            raw_content     = r.raw_content,
            verified_at     = r.verified_at,
            hard_expires_at = r.hard_expires_at,
            is_ai_assisted  = bool(r.is_ai_assisted),
        )
        for r in rows
    ]


def reassign_user(old_user_id: str, new_user_id: str, session: Session) -> int:
    """
    Re-point every EvidenceRecordRow owned by old_user_id to new_user_id.

    Takes an already-open Session so the caller (account-linking/migration
    flows in auth.py) can combine this with reassignments on other tables
    in one atomic commit.
    """
    return (
        session.query(EvidenceRecordRow)
        .filter(EvidenceRecordRow.user_id == old_user_id)
        .update({"user_id": new_user_id}, synchronize_session="fetch")
    )
