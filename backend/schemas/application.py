from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel


class ApplicationStatus(str, Enum):
    SUBMITTED = "submitted"
    VIEWED    = "viewed"
    SCREENING = "screening"
    INTERVIEW = "interview"
    OFFER     = "offer"
    REJECTED  = "rejected"
    SKIPPED   = "skipped"


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
