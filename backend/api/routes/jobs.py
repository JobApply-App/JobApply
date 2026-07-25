from __future__ import annotations

import asyncio
import logging
import traceback
import uuid
from datetime import datetime, timezone
from typing import List, Optional

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from backend.api.deps import CurrentUser, get_current_user, llm_rate_limit, require_admin
from backend.schemas.job import DetailedAnalysis, JobMatch, RawJobPosting, ReasonTag
import backend.repositories.job_repository as job_store
from backend.services import feed_service
from backend.url_scraper import scrape_job_post
from backend.scrapers.url_router import (
    scrape_jd_text,
    scrape_linkedin_job,
    LinkedInAuthWallError,
    LinkedInRedirectError,
    LinkedInChallengeError,
    LinkedInRapidApiAuthError,
    LinkedInRapidApiQuotaError,
)
from backend.agents.matcher import MatcherAgent
from backend.scrapers.scraper_manager import SCRAPER_MANAGER, scraper_from_config

_HTTP_TIMEOUT = 10  # seconds for liveness probe

logger = logging.getLogger(__name__)

router = APIRouter()

def _mock_analysis(strengths: list[str], gaps: list[str]) -> DetailedAnalysis:
    return DetailedAnalysis(
        strengths=strengths,
        critical_gaps=gaps,
        strategic_advice=[],
    )


_MOCK_JOBS: list[JobMatch] = [
    JobMatch(
        job_id="j1", title="Senior Product Designer, Platform", company="Linear Orbit",
        location="San Francisco · Remote OK", score=94, is_new=True, posted_at="2h ago",
        apply_url="https://example.com/apply/j1",
        confidence_score=82, culture_fit_score=88,
        trajectory_alignment="Strong next step — platform scope aligns with systems background.",
        company_dna_inference="Product-led, high-autonomy startup. Engineering-first culture.",
        detailed_analysis=_mock_analysis(
            strengths=["Design systems leadership", "Platform UX ownership"],
            gaps=[],
        ),
        investigation_points=["Describe your largest design system token architecture."],
        reasons=[
            ReasonTag(kind="skill", label="Design systems · 7y"),
            ReasonTag(kind="exp",   label="Platform UX"),
            ReasonTag(kind="loc",   label="Remote-friendly"),
        ],
    ),
    JobMatch(
        job_id="j2", title="Principal Designer, AI Products", company="Harbor AI",
        location="Remote, US", score=91, is_new=True, posted_at="4h ago",
        apply_url="https://example.com/apply/j2",
        confidence_score=79, culture_fit_score=84,
        trajectory_alignment="Logical step up — AI product scope matches progression.",
        company_dna_inference="Early-stage AI startup, fast-paced with high ownership expectations.",
        detailed_analysis=_mock_analysis(
            strengths=["AI product UX", "Code prototyping"],
            gaps=["Leadership tenure < 2 years at current level"],
        ),
        investigation_points=["Walk me through an AI feature you shipped end-to-end."],
        reasons=[
            ReasonTag(kind="skill", label="AI product UX"),
            ReasonTag(kind="skill", label="Prototyping in code"),
            ReasonTag(kind="exp",   label="10+ yrs leadership"),
            ReasonTag(kind="loc",   label="Fully remote"),
        ],
    ),
    JobMatch(
        job_id="j3", title="Staff UX Researcher", company="Northwind Health",
        location="New York — Hybrid", score=88, is_new=True, posted_at="6h ago",
        apply_url="https://example.com/apply/j3",
        confidence_score=75, culture_fit_score=70,
        trajectory_alignment="Reasonable fit but on-site requirement reduces flexibility.",
        company_dna_inference="Enterprise health-tech, process-heavy, compliance-oriented culture.",
        detailed_analysis=_mock_analysis(
            strengths=["Mixed-methods research", "Healthcare domain experience"],
            gaps=["On-site 3 days/week conflicts with stated remote preference"],
        ),
        investigation_points=["How do you run research in a HIPAA-constrained environment?"],
        reasons=[
            ReasonTag(kind="skill", label="Mixed-methods research"),
            ReasonTag(kind="exp",   label="Healthcare · 4y"),
            ReasonTag(kind="neg",   label="On-site 3d/wk"),
        ],
    ),
    JobMatch(
        job_id="j4", title="Senior Designer, Growth", company="Fernway",
        location="Austin · Remote OK", score=82, is_new=False, posted_at="1d ago",
        apply_url="https://example.com/apply/j4",
        confidence_score=72, culture_fit_score=78,
        trajectory_alignment="Solid lateral move — growth focus adds new dimension to portfolio.",
        company_dna_inference="Growth-stage B2C marketplace, data-driven and fast-moving.",
        detailed_analysis=_mock_analysis(
            strengths=["Growth experimentation", "B2C marketplace experience"],
            gaps=[],
        ),
        investigation_points=["What metric did you move most significantly in a growth experiment?"],
        reasons=[
            ReasonTag(kind="skill", label="Growth experimentation"),
            ReasonTag(kind="exp",   label="B2C marketplace"),
        ],
    ),
    JobMatch(
        job_id="j5", title="Lead Designer, Design Systems", company="Quillford",
        location="Remote, Americas", score=79, is_new=False, posted_at="1d ago",
        apply_url="https://example.com/apply/j5",
        confidence_score=68, culture_fit_score=74,
        trajectory_alignment="Specialisation play — narrows scope but deepens systems expertise.",
        company_dna_inference="Mid-stage SaaS, multiple brand lines, structured team hierarchy.",
        detailed_analysis=_mock_analysis(
            strengths=["Token architecture", "Multi-brand system management"],
            gaps=["Scope narrower than current trajectory suggests"],
        ),
        investigation_points=["How do you handle design token conflicts across brand themes?"],
        reasons=[
            ReasonTag(kind="skill", label="Tokens & theming"),
            ReasonTag(kind="exp",   label="Multi-brand systems"),
        ],
    ),
    JobMatch(
        job_id="j6", title="Product Designer II", company="Pallet & Co.",
        location="Remote, EU", score=71, is_new=False, posted_at="2d ago",
        apply_url="https://example.com/apply/j6",
        confidence_score=61, culture_fit_score=65,
        trajectory_alignment="Step back in seniority level — only viable as a strategic pivot.",
        company_dna_inference="Small EU-based SaaS, async-first, lean team with broad scope.",
        detailed_analysis=_mock_analysis(
            strengths=["SaaS dashboard experience"],
            gaps=["Level II is below current seniority", "EU timezone mismatch"],
        ),
        investigation_points=["Why are you considering a step back in title?"],
        reasons=[
            ReasonTag(kind="skill", label="SaaS dashboards"),
            ReasonTag(kind="neg",   label="EU hours"),
        ],
    ),
]


def _apply_filter(jobs: list[JobMatch], filter: str) -> list[JobMatch]:
    if filter == "new":
        return [j for j in jobs if j.is_new]
    if filter == "strong":
        return [j for j in jobs if j.score >= 85]
    if filter == "remote":
        return [j for j in jobs if "remote" in j.location.lower()]
    return jobs


def _apply_sort(jobs: list[JobMatch], sort: str) -> list[JobMatch]:
    if sort == "newest":
        return sorted(jobs, key=lambda j: j.posted_at)
    if sort == "oldest":
        return sorted(jobs, key=lambda j: j.posted_at, reverse=True)
    return sorted(jobs, key=lambda j: j.score, reverse=True)


@router.get("/feed", response_model=List[JobMatch])
async def get_job_feed(
    status:    Optional[str] = Query(
        None,
        description="Filter by job status: new | saved | ignored | applied. "
                    "Omit to return all non-ignored jobs.",
    ),
    limit:     int   = Query(50, le=200),
    min_score: float = Query(
        0.0,
        ge=0.0, le=100.0,
        description="Only return jobs whose match_score >= this value. "
                    "0 (default) means no minimum — all scores are included. "
                    "Sent by the frontend when the user sets a minimum match threshold "
                    "in Preferences. Does NOT affect Analytics which uses separate endpoints.",
    ),
    user: CurrentUser = Depends(get_current_user),
):
    """
    Return the personalised job feed for the authenticated user.

    Jobs are sorted by ATS match_score DESC then created_at DESC.
    Each item includes is_direct_application=True when source_type=='company_site'.

    IMPORTANT — scope: min_score and any future preference filters only affect
    this feed endpoint.  The /api/analytics/* endpoints always return raw,
    unfiltered aggregate data regardless of user preferences.

    Atomic gate
    -----------
    A job is only "ready" (surfaced as a ranked result) once it has BOTH a
    populated jd_structured JSON AND a finalised, non-proxy composite
    match_score.  Jobs that fail this gate are returned with status='analysing'
    so the frontend renders the "Analysing…" state instead of a premature
    score.  This is derived from data at read-time, so a job is never
    permanently stranded — when a later pass completes it, it surfaces normally.
    The min_score threshold is applied ONLY to ready jobs; pending jobs are
    always returned (they have no real score to threshold yet).
    """
    jobs = job_store.get_feed(user_id=user.user_id, status_filter=status)

    presented: List[JobMatch] = []
    for j in jobs:
        # Zero-Click contract: every job in the feed must be fully processed.
        # Incomplete rows (missing jd_structured, proxy score, or no match_score)
        # are silently dropped — they are pipeline artefacts, not feed content.
        is_complete = (
            bool((getattr(j, "jd_structured", None) or "").strip())
            and getattr(j, "score_is_proxy", True) is False
            and (j.match_score or 0.0) > 0
            and bool((j.company or "").strip())
            and bool((j.title or "").strip())
            # Require a real LLM analysis brief — jobs where the LLM call
            # returned an empty why_ron are held back until the next s2 cycle
            # re-attempts enrichment.  Paired with feed_service._enrich_one
            # which keeps score_is_proxy=True when why_ron is absent.
            and bool((getattr(j, "why_ron", None) or "").strip())
        )
        if not is_complete:
            continue
        # Promote any straggler still tagged 'analysing' in the DB.
        if j.status == "analysing":
            j.status = "new"
        if min_score > 0 and (j.match_score or 0.0) < min_score:
            continue
        # Derive is_direct_application at read-time so the UI renders the
        # green accent bar and ⚡ Direct badge without a separate lookup.
        j.is_direct_application = (j.source_type == "company_site")
        presented.append(j)

    return presented[:limit]


class RefreshResponse(BaseModel):
    status:  str
    scored:  int
    message: str


@router.post("/feed/refresh", response_model=RefreshResponse)
async def refresh_feed_scores(
    background_tasks: BackgroundTasks,
    user: CurrentUser = Depends(get_current_user),
):
    """
    Trigger batch ATS scoring for all unscored 'new' jobs belonging to the
    authenticated user.  Runs as a background task; returns immediately.
    """
    user_id = user.user_id

    async def _run() -> None:
        try:
            count = await feed_service.refresh_user_scores(user_id)
            logger.info("[jobs/feed/refresh] Scored %d jobs for user=%s", count, user_id)
        except Exception as exc:
            logger.exception(
                "[jobs/feed/refresh] refresh_user_scores failed for user=%s: %s",
                user_id, exc,
            )

    background_tasks.add_task(_run)
    return RefreshResponse(
        status="started",
        scored=0,
        message=f"Batch scoring started for user '{user_id}'. "
                "Poll GET /api/jobs/feed to see updated scores.",
    )


@router.post("/feed/refresh-all", response_model=RefreshResponse)
async def force_refresh_all_scores(
    background_tasks: BackgroundTasks,
    user: CurrentUser = Depends(get_current_user),
):
    """
    Force re-score ALL jobs for the authenticated user (including already-scored
    ones) using the current Master Profile.  Use after a Verify Fit session to
    propagate profile corrections to every job in the feed.
    Runs as a background task; returns immediately.
    """
    user_id = user.user_id

    async def _run() -> None:
        try:
            count = await feed_service.force_rescore_all(user_id)
            logger.info("[jobs/feed/refresh-all] Re-scored %d jobs for user=%s", count, user_id)
        except Exception as exc:
            logger.exception(
                "[jobs/feed/refresh-all] force_rescore_all failed for user=%s: %s", user_id, exc
            )

    background_tasks.add_task(_run)
    return RefreshResponse(
        status="started",
        scored=0,
        message=f"Force re-score started for all jobs of user '{user_id}'. "
                "Poll GET /api/jobs/feed to see updated scores.",
    )


class BackfillResponse(BaseModel):
    status:  str
    queued:  int
    message: str


@router.post("/feed/backfill-jd", response_model=BackfillResponse)
async def backfill_jd_text(
    background_tasks: BackgroundTasks,
    min_score: float = Query(50.0, description="Only backfill jobs with score >= this value"),
    user: CurrentUser = Depends(get_current_user),
):
    """
    Fetch full JD text for jobs with score >= min_score that currently have
    empty or very short jd_text.  After fetching, automatically re-scores all
    jobs so proficiency-aware gap tags reflect the new content.

    Returns immediately; work runs in the background.
    Queued count = number of eligible jobs selected (0 = nothing to do).
    """
    from backend.services import jd_backfill_service

    user_id = user.user_id
    # Pre-count so the UI gets a meaningful queued number in the response.
    candidates = job_store.get_jobs_missing_jd_text(user_id, min_score=min_score)
    queued = len(candidates)

    if queued == 0:
        return BackfillResponse(
            status="noop",
            queued=0,
            message=f"No jobs with score >= {min_score} and missing JD text.",
        )

    async def _run() -> None:
        try:
            await jd_backfill_service.backfill_jd_text(user_id, min_score=min_score)
        except Exception as exc:
            logger.exception(
                "[jobs/feed/backfill-jd] backfill failed for user=%s: %s", user_id, exc
            )

    background_tasks.add_task(_run)
    return BackfillResponse(
        status="started",
        queued=queued,
        message=f"Fetching JD text for {queued} job(s) with score >= {min_score}. "
                "Scores will auto-update on completion. Poll GET /api/jobs/feed for results.",
    )


@router.get("/", response_model=List[JobMatch])
async def list_jobs(
    filter: str = Query("all", description="all | new | strong | remote | saved"),
    sort:   str = Query("match", description="match | newest | oldest"),
    limit:  int = Query(50, le=200),
    user:   CurrentUser = Depends(get_current_user),
):
    """
    Return ranked job matches for the authenticated user.

    Returns only the caller's own jobs — never mock or cross-user data.
    When the user has no jobs yet (empty feed) an empty list is returned so
    the frontend can display its empty-state onboarding UI.
    """
    source = job_store.get_feed(user_id=user.user_id, status_filter=None)
    result = _apply_filter(source, filter)
    result = _apply_sort(result, sort)
    return result[:limit]


@router.get("/categories", response_model=list[str])
async def list_categories(user: CurrentUser = Depends(get_current_user)):
    """Return sorted list of unique category tags in the caller's job store."""
    return job_store.get_categories(user.user_id)


# ── Single-job JD fetch ───────────────────────────────────────────────────────

class FetchJdResponse(BaseModel):
    job_id:          str
    jd_text:         Optional[str]
    new_match_score: Optional[float]
    # True when the pipeline set is_proxy=False (i.e. a real score was computed).
    # False when rescore failed or was skipped; frontend should not clear 'analysing'.
    score_is_proxy:  bool = True
    # LLM-structured JSON string; non-null when structuring succeeded in this call.
    jd_structured:   Optional[str] = None


@router.post("/{job_id}/fetch-jd", response_model=FetchJdResponse)
async def fetch_single_jd(
    job_id: str,
    user:   CurrentUser = Depends(get_current_user),
):
    """
    Scrape the full JD for a single job owned by the caller, persist it, and
    rescore against the current Master Profile.  Runs synchronously so the card
    can update in place.

    Returns the scraped text and updated match_score (or null on rescore failure).
    Raises HTTP 404 if the job is not found or has no apply_url.
    Raises HTTP 403 if the job belongs to a different user.
    Raises HTTP 422 if the URL cannot be scraped.
    """
    job = job_store.get_by_id(job_id, user.user_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id!r} not found.")
    if not job.apply_url:
        raise HTTPException(status_code=422, detail="Job has no apply URL to scrape.")

    # ── Scrape ────────────────────────────────────────────────────────────────
    # scrape_jd_text routes to a site-specific parser (Gotfriends, Dialog,
    # Nisha, …) based on the URL domain; unknown hosts fall back to the
    # generic html scraper.
    try:
        jd_text = await asyncio.to_thread(scrape_jd_text, job.apply_url)
        jd_text = jd_text.strip()
    except Exception as exc:
        logger.error("[fetch-jd] Scrape failed for job_id=%s url=%s: %s", job_id, job.apply_url, exc)
        raise HTTPException(
            status_code=422,
            detail="Could not scrape job description. Please try again shortly.",
        )

    job_store.update_jd_text(job_id, jd_text)
    logger.info("[fetch-jd] Saved JD for job %s — %d chars", job_id, len(jd_text))

    # ── Structure JD (best-effort, non-blocking) ─────────────────────────────
    structured_json: Optional[str] = None
    try:
        from backend.services.jd_structure_service import structure_jd, extract_company_from_structured
        structured_json = await structure_jd(jd_text, user_id=user.user_id, job_id=job_id)
        if structured_json:
            job_store.update_jd_structured(job_id, structured_json)
            extracted_company = extract_company_from_structured(structured_json)
            if extracted_company:
                job_store.update_company(job_id, extracted_company)
    except Exception:
        pass  # structuring is non-critical; scrape + rescore must still succeed

    # ── Rescore ───────────────────────────────────────────────────────────────
    new_match_score: Optional[float] = None
    final_is_proxy: bool = True   # stays True unless rescore succeeds below
    try:
        from backend.services.user_profile import get_profile
        from backend.services.master_profile_service import get_skill_proficiencies
        from backend.services.feed_service import (
            _build_profile_cv_proxy,
            _proficiency_reason_tags,
        )
        from backend.services.match_score_service import compute_match_score_async

        cv_proxy      = _build_profile_cv_proxy(get_profile(user.user_id), user_id=user.user_id)
        proficiencies = get_skill_proficiencies(user.user_id)
        result        = await compute_match_score_async(
            cv_proxy, jd_text,
            run_llm_validation=False,
            skill_proficiencies=proficiencies,
            user_id=user.user_id,
        )
        new_match_score = round(float(result.total), 1)
        final_is_proxy  = False
        job_store.update_match_score(job_id, user.user_id, new_match_score, is_proxy=False)
        if result.proficiency_notes:
            tags = _proficiency_reason_tags(result.proficiency_notes)
            if tags:
                job_store.update_reasons(job_id, user.user_id, tags)
        logger.info(
            "[fetch-jd] Rescored job %s → %.1f%s",
            job_id, new_match_score,
            f" notes={result.proficiency_notes}" if result.proficiency_notes else "",
        )
    except Exception as exc:
        logger.warning("[fetch-jd] Rescore failed for job %s: %s", job_id, exc)

    return FetchJdResponse(
        job_id=job_id,
        jd_text=jd_text,
        new_match_score=new_match_score,
        score_is_proxy=final_is_proxy,
        jd_structured=structured_json,
    )


# ── Tailor CV brief endpoint ──────────────────────────────────────────────────

class TailorBriefResponse(BaseModel):
    job_id:              str
    job_title:           str
    company:             str
    generated_at:        str
    positioning_summary: str
    tailored_sections:   list[dict]
    cached:              bool = False


@router.post("/{job_id}/tailor-cv", response_model=TailorBriefResponse)
async def tailor_cv_brief(
    job_id:        str,
    force_refresh: bool = Query(False, description="Bypass cache and re-generate"),
    user:          CurrentUser = Depends(get_current_user),
):
    """
    Generate a focused CV-tailoring brief for a single job:
      • positioning_summary — 2-3 sentence pitch for this role
      • tailored_sections   — top 2-3 roles with rewritten bullets

    Results are cached in the DB; subsequent calls return the cached version
    unless force_refresh=true is passed.

    Raises 404 if the job is not found, 422 if the LLM call fails.
    """
    from backend.services.cv_tailor_service import (
        generate_tailor_brief, get_cached_tailor_brief
    )

    # Fast-path: check cache before importing heavy deps
    if not force_refresh:
        cached = get_cached_tailor_brief(job_id, user.user_id)
        if cached:
            return TailorBriefResponse(**cached, cached=True)

    job = job_store.get_by_id(job_id, user.user_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id!r} not found.")

    try:
        brief = await generate_tailor_brief(job_id, force_refresh=force_refresh, user_id=user.user_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except RuntimeError as exc:
        # RuntimeError here can wrap a raw Anthropic API error message
        # (see cv_tailor_service.py) — log the full detail, don't echo it.
        logger.error("[tailor-cv] Generation failed for job %s: %s", job_id, exc)
        raise HTTPException(
            status_code=422,
            detail="CV tailoring failed. Please try again shortly.",
        )

    return TailorBriefResponse(**brief, cached=False)


# ── CV Copilot — inline bullet editor ────────────────────────────────────────

class TailoredSection(BaseModel):
    role:    str
    company: str
    dates:   str
    bullets: list[str]

class TailorEditRequest(BaseModel):
    sections:    list[TailoredSection]
    instruction: str = Field(..., max_length=10_000)

class TailorEditResponse(BaseModel):
    sections: list[TailoredSection]
    reply:    str


_COPILOT_SYSTEM = """\
You are a concise CV editor. You receive a set of experience bullet points and a single \
editing instruction. You rewrite the bullets to satisfy the instruction, then return the \
updated sections as JSON.

RULES:
  • Apply only what the instruction asks — do not make unrequested changes.
  • Keep every bullet under 220 characters.
  • NEVER invent facts, metrics, or experience not already present in the text.
  • Do not add or remove bullet points unless the instruction explicitly says to.
  • NEVER use the em-dash character ('—') in any text you write. Use standard \
punctuation only (commas, periods, or a plain hyphen '-').
  • Output ONLY a raw JSON object — no markdown fences, no commentary.
  • Schema: {"sections": [...same structure as input...], "reply": "one sentence confirming what you changed"}

AGGRESSIVE DELETION ENFORCEMENT (highest priority):
If the user explicitly asks to remove, delete, or drop a section (e.g. "delete the \
military service section", "remove the Wix experience"), you MUST completely remove \
that section object from the "sections" array in your output. Do NOT leave it empty, \
do NOT summarize it, do NOT merely shorten its bullets. Remove the key and its \
contents entirely from the JSON structure, and confirm the removal in "reply".
"""


@router.post("/{job_id}/tailor-cv/edit", response_model=TailorEditResponse)
async def tailor_cv_edit(job_id: str, body: TailorEditRequest, user: CurrentUser = Depends(get_current_user)):
    """
    CV Copilot: apply a natural-language editing instruction to the tailored sections.

    Uses claude-haiku for fast, cheap text edits.
    Returns updated sections + a one-sentence confirmation message.
    """
    import os, json as _json, re as _re

    from backend.services.llm_client import call_llm, LLMCallError
    from backend.services.llm_validation import harden_system_prompt, sanitize_text

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="ANTHROPIC_API_KEY is not set.")

    sections_json = _json.dumps(
        [s.model_dump() for s in body.sections],
        ensure_ascii=False, indent=2,
    )
    user_msg = (
        f"SECTIONS:\n{sections_json}\n\n"
        f"INSTRUCTION: {sanitize_text(body.instruction)}"
    )

    try:
        result_llm = await call_llm(
            system     = harden_system_prompt(_COPILOT_SYSTEM),
            messages   = [{"role": "user", "content": user_msg}],
            model      = "claude-haiku-4-5",
            max_tokens = 2000,
            purpose    = "jobs_tailor_cv_edit",
            user_id    = user.user_id,
            job_id     = job_id,
        )
    except LLMCallError:
        logger.exception("[jobs] tailor_cv_edit LLM call failed")
        raise HTTPException(status_code=422, detail="AI service error. Please try again shortly.")

    raw = result_llm.text

    # Extract JSON — strip fences if model misbehaves
    text = _re.sub(r"```(?:json)?", "", raw).strip()
    try:
        data = _json.loads(text)
    except _json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            data = _json.loads(text[start : end + 1])
        else:
            logger.error("[tailor-cv/edit] Unparseable response (len=%d)", len(raw))
            raise HTTPException(status_code=422, detail="Model returned unparseable output.")

    updated_sections = [TailoredSection(**s) for s in data.get("sections", [])]
    reply = str(data.get("reply", "Done."))

    logger.info(
        "[tailor-cv/edit] job=%s instruction=%r → %d sections updated",
        job_id, body.instruction[:60], len(updated_sections),
    )
    return TailorEditResponse(sections=updated_sections, reply=reply)


# ── Scrape → RawJobPosting endpoint ──────────────────────────────────────────

class JobUrlRequest(BaseModel):
    url: str = Field(..., max_length=500)


async def _check_liveness(url: str) -> bool:
    """Return False if the URL is definitively gone (404/410); True otherwise."""
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=_HTTP_TIMEOUT) as client:
            resp = await client.head(url)
            if resp.status_code in (404, 410):
                return False
            # Some servers reject HEAD — fall back to a range-GET
            if resp.status_code == 405:
                resp = await client.get(url, headers={"Range": "bytes=0-0"})
                return resp.status_code not in (404, 410)
        return True
    except Exception:
        # Network error / timeout — assume still live rather than falsely closing
        return True


@router.post("/analyze-job", response_model=JobMatch)
async def analyze_job_url(request: JobUrlRequest, user: CurrentUser = Depends(get_current_user)):
    """
    Analyze a job URL against the caller's profile.

    - If the URL is already in the database, return the cached record immediately
      (after a quick liveness check to update is_open).
    - Otherwise: scrape → verify active → run AI analysis → persist as 'manual'.
    """
    url = request.url.strip()

    # ── Step 1: cache hit — return stored record (no LLM call) ───────────────
    cached = job_store.get_by_url(url, user.user_id)
    if cached is not None:
        # Refresh liveness in background; return cached immediately
        is_live = await _check_liveness(url)
        if not is_live and cached.is_open:
            job_store.mark_closed(cached.job_id, user.user_id)
            cached = cached.model_copy(update={"is_open": False})
        logger.info("[analyze-job] Cache hit for %s (job_id=%s)", url, cached.job_id)
        return cached

    # ── Step 2: liveness check before wasting an LLM call ────────────────────
    is_live = await _check_liveness(url)
    if not is_live:
        raise HTTPException(
            status_code=410,
            detail=(
                "This job posting appears to be closed or removed (HTTP 404/410). "
                "Please verify the URL is still active."
            ),
        )

    # ── Step 3: scrape ────────────────────────────────────────────────────────
    try:
        scraped = await asyncio.to_thread(scrape_job_post, url)
    except ValueError as exc:
        logger.warning("Scrape content too thin for %s: %s", url, exc)
        raise HTTPException(status_code=422, detail=f"Scraping Error: {exc}")
    except Exception as exc:
        logger.error("Scrape failed for %s: %s", url, exc)
        raise HTTPException(status_code=502, detail="Failed to scrape URL. Please try again shortly.")

    posting = RawJobPosting(
        id=str(uuid.uuid4()),
        title=scraped.title,
        company=scraped.company,
        source_url=url,
        raw_text=scraped.raw_text,
        scraped_at=datetime.now(timezone.utc).isoformat(),
    )

    # ── Step 4: AI match analysis ─────────────────────────────────────────────
    try:
        agent = MatcherAgent()
        match = await agent.match(posting, user_id=user.user_id)
    except EnvironmentError as exc:
        logger.error("MatcherAgent config error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))
    except ValueError as exc:
        logger.error("MatcherAgent parse error: %s", exc)
        raise HTTPException(status_code=502, detail=f"AI analysis returned invalid data: {exc}")
    except Exception as exc:
        logger.exception("MatcherAgent failed for %s", url)
        raise HTTPException(status_code=502, detail="AI analysis failed. Please try again shortly.")

    # ── Step 5: tag as manual and persist ────────────────────────────────────
    match = match.model_copy(update={"source": "manual", "is_open": True, "user_id": user.user_id})
    job_store.save(match)

    return match


# ── Full workflow trigger ─────────────────────────────────────────────────────

class AnalyzeRequest(BaseModel):
    url: str = Field(..., max_length=500)


class AnalyzeResponse(BaseModel):
    status:  str
    message: str
    job_id:  Optional[str] = None


@router.post("/analyze", response_model=JobMatch)
async def analyze_job(
    request: AnalyzeRequest,
    user:    CurrentUser = Depends(get_current_user),
):
    """
    Scrape, structure, score, and persist a single job URL — fully synchronous.

    Zero-Click contract: this call blocks until the job is either:
      • Fully processed (status='new', jd_structured present, real ATS score) → HTTP 200
      • Definitively failed at any step → HTTP 422 with the reason

    A job is NEVER written to the DB in an intermediate 'analysing' state.
    The feed will only ever see complete records.

    Pipeline:
      1. Cache check  — return immediately if URL already stored for this user.
      2. Scrape       — full JD text via scrape_job_post(). 422 on failure.
      3. Match        — MatcherAgent builds a JobMatch (title, company, apply_url).
      4. JD structure — LLM structures the raw JD into sections. 422 on failure.
      5. ATS score    — compute_match_score_async() produces the composite. 422 on failure.
      6. Persist      — written once, with status='new', score_is_proxy=False.
    """
    url = request.url.strip()
    logger.info("[analyze] Starting — url=%s user=%s", url, user.user_id)

    # ── 1. Cache check ────────────────────────────────────────────────────────
    cached = job_store.get_by_url(url, user.user_id)
    if cached is not None:
        logger.info("[analyze] Cache hit — job_id=%s", cached.job_id)
        return cached   # return the full JobMatch so the frontend can prepend it

    # ── 2. Scrape ─────────────────────────────────────────────────────────────
    # LinkedIn gets the specialized, auth-wall-aware scraper (backend.scrapers.
    # url_router); every other host keeps the existing generic scraper — this
    # is the same routing url_router.scrape_jd_text() already does internally,
    # just called directly here so we also get title/company in one request.
    is_linkedin = "linkedin.com" in url.lower()
    try:
        if is_linkedin:
            scraped = await asyncio.to_thread(scrape_linkedin_job, url)
        else:
            scraped = await asyncio.to_thread(scrape_job_post, url)
    except LinkedInAuthWallError as exc:
        logger.warning("[analyze] PIPELINE_FAILURE step=scrape url=%s error=auth_wall detail=%r", url, exc)
        raise HTTPException(
            status_code=422,
            detail=(
                "LinkedIn login wall blocked the request. This posting requires a signed-in "
                "LinkedIn session we don't have access to — try the company's own careers-page "
                "link instead, or paste the job description text directly."
            ),
        )
    except (LinkedInRedirectError, LinkedInChallengeError) as exc:
        logger.warning("[analyze] PIPELINE_FAILURE step=scrape url=%s error=bot_check detail=%r", url, exc)
        raise HTTPException(
            status_code=422,
            detail="LinkedIn blocked this request as automated traffic. Please try again in a few minutes.",
        )
    except LinkedInRapidApiQuotaError as exc:
        logger.warning("[analyze] PIPELINE_FAILURE step=scrape url=%s error=rapidapi_quota detail=%r", url, exc)
        # 429, not 422 — this is a distinct, retryable condition the frontend
        # can show a specific "quota exceeded" toast for.
        raise HTTPException(status_code=429, detail="Monthly free quota exceeded for LinkedIn job lookups.")
    except LinkedInRapidApiAuthError as exc:
        # Server misconfiguration (missing/invalid RAPIDAPI_KEY) — never 401
        # here, since the frontend treats HTTP 401 as "your session expired"
        # and force-logs the user out. 503 correctly signals "us", not "you".
        logger.error("[analyze] PIPELINE_FAILURE step=scrape url=%s error=rapidapi_auth detail=%r", url, exc)
        raise HTTPException(
            status_code=503,
            detail="LinkedIn lookup is temporarily unavailable (scraping service misconfigured). "
                   "Please try again later.",
        )
    except ValueError as exc:
        logger.error("[analyze] PIPELINE_FAILURE step=scrape url=%s error=%r", url, exc, exc_info=True)
        raise HTTPException(status_code=422, detail=f"Scrape Failed: {exc}")
    except Exception as exc:
        logger.error("[analyze] PIPELINE_FAILURE step=scrape url=%s error=%r", url, exc, exc_info=True)
        raise HTTPException(status_code=422, detail="Scrape Failed. Please try again shortly.")

    jd_text = (scraped.raw_text or "").strip()
    if not jd_text:
        logger.error("[analyze] PIPELINE_FAILURE step=scrape url=%s error=empty_jd_text", url)
        raise HTTPException(status_code=422, detail="Scrape Failed: page returned no job description text.")

    logger.info("[analyze] Scraped — title=%r company=%r chars=%d", scraped.title, scraped.company, len(jd_text))

    posting = RawJobPosting(
        id         = str(uuid.uuid4()),
        title      = scraped.title,
        company    = scraped.company,
        source_url = url,
        raw_text   = jd_text,
        scraped_at = datetime.now(timezone.utc).isoformat(),
    )

    # ── 3. Match (title / company / apply_url extraction) ────────────────────
    try:
        agent = MatcherAgent()
        match = await agent.match(posting, user_id=user.user_id)
    except Exception as exc:
        logger.error("[analyze] PIPELINE_FAILURE step=match url=%s error=%r", url, exc, exc_info=True)
        raise HTTPException(status_code=422, detail="Match Failed. Please try again shortly.")

    if "linkedin.com" in url:
        source_type = "linkedin"
    elif any(b in url for b in ("greenhouse.io", "lever.co", "comeet.com",
                                "workday.com", "taleo.net", "icims.com")):
        source_type = "company_site"
    else:
        source_type = "other"

    # ── 4. JD structuring ─────────────────────────────────────────────────────
    try:
        from backend.services.jd_structure_service import structure_jd, extract_company_from_structured
        structured_json = await structure_jd(jd_text, user_id=user.user_id, job_id=match.job_id)
    except Exception as exc:
        logger.error("[analyze] PIPELINE_FAILURE step=structure url=%s error=%r", url, exc, exc_info=True)
        raise HTTPException(status_code=422, detail="Structure Failed. Please try again shortly.")

    if not structured_json:
        logger.error("[analyze] PIPELINE_FAILURE step=structure url=%s error=empty_output", url)
        raise HTTPException(status_code=422, detail="Structure Failed: LLM returned no structured output.")

    # Overwrite company with LLM-extracted name if the scraper set a platform name
    extracted_company = extract_company_from_structured(structured_json)
    if extracted_company:
        match = match.model_copy(update={"company": extracted_company})

    # ── 5. ATS composite scoring ──────────────────────────────────────────────
    try:
        from backend.services.feed_service import _build_profile_cv_proxy
        from backend.services.match_score_service import compute_match_score_async
        from backend.services.user_profile import get_profile

        cv_proxy = _build_profile_cv_proxy(get_profile(user.user_id), user_id=user.user_id)
        result   = await compute_match_score_async(
            cv_data            = cv_proxy,
            jd_text            = jd_text,
            run_llm_validation = True,
            job_title          = match.title,
            company_name       = match.company or "",
            user_id            = user.user_id,
        )
        final_score = round(float(result.total), 1)
    except Exception as exc:
        logger.error("[analyze] PIPELINE_FAILURE step=score url=%s error=%r", url, exc, exc_info=True)
        raise HTTPException(status_code=422, detail="Score Failed. Please try again shortly.")

    # ── 6. Persist ────────────────────────────────────────────────────────────
    # Apply the same substantive-analysis gate used by the enrichment loop.
    # If the LLM returned junk (empty string, "Core Strengths:", etc.) we
    # save the job with score_is_proxy=True so the auto-enrichment loop picks
    # it up on the next cycle rather than surfacing it with a dead skeleton.
    from backend.services.feed_service import is_substantive_analysis
    analysis_ok  = is_substantive_analysis(result.why_ron)
    why_ron_save = result.why_ron if analysis_ok else None

    if not analysis_ok:
        logger.warning(
            "[analyze] LLM returned non-substantive analysis for %r — "
            "persisting with score_is_proxy=True so enrichment loop retries. "
            "why_ron=%r",
            match.title, (result.why_ron or "")[:80],
        )

    match = match.model_copy(update={
        "source":         "manual",
        "source_type":    source_type,
        "is_open":        True,
        "user_id":        user.user_id,
        "status":         "new",
        "match_score":    final_score,
        "score_is_proxy": not analysis_ok,   # False only when analysis is real
        "jd_structured":  structured_json,
        "why_ron":        why_ron_save,
        "created_at":     datetime.now(timezone.utc).isoformat(),
    })

    job_store.save(match)
    if why_ron_save:
        job_store.update_why_ron(match.job_id, user.user_id, why_ron_save)

    logger.info(
        "[analyze] Complete — job_id=%s title=%r score=%.1f "
        "analysis=%s jd_structured_len=%d user=%s",
        match.job_id, match.title, final_score,
        "✓" if analysis_ok else "∅ (pending enrichment loop)",
        len(match.jd_structured or ""), user.user_id,
    )
    # Safety assertion — catch any future regression where jd_structured is lost
    assert match.jd_structured, (
        f"[analyze] BUG: jd_structured is None/empty for job_id={match.job_id} "
        "after successful structure step — check _to_row and model_copy chain"
    )
    return match


# ── Company-site scraping ─────────────────────────────────────────────────────


class ScrapeConfig(BaseModel):
    company_name: str = Field(..., max_length=200)
    company_url:  str = Field(..., max_length=500)
    adapter:      str = Field(default="comeet", max_length=40)   # "comeet" | future adapters
    user_id:      str = "default"


class ScrapeRequest(BaseModel):
    companies: Optional[List[ScrapeConfig]] = None  # None → run default registry


class ScrapeResponse(BaseModel):
    status:    str
    new_jobs:  int
    message:   str


@router.post("/scrape", response_model=ScrapeResponse)
async def scrape_company_jobs(
    request:          ScrapeRequest,
    background_tasks: BackgroundTasks,
    auto_score:       bool = Query(
        False,
        description="After scraping, immediately run ATS scoring on the new jobs.",
    ),
    user: CurrentUser = Depends(get_current_user),
):
    """
    Trigger the scraper registry for one or more company career pages.

    Pass an explicit 'companies' list, or omit it to run all scrapers that
    have been pre-registered with SCRAPER_MANAGER at startup.

    Runs as a background task and returns immediately.  Poll
    GET /api/jobs/feed to see newly added jobs.
    """
    configs = request.companies

    _uid = user.user_id   # every scraped job belongs to the CALLER — client-supplied
                          # cfg.user_id is deliberately ignored (tenancy invariant).

    async def _run() -> None:
        manager = SCRAPER_MANAGER

        # If the caller supplied a list of configs, build a temporary manager
        # rather than mutating the global registry.
        if configs:
            from backend.scrapers.scraper_manager import ScraperManager
            manager = ScraperManager()
            for cfg in configs:
                cfg_dict = cfg.model_dump()
                cfg_dict["user_id"] = _uid
                scraper = scraper_from_config(cfg_dict)
                if scraper:
                    manager.register(scraper)

        new_count = await manager.run_all(user_id=_uid)
        logger.info("[jobs/scrape] Scrape complete — %d new jobs saved.", new_count)

        if auto_score and new_count > 0:
            try:
                scored = await feed_service.refresh_user_scores(_uid)
                logger.info("[jobs/scrape] Auto-score for user=%s: %d scored", _uid, scored)
            except Exception as exc:
                logger.warning("[jobs/scrape] Auto-score failed for user=%s: %s", _uid, exc)

    background_tasks.add_task(_run)
    return ScrapeResponse(
        status   = "started",
        new_jobs = 0,
        message  = (
            f"Scraping {len(configs)} company/companies."
            if configs
            else "Running all registered scrapers."
        ) + " Poll GET /api/jobs/feed for results.",
    )


# ── Truth-check verification (multi-turn chat) ────────────────────────────────

class VerifyChatEntry(BaseModel):
    role:          str            # "agent" | "user"
    content:       str
    gap_addressed: Optional[str] = None
    raw:           Optional[str] = None   # raw JSON the agent returned (agent turns only)


class VerifyChatRequest(BaseModel):
    history: List[VerifyChatEntry] = []
    cv_data: Optional[dict] = None        # falls back to USER_PROFILE when omitted


class VerifyChatResponse(BaseModel):
    status:               str             # "question" | "verified" | "failed"
    question:             Optional[str]  = None
    gap_addressed:        Optional[str]  = None
    raw:                  Optional[str]  = None
    fit_score_adjustment: Optional[float] = None
    new_fit_score:        Optional[float] = None
    cv_advice:            Optional[str]  = None
    summary:              Optional[str]  = None


@router.post("/{job_id}/verify/chat", response_model=VerifyChatResponse)
async def verify_chat(job_id: str, body: VerifyChatRequest, background_tasks: BackgroundTasks, user: CurrentUser = Depends(get_current_user)):
    """
    Process one turn of the truth-verification conversation.

    The client maintains the full history and sends it on every call.
    The agent either asks the next question or returns a final verdict.
    When a verdict is returned with a negative fit_score_adjustment, the
    job's score is automatically updated in the database.
    """
    job = job_store.get_by_id(job_id, user.user_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")

    cv_data = body.cv_data
    if not cv_data:
        from backend.services.user_profile import build_full_text, get_profile
        _profile = get_profile(user.user_id)
        cv_data = {
            "name":                 _profile.get("personal", {}).get("name", ""),
            "professional_summary": build_full_text(user.user_id)[:600],
            "experience":           _profile.get("experience", []),
            "skills":               _profile.get("skills", []),
        }

    critical_gaps = (
        list(job.detailed_analysis.critical_gaps)
        if job.detailed_analysis and job.detailed_analysis.critical_gaps
        else []
    )

    try:
        from backend.agents.truth_check import TruthCheckAgent
        agent  = TruthCheckAgent()
        result = await agent.chat_turn(
            job_title     = job.title,
            company       = job.company,
            jd_text       = job.jd_text,
            critical_gaps = critical_gaps,
            cv_data       = cv_data,
            history       = [h.model_dump() for h in body.history],
        )
    except EnvironmentError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    except Exception as exc:
        logger.exception("[jobs/verify/chat] Failed for job_id=%s: %s", job_id, exc)
        raise HTTPException(status_code=502, detail="Verification agent error. Please try again shortly.")

    # Persist score adjustment on verdict
    new_fit: Optional[float] = None
    adj = float(result.get("fit_score_adjustment") or 0)
    if result["status"] in ("verified", "failed") and adj < 0:
        current = float(job.score or 0)
        new_fit = round(max(0.0, current + adj), 1)
        job_store.update_scores(job_id, user.user_id, fit_score=new_fit)
        logger.info(
            "[jobs/verify/chat] %s verdict=%s fit %.1f→%.1f (Δ%.1f)",
            job_id, result["status"], current, new_fit, adj,
        )

    # After a verdict, persist any factual corrections to the master profile
    # and re-score the user's feed to reflect updated context.
    if result["status"] in ("verified", "failed"):
        history_snap  = [h.model_dump() for h in body.history]
        verdict_str   = result["status"]
        summary_str   = result.get("summary", "")

        _uid = user.user_id

        async def _persist_and_rescore() -> None:
            try:
                from backend.services.master_profile_service import update_profile_from_interaction
                count = await update_profile_from_interaction(history_snap, verdict_str, summary_str, _uid)
                if count:
                    await feed_service.refresh_user_scores(_uid)
            except Exception as exc:
                logger.warning("[jobs/verify/chat] background profile update failed: %s", exc)

        background_tasks.add_task(_persist_and_rescore)

    return VerifyChatResponse(
        status               = result["status"],
        question             = result.get("question"),
        gap_addressed        = result.get("gap_addressed"),
        raw                  = result.get("raw"),
        fit_score_adjustment = adj if result["status"] != "question" else None,
        new_fit_score        = new_fit,
        cv_advice            = result.get("cv_advice"),
        summary              = result.get("summary"),
    )


# ── Single job lookup ─────────────────────────────────────────────────────────

@router.get("/{job_id}", response_model=JobMatch)
async def get_job(job_id: str, user: CurrentUser = Depends(get_current_user)):
    """Return a single job match by ID — caller's own jobs only."""
    job = job_store.get_by_id(job_id, user.user_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


# ── Single-job analysis poll ──────────────────────────────────────────────────

class JobAnalysisState(BaseModel):
    job_id:               str
    why_ron:              Optional[str]
    score_is_proxy:       bool
    enrichment_failures:  int


@router.get("/{job_id}/analysis", response_model=JobAnalysisState)
async def get_job_analysis(
    job_id: str,
    user: CurrentUser = Depends(get_current_user),
):
    """
    Lightweight polling endpoint for the Agent Analysis box.

    Returns only the fields the frontend needs to decide whether to keep
    showing the skeleton or render the analysis.  Designed for 5-second
    polling while score_is_proxy=True; much cheaper than fetching the full feed.
    """
    job = job_store.get_by_id(job_id, user.user_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobAnalysisState(
        job_id=job.job_id,
        why_ron=job.why_ron,
        score_is_proxy=job.score_is_proxy,
        enrichment_failures=job.enrichment_failures,
    )


# ── Job match feedback (thumbs up / down, JOB-57) ────────────────────────────

class JobFeedbackRequest(BaseModel):
    feedback_type: str                      # "thumbs_up" | "thumbs_down"
    reason:        Optional[str] = None     # optional free-text why


class JobFeedbackResponse(BaseModel):
    job_id:              str
    feedback_type:       str
    preference_learning: dict


@router.post("/{job_id}/feedback", response_model=JobFeedbackResponse)
async def submit_job_feedback(
    job_id: str,
    body:   JobFeedbackRequest,
    user:   CurrentUser = Depends(get_current_user),
):
    """
    Record thumbs-up/down on a job match and run soft-preference learning
    over the user's feedback history (feedback_service). Re-rating the same
    job updates the previous rating (latest opinion wins).
    """
    from backend.services.feedback_service import VALID_FEEDBACK_TYPES, record_feedback

    if body.feedback_type not in VALID_FEEDBACK_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid feedback_type '{body.feedback_type}'. "
                   f"Must be one of: {list(VALID_FEEDBACK_TYPES)}",
        )
    job = job_store.get_by_id(job_id, user.user_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")

    result = record_feedback(
        user.user_id, job_id, body.feedback_type, body.reason, job=job,
    )
    return JobFeedbackResponse(
        job_id              = job_id,
        feedback_type       = body.feedback_type,
        preference_learning = result["preference_learning"],
    )


# ── Job status update ─────────────────────────────────────────────────────────

_VALID_STATUSES = {"new", "saved", "ignored", "applied"}


class StatusUpdateRequest(BaseModel):
    status: str


@router.patch("/{job_id}/status")
async def update_job_status(job_id: str, body: StatusUpdateRequest, user: CurrentUser = Depends(get_current_user)):
    """
    Update the workflow status for a single job.
    Valid values: new | saved | ignored | applied.
    """
    if body.status not in _VALID_STATUSES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid status '{body.status}'. Must be one of: {sorted(_VALID_STATUSES)}",
        )
    found = job_store.update_status(job_id, user.user_id, body.status)
    if not found:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")
    return {"job_id": job_id, "status": body.status}


# ── DB purge utility ──────────────────────────────────────────────────────────

class PurgeResponse(BaseModel):
    total:            int
    deleted:          int
    dry_run_preview:  Optional[int] = None
    dry_run:          bool = False


# ── ATS Keyword Extraction ────────────────────────────────────────────────────

class AtsKeywordsResponse(BaseModel):
    job_title:   str
    company:     str
    jd_keywords: list[str]
    present:     list[str]
    missing:     list[str]


@router.post("/{job_id}/ats-keywords", response_model=AtsKeywordsResponse)
async def get_ats_keywords(job_id: str, user: CurrentUser = Depends(get_current_user)):
    """
    Extract ATS keywords from a job's JD text, classify them as present in the
    candidate's profile or missing (need to be added to LinkedIn).

    Results are cached in the job's `tailored_cv` blob under "ats_keywords".
    Returns 400 if the job has no JD text (fetch the JD first).
    """
    from backend.services.ats_keyword_service import extract_ats_keywords

    try:
        result = await extract_ats_keywords(job_id, user.user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.exception("[ats-keywords] Failed for job_id=%s: %s", job_id, exc)
        raise HTTPException(status_code=500, detail="ATS keyword extraction failed")

    return AtsKeywordsResponse(**result)


# ── Active Skills Gap Analysis (JOB-59) ───────────────────────────────────────

class SkillsGapResponse(BaseModel):
    job_id:   str
    analysis: str   # free-text bullet-style gap analysis from the LLM


@router.post("/{job_id}/skills-gap", response_model=SkillsGapResponse)
async def get_skills_gap(job_id: str, user: CurrentUser = Depends(get_current_user)):
    """
    Compare a job's JD text against the candidate's profile and return a
    concise, actionable list of explicitly missing skills/requirements.

    Stateless — not persisted, mirrors the ATS keyword extraction contract
    but returns free-text LLM analysis rather than structured keyword lists.
    Returns 400 if the job has no JD text (fetch the JD first).
    """
    job = job_store.get_by_id(job_id, user.user_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id!r} not found.")

    jd_text = (job.jd_text or "").strip()
    if not jd_text:
        raise HTTPException(status_code=400, detail="Job has no JD text — fetch the full description first.")

    try:
        from backend.services.skills_gap_service import analyze_skills_gap
        from backend.services.user_profile import build_full_text

        analysis = await analyze_skills_gap(jd_text, build_full_text(user.user_id))
    except Exception as exc:
        logger.exception("[skills-gap] Failed for job_id=%s: %s", job_id, exc)
        raise HTTPException(status_code=500, detail="Skills gap analysis failed")

    return SkillsGapResponse(job_id=job_id, analysis=analysis)


# ── Ariel Mock Interview Simulator (JOB-61) ───────────────────────────────────
#
# Two stateless, job-anchored endpoints over services/interview_simulator.py:
#   POST /{job_id}/interview/question  → one targeted question for this JD
#   POST /{job_id}/interview/answer    → constructive feedback on the answer
# The frontend holds the session (question + answer) locally; nothing is
# persisted. Both are LLM calls → per-route llm_rate_limit budget, and the
# sync service functions run in the threadpool so they never block the loop.

class InterviewQuestionResponse(BaseModel):
    job_id:   str
    question: str


class InterviewAnswerRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2_000)
    answer:   str = Field(..., min_length=1, max_length=8_000)


class InterviewFeedbackResponse(BaseModel):
    job_id:   str
    feedback: str


def _interview_job_context(job_id: str, user_id: str) -> tuple[JobMatch, str]:
    """Shared guardrails: (job, jd_text) or raise the appropriate HTTPException."""
    job = job_store.get_by_id(job_id, user_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id!r} not found.")
    jd_text = (job.jd_text or "").strip()
    if not jd_text:
        raise HTTPException(status_code=400, detail="Job has no JD text — fetch the full description first.")
    return job, jd_text


def _raise_for_service_sentinel(text: str) -> None:
    """interview_simulator returns error strings instead of raising — map them."""
    if text.startswith("API Key missing"):
        raise HTTPException(status_code=503, detail="LLM unavailable — ANTHROPIC_API_KEY is not configured.")
    if text.startswith("Failed to generate") or text.startswith("Failed to evaluate"):
        raise HTTPException(status_code=502, detail="Interview simulator failed. Please try again shortly.")


@router.post(
    "/{job_id}/interview/question",
    response_model=InterviewQuestionResponse,
    dependencies=[Depends(llm_rate_limit)],
)
async def generate_mock_interview_question(
    job_id: str,
    user:   CurrentUser = Depends(get_current_user),
) -> InterviewQuestionResponse:
    """
    Generate ONE targeted mock-interview question for this job, grounded in
    the JD, the candidate's profile, and their known gaps for the role
    (stored negative reason tags + critical gaps — no extra LLM call).
    """
    from backend.services.interview_simulator import generate_interview_question
    from backend.services.user_profile import build_full_text

    job, jd_text = _interview_job_context(job_id, user.user_id)

    # Known gaps from data already on the job — cheap, no second LLM call.
    gap_parts = [r.label for r in job.reasons if r.kind == "neg"]
    gap_parts += job.detailed_analysis.critical_gaps
    skills_gap = "; ".join(dict.fromkeys(p.strip() for p in gap_parts if p.strip())) or "(none identified)"

    try:
        question = await generate_interview_question(
            jd_text, build_full_text(user.user_id), skills_gap,
        )
    except Exception as exc:
        logger.exception("[interview] question generation failed for job_id=%s: %s", job_id, exc)
        raise HTTPException(status_code=502, detail="Interview simulator failed. Please try again shortly.")

    _raise_for_service_sentinel(question)
    return InterviewQuestionResponse(job_id=job_id, question=question)


@router.post(
    "/{job_id}/interview/answer",
    response_model=InterviewFeedbackResponse,
    dependencies=[Depends(llm_rate_limit)],
)
async def evaluate_mock_interview_answer(
    job_id: str,
    body:   InterviewAnswerRequest,
    user:   CurrentUser = Depends(get_current_user),
) -> InterviewFeedbackResponse:
    """Evaluate the candidate's answer to a mock-interview question for this job."""
    from backend.services.interview_simulator import evaluate_interview_answer

    _job, jd_text = _interview_job_context(job_id, user.user_id)

    try:
        feedback = await evaluate_interview_answer(
            body.question, body.answer, jd_text,
        )
    except Exception as exc:
        logger.exception("[interview] answer evaluation failed for job_id=%s: %s", job_id, exc)
        raise HTTPException(status_code=502, detail="Interview simulator failed. Please try again shortly.")

    _raise_for_service_sentinel(feedback)
    return InterviewFeedbackResponse(job_id=job_id, feedback=feedback)


# ── DEV-only: full job state flush ───────────────────────────────────────────

class DevFlushResponse(BaseModel):
    flushed: int
    message: str


@router.post("/dev-flush", response_model=DevFlushResponse)
async def dev_flush_jobs(
    user: CurrentUser = Depends(require_admin),
):
    """
    **DEV_MODE only, admin-only** — wipe all cached JD text and scoring state
    so the pipeline re-fetches and re-scores from a clean slate on the next
    sync.

    For each job owned by the authenticated user:
      • Clears jd_text → "" (makes _is_thin() return True → triggers hydration)
      • Resets match_score → 0.0 and why_ron → None (triggers LLM enrichment)

    Returns immediately with the total number of flushed jobs.
    Raises HTTP 403 in production (DEV_MODE=False) and HTTP 403 for any
    non-admin caller (require_admin), even when DEV_MODE=True.
    """
    from backend.config import DEV_MODE

    if not DEV_MODE:
        raise HTTPException(
            status_code=403,
            detail="This endpoint is only available in development mode.",
        )

    all_jobs = job_store.get_feed(user_id=user.user_id)
    flushed = 0

    for job in all_jobs:
        job_store.reset_job_for_enrichment(job.job_id)
        job_store.update_jd_text(job.job_id, "")
        flushed += 1

    logger.info(
        "[dev-flush] Flushed %d jobs for user=%s — ready for fresh hydration + enrichment",
        flushed, user.user_id,
    )
    return DevFlushResponse(
        flushed=flushed,
        message=(
            f"Flushed {flushed} job(s). "
            "JD text cleared and scores reset. "
            "Trigger POST /api/jobs/feed/refresh to re-hydrate and re-score."
        ),
    )


# ── Purge ─────────────────────────────────────────────────────────────────────

@router.post("/purge", response_model=PurgeResponse)
async def purge_jobs(
    min_score: float = Query(30.0, description="Delete rows with match_score below this value"),
    dry_run:   bool  = Query(True,  description="Preview without deleting (default: True for safety)"),
    user: CurrentUser = Depends(require_admin),
):
    """
    Admin-only. One-time cleanup: remove job rows where match_score < min_score
    OR title does not match TARGET_SEARCH_QUERIES.

    Defaults to dry_run=True so you must explicitly pass ?dry_run=false to
    actually delete rows.  Returns a count of rows examined / deleted.

    This is a bulk-delete utility with no frontend UI wired to it — gated to
    admins (require_admin) rather than every authenticated user.
    """
    from backend.main import purge_irrelevant_jobs

    result = purge_irrelevant_jobs(min_score=min_score, dry_run=dry_run, user_id=user.user_id)
    return PurgeResponse(**result, dry_run=dry_run)
