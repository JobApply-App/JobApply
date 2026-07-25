"""
ProfileUpdateService
====================
Single entry point for all confidence-score mutations in the Active
Confidence Matrix.

Immutability contract
---------------------
• evidence_records is append-only.  This service NEVER issues UPDATE or
  DELETE against that table.
• profile_entities.confidence_score is always derived — computed from the
  full evidence ledger by _recompute_and_persist().  It is never set directly.
• Every score change produces one row in confidence_audit_log.

Public methods
--------------
ingest_cv_parse(user_id, parsed_entities)
    Bulk-create entities from a CV parse.  Low-weight cv_parse evidence.

ingest_certification(user_id, entity_name, ...)
    Record a certification or portfolio document as medium-weight evidence.

ingest_conversation_event(user_id, session_id, event)
    Process one STAR behavioral event extracted by Ariel.  Highest-weight path.

ingest_negative_flag(user_id, entity_id, session_id, flag_type, raw_content, flag_reason)
    Append a negative evidence record (contradiction / shallow STAR).
    Recomputes score downward; sets manual_review_required=1 if score < 30.

ingest_contextual_reinforcement(user_id, session_id, transcript_text)
    Scan a session transcript for unprompted skill mentions and append
    low-weight contextual_reinforcement evidence for each matching entity.
    Idempotent per session — safe to call multiple times for the same session.

enqueue_gap / resolve_gap
    Ariel gap-queue lifecycle helpers.

open_session / close_session
    Ariel session lifecycle helpers.

All methods commit their own transaction; callers do not need to commit.
"""
from __future__ import annotations

import json
import logging
import math
import re
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import text

from backend.repositories import ariel_gap_queue_repository
from backend.repositories import ariel_session_repository
from backend.repositories import conversation_event_repository
from backend.services.confidence_math import (
    BASE_WEIGHTS,
    EvidenceRow,
    MANUAL_REVIEW_THRESHOLD,
    compute_confidence_score,
    compute_decoupled_score,
    gap_severity,
    verification_status,
)

logger = logging.getLogger(__name__)

# Required confidence score for a skill to be considered "job-ready".
# Used by the gap-detection helper.
DEFAULT_REQUIRED_CONFIDENCE = 60.0


# ── Helpers ───────────────────────────────────────────────────────────────────

def _uid() -> str:
    return str(uuid.uuid4())


def _now_iso() -> str:
    """Return current UTC time as ISO-8601 string (timezone-aware)."""
    return datetime.now(timezone.utc).isoformat()


def _normalize(name: str) -> str:
    """Canonical entity key: lowercase, spaces → underscore, stripped."""
    return name.strip().lower().replace(" ", "_").replace("-", "_")


def _parse_dt(value) -> datetime:
    """Coerce a DB value (str or datetime) to a timezone-aware datetime."""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    s = str(value)
    if s.endswith("Z"):
        # Python < 3.11's datetime.fromisoformat() rejects the 'Z' UTC
        # suffix; seeded/legacy rows use it, so normalize before parsing.
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _base_profile_completeness_fraction(profile: Optional[dict]) -> float:
    """
    Return the fraction (0.0–1.0) of the three critical base-profile anchors the
    system knows about the user: name, phone, and at least one stated career
    preference (target title).

    Used by the Holistic Familiarity score as a POSITIVE contributor — the more
    of these the system knows, the more familiar it is with the user. It is
    never a penalty: a missing field simply withholds a bonus, it does not
    subtract from breadth/depth.

    A missing profile (None / not a dict) yields 0.0. Matches the schema written
    by user_profile_store.load(): personal.{full_name,phone} and
    role_preferences.target_titles.
    """
    if not isinstance(profile, dict):
        return 0.0
    personal   = profile.get("personal", {})       or {}
    role_prefs = profile.get("role_preferences", {}) or {}

    present = 0
    if str(personal.get("full_name", "")).strip():
        present += 1
    if str(personal.get("phone", "")).strip():
        present += 1
    if role_prefs.get("target_titles"):
        present += 1
    return present / 3.0


# ── Service ───────────────────────────────────────────────────────────────────

class ProfileUpdateService:
    """
    Wraps a SQLAlchemy Engine (not Session) and uses raw SQL via conn.execute()
    to match the existing db.py pattern in this project.
    """

    # ── Holistic Familiarity score constants (Phase 31) ──────────────────────
    # The System Confidence Score measures how well the system KNOWS the user
    # (breadth + depth of familiarity), not how skilled the user is. Three
    # additive pillars sum to a max of 100; see compute_profile_trust_score.
    #
    # Pillar 1 — BREADTH: saturating in the raw count of known entities. Volume
    # of parsed/known data = the system has mapped the user's landscape.
    BREADTH_MAX:   float = 40.0
    BREADTH_SCALE: float = 35.0   # entities at which breadth reaches ~63% of max
    #
    # Pillar 2 — DEPTH: saturating in the amount of VERIFIED knowledge (evidence
    # tiers + chat-confirmed proficiencies). This is the path to 100.
    DEPTH_MAX:   float = 40.0
    DEPTH_SCALE: float = 8.0      # weighted-verified units for ~63% of max
    #
    # Pillar 3 — CONTEXT: additive positives, never penalties — category
    # coverage, base-profile identity completeness, and proficiency engagement.
    CONTEXT_COVERAGE_MAX:     float = 8.0   # spread across skill/trait/exp/domain
    CONTEXT_IDENTITY_MAX:     float = 6.0   # name / phone / career-prefs known
    CONTEXT_PROFICIENCY_MAX:  float = 6.0   # user-clarified proficiency levels
    CONTEXT_PROFICIENCY_SCALE: float = 5.0

    # Graded verification weight per entity for the DEPTH pillar. An entity the
    # user has explicitly clarified (proficiency_level set) counts as at least
    # half-verified even if its score is low — knowing a weakness IS knowledge.
    VERIFICATION_WEIGHTS: dict[str, float] = {
        "verified":       1.00,
        "partial":        0.50,
        "needs_evidence": 0.25,
        "unverified":     0.00,
    }
    PROFICIENCY_MIN_VERIFICATION_WEIGHT: float = 0.50

    # The four scored entity categories (unknown types still count toward
    # breadth volume, but not toward category coverage).
    _SCORED_CATEGORIES: frozenset = frozenset({"skill", "trait", "experience", "domain"})

    # Honest confidence ceiling per self-reported proficiency level. When a user
    # clarifies their level in chat and no explicit score/modifier is supplied,
    # apply_chat_proficiency_update anchors the entity's confidence_score down to
    # (never up past) the matching ceiling — a self-claim cannot inflate a score,
    # but "I'm only a beginner" honestly lowers an over-optimistic parse.
    PROFICIENCY_CEILINGS: dict[str, float] = {
        "beginner":     30.0,
        "novice":       30.0,
        "intermediate": 55.0,
        "proficient":   65.0,
        "advanced":     75.0,
        "expert":       90.0,
    }

    def __init__(self, engine):
        """
        Parameters
        ----------
        engine : sqlalchemy.engine.Engine
            Pass ENGINE from backend.core.database — the shared SQLite engine.
        """
        self._engine = engine

    # ─────────────────────────────────────────────────────────────────────────
    # Internal: entity upsert
    # ─────────────────────────────────────────────────────────────────────────

    def _upsert_entity(
        self,
        conn,
        user_id: str,
        entity_type: str,
        name: str,
    ) -> str:
        """
        Return entity_id for (user_id, normalized_name, entity_type).
        Creates the row with confidence_score=0 if it does not exist yet.
        """
        normalized = _normalize(name)
        row = conn.execute(
            text(
                "SELECT entity_id FROM profile_entities "
                "WHERE user_id = :u AND normalized_name = :n AND entity_type = :t"
            ),
            {"u": user_id, "n": normalized, "t": entity_type},
        ).fetchone()

        if row:
            return row[0]

        entity_id = _uid()
        now       = _now_iso()
        conn.execute(
            text("""
                INSERT INTO profile_entities
                    (entity_id, user_id, entity_type, name, normalized_name,
                     confidence_score, verification_status, created_at, updated_at)
                VALUES
                    (:eid, :uid, :etype, :name, :norm,
                     0.0, 'unverified', :now, :now)
            """),
            {
                "eid":   entity_id,
                "uid":   user_id,
                "etype": entity_type,
                "name":  name.strip(),
                "norm":  normalized,
                "now":   now,
            },
        )
        logger.info(
            "profile_entity created: '%s' (%s) user=%s id=%s",
            name, entity_type, user_id, entity_id,
        )
        return entity_id

    # ─────────────────────────────────────────────────────────────────────────
    # Internal: recompute confidence and write audit row
    # ─────────────────────────────────────────────────────────────────────────

    def _recompute_and_persist(
        self,
        conn,
        entity_id: str,
        user_id: str,
        trigger_source: str,
        new_evidence_id: str,
        session_id: Optional[str] = None,
        note: Optional[str] = None,
    ) -> float:
        """
        Fetch the full evidence ledger for entity_id, recompute the score,
        persist it on profile_entities, and write one confidence_audit_log row.

        This is the ONLY function that may write to profile_entities.confidence_score.

        Returns
        -------
        float
            The new confidence score.
        """
        now = _now_iso()

        # Fetch all non-hard-expired evidence for this entity
        rows = conn.execute(
            text("""
                SELECT source_type, base_weight, verified_at, is_ai_assisted
                FROM   evidence_records
                WHERE  entity_id = :eid
                  AND  (hard_expires_at IS NULL OR hard_expires_at > :now)
            """),
            {"eid": entity_id, "now": now},
        ).fetchall()

        evidence: list[EvidenceRow] = [
            {
                "source_type":    r[0],
                "base_weight":    float(r[1]),
                "verified_at":    _parse_dt(r[2]),
                "is_ai_assisted": bool(r[3]) if r[3] is not None else False,
            }
            for r in rows
        ]

        # Decoupled truth-based scores
        dscore     = compute_decoupled_score(evidence)
        # Legacy blended score kept for backwards-compatible feed sorting and
        # match scoring.  In practice == dscore.final_score for new entities,
        # but compute_confidence_score is preserved for existing probe paths.
        new_score  = dscore.final_score
        new_status = verification_status(new_score)

        # Derive skill_tier from the evidence ledger:
        # If ANY evidence row is NOT ai_assisted, the entity has at least some
        # direct mastery proof → Core_Mastery.
        # If ALL evidence rows are ai_assisted → System_Orchestration.
        # Only set a tier when there is positive evidence; leave NULL otherwise.
        pos_evidence = [e for e in evidence if e["base_weight"] >= 0]
        if pos_evidence:
            all_ai = all(e["is_ai_assisted"] for e in pos_evidence)
            new_skill_tier: str | None = "System_Orchestration" if all_ai else "Core_Mastery"
        else:
            new_skill_tier = None

        # Fetch old score for audit delta
        old_row = conn.execute(
            text("SELECT confidence_score FROM profile_entities WHERE entity_id = :eid"),
            {"eid": entity_id},
        ).fetchone()
        old_score = float(old_row[0]) if old_row else 0.0

        # Persist new score.
        # Also clear manual_review_required when positive evidence pushes
        # the score back above the manual-review threshold — the flag was set
        # because the score dropped, and a recovery should lift the block.
        # ingest_negative_flag() is responsible for SETTING the flag;
        # all other ingest paths are responsible for CLEARING it on recovery.
        cleared_review = 1 if new_score >= MANUAL_REVIEW_THRESHOLD else None
        conn.execute(
            text("""
                UPDATE profile_entities
                SET    confidence_score           = :score,
                       verification_status        = :status,
                       skill_tier                 = COALESCE(:tier, skill_tier),
                       architecture_confidence    = :arch,
                       syntax_confidence          = :syntax,
                       verification_level         = :vl,
                       manual_review_required     = CASE
                           WHEN :clear_review = 1 THEN 0
                           ELSE manual_review_required
                       END,
                       last_evidence_at           = :now,
                       updated_at                 = :now
                WHERE  entity_id = :eid
            """),
            {
                "score":        new_score,
                "status":       new_status,
                "tier":         new_skill_tier,
                "arch":         dscore.architecture_confidence,
                "syntax":       dscore.syntax_confidence,
                "vl":           dscore.verification_level,
                "clear_review": cleared_review if cleared_review else 0,
                "now":          now,
                "eid":          entity_id,
            },
        )

        # Audit log — immutable
        conn.execute(
            text("""
                INSERT INTO confidence_audit_log
                    (entity_id, user_id, old_score, new_score, delta,
                     trigger_source, evidence_id, session_id, changed_at, note)
                VALUES
                    (:eid, :uid, :old, :new, :delta,
                     :src, :evid, :sid, :now, :note)
            """),
            {
                "eid":   entity_id,
                "uid":   user_id,
                "old":   old_score,
                "new":   new_score,
                "delta": round(new_score - old_score, 1),
                "src":   trigger_source,
                "evid":  new_evidence_id,
                "sid":   session_id,
                "now":   now,
                "note":  note,
            },
        )

        logger.info(
            "confidence: entity=%s  %.1f → %.1f  (%s)  Δ%+.1f  src=%s",
            entity_id, old_score, new_score, new_status,
            new_score - old_score, trigger_source,
        )
        return new_score

    # ─────────────────────────────────────────────────────────────────────────
    # Public: CV parse ingestion
    # ─────────────────────────────────────────────────────────────────────────

    def ingest_cv_parse(
        self,
        user_id: str,
        parsed_entities: list[dict],
    ) -> list[str]:
        """
        Bulk-ingest entities extracted from a CV parse.

        Parameters
        ----------
        user_id : str
        parsed_entities : list[dict]
            Each dict must contain:
                entity_type : 'skill' | 'trait' | 'domain' | 'experience'
                name        : str
            Optional:
                raw_content : str   — the CV line that contained this entity

        Returns
        -------
        list[str]
            entity_ids created or refreshed.

        Note: re-running on the same CV appends a new evidence_record rather
        than overwriting, so re-uploads correctly "refresh" the freshness factor
        without discarding prior evidence.
        """
        entity_ids: list[str] = []
        now = _now_iso()

        with self._engine.begin() as conn:
            for item in parsed_entities:
                entity_id = self._upsert_entity(
                    conn, user_id, item["entity_type"], item["name"]
                )
                ev_id = _uid()
                conn.execute(
                    text("""
                        INSERT INTO evidence_records
                            (evidence_id, entity_id, user_id, source_type,
                             base_weight, raw_content, verified_at)
                        VALUES
                            (:evid, :eid, :uid, 'cv_parse', :w, :raw, :now)
                    """),
                    {
                        "evid": ev_id,
                        "eid":  entity_id,
                        "uid":  user_id,
                        "w":    BASE_WEIGHTS["cv_parse"],
                        "raw":  item.get("raw_content", ""),
                        "now":  now,
                    },
                )
                self._recompute_and_persist(
                    conn, entity_id, user_id,
                    trigger_source="cv_parse",
                    new_evidence_id=ev_id,
                    note=f"CV parse: {item['name']}",
                )
                entity_ids.append(entity_id)

        logger.info(
            "ingest_cv_parse: user=%s  %d entities processed",
            user_id, len(entity_ids),
        )
        return entity_ids

    # ─────────────────────────────────────────────────────────────────────────
    # Public: Self-assertion (unverified claim made directly in conversation)
    # ─────────────────────────────────────────────────────────────────────────

    def ingest_self_assertion(
        self,
        user_id:     str,
        entity_type: str,
        name:        str,
        raw_content: str = "",
    ) -> str:
        """
        Record one entity as a self-asserted, unverified claim — the weakest
        positive evidence tier (BASE_WEIGHTS['self_assertion'], lowest of all
        positive source types). Used for profile facts a user states directly
        in an Ariel chat (e.g. via the update_experience/update_skills tools)
        that haven't been through CV parsing, a certification, or a STAR
        behavioral probe. 'self_assertion' has been a defined evidence
        source_type since the original schema (see confidence_math.py and the
        DB CHECK constraint) but had no caller until now.

        Parameters
        ----------
        user_id, entity_type, name
            Standard entity identifiers. entity_type must be one of
            'skill' | 'trait' | 'domain' | 'experience'.
        raw_content
            The chat-derived text backing this claim (e.g. "Senior PM at Acme").

        Returns
        -------
        str   entity_id
        """
        now = _now_iso()
        with self._engine.begin() as conn:
            entity_id = self._upsert_entity(conn, user_id, entity_type, name)
            ev_id = _uid()
            conn.execute(
                text("""
                    INSERT INTO evidence_records
                        (evidence_id, entity_id, user_id, source_type,
                         base_weight, raw_content, verified_at)
                    VALUES
                        (:evid, :eid, :uid, 'self_assertion', :w, :raw, :now)
                """),
                {
                    "evid": ev_id,
                    "eid":  entity_id,
                    "uid":  user_id,
                    "w":    BASE_WEIGHTS["self_assertion"],
                    "raw":  raw_content,
                    "now":  now,
                },
            )
            self._recompute_and_persist(
                conn, entity_id, user_id,
                trigger_source="self_assertion",
                new_evidence_id=ev_id,
                note=f"Chat self-assertion: {name}",
            )

        logger.info(
            "ingest_self_assertion: user=%s entity_type=%s name=%r",
            user_id, entity_type, name,
        )
        return entity_id

    # ─────────────────────────────────────────────────────────────────────────
    # Public: Certification / Portfolio
    # ─────────────────────────────────────────────────────────────────────────

    def ingest_certification(
        self,
        user_id: str,
        entity_name: str,
        entity_type: str = "skill",
        source_type: str = "certification",   # or 'portfolio'
        cert_metadata: Optional[dict] = None,
        hard_expires_at: Optional[str] = None,  # ISO-8601 UTC string
    ) -> str:
        """
        Record a certification or portfolio artifact as medium-weight evidence.

        Parameters
        ----------
        user_id, entity_name, entity_type
            Standard entity identifiers.
        source_type
            'certification' or 'portfolio'.
        cert_metadata
            Optional dict — stored as JSON in evidence_records.metadata.
            Useful for: {"issuer": "AWS", "cert_id": "abc123", "type": "portfolio"}.
        hard_expires_at
            ISO-8601 UTC string.  When set, evidence stops contributing after
            this date regardless of freshness decay.

        Returns
        -------
        str   entity_id
        """
        if source_type not in ("certification", "portfolio"):
            raise ValueError(f"source_type must be 'certification' or 'portfolio', got {source_type!r}")

        with self._engine.begin() as conn:
            entity_id = self._upsert_entity(conn, user_id, entity_type, entity_name)
            ev_id     = _uid()
            now       = _now_iso()

            conn.execute(
                text("""
                    INSERT INTO evidence_records
                        (evidence_id, entity_id, user_id, source_type,
                         base_weight, raw_content, verified_at,
                         hard_expires_at, metadata)
                    VALUES
                        (:evid, :eid, :uid, :src,
                         :w, :raw, :now,
                         :exp, :meta)
                """),
                {
                    "evid": ev_id,
                    "eid":  entity_id,
                    "uid":  user_id,
                    "src":  source_type,
                    "w":    BASE_WEIGHTS[source_type],
                    "raw":  (cert_metadata or {}).get("description", ""),
                    "now":  now,
                    "exp":  hard_expires_at,
                    "meta": json.dumps(cert_metadata or {}),
                },
            )
            self._recompute_and_persist(
                conn, entity_id, user_id,
                trigger_source=source_type,
                new_evidence_id=ev_id,
                note=f"{source_type}: {entity_name}",
            )

        return entity_id

    # ─────────────────────────────────────────────────────────────────────────
    # Public: Conversation STAR event (highest-weight path)
    # ─────────────────────────────────────────────────────────────────────────

    def ingest_conversation_event(
        self,
        user_id: str,
        session_id: str,
        event: dict,
    ) -> dict[str, float]:
        """
        Process one STAR behavioral event extracted from an Ariel session
        and update confidence scores for all referenced entities.

        event schema
        ------------
        {
            # Provide one or both:
            "extracted_entity_ids":   ["uuid-1", ...],   # existing entity_ids
            "extracted_entity_names": [                   # OR new entities to upsert
                {"entity_type": "skill", "name": "Sprint Prioritization"}
            ],

            "extraction_confidence":  0.87,   # LLM confidence, 0–1

            # STAR components (all optional but encouraged)
            "star_situation": "...",
            "star_task":      "...",
            "star_action":    "...",
            "star_result":    "...",

            "raw_quote": "..."    # verbatim user turn(s)
        }

        The conversation_star base_weight (80 pts) is scaled by
        extraction_confidence so a 0.9-confidence extraction contributes
        72 pts while a 0.5-confidence extraction contributes 40 pts.

        Returns
        -------
        dict[str, float]
            {entity_id: new_confidence_score} for every entity updated.
        """
        extraction_conf = min(max(float(event.get("extraction_confidence", 0.7)), 0.0), 1.0)
        effective_weight = BASE_WEIGHTS["conversation_star"] * extraction_conf

        with self._engine.begin() as conn:
            # Resolve entity IDs
            entity_ids: list[str] = list(event.get("extracted_entity_ids") or [])
            for ent in event.get("extracted_entity_names") or []:
                eid = self._upsert_entity(
                    conn, user_id, ent["entity_type"], ent["name"]
                )
                if eid not in entity_ids:
                    entity_ids.append(eid)

            if not entity_ids:
                logger.warning(
                    "ingest_conversation_event: no entities resolved — session=%s. "
                    "Check extraction output.",
                    session_id,
                )
                return {}

            now      = _now_iso()
            event_id = _uid()

            # Persist the conversation_event record
            conversation_event_repository.insert(
                conn,
                event_id                  = event_id,
                session_id                = session_id,
                user_id                   = user_id,
                star_situation            = event.get("star_situation"),
                star_task                 = event.get("star_task"),
                star_action               = event.get("star_action"),
                star_result               = event.get("star_result"),
                extracted_entity_ids_json = json.dumps(entity_ids),
                extraction_confidence     = extraction_conf,
                analyzed_at               = now,
                raw_quote                 = event.get("raw_quote", ""),
            )

            # Build the raw_content summary stored in each evidence_record
            star_parts = [
                f"Situation: {event.get('star_situation', '')}" if event.get("star_situation") else "",
                f"Task: {event.get('star_task', '')}"           if event.get("star_task")      else "",
                f"Action: {event.get('star_action', '')}"       if event.get("star_action")    else "",
                f"Result: {event.get('star_result', '')}"       if event.get("star_result")    else "",
            ]
            raw_content = "\n".join(p for p in star_parts if p)

            results: dict[str, float] = {}

            for entity_id in entity_ids:
                ev_id = _uid()
                conn.execute(
                    text("""
                        INSERT INTO evidence_records
                            (evidence_id, entity_id, user_id, source_type,
                             base_weight, raw_content, verified_at,
                             session_id, event_id, metadata)
                        VALUES
                            (:evid, :eid, :uid, 'conversation_star',
                             :w, :raw, :now,
                             :sid, :cevid, :meta)
                    """),
                    {
                        "evid":  ev_id,
                        "eid":   entity_id,
                        "uid":   user_id,
                        "w":     effective_weight,
                        "raw":   raw_content,
                        "now":   now,
                        "sid":   session_id,
                        "cevid": event_id,
                        "meta":  json.dumps({"extraction_confidence": extraction_conf}),
                    },
                )
                new_score = self._recompute_and_persist(
                    conn, entity_id, user_id,
                    trigger_source="conversation_star",
                    new_evidence_id=ev_id,
                    session_id=session_id,
                    note=f"STAR event confidence={extraction_conf:.2f}",
                )
                results[entity_id] = new_score

            # Update session's running confidence delta
            session_delta = sum(results.values())
            conn.execute(
                text("""
                    UPDATE ariel_sessions
                    SET    confidence_delta_total = confidence_delta_total + :delta
                    WHERE  session_id = :sid
                """),
                {"delta": session_delta, "sid": session_id},
            )

        logger.info(
            "ingest_conversation_event %s: %d entities updated  session=%s",
            event_id, len(results), session_id,
        )
        return results

    # ─────────────────────────────────────────────────────────────────────────
    # Public: Negative flag ingestion
    # ─────────────────────────────────────────────────────────────────────────

    def ingest_negative_flag(
        self,
        user_id: str,
        entity_id: str,
        session_id: str,
        flag_type: str,
        raw_content: str,
        flag_reason: str,
        weight_override: Optional[float] = None,
    ) -> float:
        """
        Append a negative evidence record and recompute confidence downward.

        Immutability rules
        ------------------
        • The evidence_records row is append-only — never deleted.
        • The penalty decays over time (180-day half-life) so fresh positive
          evidence can recover the score naturally.

        Side effects
        ------------
        • If the recomputed score falls below MANUAL_REVIEW_THRESHOLD (30.0),
          manual_review_required is set to 1 on profile_entities.
          This prevents Ariel from probing the entity in an automated loop —
          a human must review the contradiction first.
        • The audit log records the delta so the confidence history is traceable.

        Parameters
        ----------
        user_id : str
        entity_id : str
            Must already exist in profile_entities.
        session_id : str
            The Ariel session during which the flag was detected.
        flag_type : str
            One of: 'contradiction', 'shallow_star', 'inconsistency'.
        raw_content : str
            The verbatim text that triggered the flag (conflicting statements,
            thin STAR answer, etc.).
        flag_reason : str
            Human-readable explanation produced by the LLM evaluator.
        weight_override : float | None
            Negative float in [−50, 0].  Defaults to BASE_WEIGHTS['negative_flag']
            (−25.0).  Pass a value closer to 0 for mild flags, farther for severe.

        Returns
        -------
        float   New confidence score after the penalty.
        """
        valid_flag_types = {"contradiction", "shallow_star", "inconsistency"}
        if flag_type not in valid_flag_types:
            raise ValueError(
                f"flag_type must be one of {valid_flag_types}, got {flag_type!r}"
            )

        base_weight = float(weight_override or BASE_WEIGHTS["negative_flag"])
        if base_weight > 0:
            raise ValueError("weight_override for a negative flag must be ≤ 0")

        with self._engine.begin() as conn:
            ev_id = _uid()
            now   = _now_iso()

            conn.execute(
                text("""
                    INSERT INTO evidence_records
                        (evidence_id, entity_id, user_id, source_type,
                         base_weight, raw_content, verified_at,
                         session_id, metadata)
                    VALUES
                        (:evid, :eid, :uid, 'negative_flag',
                         :w, :raw, :now,
                         :sid, :meta)
                """),
                {
                    "evid": ev_id,
                    "eid":  entity_id,
                    "uid":  user_id,
                    "w":    base_weight,
                    "raw":  raw_content,
                    "now":  now,
                    "sid":  session_id,
                    "meta": json.dumps({
                        "flag_type":  flag_type,
                        "flag_reason": flag_reason,
                    }),
                },
            )

            new_score = self._recompute_and_persist(
                conn, entity_id, user_id,
                trigger_source="negative_flag",
                new_evidence_id=ev_id,
                session_id=session_id,
                note=f"Negative flag [{flag_type}]: {flag_reason}",
            )

            # Set manual_review_required if the score crossed the threshold.
            # _recompute_and_persist already CLEARS the flag on recovery;
            # this is the only place that SETS it.
            if new_score < MANUAL_REVIEW_THRESHOLD:
                conn.execute(
                    text("""
                        UPDATE profile_entities
                        SET    manual_review_required = 1,
                               updated_at             = :now
                        WHERE  entity_id = :eid
                    """),
                    {"now": now, "eid": entity_id},
                )
                logger.warning(
                    "negative_flag: entity=%s score=%.1f < %.1f threshold → "
                    "manual_review_required set. flag_type=%s reason=%r",
                    entity_id, new_score, MANUAL_REVIEW_THRESHOLD,
                    flag_type, flag_reason,
                )

        logger.info(
            "ingest_negative_flag: entity=%s  Δ%.1f  flag=%s  session=%s",
            entity_id, new_score, flag_type, session_id,
        )
        return new_score

    # ─────────────────────────────────────────────────────────────────────────
    # Public: Contextual reinforcement ingestion
    # ─────────────────────────────────────────────────────────────────────────

    def ingest_contextual_reinforcement(
        self,
        user_id: str,
        session_id: str,
        transcript_text: str,
        min_entity_name_chars: int = 4,
        weight_override: Optional[float] = None,
    ) -> dict[str, float]:
        """
        Scan a session transcript for unprompted skill mentions and append
        low-weight contextual_reinforcement evidence for each matched entity.

        "Contextual reinforcement" is the Trust Tier 2 signal: the user
        demonstrates fluency with a skill in conversation without being directly
        asked about it (e.g., mentioning "OKR alignment" while discussing a
        roadmap conflict).  Unlike a STAR probe, no structured evaluation is
        needed — the mere presence of the skill term in a coherent context is
        sufficient to bump the confidence.

        Matching algorithm
        ------------------
        For each entity in the user's profile_entities:
          1. Build a regex pattern from the entity's normalized name
             (underscores → spaces, anchored by word boundaries).
          2. Search the lowercased transcript.
          3. If found AND no contextual_reinforcement record exists for this
             session_id + entity_id (idempotency guard), append an evidence row.

        Deduplication
        -------------
        The method is safe to call multiple times for the same session —
        the SELECT … WHERE session_id = :sid AND source_type = 'contextual_reinforcement'
        guard ensures each entity only gets one reinforcement record per session.

        Minimum entity name length
        --------------------------
        Entities with normalised names shorter than min_entity_name_chars (default 4)
        are skipped to avoid false matches on single-letter abbreviations or
        common short words.

        Parameters
        ----------
        user_id : str
        session_id : str
            The Ariel session whose transcript is being scanned.
        transcript_text : str
            Full text of the session conversation (all turns concatenated or
            the raw transcript string).
        min_entity_name_chars : int
            Minimum character length of the entity name to attempt matching.
        weight_override : float | None
            Override the base weight (default BASE_WEIGHTS['contextual_reinforcement']).

        Returns
        -------
        dict[str, float]
            {entity_id: new_confidence_score} for each entity that received
            a new reinforcement record this call.  Empty dict if no matches.
        """
        if not transcript_text or not transcript_text.strip():
            return {}

        base_weight = float(weight_override or BASE_WEIGHTS["contextual_reinforcement"])
        transcript_lower = transcript_text.lower()
        now = _now_iso()
        results: dict[str, float] = {}

        with self._engine.begin() as conn:
            # Fetch all entities for this user that could appear in the transcript.
            entity_rows = conn.execute(
                text("""
                    SELECT entity_id, normalized_name, name
                    FROM   profile_entities
                    WHERE  user_id      = :uid
                      AND  entity_type IN ('skill', 'trait', 'domain')
                """),
                {"uid": user_id},
            ).fetchall()

            for entity_id, normalized_name, display_name in entity_rows:

                # Skip entities whose name is too short for reliable matching.
                if len(normalized_name) < min_entity_name_chars:
                    continue

                # Build search term: underscores → spaces for natural text matching.
                search_term = normalized_name.replace("_", " ")

                # Word-boundary regex prevents partial matches
                # (e.g., "manage" must not match inside "management").
                pattern = r"\b" + re.escape(search_term) + r"\b"
                if not re.search(pattern, transcript_lower):
                    continue

                # Idempotency: skip if this session already reinforced this entity.
                existing = conn.execute(
                    text("""
                        SELECT COUNT(*)
                        FROM   evidence_records
                        WHERE  entity_id   = :eid
                          AND  session_id  = :sid
                          AND  source_type = 'contextual_reinforcement'
                    """),
                    {"eid": entity_id, "sid": session_id},
                ).fetchone()

                if existing and existing[0] > 0:
                    logger.debug(
                        "contextual_reinforcement: entity=%s already reinforced "
                        "in session=%s — skipping",
                        entity_id, session_id,
                    )
                    continue

                # Extract a short excerpt (first match context ±60 chars).
                match = re.search(pattern, transcript_lower)
                excerpt = ""
                if match:
                    start = max(0, match.start() - 60)
                    end   = min(len(transcript_lower), match.end() + 60)
                    excerpt = transcript_text[start:end].strip()

                # Append the reinforcement evidence record.
                ev_id = _uid()
                conn.execute(
                    text("""
                        INSERT INTO evidence_records
                            (evidence_id, entity_id, user_id, source_type,
                             base_weight, raw_content, verified_at,
                             session_id, metadata)
                        VALUES
                            (:evid, :eid, :uid, 'contextual_reinforcement',
                             :w, :raw, :now,
                             :sid, :meta)
                    """),
                    {
                        "evid": ev_id,
                        "eid":  entity_id,
                        "uid":  user_id,
                        "w":    base_weight,
                        "raw":  excerpt,
                        "now":  now,
                        "sid":  session_id,
                        "meta": json.dumps({
                            "search_term":  search_term,
                            "match_method": "word_boundary_regex",
                        }),
                    },
                )

                new_score = self._recompute_and_persist(
                    conn, entity_id, user_id,
                    trigger_source="contextual_reinforcement",
                    new_evidence_id=ev_id,
                    session_id=session_id,
                    note=f"Contextual mention of '{display_name}' in session transcript",
                )
                results[entity_id] = new_score

        if results:
            logger.info(
                "ingest_contextual_reinforcement: session=%s  %d entities reinforced: %s",
                session_id,
                len(results),
                {eid: f"{score:.1f}" for eid, score in results.items()},
            )
        else:
            logger.debug(
                "ingest_contextual_reinforcement: session=%s  no new entity matches found",
                session_id,
            )

        return results

    # ─────────────────────────────────────────────────────────────────────────
    # Public: Gap queue management
    # ─────────────────────────────────────────────────────────────────────────

    def enqueue_gap(
        self,
        user_id: str,
        entity_id: str,
        required_confidence: float,
        job_id: Optional[str] = None,
    ) -> Optional[str]:
        """
        Add a detected gap to ariel_gap_queue.

        Skips silently if an identical open gap already exists for this
        (user_id, entity_id, job_id) combination (idempotent).

        Returns
        -------
        str | None
            gap_id if a new gap was enqueued, None if it already existed.
        """
        with self._engine.begin() as conn:
            # Fetch current confidence
            row = conn.execute(
                text("SELECT confidence_score FROM profile_entities WHERE entity_id = :eid"),
                {"eid": entity_id},
            ).fetchone()
            current = float(row[0]) if row else 0.0

            if current >= required_confidence:
                return None   # already meets threshold — no gap

            # Idempotency check
            exists = ariel_gap_queue_repository.find_open_gap(conn, user_id, entity_id, job_id)

            if exists:
                return None   # already queued

            severity = gap_severity(current, required_confidence)
            gap_id   = _uid()
            now      = _now_iso()

            ariel_gap_queue_repository.insert(
                conn,
                gap_id               = gap_id,
                user_id              = user_id,
                entity_id            = entity_id,
                job_id               = job_id,
                current_confidence   = current,
                required_confidence  = required_confidence,
                gap_severity         = severity,
                detected_at          = now,
            )

        logger.info(
            "gap_queue: enqueued gap_id=%s entity=%s severity=%s user=%s job=%s",
            gap_id, entity_id, severity, user_id, job_id,
        )
        return gap_id

    def resolve_gap(self, gap_id: str) -> None:
        """Mark a gap as resolved (entity score now meets threshold)."""
        ariel_gap_queue_repository.resolve(gap_id, _now_iso(), engine=self._engine)

    def open_session(
        self,
        user_id: str,
        session_type: str,
        target_entities: Optional[list[str]] = None,
        target_job_id: Optional[str] = None,
        ariel_goal: Optional[str] = None,
    ) -> str:
        """
        Create a new Ariel session row and return its session_id.

        Call this before the first Ariel turn so ingest_conversation_event()
        has a valid foreign key to reference.
        """
        session_id = _uid()
        now        = _now_iso()
        ariel_session_repository.create_session(
            session_id=session_id,
            user_id=user_id,
            session_type=session_type,
            started_at=now,
            target_job_id=target_job_id,
            target_entities=target_entities,
            ariel_goal=ariel_goal,
            engine=self._engine,
        )
        return session_id

    def close_session(self, session_id: str, status: str = "completed") -> None:
        """Mark an Ariel session as completed or abandoned."""
        now = _now_iso()
        ariel_session_repository.update_status(session_id, status, now, engine=self._engine)

    # ─────────────────────────────────────────────────────────────────────────
    # Public: weighted overall trust score
    # ─────────────────────────────────────────────────────────────────────────

    def compute_profile_trust_score(
        self, user_id: str, profile: Optional[dict] = None
    ) -> float:
        """
        Compute the System Confidence Score as a "Holistic Familiarity" metric.

        Philosophy (Phase 31)
        ---------------------
        This score does NOT measure "how skilled the user is." It measures how
        well and how deeply the system KNOWS the user's true profile. The two
        are deliberately decoupled: a user can be a self-declared beginner at
        everything, and if the system knows that clearly and completely, its
        confidence in its *understanding* is high.

        This replaces the Phase 29 "Core Profile average", which measured skill
        (a mean of the strongest capped entities) and therefore dropped to ~33
        for a heavily-parsed, lightly-verified profile — punishing exactly the
        user the system knows the most about. The four governing rules:

        1. Breadth is the baseline. Volume of known entities maps the user's
           landscape; a large parsed profile secures a solid baseline on its
           own, regardless of how weak or unverified any single entity is.
        2. Honesty is confidence. Low-proficiency or unverified entities are
           NEVER penalties. A beginner skill adds to breadth like any other,
           and a user CLARIFYING a weakness (proficiency_level set) adds to
           depth — knowing a weakness is knowledge.
        3. Depth is the path to 100. Verifying the user's claims (STAR probes,
           whiteboard tests, chat confirmations) is what carries the score up
           from the breadth baseline toward full confidence.
        4. Monotonic growth. Every pillar is a non-decreasing function of the
           counts it consumes, so adding data, correcting the system, or
           verifying a claim can only raise (never lower) the score.

        Architecture — three additive pillars, summed and clamped to [0, 100]
        --------------------------------------------------------------------
          BREADTH  (≤ BREADTH_MAX)   = BREADTH_MAX · (1 − e^(−N / BREADTH_SCALE))
              N = total known entities (all types, all confidence levels).

          DEPTH    (≤ DEPTH_MAX)     = DEPTH_MAX · (1 − e^(−V / DEPTH_SCALE))
              V = Σ per-entity verification weight, where an entity scores
              VERIFICATION_WEIGHTS[status], floored at
              PROFICIENCY_MIN_VERIFICATION_WEIGHT (0.5) whenever the user has
              clarified its proficiency_level. This is where honest correction
              of a weak skill lifts the score.

          CONTEXT  (≤ 20)           = coverage + identity + proficiency, all
              strictly additive positives (never penalties):
                coverage    = CONTEXT_COVERAGE_MAX · (distinct categories / 4)
                identity    = CONTEXT_IDENTITY_MAX · (name/phone/prefs known / 3)
                proficiency = CONTEXT_PROFICIENCY_MAX ·
                              (1 − e^(−P / CONTEXT_PROFICIENCY_SCALE))
              P = entities with a user-clarified proficiency_level.

        Note: raw confidence_score is intentionally NOT read here — it measures
        skill, which this metric must not reflect. Familiarity comes from count
        (breadth), verification (depth), and coverage/identity/engagement.

        Parameters
        ----------
        user_id : str
            The user whose profile familiarity is scored.
        profile : dict, optional
            The user's base profile (as returned by user_profile_store.load).
            Injectable for testing / to avoid a redundant disk read; when
            omitted it is loaded from the per-user profile store.

        Returns
        -------
        float   Familiarity score in [0.0, 100.0], 1 decimal place.
                Monotonically non-decreasing as the system learns more.

        See also
        --------
        compute_profile_familiarity : returns the same overall value plus its
        three-pillar breakdown (breadth / depth / context) for the UI.
        """
        return self.compute_profile_familiarity(user_id, profile)["overall"]

    def compute_profile_familiarity(
        self, user_id: str, profile: Optional[dict] = None
    ) -> dict:
        """
        Compute the Holistic Familiarity score AND its three-pillar breakdown.

        This is the source of truth for compute_profile_trust_score (which just
        returns ``["overall"]``) and for the profile/trust-score endpoint, which
        surfaces the pillars so the UI can show WHY the score is what it is
        instead of a single black-box number.

        Returns
        -------
        dict with 1-decimal floats:
            {
              "overall": 0-100,   # breadth + depth + context, clamped
              "breadth": 0-BREADTH_MAX,   # volume of known entities
              "depth":   0-DEPTH_MAX,     # graded verification + honest levels
              "context": 0-20,            # coverage + identity + engagement
            }
        An empty profile returns all-zero pillars.
        """
        empty = {"overall": 0.0, "breadth": 0.0, "depth": 0.0, "context": 0.0}

        with self._engine.connect() as conn:
            rows = conn.execute(
                text("""
                    SELECT entity_type, verification_status, proficiency_level
                    FROM   profile_entities
                    WHERE  user_id = :uid
                """),
                {"uid": user_id},
            ).fetchall()

        if not rows:
            return dict(empty)

        # ── Tally the counts each pillar consumes ────────────────────────────
        n_entities        = len(rows)              # breadth volume (every entity)
        verification_sum  = 0.0                    # depth (graded verification)
        proficiency_count = 0                      # engagement (clarified levels)
        categories_seen: set[str] = set()          # coverage

        for entity_type, vstatus, proficiency in rows:
            etype = str(entity_type or "").lower()
            if etype in self._SCORED_CATEGORIES:
                categories_seen.add(etype)

            status_weight = self.VERIFICATION_WEIGHTS.get(
                str(vstatus or "").lower(), 0.0
            )
            has_proficiency = bool(str(proficiency or "").strip())
            if has_proficiency:
                proficiency_count += 1
                # A clarified weakness is still confirmed knowledge — floor the
                # verification weight so honesty always builds depth.
                status_weight = max(
                    status_weight, self.PROFICIENCY_MIN_VERIFICATION_WEIGHT
                )
            verification_sum += status_weight

        # ── Pillar 1: BREADTH ────────────────────────────────────────────────
        breadth = self.BREADTH_MAX * (
            1.0 - math.exp(-n_entities / self.BREADTH_SCALE)
        )

        # ── Pillar 2: DEPTH ──────────────────────────────────────────────────
        depth = self.DEPTH_MAX * (
            1.0 - math.exp(-verification_sum / self.DEPTH_SCALE)
        )

        # ── Pillar 3: CONTEXT (coverage + identity + proficiency engagement) ──
        coverage = self.CONTEXT_COVERAGE_MAX * (
            len(categories_seen) / len(self._SCORED_CATEGORIES)
        )

        if profile is None:
            try:
                from backend.services import user_profile_store
                profile = user_profile_store.load(user_id)
            except Exception:
                profile = None
        identity = self.CONTEXT_IDENTITY_MAX * _base_profile_completeness_fraction(profile)

        proficiency_engagement = self.CONTEXT_PROFICIENCY_MAX * (
            1.0 - math.exp(-proficiency_count / self.CONTEXT_PROFICIENCY_SCALE)
        )

        context = coverage + identity + proficiency_engagement

        # ── Sum the pillars, clamp, round ────────────────────────────────────
        total = min(max(breadth + depth + context, 0.0), 100.0)
        return {
            "overall": round(total, 1),
            "breadth": round(breadth, 1),
            "depth":   round(depth, 1),
            "context": round(context, 1),
        }

    # ─────────────────────────────────────────────────────────────────────────
    # Chat-driven entity UPDATE (proficiency / confidence correction)
    # ─────────────────────────────────────────────────────────────────────────

    def apply_chat_proficiency_update(
        self,
        user_id: str,
        name: str,
        *,
        entity_type: str = "skill",
        proficiency_level: Optional[str] = None,
        new_confidence: Optional[float] = None,
        confidence_modifier: Optional[float] = None,
        note: Optional[str] = None,
    ) -> dict:
        """
        UPDATE an existing profile entity in place from a chat clarification.

        This is the write path for the case the user hit in Phase 30: the
        parsed profile scored "Python" at 51.7, the user clarified they are
        only a Beginner, and Ariel needs to LOWER the confidence and record the
        stated proficiency — not add or remove the skill.

        Unlike the evidence-ingest paths, this is a *direct correction*: the
        user has authoritatively stated their own level, so we override the
        score rather than blending in another weak evidence row. To honour the
        "ProfileUpdateService is the only writer of confidence_score" invariant
        (see db.py), the update lives here and writes a confidence_audit_log
        row for traceability.

        Resolution order for the new confidence_score:
          1. ``new_confidence``       — explicit target from the agent (wins).
          2. ``confidence_modifier``  — signed delta applied to the current score.
          3. ``proficiency_level``    — anchor DOWN to PROFICIENCY_CEILINGS[level]
             (i.e. min(current, ceiling)); a self-claim never inflates a score.
          4. none of the above        — score unchanged (proficiency label only).

        The final score is clamped to [0, 100]. verification_status is set to
        'verified' because the value is now user-confirmed (whether that raised
        or lowered it) — a chat admission is direct validation of the true level.

        Returns
        -------
        dict with keys: status ('updated' | 'not_found' | 'error'),
        and on success: name, entity_type, old_score, new_score,
        proficiency_level, verification_status.
        """
        normalized = _normalize(name)
        now = _now_iso()

        try:
            with self._engine.begin() as conn:
                row = conn.execute(
                    text("""
                        SELECT entity_id, confidence_score, proficiency_level
                        FROM   profile_entities
                        WHERE  user_id = :uid
                          AND  normalized_name = :norm
                          AND  entity_type = :etype
                        LIMIT 1
                    """),
                    {"uid": user_id, "norm": normalized, "etype": entity_type},
                ).fetchone()

                if row is None:
                    return {
                        "status": "not_found",
                        "name": name,
                        "entity_type": entity_type,
                    }

                entity_id  = row[0]
                old_score  = float(row[1])
                old_prof   = row[2]

                # ── Resolve the new confidence score ──────────────────────────
                if new_confidence is not None:
                    target = float(new_confidence)
                elif confidence_modifier is not None:
                    target = old_score + float(confidence_modifier)
                elif proficiency_level:
                    ceiling = self.PROFICIENCY_CEILINGS.get(
                        proficiency_level.strip().lower()
                    )
                    # Only anchor down to a known level's ceiling; unknown
                    # labels leave the score untouched (label recorded only).
                    target = min(old_score, ceiling) if ceiling is not None else old_score
                else:
                    target = old_score

                new_score = round(min(max(target, 0.0), 100.0), 1)

                # proficiency_level: COALESCE so omitting it preserves any prior
                # label; passing it overwrites.
                new_prof = proficiency_level.strip() if proficiency_level else None

                conn.execute(
                    text("""
                        UPDATE profile_entities
                        SET    confidence_score    = :score,
                               proficiency_level   = COALESCE(:prof, proficiency_level),
                               verification_status = 'verified',
                               updated_at          = :now
                        WHERE  entity_id = :eid
                    """),
                    {"score": new_score, "prof": new_prof, "now": now, "eid": entity_id},
                )

                # Immutable audit trail — mirrors _recompute_and_persist so the
                # System Confidence history shows chat corrections too.
                conn.execute(
                    text("""
                        INSERT INTO confidence_audit_log
                            (entity_id, user_id, old_score, new_score, delta,
                             trigger_source, evidence_id, session_id, changed_at, note)
                        VALUES
                            (:eid, :uid, :old, :new, :delta,
                             'chat_proficiency_update', NULL, NULL, :now, :note)
                    """),
                    {
                        "eid":   entity_id,
                        "uid":   user_id,
                        "old":   old_score,
                        "new":   new_score,
                        "delta": round(new_score - old_score, 1),
                        "now":   now,
                        "note":  note or (
                            f"chat proficiency update: {old_prof or '—'} → "
                            f"{new_prof or old_prof or '—'}"
                        ),
                    },
                )

            logger.info(
                "[profile_update] chat proficiency update user=%s '%s' (%s) "
                "%.1f → %.1f  proficiency=%s",
                user_id, name, entity_type, old_score, new_score,
                new_prof or old_prof,
            )
            return {
                "status":              "updated",
                "name":                name,
                "entity_type":         entity_type,
                "old_score":           round(old_score, 1),
                "new_score":           new_score,
                "proficiency_level":   new_prof or old_prof,
                "verification_status": "verified",
            }

        except Exception as exc:
            logger.error(
                "[profile_update] apply_chat_proficiency_update failed user=%s name=%r: %s",
                user_id, name, exc,
            )
            return {"status": "error", "name": name, "error": str(exc)}
