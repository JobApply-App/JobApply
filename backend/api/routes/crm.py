"""
CRM Kanban API — application pipeline board.

GET  /api/crm/board   → CrmBoard  (all pipeline columns with their cards)
POST /api/crm/move    → MoveResponse (drag a card to a new stage column)

Column stages are always returned in canonical order even when empty, so
the frontend can render a static 6-column skeleton without conditional logic.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.api.deps import CurrentUser, get_current_user
from backend.repositories import application_repository

router  = APIRouter()
logger  = logging.getLogger(__name__)

# ── Canonical stage taxonomy ──────────────────────────────────────────────────

_STAGES: list[tuple[str, str]] = [
    ("submitted",    "Submitted"),
    ("phone screen", "Phone Screen"),
    ("technical",    "Technical"),
    ("interview",    "Interview"),
    ("offer",        "Offer"),
    ("rejected",     "Rejected"),
]

_VALID_STAGE_KEYS: frozenset[str] = frozenset(s for s, _ in _STAGES)

# Stages a card can be moved INTO (no re-entering excluded/unknown stages)
_MOVABLE_STAGES: frozenset[str] = _VALID_STAGE_KEYS


# ── Pydantic models ───────────────────────────────────────────────────────────

class CrmCard(BaseModel):
    application_id: str
    job_id:         str
    company:        str
    title:          str
    last_update:    str
    score:          float


class CrmColumn(BaseModel):
    stage:  str
    label:  str
    cards:  List[CrmCard]


class CrmBoard(BaseModel):
    columns: List[CrmColumn]


class MoveRequest(BaseModel):
    application_id: str
    to_stage:       str


class MoveResponse(BaseModel):
    application_id:  str
    previous_stage:  str
    to_stage:        str
    updated_at:      str


# ── Helpers ───────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/board", response_model=CrmBoard)
async def get_crm_board(user: CurrentUser = Depends(get_current_user)) -> CrmBoard:
    """
    Return all pipeline applications for the authenticated user grouped into
    6 stage columns.  Columns are always present in canonical order, even when
    empty.  Only ApplicationRow entries whose status is in the pipeline are
    included (i.e. status is one of the 6 canonical stages).
    """
    rows = application_repository.get_by_statuses(user.user_id, _VALID_STAGE_KEYS)

    # Group rows by stage
    buckets: dict[str, list[CrmCard]] = {stage: [] for stage, _ in _STAGES}
    for row in rows:
        stage = (row.status or "").lower().strip()
        if stage in buckets:
            buckets[stage].append(CrmCard(
                application_id = row.application_id,
                job_id         = row.job_id,
                company        = row.company or "",
                title          = row.title   or "",
                last_update    = row.last_update or row.submitted_at or "",
                score          = float(row.score or 0.0),
            ))

    columns = [
        CrmColumn(stage=stage, label=label, cards=buckets[stage])
        for stage, label in _STAGES
    ]

    logger.info(
        "[crm/board] returning %d cards across %d columns",
        sum(len(c.cards) for c in columns), len(columns),
    )
    return CrmBoard(columns=columns)


@router.post("/move", response_model=MoveResponse)
async def move_crm_card(
    body: MoveRequest,
    user: CurrentUser = Depends(get_current_user),
) -> MoveResponse:
    """
    Move an application card from its current stage to a new one.
    Updates ApplicationRow.status and last_update.
    Only cards belonging to the authenticated user can be moved.
    """
    to_stage = body.to_stage.lower().strip()
    if to_stage not in _MOVABLE_STAGES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid stage '{body.to_stage}'. "
                   f"Must be one of: {sorted(_MOVABLE_STAGES)}",
        )

    now = _now_iso()

    result, previous_stage = application_repository.move_stage(
        body.application_id, user.user_id, to_stage, now,
    )
    if result == "not_found":
        raise HTTPException(
            status_code=404,
            detail=f"Application '{body.application_id}' not found.",
        )
    if result == "forbidden":
        raise HTTPException(
            status_code=403,
            detail="You do not have permission to move this application.",
        )

    logger.info(
        "[crm/move] %s  %r → %r", body.application_id, previous_stage, to_stage,
    )
    return MoveResponse(
        application_id = body.application_id,
        previous_stage = previous_stage,
        to_stage       = to_stage,
        updated_at     = now,
    )
