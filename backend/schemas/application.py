from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel


class ApplicationStatus(str, Enum):
    SUBMITTED     = "submitted"
    VIEWED        = "viewed"
    SCREENING     = "screening"
    # PHONE_SCREEN/TECHNICAL added 2026-08-20: the CRM board
    # (backend/api/routes/crm.py's _STAGES), its frontend Kanban
    # (ApplicationsKanban.tsx), ApplicationsTab.tsx's own status-badge map,
    # and analytics.py's _ACTIVE_STAGES already treat these two as real,
    # user-facing stages — this enum was the one place that didn't. Moving
    # a card to either one wrote a status string this enum couldn't parse,
    # so the next GET /api/applications call raised an uncaught ValueError
    # in _from_row()'s ApplicationStatus(row.status) and 500'd the entire
    # Applications tab for that user. SCREENING is left in place rather
    # than replaced — existing rows may already carry that value, and
    # removing a member here would just move the same crash onto them.
    PHONE_SCREEN  = "phone screen"
    TECHNICAL     = "technical"
    INTERVIEW     = "interview"
    OFFER         = "offer"
    REJECTED      = "rejected"
    SKIPPED       = "skipped"


class Application(BaseModel):
    application_id: str
    job_id: str
    title: str
    company: str
    ats: str = "Direct"
    status: ApplicationStatus = ApplicationStatus.SUBMITTED
    submitted_at: str          # human-readable, e.g. "Today 09:14"
    last_update: str           # human-readable, e.g. "2h ago"
    score: float
    cover_letter: Optional[str] = None
    reason: Optional[str] = None
