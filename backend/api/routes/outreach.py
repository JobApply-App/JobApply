"""
Outreach API — LinkedIn message generation endpoints.

Routes
------
POST /api/outreach/message
    Generate a LinkedIn message (consultation, escalation, or headhunter).

POST /api/outreach/headhunter
    Shortcut for headhunter-type messages; pre-fills common agency fields.

POST /api/outreach/generate/{job_id}
    Phase 3 — generate + persist a hiring-manager outreach message for one job,
    grounded in the CV tailored to that job.

GET /api/outreach/{job_id}
    Return the persisted outreach message for a job (null if not generated yet).

POST /api/outreach/pitch/{job_id}
    Direct Pitch Generator (JOB-64) — a short, punchy recruiter pitch for one
    of the caller's own jobs. Stateless (not persisted, unlike /generate) —
    the user edits/copies it directly in the UI each time.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.api.deps import CurrentUser, get_current_user, llm_rate_limit
from backend.repositories import job_repository as job_store
from backend.services.outreach_service import (
    generate_outreach,
    generate_outreach_message,
    generate_pitch_from_raw,
)
from backend.schemas.job import RawJobPosting

logger = logging.getLogger(__name__)
# Every outreach route is an LLM generation call → strict per-caller budget.
router = APIRouter(dependencies=[Depends(llm_rate_limit)])


# ── Request / Response models ─────────────────────────────────────────────────

class OutreachRequest(BaseModel):
    message_type:   Literal["consultation", "escalation", "headhunter"]
    target_name:    str = Field(..., max_length=200)
    target_title:   str = Field(..., max_length=200)
    target_company: str = Field(..., max_length=200)
    context:        Optional[str] = Field(default=None, max_length=10_000)
    job_id:         Optional[str] = Field(default=None, max_length=200)  # for escalation — fetches JD for context


class OutreachResponse(BaseModel):
    message_type: str
    message:      str
    word_count:   int


class HeadhunterRequest(BaseModel):
    recruiter_name:    str = Field(..., max_length=200)
    recruiter_title:   Optional[str] = Field(default="Recruiter", max_length=200)
    agency_name:       str = Field(..., max_length=200)
    context:           Optional[str] = Field(default=None, max_length=10_000)


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/message", response_model=OutreachResponse)
async def generate_message(body: OutreachRequest, user: CurrentUser = Depends(get_current_user)) -> OutreachResponse:
    """
    Generate a LinkedIn outreach message.

    - **consultation**: Short warm opener asking for 5-min advice.  No job ask.
    - **escalation**: Follow-up with embedded 3rd-person summary for internal forwarding.
    - **headhunter**: Direct recruiter pitch — domain, seniority, availability.
    """
    try:
        message = await generate_outreach_message(
            message_type   = body.message_type,
            target_name    = body.target_name,
            target_title   = body.target_title,
            target_company = body.target_company,
            context        = body.context or "",
            job_id         = body.job_id,
            user_id        = user.user_id,
        )
    except Exception as exc:
        logger.exception("[outreach] Message generation failed: %s", exc)
        raise HTTPException(status_code=500, detail="Message generation failed. Please try again shortly.") from exc

    return OutreachResponse(
        message_type = body.message_type,
        message      = message,
        word_count   = len(message.split()),
    )


@router.post("/headhunter", response_model=OutreachResponse)
async def generate_headhunter_message(body: HeadhunterRequest, user: CurrentUser = Depends(get_current_user)) -> OutreachResponse:
    """
    Shortcut: generate a headhunter-optimised outreach message for a named agency recruiter.
    """
    try:
        message = await generate_outreach_message(
            message_type   = "headhunter",
            target_name    = body.recruiter_name,
            target_title   = body.recruiter_title or "Recruiter",
            target_company = body.agency_name,
            context        = body.context or "",
            user_id        = user.user_id,
        )
    except Exception as exc:
        logger.exception("[outreach] Headhunter message generation failed: %s", exc)
        raise HTTPException(status_code=500, detail="Message generation failed. Please try again shortly.") from exc

    return OutreachResponse(
        message_type = "headhunter",
        message      = message,
        word_count   = len(message.split()),
    )


# ── Phase 3: job-anchored outreach (generate + persist + fetch) ───────────────

class JobOutreachResponse(BaseModel):
    job_id:       str
    outreach_text: Optional[str]   # null when never generated
    word_count:   int


@router.post("/generate/{job_id}", response_model=JobOutreachResponse)
async def generate_job_outreach(
    job_id: str,
    user:   CurrentUser = Depends(get_current_user),
) -> JobOutreachResponse:
    """Generate + persist an outreach message for one of the caller's jobs."""
    try:
        message = await generate_outreach(job_id, user.user_id)
    except ValueError as exc:
        # Job not found for this user — 404, never leak cross-tenant existence.
        raise HTTPException(status_code=404, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        logger.exception("[outreach] generate failed for job %s: %s", job_id, exc)
        raise HTTPException(status_code=502, detail="Outreach generation failed. Please try again shortly.") from exc

    return JobOutreachResponse(
        job_id        = job_id,
        outreach_text = message,
        word_count    = len(message.split()),
    )


@router.get("/{job_id}", response_model=JobOutreachResponse)
async def get_job_outreach(
    job_id: str,
    user:   CurrentUser = Depends(get_current_user),
) -> JobOutreachResponse:
    """Return the persisted outreach message for a job (null if none yet)."""
    text = job_store.get_outreach_text(job_id, user.user_id)
    return JobOutreachResponse(
        job_id        = job_id,
        outreach_text = text,
        word_count    = len(text.split()) if text else 0,
    )


# ── Direct Pitch Generator (JOB-64) ───────────────────────────────────────────

class PitchResponse(BaseModel):
    job_id:     str
    pitch:      str
    word_count: int


@router.post("/pitch/{job_id}", response_model=PitchResponse)
async def generate_direct_pitch(
    job_id: str,
    user:   CurrentUser = Depends(get_current_user),
) -> PitchResponse:
    """
    Generate a short, direct recruiter pitch (under ~120 words) for one of the
    caller's jobs — a fast alternative to a full cover letter. Stateless: the
    frontend holds/edits the returned text locally; re-calling regenerates.
    """
    job = job_store.get_by_id(job_id, user.user_id)
    if job is None:
        # Never leak cross-tenant existence — same 404 contract as /generate/{job_id}.
        raise HTTPException(status_code=404, detail=f"Job {job_id!r} not found.")

    jd_text = (job.jd_text or "").strip() or f"(No full description stored — role: {job.title} at {job.company}.)"
    posting = RawJobPosting(
        id         = job.job_id,
        title      = job.title,
        company    = job.company,
        source_url = job.apply_url or "",
        raw_text   = jd_text,
        scraped_at = job.created_at or datetime.now(timezone.utc).isoformat(),
    )

    try:
        from backend.services.user_profile import build_full_text
        pitch = await generate_pitch_from_raw(posting, build_full_text(user.user_id))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        logger.exception("[outreach] pitch generation failed for job %s: %s", job_id, exc)
        raise HTTPException(status_code=502, detail="Pitch generation failed. Please try again shortly.") from exc

    return PitchResponse(job_id=job_id, pitch=pitch, word_count=len(pitch.split()))
