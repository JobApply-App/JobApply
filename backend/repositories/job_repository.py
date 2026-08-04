"""
Persistent job store, backed by the normalized job_postings/user_job_matches
tables (Postgres/Supabase). All functions preserve the exact same signatures
and return types (JobMatch) as the old single-table `jobs` implementation, so
every calling service needs no changes.

Phase 2 jobs pipeline cutover (docs/db-redesign-proposal.md): job_postings
holds objective, normalized job facts (title, company, location, jd_text,
jd_structured, posted_at, apply_url, ...) — GLOBAL, shared across every user
who has matched against that posting. user_job_matches holds per-user
affinity/score/status state (score, match_score, status, applied,
tailored_cv, reasons, investigation_points, ...), keyed by (user_id,
job_posting_id), with its own external-facing `job_id` TEXT column that
preserves the exact same salted string identifier
(base_scraper.make_tenant_job_id) every route/service/the frontend already
passes around — only the internal storage moved, not the public contract.

Behavior change from the old jobs table, and why it's correct here: the old
save_with_source_priority() had an elaborate "match the calling user's own
row first; a match on another tenant's row is only read-only-borrowed, never
reassigned" dance (JOB-92). That existed because the old `jobs` table
illegally mixed GLOBAL posting facts with PER-USER match state in one row,
so two tenants scraping the same posting had to get two independent rows to
avoid one tenant's private score/status overwriting another's. With
job_postings/user_job_matches properly separated, that problem doesn't exist
any more: job_postings is deliberately ONE shared row per canonical_job_key,
and a source-priority upgrade there (e.g. a company-site scrape enriching a
posting previously only seen via LinkedIn) now correctly benefits every
tenant matched against it — that's what a normalized global job catalog is
for. user_job_matches rows remain strictly per-user and are never touched by
another tenant's write.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import unicodedata
import uuid as _uuid
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.core.database import ENGINE
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
    s = unicodedata.normalize("NFD", s.lower().strip())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = re.sub(r"[^\w\s]", "", s)
    return re.sub(r"\s+", " ", s).strip()


def canonical_dedup_key(title: str, company: str, location: str) -> str:
    """
    Return a 16-char hex fingerprint for (title, company, location).

    Used both as job_postings.canonical_job_key (cross-board global dedup —
    the same role posted on Drushim and AllJobs shares one job_postings row)
    and, historically, as the old jobs.dedup_key. The key is intentionally
    short to avoid uniqueness collisions from minor phrasing differences —
    it acts as a soft filter, not a strict equality check.
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


def _parse_posted_at(value: Optional[str]) -> Optional[datetime]:
    """
    Best-effort parse of JobMatch.posted_at into job_postings.posted_at
    (a real TIMESTAMPTZ). Scrapers mostly write a human-relative display
    string here ("2 hours ago", "just now") rather than a real date — those
    are left as NULL rather than guessed at; a genuinely ISO-parseable value
    (some sources do provide one) is preserved.
    """
    if not value:
        return None
    try:
        s = value[:-1] + "+00:00" if value.endswith("Z") else value
        dt = datetime.fromisoformat(s)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


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


# ── Row assembly ──────────────────────────────────────────────────────────────

_SELECT_JOINED = """
    SELECT
        ujm.job_id, ujm.user_id, ujm.score, ujm.match_score, ujm.confidence_score,
        ujm.culture_fit_score, ujm.culture_delta, ujm.culture_alignment,
        ujm.culture_category, ujm.culture_note, ujm.trajectory_alignment,
        ujm.company_dna_inference, ujm.investigation_points, ujm.detailed_analysis,
        ujm.reasons, ujm.fit_brief, ujm.scoring_rationale, ujm.category,
        ujm.tailored_cv, ujm.applied, ujm.applied_at, ujm.status, ujm.is_new,
        ujm.score_is_proxy, ujm.enrichment_failures, ujm.outreach_text,
        ujm.created_at AS match_created_at,
        jp.id AS job_posting_id, jp.title, jp.company, jp.location, jp.jd_text,
        jp.jd_structured, jp.apply_url, jp.source, jp.source_type,
        jp.company_website_url, jp.locale, jp.posted_at, jp.is_open,
        jp.canonical_job_key
    FROM public.user_job_matches ujm
    JOIN public.job_postings jp ON jp.id = ujm.job_posting_id
"""


def _row_to_jobmatch(r) -> JobMatch:
    da = r.detailed_analysis or {}
    return JobMatch(
        job_id=r.job_id,
        title=r.title,
        company=r.company,
        location=r.location,
        score=r.score,
        confidence_score=r.confidence_score,
        culture_fit_score=r.culture_fit_score,
        culture_delta=r.culture_delta,
        culture_alignment=r.culture_alignment,
        culture_category=r.culture_category,
        culture_note=r.culture_note,
        trajectory_alignment=r.trajectory_alignment or "",
        company_dna_inference=r.company_dna_inference or "",
        investigation_points=list(r.investigation_points or []),
        detailed_analysis=DetailedAnalysis(
            strengths=da.get("strengths", []),
            critical_gaps=da.get("critical_gaps", []),
            strategic_advice=da.get("strategic_advice", []),
        ),
        reasons=[ReasonTag(kind=x["kind"], label=x["label"]) for x in (r.reasons or [])],
        apply_url=r.apply_url,
        is_new=bool(r.is_new),
        posted_at=(r.posted_at.isoformat() if r.posted_at else ""),
        fit_brief=r.fit_brief,
        scoring_rationale=r.scoring_rationale,
        category=r.category,
        applied=bool(r.applied),
        applied_at=(r.applied_at.isoformat() if r.applied_at else None),
        source=r.source or 'automatic',
        is_open=bool(r.is_open) if r.is_open is not None else True,
        jd_text=r.jd_text,
        # jd_structured comes back auto-deserialized from jsonb (dict/list/None) --
        # JobMatch.jd_structured is a JSON *string* contract, so re-serialize.
        jd_structured=(json.dumps(r.jd_structured) if r.jd_structured is not None else None),
        user_id=str(r.user_id),
        source_type=_infer_source_type(r.source_type, r.apply_url),
        company_website_url=r.company_website_url,
        status=r.status or "new",
        match_score=float(r.match_score) if r.match_score is not None else 0.0,
        score_is_proxy=bool(r.score_is_proxy) if r.score_is_proxy is not None else True,
        created_at=(r.match_created_at.isoformat() if r.match_created_at else None),
        locale=r.locale,
        has_tailored_cv=bool(r.tailored_cv),
        enrichment_failures=int(r.enrichment_failures) if r.enrichment_failures is not None else 0,
    )


def _get_joined(session, *, job_id: Optional[str] = None, user_id: Optional[str] = None,
                 apply_url: Optional[str] = None, extra_where: str = "", params: Optional[dict] = None):
    """Shared SELECT ... WHERE builder for the common (job_id, user_id) / (apply_url, user_id) lookups."""
    where = []
    p = dict(params or {})
    if job_id is not None:
        where.append("ujm.job_id = :job_id")
        p["job_id"] = job_id
    if user_id is not None:
        where.append("ujm.user_id = CAST(:user_id AS uuid)")
        p["user_id"] = user_id
    if apply_url is not None:
        where.append("jp.apply_url = :apply_url")
        p["apply_url"] = apply_url
    if extra_where:
        where.append(extra_where)
    sql = _SELECT_JOINED + (" WHERE " + " AND ".join(where) if where else "")
    return session.execute(text(sql), p).fetchall()


# ── Posting upsert (global, shared across tenants) ───────────────────────────

def _upsert_posting(session, job: JobMatch) -> _uuid.UUID:
    """
    Upsert job_postings by canonical_job_key. On conflict, only upgrades
    source-origin fields (source_type/apply_url/company_website_url/jd_text)
    when the incoming source outranks the stored one — this benefits every
    tenant matched against this posting, since job_postings is shared.
    """
    canonical_key = canonical_dedup_key(job.title, job.company, job.location)

    existing = session.execute(
        text("SELECT id, source_type, apply_url, company_website_url, jd_text, locale "
             "FROM public.job_postings WHERE canonical_job_key = :key"),
        {"key": canonical_key},
    ).fetchone()

    if existing is None:
        posting_id = session.execute(
            text("""
                INSERT INTO public.job_postings
                    (canonical_job_key, title, company, company_website_url, location, jd_text,
                     jd_structured, apply_url, source, source_type, locale, posted_at, is_open)
                VALUES
                    (:key, :title, :company, :company_url, :location, :jd_text,
                     CAST(:jd_structured AS jsonb), :apply_url, :source, :source_type, :locale,
                     :posted_at, :is_open)
                RETURNING id
            """),
            {
                "key": canonical_key, "title": job.title, "company": job.company,
                "company_url": job.company_website_url, "location": job.location,
                "jd_text": job.jd_text,
                # jd_structured is already a JSON string (JobMatch's own contract) --
                "jd_structured": job.jd_structured,
                "apply_url": job.apply_url, "source": job.source, "source_type": job.source_type,
                "locale": job.locale, "posted_at": _parse_posted_at(job.posted_at), "is_open": job.is_open,
            },
        ).scalar_one()
        return posting_id

    posting_id = existing.id
    updates = {}
    if _source_rank(job.source_type) > _source_rank(existing.source_type):
        updates["source_type"] = job.source_type
        updates["apply_url"] = job.apply_url or existing.apply_url
        updates["company_website_url"] = job.company_website_url or existing.company_website_url
    if job.jd_text and not existing.jd_text:
        updates["jd_text"] = job.jd_text
    if job.locale and not existing.locale:
        updates["locale"] = job.locale
    if updates:
        set_clause = ", ".join(f"{k} = :{k}" for k in updates)
        session.execute(
            text(f"UPDATE public.job_postings SET {set_clause} WHERE id = :id"),
            {**updates, "id": posting_id},
        )
    return posting_id


def _insert_match(session, job: JobMatch, posting_id) -> None:
    session.execute(
        text("""
            INSERT INTO public.user_job_matches
                (user_id, job_posting_id, job_id, score, match_score, confidence_score,
                 culture_fit_score, trajectory_alignment, company_dna_inference,
                 investigation_points, detailed_analysis, reasons, fit_brief, scoring_rationale,
                 tailored_cv, status, is_new, applied, applied_at, category, score_is_proxy,
                 enrichment_failures, outreach_text, culture_delta, culture_alignment,
                 culture_category, culture_note)
            VALUES
                (CAST(:user_id AS uuid), :posting_id, :job_id, :score, :match_score,
                 :confidence_score, :culture_fit_score, :trajectory_alignment,
                 :company_dna_inference, CAST(:investigation_points AS jsonb),
                 CAST(:detailed_analysis AS jsonb), CAST(:reasons AS jsonb), :fit_brief,
                 :scoring_rationale, CAST(:tailored_cv AS jsonb), :status, :is_new, :applied,
                 :applied_at, :category, :score_is_proxy, :enrichment_failures, :outreach_text,
                 :culture_delta, :culture_alignment, :culture_category, :culture_note)
        """),
        {
            "user_id": job.user_id, "posting_id": posting_id, "job_id": job.job_id,
            "score": job.score, "match_score": job.match_score,
            "confidence_score": job.confidence_score, "culture_fit_score": job.culture_fit_score,
            "trajectory_alignment": job.trajectory_alignment,
            "company_dna_inference": job.company_dna_inference,
            "investigation_points": json.dumps(list(job.investigation_points)),
            "detailed_analysis": json.dumps({
                "strengths": list(job.detailed_analysis.strengths),
                "critical_gaps": list(job.detailed_analysis.critical_gaps),
                "strategic_advice": list(job.detailed_analysis.strategic_advice),
            }),
            "reasons": json.dumps([{"kind": r.kind, "label": r.label} for r in job.reasons]),
            "fit_brief": job.fit_brief, "scoring_rationale": job.scoring_rationale,
            "tailored_cv": json.dumps(job.tailored_cv) if getattr(job, "tailored_cv", None) else None,
            "status": job.status, "is_new": job.is_new, "applied": job.applied,
            "applied_at": job.applied_at, "category": job.category,
            "score_is_proxy": job.score_is_proxy, "enrichment_failures": job.enrichment_failures,
            "outreach_text": getattr(job, "outreach_text", None),
            "culture_delta": job.culture_delta, "culture_alignment": job.culture_alignment,
            "culture_category": job.culture_category, "culture_note": job.culture_note,
        },
    )


# ── Public API (same signatures as the old in-memory/single-table store) ─────

def save(job: JobMatch) -> None:
    """Upsert a JobMatch: insert on first save, update on re-analysis of the same job_id."""
    with Session(ENGINE) as session:
        existing = _get_joined(session, job_id=job.job_id, user_id=job.user_id)
        posting_id = _upsert_posting(session, job)
        if existing:
            _update_match_from_jobmatch(session, job.job_id, job.user_id, job)
        else:
            _insert_match(session, job, posting_id)
        session.commit()


def _update_match_from_jobmatch(session, job_id: str, user_id: str, job: JobMatch) -> None:
    session.execute(
        text("""
            UPDATE public.user_job_matches SET
                score = :score, match_score = :match_score, confidence_score = :confidence_score,
                culture_fit_score = :culture_fit_score, trajectory_alignment = :trajectory_alignment,
                company_dna_inference = :company_dna_inference,
                investigation_points = CAST(:investigation_points AS jsonb),
                detailed_analysis = CAST(:detailed_analysis AS jsonb),
                reasons = CAST(:reasons AS jsonb), fit_brief = :fit_brief,
                scoring_rationale = :scoring_rationale, status = :status, is_new = :is_new,
                applied = :applied, applied_at = :applied_at, category = :category,
                score_is_proxy = :score_is_proxy, enrichment_failures = :enrichment_failures,
                culture_delta = :culture_delta, culture_alignment = :culture_alignment,
                culture_category = :culture_category, culture_note = :culture_note
            WHERE job_id = :job_id AND user_id = CAST(:user_id AS uuid)
        """),
        {
            "job_id": job_id, "user_id": user_id, "score": job.score, "match_score": job.match_score,
            "confidence_score": job.confidence_score, "culture_fit_score": job.culture_fit_score,
            "trajectory_alignment": job.trajectory_alignment,
            "company_dna_inference": job.company_dna_inference,
            "investigation_points": json.dumps(list(job.investigation_points)),
            "detailed_analysis": json.dumps({
                "strengths": list(job.detailed_analysis.strengths),
                "critical_gaps": list(job.detailed_analysis.critical_gaps),
                "strategic_advice": list(job.detailed_analysis.strategic_advice),
            }),
            "reasons": json.dumps([{"kind": r.kind, "label": r.label} for r in job.reasons]),
            "fit_brief": job.fit_brief, "scoring_rationale": job.scoring_rationale,
            "status": job.status, "is_new": job.is_new, "applied": job.applied,
            "applied_at": job.applied_at, "category": job.category,
            "score_is_proxy": job.score_is_proxy, "enrichment_failures": job.enrichment_failures,
            "culture_delta": job.culture_delta, "culture_alignment": job.culture_alignment,
            "culture_category": job.culture_category, "culture_note": job.culture_note,
        },
    )


def save_with_source_priority(job: JobMatch) -> bool:
    """
    Upsert with source priority: company_site > linkedin > other.

    job_postings is upserted by canonical_job_key (global — see module
    docstring); a higher-priority source upgrades it for every tenant.
    user_job_matches existence is then just (user_id, job_posting_id):
    if the calling user already has a match row for this posting, it's
    updated in place; otherwise a new one is inserted.

    Returns True only when a brand-new user_job_matches row was inserted.
    """
    with Session(ENGINE) as session:
        posting_id = _upsert_posting(session, job)
        existing = session.execute(
            text("SELECT 1 FROM public.user_job_matches WHERE job_posting_id = :pid AND user_id = CAST(:uid AS uuid)"),
            {"pid": posting_id, "uid": job.user_id},
        ).fetchone()
        if existing:
            _update_match_from_jobmatch(session, job.job_id, job.user_id, job)
            session.commit()
            return False
        _insert_match(session, job, posting_id)
        session.commit()
        return True


def update_scores(job_id: str, user_id: str, *, fit_score: Optional[float] = None,
                   ats_score: Optional[float] = None) -> bool:
    """Update fit score and/or ATS match_score for a job owned by user_id. Returns True if found."""
    with Session(ENGINE) as session:
        sets, params = [], {"job_id": job_id, "user_id": user_id}
        if fit_score is not None:
            sets.append("score = :score")
            params["score"] = max(0.0, float(fit_score))
        if ats_score is not None:
            sets.append("match_score = :match_score")
            params["match_score"] = max(0.0, float(ats_score))
        if not sets:
            return False
        result = session.execute(
            text(f"UPDATE public.user_job_matches SET {', '.join(sets)} "
                 "WHERE job_id = :job_id AND user_id = CAST(:user_id AS uuid)"),
            params,
        )
        session.commit()
        return result.rowcount > 0


def get_all(user_id: str) -> list[JobMatch]:
    """Return all stored jobs owned by user_id, sorted by score descending."""
    with Session(ENGINE) as session:
        rows = _get_joined(session, user_id=user_id)
        rows = sorted(rows, key=lambda r: (r.score if r.score is not None else 0), reverse=True)
        return [_row_to_jobmatch(r) for r in rows]


def is_empty(user_id: str) -> bool:
    with Session(ENGINE) as session:
        n = session.execute(
            text("SELECT count(*) FROM public.user_job_matches WHERE user_id = CAST(:uid AS uuid)"),
            {"uid": user_id},
        ).scalar_one()
        return n == 0


def contains_url(url: str, user_id: str) -> bool:
    """Return True if a job with this apply_url already exists for user_id."""
    with Session(ENGINE) as session:
        rows = _get_joined(session, user_id=user_id, apply_url=url)
        return len(rows) > 0


def get_by_id(job_id: str, user_id: str) -> Optional[JobMatch]:
    """Return the stored JobMatch for a job_id owned by user_id, or None if not found/not owned."""
    with Session(ENGINE) as session:
        rows = _get_joined(session, job_id=job_id, user_id=user_id)
        return _row_to_jobmatch(rows[0]) if rows else None


def get_by_url(url: str, user_id: str) -> Optional[JobMatch]:
    """Return the stored JobMatch for a URL owned by user_id, or None if not found."""
    with Session(ENGINE) as session:
        rows = _get_joined(session, user_id=user_id, apply_url=url)
        return _row_to_jobmatch(rows[0]) if rows else None


def mark_closed(job_id: str, user_id: str) -> None:
    """Set is_open=False on the job posting for a match owned by user_id."""
    with Session(ENGINE) as session:
        session.execute(
            text("""
                UPDATE public.job_postings SET is_open = false
                WHERE id = (
                    SELECT job_posting_id FROM public.user_job_matches
                    WHERE job_id = :job_id AND user_id = CAST(:user_id AS uuid)
                )
            """),
            {"job_id": job_id, "user_id": user_id},
        )
        session.commit()


def get_categories(user_id: str) -> list[str]:
    """Return sorted list of unique non-null category tags for user_id."""
    with Session(ENGINE) as session:
        rows = session.execute(
            text("SELECT DISTINCT category FROM public.user_job_matches "
                 "WHERE user_id = CAST(:uid AS uuid) AND category IS NOT NULL"),
            {"uid": user_id},
        ).fetchall()
        return sorted(r[0] for r in rows)


def get_eligible_for_apply(threshold: float, user_id: str) -> list[JobMatch]:
    """Return jobs for user_id with score >= threshold that have not been applied to yet."""
    with Session(ENGINE) as session:
        rows = _get_joined(session, user_id=user_id, extra_where="ujm.score >= :threshold AND ujm.applied = false",
                            params={"threshold": threshold})
        rows = sorted(rows, key=lambda r: (r.score if r.score is not None else 0), reverse=True)
        return [_row_to_jobmatch(r) for r in rows]


def mark_applied(job_id: str, applied_at: str, user_id: str) -> None:
    """Set applied=True and record the timestamp on a job row owned by user_id."""
    with Session(ENGINE) as session:
        session.execute(
            text("UPDATE public.user_job_matches SET applied = true, applied_at = CAST(:applied_at AS timestamptz) "
                 "WHERE job_id = :job_id AND user_id = CAST(:user_id AS uuid)"),
            {"job_id": job_id, "applied_at": applied_at, "user_id": user_id},
        )
        session.commit()


def get_tailored_cv(job_id: str, user_id: str) -> Optional[dict]:
    """
    Return the cached tailored CV payload for a job owned by user_id, or None.

    Returns None when the cached draft was generated from an older version of
    the user's master profile (see profile_fingerprint) — the caller then
    regenerates from current data instead of serving a draft built from
    since-edited experience/skills/contact details.
    """
    with Session(ENGINE) as session:
        row = session.execute(
            text("SELECT tailored_cv FROM public.user_job_matches "
                 "WHERE job_id = :job_id AND user_id = CAST(:user_id AS uuid)"),
            {"job_id": job_id, "user_id": user_id},
        ).fetchone()
        cached = row.tailored_cv if row else None

    if not cached:
        return None

    current = profile_fingerprint(user_id)
    if current and cached.get("profile_fingerprint") != current:
        logger.info(
            "[job_store] Tailored CV for job=%s is stale (profile changed) — ignoring cache",
            job_id,
        )
        return None
    return cached


def profile_fingerprint(user_id: str) -> str:
    """
    profiles.updated_at for user_id ("" when absent/unreadable).

    Stamped into the tailored-CV cache so a draft generated from an older
    master profile can be detected as stale — every write path through
    profile_repository / master_profile_service bumps updated_at, so a
    changed value means the source data the draft was built from has moved.
    """
    from backend.repositories.profile_repository import get_updated_at
    return get_updated_at(user_id)


def save_tailored_cv(job_id: str, user_id: str, cv_data: dict, match_score: Optional[dict]) -> None:
    """Persist the generated CV data + match score for a job owned by user_id."""
    payload = {
        "cv_data": cv_data,
        "match_score": match_score,
        "profile_fingerprint": profile_fingerprint(user_id),
    }
    with Session(ENGINE) as session:
        session.execute(
            text("UPDATE public.user_job_matches SET tailored_cv = CAST(:payload AS jsonb) "
                 "WHERE job_id = :job_id AND user_id = CAST(:user_id AS uuid)"),
            {"payload": json.dumps(payload), "job_id": job_id, "user_id": user_id},
        )
        session.commit()


def clear_tailored_cv(job_id: str, user_id: str) -> bool:
    """
    Drop the cached tailored CV for a job owned by user_id. Returns True if a
    cached payload was actually removed.
    """
    with Session(ENGINE) as session:
        result = session.execute(
            text("UPDATE public.user_job_matches SET tailored_cv = NULL "
                 "WHERE job_id = :job_id AND user_id = CAST(:user_id AS uuid) AND tailored_cv IS NOT NULL"),
            {"job_id": job_id, "user_id": user_id},
        )
        session.commit()
        return result.rowcount > 0


def get_feed(user_id: str, status_filter: Optional[str] = None) -> List[JobMatch]:
    """
    Return the job feed for a user, sorted by match_score DESC then created_at DESC.

    status_filter: optional JobStatus value ('new', 'saved', 'ignored', 'applied').
    When omitted, all statuses except 'ignored' are returned.

    AUTOCOMMIT is set on this one connection only (not the global engine) —
    a single read-only JOIN with no write and no cross-statement snapshot
    requirement, same reasoning as backend/api/routes/analytics.py's
    analytics_summary(). Measured: ~248ms average saved, 6/6 wins across
    interleaved A/B trials, byte-for-byte identical output.
    """
    with ENGINE.connect().execution_options(isolation_level="AUTOCOMMIT") as conn, \
            Session(bind=conn) as session:
        if status_filter:
            rows = _get_joined(session, user_id=user_id, extra_where="ujm.status = :status",
                                params={"status": status_filter})
        else:
            rows = _get_joined(session, user_id=user_id, extra_where="ujm.status != 'ignored'")
        rows = sorted(
            rows,
            key=lambda r: (
                r.match_score if r.match_score is not None else 0,
                r.match_created_at or datetime.min.replace(tzinfo=timezone.utc),
            ),
            reverse=True,
        )
        jobs = [_row_to_jobmatch(r) for r in rows]
        for job in jobs:
            job.is_direct_application = job.source_type == "company_site"
            job.is_bulk_import = job.job_id.startswith("li-bulk-")
        return jobs


def update_match_score(job_id: str, user_id: str, score: float, is_proxy: bool = False) -> None:
    """Persist a newly computed ATS match_score onto a job row owned by user_id."""
    with Session(ENGINE) as session:
        session.execute(
            text("UPDATE public.user_job_matches SET match_score = :score, score_is_proxy = :is_proxy "
                 "WHERE job_id = :job_id AND user_id = CAST(:user_id AS uuid)"),
            {"score": score, "is_proxy": is_proxy, "job_id": job_id, "user_id": user_id},
        )
        session.commit()


def update_reasons(job_id: str, user_id: str, reasons: list[dict]) -> None:
    """Replace the reasons column on a job row owned by user_id."""
    with Session(ENGINE) as session:
        session.execute(
            text("UPDATE public.user_job_matches SET reasons = CAST(:reasons AS jsonb) "
                 "WHERE job_id = :job_id AND user_id = CAST(:user_id AS uuid)"),
            {"reasons": json.dumps(reasons), "job_id": job_id, "user_id": user_id},
        )
        session.commit()


def update_status(job_id: str, user_id: str, status: str) -> bool:
    """
    Set the status field on a job row owned by user_id.
    Returns True if the row was found and updated, False if job_id unknown or not owned.
    """
    with Session(ENGINE) as session:
        result = session.execute(
            text("UPDATE public.user_job_matches SET status = :status "
                 "WHERE job_id = :job_id AND user_id = CAST(:user_id AS uuid)"),
            {"status": status, "job_id": job_id, "user_id": user_id},
        )
        session.commit()
        return result.rowcount > 0


def get_jobs_missing_jd_text(user_id: str, min_score: float = 50.0) -> List[JobMatch]:
    """
    Return jobs for a user with score >= min_score whose jd_text is missing or
    too short to be a real JD (< 100 chars after stripping whitespace).
    """
    with Session(ENGINE) as session:
        rows = _get_joined(session, user_id=user_id,
                            extra_where="ujm.score >= :min_score AND jp.apply_url IS NOT NULL",
                            params={"min_score": min_score})
        result = []
        for r in rows:
            t = (r.jd_text or "").strip()
            if len(t) < 100:
                result.append(_row_to_jobmatch(r))
        result.sort(key=lambda j: j.score, reverse=True)
        return result


def update_jd_text(job_id: str, text_: str) -> None:
    """Persist fetched JD text onto the job posting for job_id (any tenant's match row)."""
    with Session(ENGINE) as session:
        session.execute(
            text("""
                UPDATE public.job_postings SET jd_text = :jd_text
                WHERE id = (SELECT job_posting_id FROM public.user_job_matches WHERE job_id = :job_id LIMIT 1)
            """),
            {"jd_text": text_, "job_id": job_id},
        )
        session.commit()


def update_jd_structured(job_id: str, structured_json: str) -> None:
    """Persist LLM-structured JD JSON string onto the job posting for job_id."""
    with Session(ENGINE) as session:
        session.execute(
            text("""
                UPDATE public.job_postings SET jd_structured = CAST(:structured AS jsonb)
                WHERE id = (SELECT job_posting_id FROM public.user_job_matches WHERE job_id = :job_id LIMIT 1)
            """),
            {"structured": structured_json, "job_id": job_id},
        )
        session.commit()


def update_company(job_id: str, company: str) -> None:
    """Overwrite the company field on the job posting for job_id."""
    if not company or not company.strip():
        return
    with Session(ENGINE) as session:
        session.execute(
            text("""
                UPDATE public.job_postings SET company = :company
                WHERE id = (SELECT job_posting_id FROM public.user_job_matches WHERE job_id = :job_id LIMIT 1)
            """),
            {"company": company.strip(), "job_id": job_id},
        )
        session.commit()


def get_unscored_new_jobs(user_id: str) -> List[JobMatch]:
    """
    Return jobs for a user that are status='new' and have not yet been
    ATS-scored (match_score == 0.0).
    """
    with Session(ENGINE) as session:
        rows = _get_joined(session, user_id=user_id,
                            extra_where="ujm.status = 'new' AND ujm.match_score = 0.0")
        return [_row_to_jobmatch(r) for r in rows]


def get_jobs_needing_llm_enrichment(user_id: str) -> List[JobMatch]:
    """
    Return all jobs for user_id that need the s2 LLM enrichment pass:
    match_score == 0.0 OR fit_brief IS NULL, ordered by match_score DESC.
    """
    with Session(ENGINE) as session:
        rows = _get_joined(
            session, user_id=user_id,
            extra_where="ujm.status IN ('new', 'saved') AND (ujm.match_score = 0.0 OR ujm.fit_brief IS NULL)",
        )
        rows = sorted(rows, key=lambda r: (r.match_score if r.match_score is not None else 0), reverse=True)
        return [_row_to_jobmatch(r) for r in rows]


def update_fit_brief(job_id: str, user_id: str, fit_brief: str) -> None:
    """Persist the LLM-generated 'why apply' brief onto a job row owned by user_id."""
    with Session(ENGINE) as session:
        session.execute(
            text("UPDATE public.user_job_matches SET fit_brief = :fit_brief "
                 "WHERE job_id = :job_id AND user_id = CAST(:user_id AS uuid)"),
            {"fit_brief": fit_brief, "job_id": job_id, "user_id": user_id},
        )
        session.commit()


def get_outreach_text(job_id: str, user_id: str) -> Optional[str]:
    """Return the persisted outreach message for a job owned by user_id, or None."""
    with Session(ENGINE) as session:
        row = session.execute(
            text("SELECT outreach_text FROM public.user_job_matches "
                 "WHERE job_id = :job_id AND user_id = CAST(:user_id AS uuid)"),
            {"job_id": job_id, "user_id": user_id},
        ).fetchone()
        return (row.outreach_text or None) if row else None


def save_outreach_text(job_id: str, user_id: str, text_: str) -> None:
    """Persist a generated outreach message onto a job row owned by user_id."""
    with Session(ENGINE) as session:
        session.execute(
            text("UPDATE public.user_job_matches SET outreach_text = :text "
                 "WHERE job_id = :job_id AND user_id = CAST(:user_id AS uuid)"),
            {"text": text_, "job_id": job_id, "user_id": user_id},
        )
        session.commit()


def increment_enrichment_failures(job_id: str) -> int:
    """
    Increment the enrichment_failures counter for a job (any tenant's match
    row for this job_id) and return the new count.
    """
    with Session(ENGINE) as session:
        row = session.execute(
            text("UPDATE public.user_job_matches SET enrichment_failures = enrichment_failures + 1 "
                 "WHERE job_id = :job_id RETURNING enrichment_failures"),
            {"job_id": job_id},
        ).fetchone()
        session.commit()
        return int(row[0]) if row else 0


def update_enrichment_result(
    job_id: str,
    user_id: str,
    *,
    score: float,
    is_proxy: bool,
    reasons: list[dict],
    fit_brief: Optional[str] = None,
    culture_delta: Optional[float] = None,
    culture_alignment: Optional[float] = None,
    culture_category: Optional[str] = None,
    culture_note: Optional[str] = None,
    increment_failure: bool = False,
) -> int:
    """
    Persist one s2 enrichment outcome in a single UPDATE instead of three
    separate round trips (JOB-6 write N+1 fix) — same contract as before.

    Returns the row's enrichment_failures count after the update (0 if the
    row wasn't found/owned).
    """
    with Session(ENGINE) as session:
        sets = [
            "match_score = :score", "score_is_proxy = :is_proxy",
            "reasons = CAST(:reasons AS jsonb)",
        ]
        params = {
            "score": score, "is_proxy": is_proxy, "reasons": json.dumps(reasons),
            "job_id": job_id, "user_id": user_id,
        }
        if fit_brief is not None:
            sets.append("fit_brief = :fit_brief")
            params["fit_brief"] = fit_brief
        if culture_delta is not None:
            sets.append("culture_delta = :culture_delta")
            params["culture_delta"] = culture_delta
        if culture_alignment is not None:
            sets.append("culture_alignment = :culture_alignment")
            params["culture_alignment"] = culture_alignment
        if culture_category is not None:
            sets.append("culture_category = :culture_category")
            params["culture_category"] = culture_category
        if culture_note is not None:
            sets.append("culture_note = :culture_note")
            params["culture_note"] = culture_note
        if increment_failure:
            sets.append("enrichment_failures = enrichment_failures + 1")

        row = session.execute(
            text(f"UPDATE public.user_job_matches SET {', '.join(sets)} "
                 "WHERE job_id = :job_id AND user_id = CAST(:user_id AS uuid) "
                 "RETURNING enrichment_failures"),
            params,
        ).fetchone()
        session.commit()
        return int(row[0]) if row else 0


def reset_job_for_enrichment(job_id: str) -> bool:
    """
    Force a job row back to "un-enriched" state so the next s2 run picks it
    up unconditionally. Intended for DEV_MODE pre-enrichment resets.
    """
    with Session(ENGINE) as session:
        result = session.execute(
            text("UPDATE public.user_job_matches SET match_score = 0.0, fit_brief = NULL "
                 "WHERE job_id = :job_id"),
            {"job_id": job_id},
        )
        session.commit()
        return result.rowcount > 0


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
        fit_brief=result.get("fit_brief") or None,
    )


def count_for_user(user_id: str, session: Optional[Session] = None) -> int:
    """Number of user_job_matches rows owned by user_id."""
    def _count(s):
        return s.execute(
            text("SELECT count(*) FROM public.user_job_matches WHERE user_id = CAST(:uid AS uuid)"),
            {"uid": user_id},
        ).scalar_one()
    if session is not None:
        return _count(session)
    with Session(ENGINE) as owned_session:
        return _count(owned_session)


def reassign_user(old_user_id: str, new_user_id: str, session: Session) -> int:
    """
    Re-point every user_job_matches row owned by old_user_id to new_user_id.

    Takes an already-open Session so the caller (account-linking flow in
    auth.py) can combine this with reassignments on other tables in one
    atomic commit. Both ids must be valid auth.users UUIDs (FK-enforced).
    """
    result = session.execute(
        text("UPDATE public.user_job_matches SET user_id = CAST(:new_uid AS uuid) "
             "WHERE user_id = CAST(:old_uid AS uuid)"),
        {"new_uid": new_user_id, "old_uid": old_user_id},
    )
    return result.rowcount
