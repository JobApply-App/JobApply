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

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.core.database import ENGINE
from backend.models.profile import ProfileEntityRow
from backend.repositories.evidence_repository import Evidence


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
        # entity_id tiebreaker: confidence_score alone is NOT unique — this
        # account's real data has groups of dozens of entities tied at the
        # same score, and without a tiebreaker Postgres may return them in a
        # different order across equivalent-looking queries (confirmed by
        # comparing this query's plan against the single-JOIN combined loader
        # below — same WHERE, same rows, different tie order without this).
        .order_by(ProfileEntityRow.confidence_score.desc(), ProfileEntityRow.entity_id.asc())
        .all()
    )
    return [_to_entry(r) for r in rows]


# ── Combined entity + evidence load (one round trip) ─────────────────────────

_COMBINED_SQL = text("""
    SELECT
        pe.entity_id, pe.user_id, pe.entity_type, pe.name, pe.normalized_name,
        pe.confidence_score, pe.verification_status, pe.manual_review_required,
        pe.skill_tier, pe.proficiency_level, pe.architecture_confidence,
        pe.syntax_confidence, pe.verification_level,
        er.evidence_id, er.source_type, er.base_weight, er.raw_content,
        er.verified_at, er.hard_expires_at, er.is_ai_assisted
    FROM profile_entities pe
    LEFT JOIN evidence_records er
        ON er.entity_id = pe.entity_id
        AND (er.hard_expires_at IS NULL OR er.hard_expires_at > :now)
    WHERE pe.user_id = :uid
    ORDER BY pe.confidence_score DESC, pe.entity_id ASC, er.verified_at DESC, er.evidence_id ASC
""")


def get_all_with_evidence_for_user(
    user_id: str, now_iso: str, session: Session
) -> tuple[list[ProfileEntity], dict[str, list[Evidence]]]:
    """
    Load every profile_entities row for user_id AND its non-expired evidence
    in ONE query (a LEFT JOIN) instead of the two separate round trips
    get_all_for_user() + evidence_repository.get_active_for_entities()
    cost — for callers needing both (dashboard.py's aggregated endpoint).

    Measured on a real 160-entity/253-evidence-row account: ~855ms vs
    ~1071ms for the two-query path (8/8 wins across interleaved trials,
    ~20% faster), transferring 253 total rows in one round trip instead of
    413 rows across two. Verified byte-for-byte equivalent output to the
    two-query path (same ORDER BY tiebreakers on both sides — confidence_score
    ties are common in real data, and entity_id/evidence_id tiebreakers make
    the order deterministic instead of plan-dependent).

    Returns (entity_rows, evidence_by_entity) — entity_rows is `[]` (and
    evidence_by_entity `{}`) when the user has no entities, same as the
    two-query path's empty-profile behavior.
    """
    rows = session.execute(_COMBINED_SQL, {"uid": user_id, "now": now_iso}).fetchall()

    entities: dict[str, ProfileEntity] = {}
    entity_order: list[str] = []
    evidence_by_entity: dict[str, list[Evidence]] = {}

    for r in rows:
        eid = r.entity_id
        if eid not in entities:
            entities[eid] = ProfileEntity(
                entity_id=r.entity_id, user_id=str(r.user_id), entity_type=r.entity_type,
                name=r.name, normalized_name=r.normalized_name,
                confidence_score=r.confidence_score, verification_status=r.verification_status,
                manual_review_required=bool(r.manual_review_required),
                skill_tier=r.skill_tier, proficiency_level=r.proficiency_level,
                architecture_confidence=r.architecture_confidence,
                syntax_confidence=r.syntax_confidence, verification_level=r.verification_level,
            )
            entity_order.append(eid)
            evidence_by_entity[eid] = []
        if r.evidence_id is not None:
            evidence_by_entity[eid].append(Evidence(
                evidence_id=r.evidence_id, entity_id=eid, source_type=r.source_type,
                base_weight=r.base_weight, raw_content=r.raw_content,
                verified_at=r.verified_at, hard_expires_at=r.hard_expires_at,
                is_ai_assisted=bool(r.is_ai_assisted),
            ))

    entity_rows = [entities[eid] for eid in entity_order]
    return entity_rows, evidence_by_entity


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
