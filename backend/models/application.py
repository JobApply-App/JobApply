"""ORM models for applications, recruiter reply drafts, and job feedback.

Extracted from the former backend/services/db.py.
"""
from __future__ import annotations

from sqlalchemy import Column, Float, Integer, String, Text, UniqueConstraint

from backend.core.database import Base


class ApplicationRow(Base):
    """One row = one submitted application."""
    __tablename__ = "applications"

    application_id = Column(String, primary_key=True)
    # Multi-tenant owner — added in v2; existing rows migrated to 'default'
    user_id        = Column(String, nullable=False, default="default", index=True)
    tenant_id      = Column(String, nullable=True, index=True)   # see JobRow.tenant_id docstring
    job_id         = Column(String, nullable=False, index=True)
    title          = Column(String, nullable=False)
    company        = Column(String, nullable=False)
    ats            = Column(String, nullable=False, default="Direct")
    status         = Column(String, nullable=False, default="submitted")
    submitted_at   = Column(String, nullable=False)
    last_update    = Column(String, nullable=False)
    score          = Column(Float,  nullable=False, default=0.0)
    cover_letter   = Column(Text,   nullable=True)
    reason         = Column(Text,   nullable=True)


class RecruiterReplyDraftRow(Base):
    """
    Phase 6 — AI-drafted reply to an inbound recruiter email.

    One row per drafted reply, linked to the owning user and the job whose
    application the recruiter email referred to. Drafts are never sent
    automatically — the user reviews them in the dashboard first.

    Table is created by Base.metadata.create_all() in init_db() on startup.
    """
    __tablename__ = "recruiter_reply_drafts"

    draft_id      = Column(String, primary_key=True)
    user_id       = Column(String, nullable=False, index=True)
    tenant_id     = Column(String, nullable=True, index=True)   # see JobRow.tenant_id docstring
    job_id        = Column(String, nullable=False, index=True)
    # Sanitized excerpt of the inbound email the draft responds to (audit trail)
    email_excerpt = Column(Text,   nullable=False, default="")
    draft_text    = Column(Text,   nullable=False, default="")
    status        = Column(String, nullable=False, default="draft")  # draft | sent | discarded
    created_at    = Column(String, nullable=False, default="")


class JobFeedbackRow(Base):
    """
    User thumbs-up / thumbs-down feedback on job matches (JOB-57).

    One row per (user, job) — re-rating updates the row in place (latest
    opinion wins), enforced by UNIQUE(user_id, job_id). snapshot_json freezes
    the job's characteristics at rating time (match score, culture axis/
    category, pace, work model) so preference learning keeps working even if
    the job row is later re-scored, archived, or purged.
    """
    __tablename__ = "job_feedback"

    id            = Column(Integer, primary_key=True, autoincrement=True)
    user_id       = Column(String,  nullable=False, index=True)
    tenant_id     = Column(String,  nullable=True, index=True)   # see JobRow.tenant_id docstring
    job_id        = Column(String,  nullable=False)
    feedback_type = Column(String,  nullable=False)               # thumbs_up | thumbs_down
    reason        = Column(Text,    nullable=True)                # optional free-text why
    snapshot_json = Column(Text,    nullable=False, default="{}") # job characteristics at rating time
    created_at    = Column(String,  nullable=False)
    updated_at    = Column(String,  nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", "job_id", name="uq_job_feedback_user_job"),
    )
