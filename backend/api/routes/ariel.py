"""
Ariel Probe API routes
======================

POST /api/ariel/probe/start    — start a STAR behavioral probe session for a
                                  low-confidence entity and return the first
                                  question.

POST /api/ariel/probe/respond  — submit a turn answer; returns the next question
                                  or, after the 3rd turn, fires the LLM evaluator
                                  and returns the evaluation result with the
                                  updated confidence score.

GET  /api/ariel/probe/pending  — list all entities currently eligible for probing
                                  (confidence < 70, not flagged for review, not
                                  probed in the last 48 h).

GET  /api/ariel/audit/{entity_id}
                               — return the full confidence_audit_log for one
                                 entity so the ManualReviewModal can surface the
                                 exact note that explains a negative flag.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.api.deps import CurrentUser, get_current_user
from backend.core.database import ENGINE
from backend.repositories import ariel_session_repository
from backend.repositories import confidence_audit_log_repository
from backend.repositories import profile_entity_repository
from backend.services.profile_update_service import ProfileUpdateService
from backend.services.ariel_probe_service import ArielProbeService

logger = logging.getLogger(__name__)
router = APIRouter()

# ── Shared service factory ────────────────────────────────────────────────────

def _svc() -> ArielProbeService:
    pus = ProfileUpdateService(ENGINE)
    return ArielProbeService(ENGINE, pus)

def _pus() -> ProfileUpdateService:
    return ProfileUpdateService(ENGINE)


# ── POST /api/ariel/probe/start ───────────────────────────────────────────────

class ProbeStartRequest(BaseModel):
    entity_id: str

class ProbeStartResponse(BaseModel):
    session_id:       str
    entity_id:        str
    entity_name:      str
    turn:             int        # always 1 on a fresh start
    question:         str
    confidence_score: float


@router.post("/probe/start", response_model=ProbeStartResponse)
async def start_probe(
    req:  ProbeStartRequest,
    user: CurrentUser = Depends(get_current_user),
):
    """
    Initialise a STAR behavioral probe session for the given entity.

    Pre-conditions (enforced here so the frontend gets a clear error):
      • entity must exist and belong to the caller
      • confidence_score must be < 70
      • manual_review_required must be 0

    Creates an ariel_sessions row (type='behavioral_interview'), writes the
    probe_log entry for cooldown tracking, and returns the first STAR question
    (Situation turn).

    The session_id must be threaded through every subsequent /respond call.
    """
    entity = profile_entity_repository.get_by_id(req.entity_id)

    if entity is None:
        raise HTTPException(status_code=404, detail="Entity not found.")
    if entity.user_id != user.user_id:
        raise HTTPException(status_code=403, detail="Entity does not belong to you.")
    if entity.manual_review_required:
        raise HTTPException(
            status_code=409,
            detail=(
                "This entity is flagged for manual review. "
                "Ariel cannot probe it until a human reviewer approves."
            ),
        )
    if entity.confidence_score >= 70:
        raise HTTPException(
            status_code=409,
            detail=f"Entity confidence is {entity.confidence_score:.1f} (≥70). No probe needed.",
        )

    svc = _svc()
    pus = _pus()

    # Open the Ariel session (creates ariel_sessions row)
    session_id = pus.open_session(
        user_id        = user.user_id,
        session_type   = "behavioral_interview",
        target_entities= [req.entity_id],
        ariel_goal     = f"STAR probe: {entity.name}",
    )

    entity_dict = {
        "entity_id":        entity.entity_id,
        "name":             entity.name,
        "entity_type":      entity.entity_type,
        "confidence_score": entity.confidence_score,
    }

    question = svc.get_probe_question(entity_dict, turn=1)

    logger.info(
        "[ariel/probe/start] user=%s entity=%s (%s) session=%s",
        user.user_id, req.entity_id, entity.name, session_id,
    )

    return ProbeStartResponse(
        session_id       = session_id,
        entity_id        = req.entity_id,
        entity_name      = entity.name,
        turn             = 1,
        question         = question,
        confidence_score = entity.confidence_score,
    )


# ── POST /api/ariel/probe/respond ─────────────────────────────────────────────

class ProbeRespondRequest(BaseModel):
    session_id: str
    entity_id:  str
    turn:       int        # 1, 2, or 3
    answer:     str

class ProbeRespondResponse(BaseModel):
    session_id:        str
    entity_id:         str
    turn:              int
    # present when turn < 3 (next question)
    next_question:          Optional[str]   = None
    # present when turn == 3 and LLM succeeded
    evaluation_done:        bool            = False
    flag_type:              Optional[str]   = None
    new_confidence:         Optional[float] = None
    extraction_confidence:  Optional[float] = None
    # present when LLM timed out / errored — user should retry turn 3
    retry_suggested:        bool            = False
    retry_message:          Optional[str]   = None


@router.post("/probe/respond", response_model=ProbeRespondResponse)
async def respond_to_probe(
    req:  ProbeRespondRequest,
    user: CurrentUser = Depends(get_current_user),
):
    """
    Submit a turn answer within an active probe session.

    Turns 1–2 → return the next STAR question.
    Turn 3 → fire the LLM evaluator, call ingest_conversation_event or
              ingest_negative_flag, close the session, and return the result.

    The frontend must store all three answers locally (turn_1, turn_2, turn_3)
    and include them all in the turn-3 request via the `answer` field.  Or the
    frontend can just send the single turn answer and we accumulate in-session
    via the ariel_sessions.transcript_json field.

    Design choice: we accumulate turns in the session transcript so this endpoint
    is stateless on the client side — each turn only needs to send its own answer.
    """
    if req.turn not in (1, 2, 3):
        raise HTTPException(status_code=422, detail="turn must be 1, 2, or 3.")

    entity = profile_entity_repository.get_by_id(req.entity_id)

    if entity is None:
        raise HTTPException(status_code=404, detail="Entity not found.")
    if entity.user_id != user.user_id:
        raise HTTPException(status_code=403, detail="Entity does not belong to you.")

    # ── Accumulate the answer in session transcript_json ─────────────────────
    # Filtered by user_id (not just session_id) so a caller can never read or
    # write another user's session transcript — mismatch is indistinguishable
    # from "not found". append_turn() merges the new answer in atomically (a
    # single UPDATE...RETURNING statement), so two concurrent requests for
    # the same session can never race and silently drop one turn's answer.
    transcript = ariel_session_repository.append_turn(req.session_id, user.user_id, req.turn, req.answer)

    if transcript is None:
        raise HTTPException(status_code=404, detail="Session not found.")

    entity_dict = {
        "entity_id":        entity.entity_id,
        "name":             entity.name,
        "entity_type":      entity.entity_type,
        "confidence_score": entity.confidence_score,
    }

    svc = _svc()
    pus = _pus()

    # ── Turns 1–2: return next question ──────────────────────────────────────
    if req.turn < 3:
        next_q = svc.get_probe_question(entity_dict, turn=req.turn + 1)
        return ProbeRespondResponse(
            session_id    = req.session_id,
            entity_id     = req.entity_id,
            turn          = req.turn + 1,
            next_question = next_q,
        )

    # ── Turn 3: evaluate + conditionally ingest ──────────────────────────────
    # Ensure we have all three turns; earlier turns may already be in transcript.
    full_transcript = {
        "turn_1": transcript.get("turn_1", ""),
        "turn_2": transcript.get("turn_2", ""),
        "turn_3": transcript.get("turn_3", req.answer),
    }

    evaluation = await svc.evaluate_star_response(
        full_transcript, entity_dict, session_id=req.session_id
    )

    # ── LLM timeout / error → don't ingest; let the user retry ───────────────
    # retry_suggested=True means the LLM call failed (timeout or API error).
    # We leave the session open (status stays 'active') so the user can submit
    # a fresh turn-3 answer.  No evidence — positive or negative — is recorded.
    if evaluation.get("retry_suggested"):
        logger.warning(
            "[ariel/probe/respond] LLM eval failed — retry suggested "
            "entity=%s session=%s",
            req.entity_id, req.session_id,
        )
        return ProbeRespondResponse(
            session_id    = req.session_id,
            entity_id     = req.entity_id,
            turn          = 3,             # stay on turn 3 so the user can retry
            retry_suggested = True,
            retry_message   = evaluation.get("retry_message"),
        )

    # ── LLM succeeded → commit evidence + close session ──────────────────────
    svc.record_probe_outcome(user.user_id, entity_dict, req.session_id, evaluation)
    pus.close_session(req.session_id)

    # Fetch updated confidence score after evidence was ingested
    refreshed = profile_entity_repository.get_by_id(req.entity_id)
    new_conf = refreshed.confidence_score if refreshed else None

    logger.info(
        "[ariel/probe/respond] turn=3 complete — entity=%s flag=%s "
        "new_conf=%s session=%s",
        req.entity_id, evaluation.get("flag_type"), new_conf, req.session_id,
    )

    return ProbeRespondResponse(
        session_id            = req.session_id,
        entity_id             = req.entity_id,
        turn                  = 3,
        evaluation_done       = True,
        flag_type             = evaluation.get("flag_type"),
        new_confidence        = new_conf,
        extraction_confidence = evaluation.get("extraction_confidence"),
    )


# ── GET /api/ariel/probe/pending ──────────────────────────────────────────────

@router.get("/probe/pending")
async def get_pending_probes(user: CurrentUser = Depends(get_current_user)):
    """
    Return all entities eligible for a STAR probe for the authenticated user.
    Ordered weakest-first (ascending confidence_score).
    """
    svc  = _svc()
    probes = svc.get_pending_probes(user.user_id)
    return {"entities": probes, "count": len(probes)}


# ── GET /api/ariel/audit/{entity_id} ─────────────────────────────────────────

@router.get("/audit/{entity_id}")
async def get_entity_audit(
    entity_id: str,
    user:      CurrentUser = Depends(get_current_user),
):
    """
    Return the full confidence_audit_log for one entity so the
    ManualReviewModal can surface the exact flag note.

    Also returns the entity name and current confidence_score.

    Access control: entity must belong to the caller.
    """
    entity = profile_entity_repository.get_by_id(entity_id)

    if entity is None:
        raise HTTPException(status_code=404, detail="Entity not found.")
    if entity.user_id != user.user_id:
        raise HTTPException(status_code=403, detail="Entity does not belong to you.")

    audit_log = confidence_audit_log_repository.get_recent_for_entity(entity_id, limit=50)

    # Surface the most recent negative-flag note for the ManualReviewModal
    latest_flag_note = next(
        (
            e["note"]
            for e in audit_log
            if e["trigger_source"] == "negative_flag" and e["note"]
        ),
        None,
    )

    return {
        "entity_id":        entity_id,
        "entity_name":      entity.name,
        "entity_type":      entity.entity_type,
        "confidence_score": entity.confidence_score,
        "manual_review_required": bool(entity.manual_review_required),
        "latest_flag_note": latest_flag_note,
        "audit_log":        audit_log,
    }
