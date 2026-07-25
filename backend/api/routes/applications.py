from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.api.deps import CurrentUser, get_current_user
from backend.schemas.application import Application, ApplicationStatus
from backend.repositories import application_repository as app_store
from backend.repositories import job_repository as job_store
from backend.core.database import ENGINE
from backend.models.job import JobRow

logger = logging.getLogger(__name__)

router = APIRouter()


class RunCycleResponse(BaseModel):
    submitted: int
    applications: list[Application]


@router.get("", response_model=list[Application])
async def list_applications(user: CurrentUser = Depends(get_current_user)):
    """
    Return all submitted applications for the authenticated user, most recent first.

    Registered at "" (not "/") so the effective path is exactly "/api/applications"
    with no trailing slash. Next.js's own routing normalizes trailing-slash URLs to
    their no-slash form (a 308) before rewrites apply; if this route required the
    slash, FastAPI's redirect_slashes would then 307 the already-normalized request
    back to the slash form — but that redirect's Location header reflects the
    internal Docker-network hostname (backend:8000) that the proxy dialed, which
    the browser can never resolve directly, surfacing as a bare "Failed to fetch".
    Matching Next's no-slash form exactly on both ends means neither side ever
    needs to redirect.
    """
    return app_store.get_all(user_id=user.user_id)


class DeleteApplicationResponse(BaseModel):
    deleted: bool


@router.delete("/{application_id}", response_model=DeleteApplicationResponse)
async def delete_application(application_id: str, user: CurrentUser = Depends(get_current_user)):
    """Delete a single application, scoped to the authenticated user."""
    deleted = app_store.delete(application_id, user_id=user.user_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Application '{application_id}' not found.")
    return DeleteApplicationResponse(deleted=True)


@router.post("/run", response_model=RunCycleResponse)
async def run_applier_cycle(
    background_tasks: BackgroundTasks,
    user: CurrentUser = Depends(get_current_user),
):
    """
    Trigger the ApplierAgent cycle synchronously.
    Finds all jobs with score >= 85 that haven't been applied to yet,
    submits simulated applications, and returns the results.
    """
    from backend.agents.applier import ApplierAgent
    agent   = ApplierAgent(user_id=user.user_id)
    results = await asyncio.to_thread(agent.run_cycle)
    logger.info("[api/applications] run_cycle completed — %d submitted", len(results))
    return RunCycleResponse(submitted=len(results), applications=results)


@router.post("/{job_id}/apply", response_model=Application)
async def apply_to_job(
    job_id: str,
    user: CurrentUser = Depends(get_current_user),
):
    """Manually trigger an application for a specific job."""
    from backend.agents.applier import ApplierAgent
    app = await asyncio.to_thread(ApplierAgent(user_id=user.user_id).apply_single, job_id)
    if app is None:
        raise HTTPException(
            status_code=404,
            detail=f"Job '{job_id}' not found or has already been applied to.",
        )
    return app


@router.get("/{application_id}", response_model=Application)
async def get_application(
    application_id: str,
    user: CurrentUser = Depends(get_current_user),
):
    """Return a single application by ID, scoped to the authenticated user."""
    match = app_store.get_by_id(application_id, user_id=user.user_id)
    if match is None:
        raise HTTPException(status_code=404, detail="Application not found.")
    return match


# ── Mark as Applied — explicit user action ────────────────────────────────────

class MarkAppliedRequest(BaseModel):
    job_id: str


class MarkAppliedResponse(BaseModel):
    application_id: str
    job_id:         str
    company:        str
    title:          str
    status:         str
    created:        bool   # True = new record; False = record already existed


@router.post("/mark-applied", response_model=MarkAppliedResponse)
async def mark_applied(
    body: MarkAppliedRequest,
    user: CurrentUser = Depends(get_current_user),
) -> MarkAppliedResponse:
    """
    Explicitly record that the user submitted their tailored CV for a job.

    - Looks up the JobRow to get company/title/score.
    - Checks whether an ApplicationRow already exists for this job.
      If yes → updates status to 'submitted' and returns it.
      If no  → creates a new ApplicationRow with status='submitted'.
    - Marks JobRow.applied = True and sets applied_at timestamp.

    This is the canonical action that moves a job card into the Kanban pipeline.
    Calling /tailor-cv does NOT trigger this — the user must explicitly click
    "Mark as Applied" to confirm they sent the CV.
    """
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    with Session(ENGINE) as db:
        # ── Verify job exists AND belongs to the caller ───────────────────────
        # Filtering by user_id here (not just job_id) prevents a caller from
        # mutating another user's JobRow.applied/status by guessing a job_id —
        # a mismatch is indistinguishable from "not found" (never leak
        # cross-tenant existence).
        job_row = (
            db.query(JobRow)
            .filter(JobRow.job_id == body.job_id, JobRow.user_id == user.user_id)
            .first()
        )
        if not job_row:
            raise HTTPException(
                status_code=404,
                detail=f"Job '{body.job_id}' not found.",
            )

        company = job_row.company or ""
        title   = job_row.title   or ""
        score   = float(job_row.score or 0.0)

        # ── Upsert ApplicationRow ─────────────────────────────────────────────
        application_id, created = app_store.upsert_submitted(
            db,
            new_application_id = str(uuid.uuid4()),
            job_id              = body.job_id,
            user_id             = user.user_id,
            title               = title,
            company             = company,
            score               = score,
            now                 = now_str,
        )

        # ── Mark job as applied ───────────────────────────────────────────────
        job_row.applied    = True
        job_row.applied_at = now_str
        job_row.status     = "applied"   # feed-level status

        db.commit()

    logger.info(
        "[applications/mark-applied] job=%s → application=%s  created=%s",
        body.job_id, application_id, created,
    )
    return MarkAppliedResponse(
        application_id = application_id,
        job_id         = body.job_id,
        company        = company,
        title          = title,
        status         = "submitted",
        created        = created,
    )
