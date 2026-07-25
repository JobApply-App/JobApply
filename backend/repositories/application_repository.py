"""
Repository for the applications table.

Consolidates CRUD previously split between this module (as
backend/services/app_store.py) and the inline upsert logic in
backend/api/routes/applications.py's mark_applied handler.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from backend.core.database import ENGINE
from backend.models.application import ApplicationRow
from backend.schemas.application import Application, ApplicationStatus


def _to_row(app: Application) -> ApplicationRow:
    return ApplicationRow(
        application_id=app.application_id,
        job_id=app.job_id,
        title=app.title,
        company=app.company,
        ats=app.ats,
        status=app.status.value,
        submitted_at=app.submitted_at,
        last_update=app.last_update,
        score=app.score,
        cover_letter=app.cover_letter,
        reason=app.reason,
    )


def _from_row(row: ApplicationRow) -> Application:
    return Application(
        application_id=row.application_id,
        job_id=row.job_id,
        title=row.title,
        company=row.company,
        ats=row.ats,
        status=ApplicationStatus(row.status),
        submitted_at=row.submitted_at,
        last_update=row.last_update,
        score=row.score,
        cover_letter=row.cover_letter,
        reason=row.reason,
    )


def save(app: Application) -> None:
    with Session(ENGINE) as session:
        session.merge(_to_row(app))
        session.commit()


def get_all(user_id: str = "default") -> list[Application]:
    """Return all applications for user_id, ordered by most recently submitted first."""
    with Session(ENGINE) as session:
        rows = (
            session.query(ApplicationRow)
            .filter(ApplicationRow.user_id == user_id)
            .order_by(ApplicationRow.submitted_at.desc())
            .all()
        )
        return [_from_row(r) for r in rows]


def get_by_id(application_id: str, user_id: str = "default") -> Optional[Application]:
    """
    Return a single application by its primary key, scoped to user_id.

    Direct indexed lookup — replaces the previous get_application() route
    pattern of fetching every application for the user via get_all() and
    linear-scanning in Python for one application_id (JOB-6).
    """
    with Session(ENGINE) as session:
        row = session.get(ApplicationRow, application_id)
        if not row or row.user_id != user_id:
            return None
        return _from_row(row)


def has_application(job_id: str, user_id: str = "default") -> bool:
    """Return True if user_id already has an application row for job_id."""
    with Session(ENGINE) as session:
        return (
            session.query(ApplicationRow)
            .filter(
                ApplicationRow.job_id  == job_id,
                ApplicationRow.user_id == user_id,
            )
            .count() > 0
        )


def delete(application_id: str, user_id: str = "default") -> bool:
    """
    Delete a single application row, scoped to user_id.

    Returns True if a row belonging to user_id was found and deleted, False
    if no such row exists — including when application_id exists but belongs
    to a different user, so this never leaks cross-tenant existence.
    """
    with Session(ENGINE) as session:
        row = session.get(ApplicationRow, application_id)
        if not row or row.user_id != user_id:
            return False
        session.delete(row)
        session.commit()
        return True


def upsert_submitted(
    session: Session,
    *,
    new_application_id: str,
    job_id: str,
    user_id: str,
    title: str,
    company: str,
    score: float,
    now: str,
) -> tuple[str, bool]:
    """
    Upsert the ApplicationRow for (job_id, user_id) to status='submitted'.

    Takes an already-open, uncommitted Session so the caller can combine this
    write with other mutations (e.g. flipping JobRow.applied) in one atomic
    commit — mirrors the exact upsert-or-create logic that previously lived
    inline in the mark_applied route handler.

    Returns (application_id, created) — created=True only when a brand new
    row was added under new_application_id.
    """
    existing = (
        session.query(ApplicationRow)
        .filter(
            ApplicationRow.job_id  == job_id,
            ApplicationRow.user_id == user_id,
        )
        .first()
    )

    if existing:
        # Already in the pipeline — ensure status is at least 'submitted'
        # but do not downgrade a card that has already advanced.
        already_advanced = existing.status not in ("", None)
        if not already_advanced or existing.status == "submitted":
            existing.status      = "submitted"
            existing.last_update = now
        return existing.application_id, False

    session.add(ApplicationRow(
        application_id = new_application_id,
        user_id        = user_id,
        job_id         = job_id,
        title          = title,
        company        = company,
        ats            = "Direct",
        status         = "submitted",
        submitted_at   = now,
        last_update    = now,
        score          = score,
    ))
    return new_application_id, True


def find_updatable_by_company(
    session: Session,
    company_name: str,
    updatable_statuses: frozenset[str],
) -> Optional[ApplicationRow]:
    """
    Return the most-recently-submitted application whose company name
    fuzzy-matches company_name AND whose status is in updatable_statuses.

    Matching strategy (both directions of substring, case-insensitive):
      • DB row "Wix"          matches extracted "Wix Engineering"
      • DB row "Google Inc."  matches extracted "Google"
    This covers the most common formatting mismatches without a full
    fuzzy-similarity library.

    Takes an already-open Session so the caller (e.g. the inbound-email
    webhook) can mutate the returned row and commit it in the same
    transaction as the read, atomically.
    """
    candidates: list[ApplicationRow] = (
        session.query(ApplicationRow)
        .filter(ApplicationRow.status.in_(updatable_statuses))
        .order_by(ApplicationRow.submitted_at.desc())
        .all()
    )

    company_lower = company_name.strip().lower()
    for row in candidates:
        row_company = (row.company or "").strip().lower()
        if company_lower in row_company or row_company in company_lower:
            return row

    return None


def get_all_rows(user_id: str = "default", session: Optional[Session] = None) -> list[ApplicationRow]:
    """
    Return all ApplicationRow ORM objects for user_id, unordered — for
    callers that need the raw stored status string (e.g. analytics
    aggregation over stage values like "phone screen"/"technical" that
    ApplicationStatus's restrictive enum doesn't cover) rather than the
    Application schema returned by get_all().

    Accepts an optional already-open Session so a caller reading another
    table in the same request (e.g. analytics.py also queries JobRow) can
    share one session instead of opening a new one.
    """
    if session is not None:
        return _query_all_rows(session, user_id)
    with Session(ENGINE) as owned_session:
        return _query_all_rows(owned_session, user_id)


def _query_all_rows(session: Session, user_id: str) -> list[ApplicationRow]:
    return session.query(ApplicationRow).filter(ApplicationRow.user_id == user_id).all()


def get_by_statuses(
    user_id: str,
    statuses: frozenset[str],
    session: Optional[Session] = None,
) -> list[ApplicationRow]:
    """
    Return ApplicationRow ORM objects for user_id whose status is in
    statuses, most-recently-submitted first.
    """
    if session is not None:
        return _query_by_statuses(session, user_id, statuses)
    with Session(ENGINE) as owned_session:
        return _query_by_statuses(owned_session, user_id, statuses)


def _query_by_statuses(session: Session, user_id: str, statuses: frozenset[str]) -> list[ApplicationRow]:
    return (
        session.query(ApplicationRow)
        .filter(
            ApplicationRow.user_id == user_id,
            ApplicationRow.status.in_(statuses),
        )
        .order_by(ApplicationRow.submitted_at.desc())
        .all()
    )


def move_stage(
    application_id: str,
    user_id: str,
    to_stage: str,
    now: str,
) -> tuple[str, Optional[str]]:
    """
    Move application_id to to_stage, ownership-checked against user_id.

    Returns (result, previous_stage):
      result = "not_found" — no such application_id at all
      result = "forbidden" — exists but belongs to a different user
      result = "moved"     — updated; previous_stage is the prior status
    """
    with Session(ENGINE) as session:
        row = session.get(ApplicationRow, application_id)
        if not row:
            return "not_found", None
        if row.user_id != user_id:
            return "forbidden", None
        previous_stage  = (row.status or "submitted").lower()
        row.status      = to_stage
        row.last_update = now
        session.commit()
        return "moved", previous_stage


def count_for_user(user_id: str, session: Optional[Session] = None) -> int:
    """Number of ApplicationRow rows owned by user_id."""
    if session is not None:
        return session.query(ApplicationRow).filter(ApplicationRow.user_id == user_id).count()
    with Session(ENGINE) as owned_session:
        return owned_session.query(ApplicationRow).filter(ApplicationRow.user_id == user_id).count()


def reassign_user(old_user_id: str, new_user_id: str, session: Session) -> int:
    """
    Re-point every ApplicationRow owned by old_user_id to new_user_id.

    Takes an already-open Session so the caller (account-linking/migration
    flows in auth.py) can combine this with reassignments on other tables
    in one atomic commit.
    """
    return (
        session.query(ApplicationRow)
        .filter(ApplicationRow.user_id == old_user_id)
        .update({"user_id": new_user_id}, synchronize_session="fetch")
    )
