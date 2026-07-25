"""
Persistent job store backed by SQLite via SQLAlchemy.

All functions preserve the exact same signatures and return types as the
previous in-memory store so the rest of the codebase needs no changes.
"""
from __future__ import annotations

import hashlib
import logging
import re
import unicodedata
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from backend.core.database import ENGINE
from backend.models.job import JobRow
from backend.schemas.job import DetailedAnalysis, JobMatch, ReasonTag

logger = logging.getLogger(__name__)


# ── Cross-board deduplication fingerprint ────────────────────────────────────

def _normalize_for_dedup(s: str) -> str:
    """
    Normalise a string for dedup comparison:
      - Lower-case
      - Strip Hebrew nikud (combining diacritical marks)
      - Remove punctuation
      - Collapse whitespace
    """
    # Decompose Unicode, then strip combining marks (category Mn = Mark, Nonspacing)
    s = unicodedata.normalize("NFD", s.lower().strip())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = re.sub(r"[^\w\s]", "", s)
    return re.sub(r"\s+", " ", s).strip()


def canonical_dedup_key(title: str, company: str, location: str) -> str:
    """
    Return a 16-char hex fingerprint for (title, company, location).

    Used to detect cross-board duplicates: the same role posted on both
    Drushim and AllJobs will share the same key even though the URLs differ.
    The key is intentionally short to avoid uniqueness collisions from minor
    phrasing differences — it acts as a soft filter, not a strict equality check.
    """
    canonical = (
        _normalize_for_dedup(title)
        + "|"
        + _normalize_for_dedup(company)
        + "|"
        + _normalize_for_dedup(location)
    )
    return hashlib.sha1(canonical.encode("utf-8")).hexdigest()[:16]

# Source priority: higher number wins
_SOURCE_PRIORITY = {'company_site': 3, 'linkedin': 2, 'other': 1}


def _source_rank(source_type: Optional[str]) -> int:
    return _SOURCE_PRIORITY.get(source_type or 'other', 1)


def _infer_source_type(stored: Optional[str], url: Optional[str]) -> str:
    """
    Fill in 'linkedin' when the stored type is 'other' but the URL is from LinkedIn.
    Fixes legacy rows imported before source_type was properly set.
    """
    if stored and stored != 'other':
        return stored
    if url and 'linkedin.com' in url:
        return 'linkedin'
    return stored or 'other'


# ── Serialisation helpers ─────────────────────────────────────────────────────

def _to_row(job: JobMatch) -> JobRow:
    return JobRow(
        job_id=job.job_id,
        title=job.title,
        company=job.company,
        location=job.location,
        score=job.score,
        confidence_score=job.confidence_score,
        culture_fit_score=job.culture_fit_score,
        culture_delta=job.culture_delta,
        culture_alignment=job.culture_alignment,
        culture_category=job.culture_category,
        culture_note=job.culture_note,
        trajectory_alignment=job.trajectory_alignment,
        company_dna_inference=job.company_dna_inference,
        investigation_points=list(job.investigation_points),
        detailed_analysis={
            "strengths":       list(job.detailed_analysis.strengths),
            "critical_gaps":   list(job.detailed_analysis.critical_gaps),
            "strategic_advice":list(job.detailed_analysis.strategic_advice),
        },
        reasons=[{"kind": r.kind, "label": r.label} for r in job.reasons],
        apply_url=job.apply_url,
        is_new=job.is_new,
        posted_at=job.posted_at,
        why_ron=job.why_ron,
        scoring_rationale=job.scoring_rationale,
        category=job.category,
        applied=job.applied,
        applied_at=job.applied_at,
        source=job.source,
        is_open=job.is_open,
        jd_text=job.jd_text,
        jd_structured=job.jd_structured,
        user_id=job.user_id,
        source_type=job.source_type,
        company_website_url=job.company_website_url,
        status=job.status,
        match_score=job.match_score,
        score_is_proxy=job.score_is_proxy,
        created_at=job.created_at or datetime.now(timezone.utc).isoformat(),
        locale=job.locale,
        dedup_key=canonical_dedup_key(job.title, job.company, job.location),
        enrichment_failures=job.enrichment_failures,
    )


def _from_row(row: JobRow) -> JobMatch:
    da = row.detailed_analysis or {}
    return JobMatch(
        job_id=row.job_id,
        title=row.title,
        company=row.company,
        location=row.location,
        score=row.score,
        confidence_score=row.confidence_score,
        culture_fit_score=row.culture_fit_score,
        culture_delta=row.culture_delta,
        culture_alignment=row.culture_alignment,
        culture_category=row.culture_category,
        culture_note=row.culture_note,
        trajectory_alignment=row.trajectory_alignment or "",
        company_dna_inference=row.company_dna_inference or "",
        investigation_points=list(row.investigation_points or []),
        detailed_analysis=DetailedAnalysis(
            strengths=da.get("strengths", []),
            critical_gaps=da.get("critical_gaps", []),
            strategic_advice=da.get("strategic_advice", []),
        ),
        reasons=[
            ReasonTag(kind=r["kind"], label=r["label"])
            for r in (row.reasons or [])
        ],
        apply_url=row.apply_url,
        is_new=bool(row.is_new),
        posted_at=row.posted_at or "",
        why_ron=row.why_ron,
        scoring_rationale=row.scoring_rationale,
        category=row.category,
        applied=bool(row.applied),
        applied_at=row.applied_at,
        source=row.source or 'automatic',
        is_open=bool(row.is_open) if row.is_open is not None else True,
        jd_text=row.jd_text,
        jd_structured=row.jd_structured,
        user_id=row.user_id or "default",
        source_type=_infer_source_type(row.source_type, row.apply_url),
        company_website_url=row.company_website_url,
        status=row.status or "new",
        match_score=float(row.match_score) if row.match_score is not None else 0.0,
        score_is_proxy=bool(row.score_is_proxy) if row.score_is_proxy is not None else True,
        created_at=row.created_at,
        locale=row.locale,
        has_tailored_cv=bool(row.tailored_cv),
        enrichment_failures=int(row.enrichment_failures) if row.enrichment_failures is not None else 0,
    )


# ── Public API (same signatures as the old in-memory store) ──────────────────

def save(job: JobMatch) -> None:
    """Upsert a JobMatch: insert on first save, update on re-analysis of the same URL."""
    with Session(ENGINE) as session:
        session.merge(_to_row(job))
        session.commit()


def _upgrade_source_fields(row: JobRow, job: JobMatch) -> None:
    """
    Overwrite source-origin fields on an existing row with higher-priority data.

    Only ever called on a row already owned by job.user_id — see the
    same-user/cross-tenant split in save_with_source_priority(). row.user_id
    is deliberately NOT touched here: it must never move a row between
    tenants (JOB-92).
    """
    row.source_type         = job.source_type
    row.apply_url           = job.apply_url or row.apply_url
    row.company_website_url = job.company_website_url or row.company_website_url
    if job.jd_text:
        row.jd_text = job.jd_text


def _fresh_row_for_user(job: JobMatch, cross_tenant_match: Optional[JobRow] = None) -> JobRow:
    """
    Build a brand-new row for job.user_id.

    If cross_tenant_match is given (an existing row matched by apply_url/
    dedup_key/title+company but owned by a DIFFERENT user), borrow its
    shared/source-origin fields when it outranks the incoming source —
    read-only. cross_tenant_match itself is never mutated, and none of its
    private analysis (score, status, applied, why_ron, tailored_cv, ...) is
    copied. This is what lets a second user benefit from another tenant's
    higher-priority scrape without that tenant's row being reassigned (JOB-92).
    """
    if cross_tenant_match is not None:
        if _source_rank(cross_tenant_match.source_type) > _source_rank(job.source_type):
            job = job.model_copy(update={
                "source_type":         cross_tenant_match.source_type,
                "apply_url":           cross_tenant_match.apply_url or job.apply_url,
                "company_website_url": cross_tenant_match.company_website_url or job.company_website_url,
            })
        job = job.model_copy(update={
            "jd_text": job.jd_text or cross_tenant_match.jd_text,
            "locale":  job.locale or cross_tenant_match.locale,
        })
    return _to_row(job)


def save_with_source_priority(job: JobMatch) -> bool:
    """
    Upsert with source priority: company_site > linkedin > other.

    Every match step below checks the CALLING USER's own rows first. A match
    belonging to a different user is never mutated or reassigned — instead a
    brand-new row is inserted for the incoming user, optionally enriched
    (read-only) from the other user's higher-priority shared fields. This is
    the JOB-92 fix: previously these lookups ignored user_id entirely, so a
    higher-priority save from one user could silently reassign another
    user's row (and their private score/status/analysis) to itself.

    1. Exact apply_url match — same-user: upgrade in place. Different-user:
       clone a fresh row for the incoming user.
    2. dedup_key match — same job cross-posted on multiple boards. Same rules.
    3. (title, company) match with a lower-priority source (company_site
       upgrades). Same rules.
    4. No match — fresh insert.

    Returns True only when a brand-new row was inserted for job.user_id.
    """
    incoming_rank = _source_rank(job.source_type)
    job_dedup_key = canonical_dedup_key(job.title, job.company, job.location)

    with Session(ENGINE) as session:
        # ── 1. Exact URL match ────────────────────────────────────────────────
        if job.apply_url:
            same_user = (
                session.query(JobRow)
                .filter(JobRow.apply_url == job.apply_url, JobRow.user_id == job.user_id)
                .first()
            )
            if same_user:
                if incoming_rank > _source_rank(same_user.source_type):
                    _upgrade_source_fields(same_user, job)
                    session.commit()
                    logger.debug(
                        "[job_store] Source upgraded %s → %s for job_id=%s",
                        same_user.source_type, job.source_type, same_user.job_id,
                    )
                # Always backfill locale if missing
                if not same_user.locale and job.locale:
                    same_user.locale = job.locale
                    session.commit()
                return False  # already existed for this user

            other_user = (
                session.query(JobRow)
                .filter(JobRow.apply_url == job.apply_url, JobRow.user_id != job.user_id)
                .first()
            )
            if other_user:
                session.add(_fresh_row_for_user(job, other_user))
                session.commit()
                logger.info(
                    "[job_store] Cross-tenant apply_url match for '%s @ %s' — "
                    "cloned a private row for user_id=%s (ownership NOT reassigned)",
                    job.title, job.company, job.user_id,
                )
                return True

        # ── 2. Cross-board dedup_key match ────────────────────────────────────
        # Catches the same job posted on Drushim, AllJobs, LinkedIn etc.
        # The higher-priority source wins; the lower-priority record is skipped.
        same_user_dup = (
            session.query(JobRow)
            .filter(JobRow.dedup_key == job_dedup_key, JobRow.user_id == job.user_id)
            .first()
        )
        if same_user_dup:
            existing_rank = _source_rank(same_user_dup.source_type)
            if incoming_rank > existing_rank:
                _upgrade_source_fields(same_user_dup, job)
                session.commit()
                logger.info(
                    "[job_store] dedup_key hit: upgraded '%s @ %s' source %s→%s",
                    job.title, job.company, same_user_dup.source_type, job.source_type,
                )
            else:
                # Backfill locale/jd_text if the existing row lacks them
                changed = False
                if not same_user_dup.locale and job.locale:
                    same_user_dup.locale = job.locale
                    changed = True
                if not same_user_dup.jd_text and job.jd_text:
                    same_user_dup.jd_text = job.jd_text
                    changed = True
                if changed:
                    session.commit()
                logger.debug(
                    "[job_store] dedup_key hit (cross-board dup): skipping '%s @ %s' from %s",
                    job.title, job.company, job.source_type,
                )
            return False

        other_user_dup = (
            session.query(JobRow)
            .filter(JobRow.dedup_key == job_dedup_key, JobRow.user_id != job.user_id)
            .first()
        )
        if other_user_dup:
            session.add(_fresh_row_for_user(job, other_user_dup))
            session.commit()
            logger.info(
                "[job_store] Cross-tenant dedup_key match for '%s @ %s' — "
                "cloned a private row for user_id=%s (ownership NOT reassigned)",
                job.title, job.company, job.user_id,
            )
            return True

        # ── 3. Title + company cross-source dedup (company_site only) ─────────
        if incoming_rank >= _SOURCE_PRIORITY['company_site']:
            same_user_tc = (
                session.query(JobRow)
                .filter(
                    func.lower(JobRow.title)   == job.title.strip().lower(),
                    func.lower(JobRow.company) == job.company.strip().lower(),
                    JobRow.source_type         != 'company_site',
                    JobRow.user_id             == job.user_id,
                )
                .first()
            )
            if same_user_tc:
                logger.info(
                    "[job_store] Upgrading '%s @ %s' source '%s' → 'company_site'",
                    job.title, job.company, same_user_tc.source_type,
                )
                _upgrade_source_fields(same_user_tc, job)
                session.commit()
                return False

            other_user_tc = (
                session.query(JobRow)
                .filter(
                    func.lower(JobRow.title)   == job.title.strip().lower(),
                    func.lower(JobRow.company) == job.company.strip().lower(),
                    JobRow.source_type         != 'company_site',
                    JobRow.user_id             != job.user_id,
                )
                .first()
            )
            if other_user_tc:
                session.add(_fresh_row_for_user(job, other_user_tc))
                session.commit()
                logger.info(
                    "[job_store] Cross-tenant title+company match for '%s @ %s' — "
                    "cloned a private row for user_id=%s (ownership NOT reassigned)",
                    job.title, job.company, job.user_id,
                )
                return True

        # ── 4. Fresh insert ───────────────────────────────────────────────────
        session.merge(_to_row(job))
        session.commit()
        return True


def update_scores(
    job_id: str,
    user_id: str,
    *,
    fit_score: Optional[float] = None,
    ats_score: Optional[float] = None,
) -> bool:
    """Update fit score and/or ATS match_score for a job owned by user_id. Returns True if found."""
    with Session(ENGINE) as session:
        row = session.get(JobRow, job_id)
        if not row or row.user_id != user_id:
            return False
        if fit_score is not None:
            row.score = max(0.0, float(fit_score))
        if ats_score is not None:
            row.match_score = max(0.0, float(ats_score))
        session.commit()
        return True


def get_all(user_id: str) -> list[JobMatch]:
    """Return all stored jobs owned by user_id, sorted by score descending."""
    with Session(ENGINE) as session:
        rows = (
            session.query(JobRow)
            .filter(JobRow.user_id == user_id)
            .order_by(JobRow.score.desc())
            .all()
        )
        return [_from_row(r) for r in rows]


def is_empty(user_id: str) -> bool:
    with Session(ENGINE) as session:
        return session.query(JobRow).filter(JobRow.user_id == user_id).count() == 0


def contains_url(url: str, user_id: str) -> bool:
    """Return True if a job with this apply_url already exists for user_id."""
    with Session(ENGINE) as session:
        return (
            session.query(JobRow)
            .filter(JobRow.apply_url == url, JobRow.user_id == user_id)
            .count() > 0
        )


def get_by_id(job_id: str, user_id: str) -> Optional[JobMatch]:
    """Return the stored JobMatch for a job_id owned by user_id, or None if not found/not owned."""
    with Session(ENGINE) as session:
        row = session.get(JobRow, job_id)
        if not row or row.user_id != user_id:
            return None
        return _from_row(row)


def get_by_url(url: str, user_id: str) -> Optional[JobMatch]:
    """Return the stored JobMatch for a URL owned by user_id, or None if not found."""
    with Session(ENGINE) as session:
        row = (
            session.query(JobRow)
            .filter(JobRow.apply_url == url, JobRow.user_id == user_id)
            .first()
        )
        return _from_row(row) if row else None


def mark_closed(job_id: str, user_id: str) -> None:
    """Set is_open=False on an existing job row owned by user_id."""
    with Session(ENGINE) as session:
        row = session.get(JobRow, job_id)
        if row and row.user_id == user_id:
            row.is_open = False
            session.commit()


def get_categories(user_id: str) -> list[str]:
    """Return sorted list of unique non-null category tags for user_id."""
    with Session(ENGINE) as session:
        rows = (
            session.query(JobRow.category)
            .filter(JobRow.category.isnot(None), JobRow.user_id == user_id)
            .distinct()
            .all()
        )
        return sorted(r[0] for r in rows)


def get_eligible_for_apply(threshold: float, user_id: str) -> list[JobMatch]:
    """Return jobs for user_id with score >= threshold that have not been applied to yet."""
    with Session(ENGINE) as session:
        rows = (
            session.query(JobRow)
            .filter(
                JobRow.score >= threshold,
                JobRow.applied == False,  # noqa: E712
                JobRow.user_id == user_id,
            )
            .order_by(JobRow.score.desc())
            .all()
        )
        return [_from_row(r) for r in rows]


def mark_applied(job_id: str, applied_at: str, user_id: str) -> None:
    """Set applied=True and record the timestamp on a job row owned by user_id."""
    with Session(ENGINE) as session:
        row = session.get(JobRow, job_id)
        if row and row.user_id == user_id:
            row.applied    = True
            row.applied_at = applied_at
            session.commit()


def get_tailored_cv(job_id: str, user_id: str) -> Optional[dict]:
    """
    Return the cached tailored CV payload for a job owned by user_id, or None.

    Returns None when the cached draft was generated from an older version of
    the user's master profile (see profile_fingerprint) — the caller then
    regenerates from current data instead of serving a draft built from
    since-edited experience/skills/contact details. Drafts cached before this
    stamp existed carry no fingerprint and are treated as stale exactly once,
    on first read after this change.
    """
    with Session(ENGINE) as session:
        row = session.get(JobRow, job_id)
        if not row or row.user_id != user_id:
            return None
        cached = row.tailored_cv or None

    if not cached:
        return None

    current = profile_fingerprint(user_id)
    # Only enforce when a fingerprint is actually resolvable — if the profile
    # row is unreadable, serving the existing draft beats forcing a needless
    # (and expensive) LLM regeneration on every open.
    if current and cached.get("profile_fingerprint") != current:
        logger.info(
            "[job_store] Tailored CV for job=%s is stale (profile changed) — ignoring cache",
            job_id,
        )
        return None
    return cached


def profile_fingerprint(user_id: str) -> str:
    """
    master_profiles.updated_at for user_id ("" when absent/unreadable).

    Stamped into the tailored-CV cache so a draft generated from an older
    master profile can be detected as stale — every write path through
    master_profile_repository / master_profile_service bumps updated_at, so
    a changed value means the source data the draft was built from has moved.
    """
    try:
        from backend.repositories import master_profile_repository
        row = master_profile_repository.get(user_id)
        return str(row.updated_at or "") if row else ""
    except Exception:
        return ""


def save_tailored_cv(job_id: str, user_id: str, cv_data: dict, match_score: Optional[dict]) -> None:
    """Persist the generated CV data + match score for a job owned by user_id."""
    with Session(ENGINE) as session:
        row = session.get(JobRow, job_id)
        if row and row.user_id == user_id:
            row.tailored_cv = {
                "cv_data":     cv_data,
                "match_score": match_score,
                # Staleness stamp — compared on read (see get_tailored_cv).
                "profile_fingerprint": profile_fingerprint(user_id),
            }
            session.commit()


def clear_tailored_cv(job_id: str, user_id: str) -> bool:
    """
    Drop the cached tailored CV for a job owned by user_id. Returns True if a
    cached payload was actually removed.

    Used by the "Regenerate from scratch" path so the stale draft is gone
    BEFORE the LLM runs — previously `force=True` only skipped the cache read
    and relied on a successful run overwriting it at the end, which meant a
    failed regeneration silently left the old draft in place and the user was
    served it again on the next open.
    """
    with Session(ENGINE) as session:
        row = session.get(JobRow, job_id)
        if row and row.user_id == user_id and row.tailored_cv:
            row.tailored_cv = None
            session.commit()
            return True
    return False


def get_feed(user_id: str, status_filter: Optional[str] = None) -> List[JobMatch]:
    """
    Return the job feed for a user, sorted by match_score DESC then created_at DESC.

    status_filter: optional JobStatus value ('new', 'saved', 'ignored', 'applied').
    When omitted, all statuses except 'ignored' are returned.
    """
    with Session(ENGINE) as session:
        query = session.query(JobRow).filter(JobRow.user_id == user_id)
        if status_filter:
            query = query.filter(JobRow.status == status_filter)
        else:
            query = query.filter(JobRow.status != "ignored")
        rows = (
            query
            .order_by(JobRow.match_score.desc(), JobRow.created_at.desc())
            .all()
        )
        jobs = [_from_row(r) for r in rows]
        for job in jobs:
            job.is_direct_application = job.source_type == "company_site"
            job.is_bulk_import = job.job_id.startswith("li-bulk-")
        return jobs


def update_match_score(job_id: str, user_id: str, score: float, is_proxy: bool = False) -> None:
    """Persist a newly computed ATS match_score onto a job row owned by user_id.

    Pass is_proxy=False (the default) when this is a full LLM-backed Phase B
    score so the UI can stop showing "Analysing…".  Pass is_proxy=True only
    when persisting the fast Phase A proxy from the scraper.
    """
    with Session(ENGINE) as session:
        row = session.get(JobRow, job_id)
        if row and row.user_id == user_id:
            row.match_score   = score
            row.score_is_proxy = is_proxy
            session.commit()


def update_reasons(job_id: str, user_id: str, reasons: list[dict]) -> None:
    """
    Replace the reasons column on a job row owned by user_id.
    Each reason must be {kind: 'skill'|'exp'|'loc'|'neg', label: str}.
    Called after proficiency-aware rescoring to surface context tags like
    "Academic Python vs. Professional req." in the UI.
    """
    with Session(ENGINE) as session:
        row = session.get(JobRow, job_id)
        if row and row.user_id == user_id:
            row.reasons = reasons
            session.commit()


def update_status(job_id: str, user_id: str, status: str) -> bool:
    """
    Set the status field on a job row owned by user_id.
    Returns True if the row was found and updated, False if job_id unknown or not owned.
    """
    with Session(ENGINE) as session:
        row = session.get(JobRow, job_id)
        if not row or row.user_id != user_id:
            return False
        row.status = status
        session.commit()
        return True


def get_jobs_missing_jd_text(user_id: str, min_score: float = 50.0) -> List[JobMatch]:
    """
    Return jobs for a user with score >= min_score whose jd_text is missing or
    too short to be a real JD (< 100 chars after stripping whitespace).

    Used by the JD backfill task to find jobs worth fetching descriptions for.
    Ordered by score DESC so the highest-value jobs are fetched first.
    """
    with Session(ENGINE) as session:
        rows = (
            session.query(JobRow)
            .filter(
                and_(
                    JobRow.user_id == user_id,
                    JobRow.score   >= min_score,
                    JobRow.apply_url.isnot(None),
                )
            )
            .order_by(JobRow.score.desc())
            .all()
        )
        # Post-filter in Python: jd_text missing or shorter than a real JD
        result = []
        for row in rows:
            text = (row.jd_text or "").strip()
            if len(text) < 100:
                result.append(_from_row(row))
        return result


def update_jd_text(job_id: str, text: str) -> None:
    """Persist fetched JD text onto an existing job row."""
    with Session(ENGINE) as session:
        row = session.get(JobRow, job_id)
        if row:
            row.jd_text = text
            session.commit()


def update_jd_structured(job_id: str, structured_json: str) -> None:
    """Persist LLM-structured JD JSON string onto an existing job row."""
    with Session(ENGINE) as session:
        row = session.get(JobRow, job_id)
        if row:
            row.jd_structured = structured_json
            session.commit()


def update_company(job_id: str, company: str) -> None:
    """Overwrite the company field on an existing job row."""
    if not company or not company.strip():
        return
    with Session(ENGINE) as session:
        row = session.get(JobRow, job_id)
        if row:
            row.company = company.strip()
            session.commit()


def get_unscored_new_jobs(user_id: str) -> List[JobMatch]:
    """
    Return jobs for a user that are status='new' and have not yet been
    ATS-scored (match_score == 0.0).  Used by refresh_user_scores().
    """
    with Session(ENGINE) as session:
        rows = (
            session.query(JobRow)
            .filter(
                and_(
                    JobRow.user_id == user_id,
                    JobRow.status  == "new",
                    JobRow.match_score == 0.0,
                )
            )
            .all()
        )
        return [_from_row(r) for r in rows]


def get_jobs_needing_llm_enrichment(user_id: str) -> List[JobMatch]:
    """
    Return all jobs for user_id that need the s2 LLM enrichment pass.

    A job needs enrichment when EITHER:
      • match_score == 0.0  — never scored at all (legacy / pre-two-phase rows)
      • why_ron IS NULL     — locally scored in s1 but LLM brief not yet written

    Jobs are ordered by match_score DESC so the most promising ones are
    enriched first when the batch is rate-limited by the Semaphore.
    """
    with Session(ENGINE) as session:
        rows = (
            session.query(JobRow)
            .filter(
                and_(
                    JobRow.user_id == user_id,
                    JobRow.status.in_(["new", "saved"]),
                    or_(
                        JobRow.match_score == 0.0,
                        JobRow.why_ron.is_(None),
                    ),
                )
            )
            .order_by(JobRow.match_score.desc())
            .all()
        )
        return [_from_row(r) for r in rows]


def update_why_ron(job_id: str, user_id: str, why_ron: str) -> None:
    """
    Persist the LLM-generated 'why apply' brief onto a job row owned by user_id.

    Called by feed_service after s2 enrichment completes.  A non-NULL
    why_ron signals that this job has been fully LLM-scored and should
    not be re-processed in subsequent s2 runs.
    """
    with Session(ENGINE) as session:
        row = session.get(JobRow, job_id)
        if row and row.user_id == user_id:
            row.why_ron = why_ron
            session.commit()


def get_outreach_text(job_id: str, user_id: str) -> Optional[str]:
    """Return the persisted outreach message for a job owned by user_id, or None."""
    with Session(ENGINE) as session:
        row = session.get(JobRow, job_id)
        if not row or row.user_id != user_id:
            return None
        return row.outreach_text or None


def save_outreach_text(job_id: str, user_id: str, text: str) -> None:
    """Persist a generated outreach message onto a job row owned by user_id."""
    with Session(ENGINE) as session:
        row = session.get(JobRow, job_id)
        if row and row.user_id == user_id:
            row.outreach_text = text
            session.commit()


def increment_enrichment_failures(job_id: str) -> int:
    """
    Increment the enrichment_failures counter for a job and return the new count.
    Called when the s2 LLM pass returns a non-substantive result.
    """
    with Session(ENGINE) as session:
        row = session.get(JobRow, job_id)
        if row:
            current = int(row.enrichment_failures or 0)
            row.enrichment_failures = current + 1
            session.commit()
            return row.enrichment_failures
    return 0


def update_enrichment_result(
    job_id: str,
    user_id: str,
    *,
    score: float,
    is_proxy: bool,
    reasons: list[dict],
    why_ron: Optional[str] = None,
    culture_delta: Optional[float] = None,
    culture_alignment: Optional[float] = None,
    culture_category: Optional[str] = None,
    culture_note: Optional[str] = None,
    increment_failure: bool = False,
) -> int:
    """
    Persist one s2 enrichment outcome in a single SELECT + UPDATE instead of
    the three separate round trips (update_match_score, then either
    update_why_ron or increment_enrichment_failures, then update_reasons)
    feed_service._enrich_one previously issued per job (JOB-6 write N+1 fix).

    Exactly one of `why_ron` / `increment_failure=True` should be passed,
    matching the has_analysis / not-has_analysis branches in _enrich_one.

    Returns the row's enrichment_failures count after the update (0 if the
    row wasn't found/owned, or if increment_failure was not requested and the
    stored value is unchanged — callers that don't need it can ignore it).
    """
    with Session(ENGINE) as session:
        row = session.get(JobRow, job_id)
        if not row or row.user_id != user_id:
            return 0

        row.match_score    = score
        row.score_is_proxy = is_proxy
        row.reasons        = reasons
        if why_ron is not None:
            row.why_ron = why_ron
        if culture_delta is not None:
            row.culture_delta = culture_delta
        if culture_alignment is not None:
            row.culture_alignment = culture_alignment
        if culture_category is not None:
            row.culture_category = culture_category
        if culture_note is not None:
            row.culture_note = culture_note
        if increment_failure:
            row.enrichment_failures = int(row.enrichment_failures or 0) + 1

        session.commit()
        return int(row.enrichment_failures or 0)


def reset_job_for_enrichment(job_id: str) -> bool:
    """
    Force a job row back to "un-enriched" state so the next s2 run picks it
    up unconditionally, even if why_ron was previously set by a DEV mock or
    an earlier enrichment pass.

    Sets:
      • match_score = 0.0  — makes the job visible to get_jobs_needing_llm_enrichment
      • why_ron     = None — clears the "already enriched" sentinel

    Only touches the row if it exists.  Returns True when found, False otherwise.
    Intended for DEV_MODE pre-enrichment resets; safe to call in production but
    generally not needed there.
    """
    with Session(ENGINE) as session:
        row = session.get(JobRow, job_id)
        if not row:
            return False
        row.match_score = 0.0
        row.why_ron     = None
        session.commit()
        return True


# ── Legacy helper (used by the LangGraph orchestrator workflow) ───────────────

def build_from_result(result: dict) -> JobMatch:
    """Convert a run_analysis() result dict into a JobMatch for storage."""
    job_info = result.get("job_info", {})
    gap      = result.get("gap_analysis", {})
    truth    = result.get("truth_report", {})

    score  = truth.get("fit_score") or gap.get("overall_fit_score", 50)
    url    = job_info.get("url", "")
    job_id = f"analyzed-{abs(hash(url)) % 10_000_000}"

    reasons: list[ReasonTag] = []
    for match in gap.get("direct_matches", [])[:3]:
        req      = match.get("requirement", "")
        evidence = match.get("evidence", "")
        label    = req[:40] if req else evidence[:40]
        kind     = "exp" if any(w in req.lower() for w in ["year", "experience", "background"]) else "skill"
        if label:
            reasons.append(ReasonTag(kind=kind, label=label))

    location = job_info.get("location", "")
    if "remote" in location.lower():
        reasons.append(ReasonTag(kind="loc", label="Remote"))

    for gap_item in gap.get("profile_gaps", []):
        if gap_item.get("severity") == "high":
            label = gap_item.get("gap", "")[:40]
            if label:
                reasons.append(ReasonTag(kind="neg", label=label))
            break

    now       = datetime.now(timezone.utc)
    posted_at = now.strftime("%-I:%M %p").lower() + " today"

    return JobMatch(
        job_id=job_id,
        title=job_info.get("title", "Analyzed Role"),
        company=job_info.get("company", "Unknown Company"),
        location=location or "Unknown",
        score=float(score),
        confidence_score=50,
        culture_fit_score=50,
        trajectory_alignment="",
        company_dna_inference="",
        detailed_analysis=DetailedAnalysis(
            strengths=[],
            critical_gaps=[],
            strategic_advice=[],
        ),
        investigation_points=[],
        reasons=reasons,
        apply_url=url or None,
        is_new=True,
        posted_at=posted_at,
        why_ron=result.get("why_ron") or None,
    )


def count_for_user(user_id: str, session: Optional[Session] = None) -> int:
    """Number of JobRow rows owned by user_id."""
    if session is not None:
        return session.query(JobRow).filter(JobRow.user_id == user_id).count()
    with Session(ENGINE) as owned_session:
        return owned_session.query(JobRow).filter(JobRow.user_id == user_id).count()


def reassign_user(old_user_id: str, new_user_id: str, session: Session) -> int:
    """
    Re-point every JobRow owned by old_user_id to new_user_id.

    Takes an already-open Session so the caller (account-linking/migration
    flows in auth.py) can combine this with reassignments on other tables
    in one atomic commit.
    """
    return (
        session.query(JobRow)
        .filter(JobRow.user_id == old_user_id)
        .update({"user_id": new_user_id}, synchronize_session="fetch")
    )
