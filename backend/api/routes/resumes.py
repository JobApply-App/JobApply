from __future__ import annotations

import base64
import json
import logging
import re
import time

from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from pydantic import BaseModel, Field

from backend.repositories import job_repository as job_store, profile_repository
from backend.agents.resume import ResumeAgent
from backend.agents.tailor import TailorAgent, _inject_static_sections
from backend.agents.gatekeeper import RevisionGatekeeper
from backend.agents.copilot import CopilotAgent
from backend.services.pdf_builder import build_pdf, PdfEngineUnavailable, TEMPLATE_REGISTRY
from backend.models.cv import normalize_cv
from backend.services.supplemental_store import save as save_supplemental
from backend.services.user_profile import get_profile, save_personal_field
from backend.services.match_score_service import (
    compute_match_score_async,
    _cv_experience_text,
    _is_experience_backed,
)
from backend.api.deps import CurrentUser, daily_generation_limit, get_current_user, llm_rate_limit, standard_rate_limit
from backend.services.master_profile_service import get_cached_answer, merge_answers
from backend.repositories.job_repository import clear_tailored_cv, get_tailored_cv, save_tailored_cv

logger = logging.getLogger(__name__)


def _pdf_http_error(exc: Exception, *, context: str) -> HTTPException:
    """
    Map a PDF-build failure to the response the client should actually get.

    Two genuinely different failures were previously reported identically as
    502 "Please try again shortly":

      • PdfEngineUnavailable — Chromium isn't installed in this deployment.
        Permanent. Retrying can never succeed, so telling the user to retry
        sends them into an endless loop against a wall. 503 + a message that
        says the feature is unavailable, so they stop and we get a support
        report naming the real problem.

      • anything else — a real transient render failure (timeout, OOM, a
        malformed template). 502 + retry advice, which is honest here.

    Centralised so the several call sites can't drift into telling users
    different stories about the same condition.
    """
    if isinstance(exc, PdfEngineUnavailable):
        logger.error("[%s] PDF engine unavailable — Chromium not installed: %s", context, exc)
        return HTTPException(
            status_code=503,
            detail=(
                "PDF export is currently unavailable on this server. This is a "
                "configuration issue on our side, not something retrying will fix — "
                "your CV content has been saved and can still be edited."
            ),
        )
    logger.exception("[%s] PDF build failed", context)
    return HTTPException(
        status_code=502,
        detail="PDF generation failed. Please try again shortly.",
    )


# Standard budget on every resumes route; the LLM-generation endpoints below
# additionally carry the strict llm_rate_limit.
router = APIRouter(dependencies=[Depends(standard_rate_limit)])

# Accepted MIME types and their human-readable labels
_ALLOWED_FILE_TYPES: dict[str, str] = {
    "image/jpeg":                "JPEG image",
    "image/png":                 "PNG image",
    "image/webp":                "WebP image",
    "image/gif":                 "GIF image",
    "application/pdf":           "PDF document",
    # .docx only — python-docx cannot parse legacy .doc (OLE2 format)
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "Word document (.docx)",
}

# application/msword is the legacy .doc format — reject with a helpful message
_LEGACY_DOC_MIME = "application/msword"

_MAX_FILE_BYTES = 10 * 1024 * 1024   # 10 MB


class MissingDataRequest(BaseModel):
    id: str
    question: str
    context: str


class ResumeGenerateResponse(BaseModel):
    html: str
    missing_data_requests: list[MissingDataRequest]
    job_id: str
    layout_variant: str


@router.post("/generate", response_model=ResumeGenerateResponse, dependencies=[Depends(llm_rate_limit)])
async def generate_resume(
    job_id: str = Form(...),
    supplemental_answers_json: str = Form(default="{}"),
    reference_file: Optional[UploadFile] = File(default=None),
    user: CurrentUser = Depends(get_current_user),
):
    """
    Generate a tailored HTML resume for a job.

    - job_id: ID of a stored JobMatch.
    - supplemental_answers_json: JSON object mapping question ID → user answer.
    - reference_file: optional image (jpg/png/webp), PDF, or Word (.docx) whose
      layout the agent will analyse and mimic.
    """
    # ── Load job ──────────────────────────────────────────────────────────────
    all_jobs = job_store.get_all(user.user_id)
    job      = next((j for j in all_jobs if j.job_id == job_id), None)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")

    # ── Parse supplemental answers ────────────────────────────────────────────
    try:
        supplemental: dict[str, str] = json.loads(supplemental_answers_json)
    except (json.JSONDecodeError, ValueError):
        raise HTTPException(status_code=422, detail="supplemental_answers_json must be valid JSON.")

    # ── Optional reference file ───────────────────────────────────────────────
    ref_bytes: Optional[bytes] = None
    ref_mime:  Optional[str]   = None

    if reference_file and reference_file.filename:
        mime = (reference_file.content_type or "").lower().strip()

        # Reject legacy .doc with a clear message
        if mime == _LEGACY_DOC_MIME or reference_file.filename.lower().endswith(".doc"):
            raise HTTPException(
                status_code=415,
                detail=(
                    "Legacy .doc format is not supported. "
                    "Please save the file as .docx (Word 2007+) or PDF and re-upload."
                ),
            )

        if mime not in _ALLOWED_FILE_TYPES:
            raise HTTPException(
                status_code=415,
                detail=(
                    f"Unsupported file type '{mime}'. "
                    f"Allowed: {', '.join(_ALLOWED_FILE_TYPES.values())}."
                ),
            )

        raw = await reference_file.read()
        if len(raw) > _MAX_FILE_BYTES:
            raise HTTPException(status_code=413, detail="Reference file must be ≤ 10 MB.")

        ref_bytes = raw
        ref_mime  = mime
        logger.info(
            "[resumes] Reference file: %s (%d bytes, %s)",
            reference_file.filename, len(raw), mime,
        )

    # ── Run agent ─────────────────────────────────────────────────────────────
    try:
        agent                          = ResumeAgent()
        html, missing_raw, layout_name = await agent.generate(
            job                  = job,
            user_id              = user.user_id,
            supplemental_answers = supplemental or None,
            reference_bytes      = ref_bytes,
            reference_mime       = ref_mime,
        )
    except Exception as exc:
        logger.exception("[resumes] ResumeAgent failed for job %s", job_id)
        raise HTTPException(status_code=502, detail="Resume generation failed. Please try again shortly.") from exc

    missing = [
        MissingDataRequest(
            id      = item.get("id", f"q{i}"),
            question= item.get("question", ""),
            context = item.get("context", ""),
        )
        for i, item in enumerate(missing_raw)
        if isinstance(item, dict)
    ]

    return ResumeGenerateResponse(
        html                  = html,
        missing_data_requests = missing,
        job_id                = job_id,
        layout_variant        = layout_name,
    )


# ── Tailor + PDF ──────────────────────────────────────────────────────────────

class TailorRequest(BaseModel):
    job_id: str
    # Answers from a previous missing_data round: question_id -> user answer.
    # Pass on retry so the agent can proceed without re-asking.
    supplemental_answers: Optional[dict] = None
    # Set to True to skip any cached CV and force a fresh LLM generation.
    force: bool = False
    # Language to write THIS CV in, overriding the user's stored default.
    # Lets someone reading the site in Hebrew generate one English CV for a
    # specific job without changing their standing preference.
    cv_locale: Optional[str] = None


class TailorResponse(BaseModel):
    # "ok"           — cv_data and pdf_b64 are populated
    # "missing_data" — missing_data_requests is populated; pdf_b64 / cv_data are null
    status:                str
    cv_data:               Optional[dict] = None
    pdf_b64:               Optional[str]  = None
    missing_data_requests: list           = []
    match_score:           Optional[dict] = None   # MatchScoreResult.as_dict()
    preferred_template:    str            = "t2_modern"


def _build_jd_proxy(job) -> str:
    """
    Full JD proxy for the TailorAgent prompt — includes AI analysis fields
    (fit_brief, scoring_rationale, critical_gaps) so the agent understands the
    gap context.  NOT used for match scoring.
    """
    parts = [f"{job.title} at {job.company}"]
    if job.fit_brief:
        parts.append(job.fit_brief)
    if job.scoring_rationale:
        parts.append(job.scoring_rationale)
    if job.detailed_analysis and job.detailed_analysis.critical_gaps:
        parts.append("Required: " + ", ".join(job.detailed_analysis.critical_gaps))
    return " ".join(parts)


# Negative prefixes the AI matcher emits in critical_gaps.
# Stripping them recovers the actual employer requirement.
# e.g. "No experience with Salesforce" → "salesforce"
_GAP_STRIP_PREFIXES = (
    "no experience with ", "no documented experience with ",
    "no experience in ", "no documented experience in ",
    "no background in ", "no formal background in ",
    "no direct experience", "no evidence of ",
    "lacks ", "limited experience with ", "limited experience in ",
    "no documented ", "not demonstrated: ", "gap: ", "missing: ",
    "candidate lacks ", "candidate has no ", "candidate does not ",
    "ron lacks ", "ron has no ", "ron does not ",
)


# Prepositions/articles that can lead the residual after prefix stripping
# e.g. "no direct experience" + " with X" → skip "with" to get "X"
_GAP_LEADING_SKIP = frozenset({
    "with", "in", "of", "for", "by", "on", "at", "a", "an", "the",
    # category meta-words that can lead the residual after modifier stripping
    # e.g. "lacks formal background in fintech" → skip "background" + "in" → "fintech"
    "background", "expertise", "exposure", "familiarity",
})

# First-token hard rejects — phrase is still a negative/meta statement
_GAP_FIRST_TOKEN_REJECTS = frozenset({
    "no", "not", "never", "none", "lacks", "limited", "unclear", "absent",
})

# Mid-phrase negation cut-points — stop before these so we keep only the subject
# e.g. "QBRs not mentioned in profile" → take tokens before "not" → "qbrs"
_GAP_MID_NEGATIONS = frozenset({"not", "without", "never"})


# Single-word adjective modifiers the AI inserts between "No" and the skill.
_GAP_NO_MODIFIERS = frozenset({
    "explicit", "documented", "formal", "direct", "hands-on",
    "specific", "relevant", "prior", "previous", "clear", "strong",
    "dedicated", "significant", "meaningful",
})

# Words that signal the end of the requirement (qualifier clause begins here).
_GAP_STOP_WORDS = frozenset({
    "outside", "beyond", "within", "except", "excluding", "unless",
    "other", "besides",
})

# Before-colon labels that are meta-words, not employer requirements.
# When these appear before the colon, fall through to the prefix-strip path.
_GAP_COLON_LABEL_REJECTS = frozenset({
    "missing", "gap", "note", "warning", "issue", "concern",
    "weakness", "risk", "flag",
})


def _clean_gap_phrase(gap: str) -> str:
    """
    Strip AI meta language from a critical_gaps entry and return the
    underlying employer requirement as 1-3 clean tokens.

    Handles four formats produced by the discovery agent:
      A) "Category label: no direct ..."  → extract label before colon
      B) Standard prefix: "No experience with X", "Lacks X", etc.
      C) "No [adjective] X experience..." → skip "No" + optional modifier
      D) "X not mentioned in profile"     → cut at mid-phrase negation
    """
    s = gap.lower().strip()

    # ── Format A: "Label text: negative statement" ──────────────────────────
    # e.g. "Telecom domain experience: no direct background"
    # The text before the colon IS the employer requirement label — use it.
    # Exception: if the label is itself a meta-word (e.g. "missing:"), fall through.
    colon = s.find(":")
    if colon > 3:
        before = s[:colon].rstrip(".,; ")
        b_tokens = before.split()
        if (b_tokens
                and b_tokens[0] not in _GAP_FIRST_TOKEN_REJECTS
                and b_tokens[0] not in _GAP_COLON_LABEL_REJECTS):
            # Digit-led label (e.g. "5-year threshold") is a quantifier, not a skill
            if b_tokens[0][0].isdigit():
                return ""
            while b_tokens and b_tokens[-1] in {
                "experience", "background", "skill", "skills", "expertise",
            }:
                b_tokens.pop()
            if b_tokens:
                return " ".join(b_tokens[:3])
        # If label is rejected, strip it and continue to process after-colon text
        s = s[colon + 1:].strip()

    # ── Format B: known prefix strip ────────────────────────────────────────
    stripped = False
    for prefix in _GAP_STRIP_PREFIXES:
        if s.startswith(prefix):
            s = s[len(prefix):]
            stripped = True
            break

    if not stripped:
        # ── Format C: "no [modifier] X experience" — no prefix match ────────
        tokens_c = s.split()
        if tokens_c and tokens_c[0] in _GAP_FIRST_TOKEN_REJECTS:
            skip = 1
            if len(tokens_c) > skip and tokens_c[skip] in _GAP_NO_MODIFIERS:
                skip += 1
            s = " ".join(tokens_c[skip:])
    else:
        # After a successful prefix strip, also skip a leading modifier word.
        # e.g. "no documented " + "hands-on Salesforce" → skip "hands-on"
        tokens_after = s.split()
        if tokens_after and tokens_after[0] in _GAP_NO_MODIFIERS:
            s = " ".join(tokens_after[1:])

    s = re.sub(r'\s*\(.*?\)', '', s)   # remove "(not stated)" etc.
    s = s.rstrip('.,;:()')
    tokens = s.split()

    # Skip leading prepositions that survived stripping
    while tokens and tokens[0] in _GAP_LEADING_SKIP:
        tokens.pop(0)

    # Cut at mid-phrase negation (Format D): ["qbrs", "not", ...] → ["qbrs"]
    for i, tok in enumerate(tokens):
        if i > 0 and tok in _GAP_MID_NEGATIONS:
            tokens = tokens[:i]
            break

    # Cut at qualifier clauses: "SaaS platform outside ticketing" → "SaaS platform"
    for i, tok in enumerate(tokens):
        if i > 0 and tok in _GAP_STOP_WORDS:
            tokens = tokens[:i]
            break

    # Cut at linking verbs / conjunctions after position 0.
    # "onboarding experience is X" → cut at "is" → ["onboarding"]
    # "renewal negotiations or expansion" → cut at "or" → ["renewal", "negotiations"]
    _PHRASE_CUT = frozenset({"is", "are", "was", "were", "or", "and"})
    for i, tok in enumerate(tokens):
        if i > 0 and tok in _PHRASE_CUT:
            tokens = tokens[:i]
            break

    # Drop trailing implied/noise words — multiple passes until stable
    # "management" intentionally excluded — it's meaningful in "account management",
    # "contract management", etc. and would corrupt those ATS keywords if stripped.
    _TRAILING_DROP = {"experience", "background", "skills", "skill", "workflows"}
    changed = True
    while changed and tokens:
        if tokens[-1] in _TRAILING_DROP:
            tokens.pop()
        else:
            changed = False

    if not tokens or len(tokens[0]) < 2:
        return ""
    if tokens[0] in _GAP_FIRST_TOKEN_REJECTS:
        return ""
    # Reject if first token is a digit-led quantifier (e.g. "5-year", "10+")
    if tokens[0][0].isdigit():
        return ""
    return " ".join(tokens[:3])


_GAP_CONJ_SPLIT_RE = re.compile(r'\s+(?:or|and)\s+', re.IGNORECASE)


def _extract_gap_terms(gap: str) -> list[str]:
    """
    Extract ALL employer requirement terms from one critical_gaps entry.

    Handles compound gaps joined by 'or'/'and':
      'No experience with account management or valuation'
        → ['account management', 'valuation']
      'No experience with Salesforce or HubSpot CRM'
        → ['salesforce', 'hubspot crm']

    _clean_gap_phrase handles the primary (first) term; this function
    also captures the conjunction-split tails that the single-pass
    cleaner discards.
    """
    primary = _clean_gap_phrase(gap)
    terms: list[str] = [primary] if primary else []

    # Isolate the noun portion by stripping the known AI prefix so we can
    # find the conjunction split point cleanly.
    noun_part = gap.lower().strip()
    for prefix in _GAP_STRIP_PREFIXES:
        if noun_part.startswith(prefix):
            noun_part = noun_part[len(prefix):]
            break

    # Handle Format C residual: leading reject word + optional modifier
    toks = noun_part.split()
    if toks and toks[0] in _GAP_FIRST_TOKEN_REJECTS:
        skip = 1
        if len(toks) > 1 and toks[1] in _GAP_NO_MODIFIERS:
            skip += 1
        noun_part = " ".join(toks[skip:])

    # Split at conjunctions to capture secondary requirement terms.
    # _clean_gap_phrase is safe to call on a bare noun phrase — no prefix
    # will match and no reject-word will fire, so it returns the phrase as-is
    # (modulo trailing-noise removal).
    parts = _GAP_CONJ_SPLIT_RE.split(noun_part)
    for part in parts[1:]:
        part = part.strip()
        if not part:
            continue
        term = _clean_gap_phrase(part)
        if term and term not in terms:
            terms.append(term)

    return terms


def _build_match_proxy(job) -> str:
    """
    Clean JD proxy for match scoring — ONLY employer-facing text.

    Priority 1: job.jd_text (raw scraped employer posting).
      Gives the extractor real employer language to work with.

    Priority 2: Synthetic proxy for legacy jobs (jd_text is None).
      Takes title + category + requirement terms extracted from critical_gaps
      by stripping AI meta prefixes.  Formatted as "Required: X, Y, Z"
      so the Tier 2 keyword extractor in match_score_service handles them.

    NEVER passes fit_brief or scoring_rationale as-is — they contain
    inverted-logic AI assessments ("no experience with...") that corrupt
    keyword extraction.
    """
    if job.jd_text:
        return f"{job.title} at {job.company}\n{job.jd_text}"

    # Legacy job: no raw JD stored — build a synthetic proxy.
    parts = [f"{job.title} at {job.company}"]
    if job.category:
        parts.append(job.category)

    gap_terms: list[str] = []
    seen_terms: set[str] = set()
    if job.detailed_analysis and job.detailed_analysis.critical_gaps:
        for gap in job.detailed_analysis.critical_gaps[:15]:
            for term in _extract_gap_terms(gap):
                if term not in seen_terms:
                    seen_terms.add(term)
                    gap_terms.append(term)

    if gap_terms:
        # "Required: X, Y, Z" is parsed by Tier 2 of _extract_jd_keywords
        parts.append("Required: " + ", ".join(gap_terms))

    proxy = " ".join(parts)
    logger.info(
        "[match_proxy] jd_text=None — synthetic proxy built (%d chars, %d gap terms): %s…",
        len(proxy), len(gap_terms), proxy[:120],
    )
    return proxy


@router.post(
    "/tailor", response_model=TailorResponse,
    dependencies=[Depends(llm_rate_limit), Depends(daily_generation_limit)],
)
async def tailor_resume(req: TailorRequest, user: CurrentUser = Depends(get_current_user)):
    """
    Run TailorAgent for a job.

    Returns one of two shapes depending on whether the agent has enough data:

    • status="ok"           — CV generated; cv_data + pdf_b64 populated.
    • status="missing_data" — Agent needs more info; missing_data_requests
                              contains questions the frontend must present to
                              the user.  Call this endpoint again with
                              supplemental_answers to complete generation.
    """
    # Whole-request wall clock. The client aborts at 180s (ApplierPreview.tsx),
    # and one request can chain JD structuring -> tailoring -> refinement ->
    # scoring, each with its own provider fallback/retries — so the total is
    # what actually matters for timeouts, not any single call's latency.
    _req_t0 = time.perf_counter()

    all_jobs = job_store.get_all(user.user_id)
    job      = next((j for j in all_jobs if j.job_id == req.job_id), None)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job '{req.job_id}' not found.")

    # ── Regenerate from scratch: purge the stale draft up front ───────────────
    # Deliberately BEFORE the LLM runs, not after. Relying on the successful
    # run's save_tailored_cv() to overwrite meant a failed regeneration left
    # the old draft intact and silently served it again on the next open —
    # the exact "loads a previously generated draft instead of fresh content"
    # symptom. Purging here makes a failure surface as "no draft" (which
    # correctly re-runs generation) rather than as stale content.
    if req.force:
        purged = clear_tailored_cv(req.job_id, user.user_id)
        logger.info(
            "[resumes/tailor] force=True for job %s — purged cached draft: %s",
            req.job_id, purged,
        )

    # An explicit cv_locale on the request wins (generating one CV in another
    # language without changing the standing preference); otherwise use the
    # user's stored default. Resolved before the cache lookup because the
    # cache is language-specific — a draft written in the other language is a
    # miss, not a hit.
    cv_locale = req.cv_locale or profile_repository.get_locales(user.user_id)["cv_locale"]

    # ── Return cached CV if available and force=False ─────────────────────────
    if not req.force and not req.supplemental_answers:
        cached = get_tailored_cv(req.job_id, user.user_id, cv_locale=cv_locale)
        if cached and cached.get("cv_data"):
            logger.info(
                "[resumes/tailor] Cache hit for job %s — returning persisted CV", req.job_id
            )
            # Stored CVs may predate the schema unification.
            cached_cv_data = normalize_cv(cached["cv_data"], context="resumes/tailor:cache")
            try:
                cached_pdf = await build_pdf(cached_cv_data, template_id="t2_modern", user_id=user.user_id)
            except Exception as exc:
                logger.warning("[resumes/tailor] PDF rebuild from cache failed: %s", exc)
                cached_pdf = None
            return TailorResponse(
                status             = "ok",
                cv_data            = cached_cv_data,
                pdf_b64            = base64.b64encode(cached_pdf).decode() if cached_pdf else None,
                match_score        = cached.get("match_score"),
                preferred_template = "t2_modern",
            )

    # Persist answers before calling the agent so that even if generation fails
    # the user's answers are recorded and won't be asked again.
    # core_* answers (phone, location) update USER_PROFILE["personal"] directly
    # and are written to personal_overrides.json so they survive restarts.
    # All other answers go to supplemental_answers.json for JD-gap context.
    jd_answers: dict = {}
    if req.supplemental_answers:
        for qid, answer in req.supplemental_answers.items():
            if qid.startswith("core_"):
                # Strip the "core_" prefix to get the profile field name
                field = qid[len("core_"):]
                try:
                    save_personal_field(field, answer)
                    logger.info(
                        "[resumes/tailor] Saved core profile field '%s' for job %s",
                        field, req.job_id,
                    )
                except Exception:
                    logger.exception(
                        "[resumes/tailor] Failed to save core profile field '%s'", field
                    )
            else:
                jd_answers[qid] = answer

        if jd_answers:
            try:
                n = save_supplemental(jd_answers)
                if n:
                    logger.info(
                        "[resumes/tailor] Persisted %d supplemental answer(s) for job %s",
                        n, req.job_id,
                    )
            except Exception:
                logger.exception("[resumes/tailor] Failed to persist supplemental answers")

    auto_filled: dict[str, str] = {}

    try:
        agent  = TailorAgent(user.user_id)
        result = await agent.tailor(
            job, supplemental_answers=jd_answers or None, cv_locale=cv_locale,
        )
    except Exception as exc:
        logger.exception("[resumes/tailor] TailorAgent failed for job %s", req.job_id)
        raise HTTPException(status_code=502, detail="CV tailoring failed. Please try again shortly.") from exc

    # ── Missing data: attempt auto-fill from master profile ───────────────────
    if result["type"] == "missing_data":
        requests = result.get("requests", [])

        for item in requests:
            qid = str(item.get("id", "")).strip()
            if not qid or qid.startswith("core_"):
                continue
            cached = get_cached_answer(qid, user.user_id)
            if cached:
                auto_filled[qid] = cached

        if auto_filled:
            logger.info(
                "[resumes/tailor] Auto-filling %d answer(s) from master profile for job %s",
                len(auto_filled), req.job_id,
            )
            try:
                result = await agent.tailor(
                    job,
                    supplemental_answers={**jd_answers, **auto_filled},
                    cv_locale=cv_locale,
                )
            except Exception as exc:
                logger.exception(
                    "[resumes/tailor] TailorAgent (auto-fill retry) failed for job %s", req.job_id
                )
                raise HTTPException(status_code=502, detail="CV tailoring failed. Please try again shortly.") from exc

        # Still missing data after auto-fill attempt (or no hits): return only
        # the questions that were NOT resolved by the cache.
        if result["type"] == "missing_data":
            answered_ids = set(auto_filled) | set(jd_answers)
            unanswered   = [
                r for r in result.get("requests", [])
                if str(r.get("id", "")) not in answered_ids
            ]
            logger.info(
                "[resumes/tailor] TOTAL %.1fs for job %s (status=missing_data, %d question(s))",
                time.perf_counter() - _req_t0, req.job_id, len(unanswered),
            )
            return TailorResponse(
                status                = "missing_data",
                missing_data_requests = unanswered,
            )

    # ── CV ready: build PDF ───────────────────────────────────────────────────
    cv_data = normalize_cv(result["cv_data"], context="resumes")

    # Persist all JD answers (user-supplied + auto-filled) to the master profile
    # so subsequent generations for any job can benefit from the cache.
    all_answers = {**jd_answers, **auto_filled}
    if all_answers:
        try:
            merge_answers(all_answers, user.user_id)
        except Exception as exc:
            logger.warning("[resumes/tailor] merge_answers failed (non-fatal): %s", exc)

    try:
        pdf_bytes = await build_pdf(cv_data, template_id="t2_modern", user_id=user.user_id)
    except Exception as exc:
        raise _pdf_http_error(exc, context=f"resumes/tailor job={req.job_id}") from exc

    # ── Compute match score against the freshly generated cv_data ────────────
    # cv_data is always the just-produced output from TailorAgent — never cached.
    # jd_proxy is built from raw employer text (job.jd_text) when available,
    # or from a synthetic proxy derived from critical_gaps for legacy jobs.
    match_score_dict: Optional[dict] = None
    score_result = None
    jd_proxy     = _build_match_proxy(job)
    try:
        logger.info(
            "[resumes/tailor] Scoring: job_id=%s has_raw_jd=%s "
            "proxy_len=%d cv_bullets=%d",
            req.job_id,
            bool(job.jd_text),
            len(jd_proxy),
            sum(len(e.get("bullets", [])) for e in cv_data.get("experience", [])),
        )
        score_result = await compute_match_score_async(cv_data, jd_proxy, run_llm_validation=False, user_id=user.user_id)
        match_score_dict = score_result.as_dict()
        logger.info(
            "[resumes/tailor] Score: total=%d  kw=%.0f/40  skills=%.0f/35  seniority=%.0f/25  "
            "matched_kw=%d  missing_kw=%d",
            score_result.total,
            score_result.keyword_overlap,
            score_result.skills_alignment,
            score_result.seniority_alignment,
            len(score_result.matched_keywords),
            len(score_result.missing_keywords),
        )
    except Exception as exc:
        logger.warning("[resumes/tailor] Match score failed (non-fatal): %s", exc)

    # ── Auto-refinement: close gap between discovery score and CV ATS score ───
    # If the CV's ATS score falls more than 8 points below the job's fit score,
    # the TailorAgent likely dropped critical keywords due to length constraints.
    # One targeted refinement pass rewrites the weakest bullets to inject them.
    _GAP_THRESHOLD = 8.0
    if (
        score_result is not None
        and job.score > 0
        and (job.score - score_result.total) > _GAP_THRESHOLD
        and score_result.missing_keywords
    ):
        logger.info(
            "[resumes/tailor] Score gap %.1f (job=%.1f  cv=%d) exceeds threshold %.1f — "
            "triggering refinement pass. Missing: %s",
            job.score - score_result.total,
            job.score,
            score_result.total,
            _GAP_THRESHOLD,
            score_result.missing_keywords[:6],
        )
        try:
            refined_data = await agent.refine(
                cv_data          = cv_data,
                missing_keywords = score_result.missing_keywords,
                jd_context       = jd_proxy,
            )
            refined_score = await compute_match_score_async(
                refined_data, jd_proxy, run_llm_validation=False, user_id=user.user_id
            )
            logger.info(
                "[resumes/tailor] Refinement result: total=%d  (was %d  delta=%+d)",
                refined_score.total,
                score_result.total,
                refined_score.total - score_result.total,
            )
            if refined_score.total >= score_result.total:
                # Adopt refinement — rebuild PDF from the improved cv_data
                cv_data          = refined_data
                score_result     = refined_score
                match_score_dict = refined_score.as_dict()
                try:
                    pdf_bytes = await build_pdf(cv_data, template_id="t2_modern", user_id=user.user_id)
                    logger.info(
                        "[resumes/tailor] Refined PDF rebuilt for job %s", req.job_id
                    )
                except Exception as pdf_exc:
                    logger.warning(
                        "[resumes/tailor] Refined PDF build failed — keeping original PDF: %s",
                        pdf_exc,
                    )
            else:
                logger.info(
                    "[resumes/tailor] Refinement did not improve score — keeping original CV"
                )
        except Exception as exc:
            logger.warning("[resumes/tailor] Refinement pass failed (non-fatal): %s", exc)

    # ── Persist generated CV so future requests are served from cache ─────────
    try:
        save_tailored_cv(req.job_id, user.user_id, cv_data, match_score_dict, cv_locale=cv_locale)
        logger.info(
            "[resumes/tailor] Cached tailored CV for job %s (locale=%s)", req.job_id, cv_locale,
        )
    except Exception as exc:
        logger.warning("[resumes/tailor] Failed to cache CV (non-fatal): %s", exc)

    _elapsed = time.perf_counter() - _req_t0
    logger.info(
        "[resumes/tailor] TOTAL %.1fs for job %s (status=ok) — client aborts at 180s",
        _elapsed, req.job_id,
    )
    if _elapsed > 120:
        logger.warning(
            "[resumes/tailor] SLOW generation: %.1fs for job %s — approaching the "
            "180s client abort. Check preceding llm_client lines for provider "
            "fallbacks/retries.",
            _elapsed, req.job_id,
        )

    # Counts against the daily cap (backend/api/deps.py's
    # daily_generation_limit) ONLY here — this is the one path in this route
    # that actually ran the agent. The cache-hit return above and the
    # missing_data return earlier never reach this line, so neither burns a
    # generation the user didn't get. Best-effort: a logging failure here
    # must not turn a successful generation into a 500 for the user.
    try:
        from backend.repositories import cv_generation_repository
        cv_generation_repository.record(user.user_id, req.job_id)
    except Exception as exc:
        logger.warning("[resumes/tailor] Failed to log generation for daily cap: %s", exc)

    return TailorResponse(
        status             = "ok",
        cv_data            = cv_data,
        pdf_b64            = base64.b64encode(pdf_bytes).decode(),
        match_score        = match_score_dict,
        preferred_template = "t2_modern",
    )


# ── Cached CV retrieval ───────────────────────────────────────────────────────

from fastapi.responses import Response as _FastAPIResponse


@router.get("/cached/{job_id}")
async def get_cached_resume(job_id: str, user: CurrentUser = Depends(get_current_user)):
    """
    Return the cached tailored CV for a job without calling the LLM.
    Returns 204 No Content if no CV has been generated yet.
    """
    cached = get_tailored_cv(job_id, user.user_id)
    if not cached or not cached.get("cv_data"):
        return _FastAPIResponse(status_code=204)

    cv_data = normalize_cv(cached["cv_data"], context="resumes/cached")
    try:
        pdf_bytes = await build_pdf(cv_data, template_id="t2_modern", user_id=user.user_id)
        pdf_b64   = base64.b64encode(pdf_bytes).decode()
    except Exception as exc:
        logger.warning("[resumes/cached] PDF rebuild failed for job %s: %s", job_id, exc)
        pdf_b64 = None

    return TailorResponse(
        status             = "ok",
        cv_data            = cv_data,
        pdf_b64            = pdf_b64,
        match_score        = cached.get("match_score"),
        preferred_template = "t2_modern",
    )


# ── Copilot targeted edit ─────────────────────────────────────────────────────

class CopilotRequest(BaseModel):
    job_id:       str
    cv_data:      dict
    user_prompt:  str = Field(..., max_length=10_000)
    chat_history: Optional[list[dict]] = None


class CopilotResponse(BaseModel):
    status:          str
    message:         Optional[str]  = None   # explanation for warning / rejected
    changes_summary: Optional[str]  = None   # what was added/removed/edited (success only)
    cv_data:         Optional[dict] = None
    pdf_b64:         Optional[str]  = None
    match_score:     Optional[dict] = None
    # RFC 6902 operations describing this edit. The server has ALREADY applied
    # them — cv_data above is authoritative — but the client gets the ops too so
    # the Live Editor can update the touched fields in place instead of
    # re-rendering the document. Empty when nothing changed or the edit was
    # refused. See backend/services/cv_patch_service.py.
    patch:           list[dict]     = []


@router.post("/copilot", response_model=CopilotResponse, dependencies=[Depends(llm_rate_limit)])
async def copilot_edit(req: CopilotRequest, user: CurrentUser = Depends(get_current_user)):
    """
    Apply a targeted, plain-English editing instruction to an existing cv_data.

    The CopilotAgent mutates only the fields the instruction targets,
    then recomputes match score, saves to cache, and returns the rebuilt PDF.
    """
    print(f"=== DEBUG [resumes/copilot] job_id={req.job_id}  prompt_len={len(req.user_prompt)}  cv_keys={list(req.cv_data.keys()) if req.cv_data else None} ===")

    if not req.user_prompt.strip():
        raise HTTPException(status_code=422, detail="user_prompt must not be empty.")
    if not req.cv_data:
        raise HTTPException(status_code=422, detail="cv_data must not be empty.")

    all_jobs = job_store.get_all(user.user_id)
    job      = next((j for j in all_jobs if j.job_id == req.job_id), None)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job '{req.job_id}' not found.")

    try:
        agent  = CopilotAgent()
        result = await agent.edit(
            cv_data        = req.cv_data,
            user_prompt    = req.user_prompt,
            master_profile = get_profile(user.user_id),
            chat_history   = req.chat_history,
            user_id        = user.user_id,
        )
    except Exception as exc:
        logger.exception("[resumes/copilot] CopilotAgent failed for job %s", req.job_id)
        raise HTTPException(status_code=502, detail="Copilot edit failed. Please try again shortly.") from exc

    # ── warning / rejected: skip rebuild, return agent's message immediately ──
    if result["status"] in ("warning", "rejected"):
        logger.info(
            "[resumes/copilot] %s for job %s: %s",
            result["status"], req.job_id, (result.get("message") or "")[:100],
        )
        return CopilotResponse(
            status          = result["status"],
            message         = result.get("message"),
            changes_summary = None,
        )

    # ── success: rebuild PDF, recompute score, save to cache ─────────────────
    cv_data = normalize_cv(result["cv_data"], context="resumes")

    # Re-inject canonical static sections (education, military, skills) from
    # THIS USER's profile after every Copilot edit.  This guarantees these
    # sections are never silently dropped when the LLM merely forgets to
    # include them, and ensures the canonical profile dates/unit/role are
    # always present in that case. respect_deletions=True means an explicit
    # null/[] the CopilotAgent wrote for one of these keys (an intentional
    # user deletion) is honored instead of being overwritten from the Master
    # Profile.
    cv_data = _inject_static_sections(
        cv_data, respect_deletions=True, user_id=user.user_id, jd_text=job.jd_text or ""
    )

    try:
        pdf_bytes = await build_pdf(cv_data, template_id="t2_modern", user_id=user.user_id)
    except Exception as exc:
        raise _pdf_http_error(exc, context=f"resumes/copilot job={req.job_id}") from exc

    match_score_dict: Optional[dict] = None
    score_result = None
    jd_proxy = _build_match_proxy(job)
    try:
        score_result     = await compute_match_score_async(cv_data, jd_proxy, run_llm_validation=False, user_id=user.user_id)
        match_score_dict = score_result.as_dict()
        logger.info(
            "[resumes/copilot] Score after edit: total=%d  kw=%.0f/40  skills=%.0f/35  "
            "exp_count=%d  prompt=%r",
            score_result.total,
            score_result.keyword_overlap,
            score_result.skills_alignment,
            len(cv_data.get("experience", [])),
            req.user_prompt[:60],
        )
    except Exception as exc:
        logger.warning(
            "[resumes/copilot] Match score computation FAILED (score will be null in response): %s",
            exc, exc_info=True,
        )

    # ── Auto-refinement: same logic as /tailor — close the keyword gap ────────
    # When the user restores a large block (e.g. GO-OUT) via Copilot, the
    # reinserted bullets may not be JD-optimised. If the score is still well
    # below the job's fit score, run one TailorAgent.refine() pass to rewrite
    # the weakest bullets and embed missing keywords — then adopt the result
    # only if it improves the score.
    #
    # Destructive-edit guard: if the user intentionally deleted experience
    # entries or significantly shrunk the experience section, refinement must
    # not run — it would hallucinate missing JD keywords into the remaining
    # unrelated bullets to artificially restore the score.
    _orig_exp_count = len(req.cv_data.get("experience", []))
    _new_exp_count  = len(cv_data.get("experience", []))
    _orig_exp_chars = len(_cv_experience_text(req.cv_data))
    _new_exp_chars  = len(_cv_experience_text(cv_data))
    _is_destructive = (
        _new_exp_count < _orig_exp_count
        or (
            _orig_exp_chars > 0
            and (_orig_exp_chars - _new_exp_chars) / _orig_exp_chars > 0.15
        )
    )
    if _is_destructive:
        logger.info(
            "[resumes/copilot] Destructive edit detected (exp entries %d→%d, "
            "exp chars %d→%d) — skipping refinement loop",
            _orig_exp_count, _new_exp_count,
            _orig_exp_chars, _new_exp_chars,
        )

    _GAP_THRESHOLD = 8.0
    if (
        not _is_destructive
        and
        score_result is not None
        and job.score > 0
        and (job.score - score_result.total) > _GAP_THRESHOLD
        and score_result.missing_keywords
    ):
        logger.info(
            "[resumes/copilot] Score gap %.1f (job=%.1f  cv=%d) exceeds threshold %.1f — "
            "triggering refinement pass. Missing: %s",
            job.score - score_result.total,
            job.score,
            score_result.total,
            _GAP_THRESHOLD,
            score_result.missing_keywords[:6],
        )
        try:
            tailor_agent  = TailorAgent(user.user_id)
            refined_data  = await tailor_agent.refine(
                cv_data          = cv_data,
                missing_keywords = score_result.missing_keywords,
                jd_context       = jd_proxy,
            )
            refined_score = await compute_match_score_async(
                refined_data, jd_proxy, run_llm_validation=False, user_id=user.user_id
            )
            logger.info(
                "[resumes/copilot] Refinement result: total=%d  (was %d  delta=%+d)",
                refined_score.total,
                score_result.total,
                refined_score.total - score_result.total,
            )
            if refined_score.total >= score_result.total:
                cv_data          = refined_data
                score_result     = refined_score
                match_score_dict = refined_score.as_dict()
                try:
                    pdf_bytes = await build_pdf(cv_data, template_id="t2_modern", user_id=user.user_id)
                    logger.info(
                        "[resumes/copilot] Refined PDF rebuilt for job %s", req.job_id
                    )
                except Exception as pdf_exc:
                    logger.warning(
                        "[resumes/copilot] Refined PDF build failed — keeping pre-refinement PDF: %s",
                        pdf_exc,
                    )
            else:
                logger.info(
                    "[resumes/copilot] Refinement did not improve score — keeping Copilot output"
                )
        except Exception as exc:
            logger.warning("[resumes/copilot] Refinement pass failed (non-fatal): %s", exc)

    # ── Orphaned skills pruning ───────────────────────────────────────────────
    # After the Copilot edit and any refinement, skills that no longer appear
    # in any experience bullet or role title earn zero ATS credit (zone-based
    # scoring ignores them) and reduce CV credibility.  Strip them now so
    # the rendered PDF and cached cv_data stay internally consistent.
    try:
        exp_text   = _cv_experience_text(cv_data)
        categories = (cv_data.get("skills") or {}).get("categories", [])
        pruned_cats: list[dict] = []
        removed_count = 0
        for cat in categories:
            original_items = cat.get("items") or []
            kept_items     = [
                item for item in original_items
                if _is_experience_backed(item.lower(), exp_text)
            ]
            removed_count += len(original_items) - len(kept_items)
            if kept_items:
                pruned_cats.append({**cat, "items": kept_items})

        if removed_count:
            logger.info(
                "[resumes/copilot] Pruned %d orphaned skill(s) not backed by experience",
                removed_count,
            )
            cv_data = {**cv_data, "skills": {"categories": pruned_cats}}
            # Rebuild PDF so the visual skills sidebar reflects the pruned list
            try:
                pdf_bytes = await build_pdf(cv_data, template_id="t2_modern", user_id=user.user_id)
            except Exception as pdf_exc:
                logger.warning(
                    "[resumes/copilot] PDF rebuild after skills pruning failed: %s", pdf_exc
                )
            # Recompute score — pruned skills were already zero-credit, so the
            # delta should be negligible, but we want the cache to be exact.
            try:
                score_result     = await compute_match_score_async(
                    cv_data, jd_proxy, run_llm_validation=False, user_id=user.user_id
                )
                match_score_dict = score_result.as_dict()
            except Exception as score_exc:
                logger.warning(
                    "[resumes/copilot] Score recomputation after pruning failed: %s", score_exc
                )
    except Exception as exc:
        logger.warning("[resumes/copilot] Skills pruning step failed (non-fatal): %s", exc)

    # ── Draft mode ─────────────────────────────────────────────────────────────
    # Copilot edits are session-scoped by design: they must NOT be written to
    # the persistent cache here. The frontend holds this response's cv_data as
    # a local draft; it only becomes durable if the user explicitly calls
    # POST /save-cv ("Save Changes to Base Profile"). If the modal is closed
    # without saving, the next /cached/{job_id} read returns the last
    # explicitly-persisted state (from /tailor or a prior /save-cv), not this
    # edit — this is what makes Copilot edits temporary/undoable across
    # sessions instead of silently permanent.
    # Recompute the patch here rather than forwarding the agent's ops. Between
    # the agent returning and this point the route re-injects canonical static
    # sections, clamps limits and may run a refine() pass — so the agent's ops
    # describe an intermediate document, not the one being returned. Diffing the
    # request's cv_data against the final cv_data is the only version the client
    # can apply optimistically and still land exactly where the server did.
    from backend.services.cv_patch_service import diff_cv
    final_patch = diff_cv(req.cv_data, cv_data)
    logger.info("[resumes/copilot] job=%s returning %d patch op(s)", req.job_id, len(final_patch))

    return CopilotResponse(
        status          = "success",
        changes_summary = result.get("changes_summary"),
        cv_data         = cv_data,
        pdf_b64         = base64.b64encode(pdf_bytes).decode(),
        match_score     = match_score_dict,
        patch           = final_patch,
    )


# ── Explicit draft save ───────────────────────────────────────────────────────

class SaveCvRequest(BaseModel):
    job_id:      str
    cv_data:     dict
    match_score: Optional[dict] = None
    # Language the edited CV is written in. Sent by the editor so a Hebrew
    # CV is not re-cached as English, which would make the next open treat
    # it as a language mismatch and silently regenerate over the user's
    # manual edits.
    cv_locale:   Optional[str] = None


@router.post("/save-cv")
async def save_cv(req: SaveCvRequest, user: CurrentUser = Depends(get_current_user)):
    """
    Explicitly persist the caller-supplied cv_data (+ match_score) as the
    saved base state for this job — the "Save Changes to Base Profile" action.

    This is the ONLY way Copilot/LiveEditor edits become durable. /tailor
    still auto-persists its own freshly-generated output (that's the base
    profile CV, not a draft edit); /copilot no longer does.
    """
    all_jobs = job_store.get_all(user.user_id)
    job      = next((j for j in all_jobs if j.job_id == req.job_id), None)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job '{req.job_id}' not found.")

    # Fall back to the stored default only when the editor did not say —
    # an older client that predates the field is far likelier to be editing
    # a CV in the user's usual language than in the other one.
    saved_locale = req.cv_locale or profile_repository.get_locales(user.user_id)["cv_locale"]
    save_tailored_cv(req.job_id, user.user_id, req.cv_data, req.match_score, cv_locale=saved_locale)
    logger.info(
        "[resumes/save-cv] Explicitly saved draft CV for job %s (locale=%s)",
        req.job_id, saved_locale,
    )
    return {"status": "ok"}


# ── Gatekeeper revision ───────────────────────────────────────────────────────

class ReviseRequest(BaseModel):
    job_id:        str
    revision_text: str = Field(..., max_length=10_000)
    cv_data:       dict


class ReviseResponse(BaseModel):
    status:  str                # "approved" | "rejected"
    message: str                # rejection reason or empty string
    cv_data: Optional[dict]     # updated cv_data (if approved)
    pdf_b64: Optional[str]      # base64 PDF (if approved)


@router.post("/revise", response_model=ReviseResponse, dependencies=[Depends(llm_rate_limit)])
async def revise_resume(req: ReviseRequest, user: CurrentUser = Depends(get_current_user)):
    """
    Submit a revision request for a tailored CV.

    The RevisionGatekeeper evaluates the request against hard constraints
    (single-page limit, no fabrication, relevance preservation) and either:
      • Applies the revision and returns updated cv_data + PDF (status="approved")
      • Rejects the request with a plain-English explanation  (status="rejected")
    """
    if not req.revision_text.strip():
        raise HTTPException(status_code=422, detail="revision_text must not be empty.")
    if not req.cv_data:
        raise HTTPException(status_code=422, detail="cv_data must not be empty.")

    all_jobs = job_store.get_all(user.user_id)
    job      = next((j for j in all_jobs if j.job_id == req.job_id), None)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job '{req.job_id}' not found.")

    try:
        gk     = RevisionGatekeeper(user.user_id)
        result = await gk.revise(
            revision_text = req.revision_text,
            cv_data       = req.cv_data,
            job           = job,
        )
    except Exception as exc:
        logger.exception("[resumes/revise] Gatekeeper failed for job %s", req.job_id)
        raise HTTPException(status_code=502, detail="Revision failed. Please try again shortly.") from exc

    pdf_b64: Optional[str] = None
    if result.pdf_bytes:
        pdf_b64 = base64.b64encode(result.pdf_bytes).decode()

    return ReviseResponse(
        status  = result.status,
        message = result.message,
        cv_data = result.cv_data,
        pdf_b64 = pdf_b64,
    )


# ── Templates list ────────────────────────────────────────────────────────────

@router.get("/templates")
async def list_templates(user: CurrentUser = Depends(get_current_user)):
    """Return the static list of available CV templates."""
    return {"templates": TEMPLATE_REGISTRY}


# ── Render PDF (Live Editor + template switching) ─────────────────────────────

class RenderPdfRequest(BaseModel):
    cv_data:     dict
    template_id: str = "t2_modern"


@router.post("/render-pdf")
async def render_pdf(req: RenderPdfRequest, user: CurrentUser = Depends(get_current_user)):
    """
    Render cv_data with the chosen template and return a base64 PDF.
    No LLM call — pure rendering only. Used by the Live Editor for
    template switching and final export.
    """
    try:
        pdf_bytes = await build_pdf(req.cv_data, template_id=req.template_id, user_id=user.user_id)
    except Exception as exc:
        raise _pdf_http_error(exc, context=f"resumes/render-pdf template={req.template_id}") from exc

    return {"pdf_b64": base64.b64encode(pdf_bytes).decode()}


def _cv_filename(user_id: str) -> tuple[str, str]:
    """
    Build the download filename, returning (ascii_fallback, utf8_original).

    Content-Disposition is a latin-1 header. An Israeli candidate whose profile
    name is in Hebrew would make a naive f-string raise UnicodeEncodeError at
    response time — the download fails for exactly the users this product is
    built for. RFC 6266/5987 solves it: a plain ASCII `filename=` that every
    client understands, plus a `filename*=UTF-8''…` that modern browsers prefer
    and which preserves the real name.
    """
    from urllib.parse import quote

    try:
        personal = get_profile(user_id).get("personal", {}) or {}
        name = str(personal.get("name") or "").strip()
    except Exception:
        name = ""

    safe = re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_")
    ascii_name = f"{safe}_CV.pdf" if safe else "CV.pdf"

    utf8_source = f"{name} CV.pdf" if name else "CV.pdf"
    return ascii_name, quote(utf8_source, safe="")


@router.post("/export-pdf")
async def export_pdf(req: RenderPdfRequest, user: CurrentUser = Depends(get_current_user)):
    """
    Stream the CV as a raw PDF binary for a one-click browser download.

    Distinct from /render-pdf, which returns base64 and exists because the
    preview embeds the document as a data: URI. Base64 is the wrong transport
    for a download — it inflates the payload ~33%, forces the whole file
    through a JSON string, and leaves the client to reconstruct bytes it never
    needed to decode. This returns the bytes.

    Content-Disposition: attachment is what makes it a download rather than a
    navigation, so no print dialog or viewer tab is involved at any point.
    """
    try:
        pdf_bytes = await build_pdf(req.cv_data, template_id=req.template_id, user_id=user.user_id)
    except Exception as exc:
        raise _pdf_http_error(exc, context=f"resumes/export-pdf template={req.template_id}") from exc

    ascii_name, utf8_name = _cv_filename(user.user_id)
    logger.info("[resumes/export-pdf] streaming %d bytes as %r (template=%s)",
                len(pdf_bytes), ascii_name, req.template_id)

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{utf8_name}",
            "Content-Length": str(len(pdf_bytes)),
            # The document is per-user and regenerated on every edit; a cached
            # copy would hand someone last week's CV after they changed it.
            "Cache-Control": "no-store",
        },
    )


# ── Match Score ───────────────────────────────────────────────────────────────

class MatchScoreRequest(BaseModel):
    job_id:         str
    cv_data:        dict
    llm_validation: bool = False   # False = Phase 1 only (<100ms) for Live Editor


class MatchScoreResponse(BaseModel):
    total:               float
    keyword_overlap:     float
    skills_alignment:    float
    seniority_alignment: float
    matched_keywords:    list[str] = []
    missing_keywords:    list[str] = []
    matched_skills:      list[str] = []
    missing_skills:      list[str] = []
    suggestions:         list[str] = []
    llm_validated:       bool      = False
    
    # JOB-20: Dynamic culture fit scoring dimensions
    culture_delta:       Optional[float] = None
    culture_alignment:   Optional[float] = None
    culture_category:    Optional[str]   = None
    culture_note:        Optional[str]   = None

    # Bullet-level skills-gap mapping (CVParser/LiveEditor integration) —
    # see match_score_service.py's _map_bullet_matches(). Each entry:
    # {experience_index, bullet_index, matched_terms, seniority_aligned}.
    bullet_matches:      list[dict] = []


@router.post("/match-score", response_model=MatchScoreResponse, dependencies=[Depends(llm_rate_limit)])
async def match_score(req: MatchScoreRequest, user: CurrentUser = Depends(get_current_user)):
    """
    Compute a 0-100 ATS match score between cv_data and the stored job.
    Set llm_validation=False for instant re-score from the Live Editor.
    """
    all_jobs = job_store.get_all(user.user_id)
    job      = next((j for j in all_jobs if j.job_id == req.job_id), None)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job '{req.job_id}' not found.")

    jd_proxy = _build_match_proxy(job)

    try:
        result = await compute_match_score_async(
            req.cv_data, jd_proxy, run_llm_validation=req.llm_validation, user_id=user.user_id
        )
    except Exception as exc:
        logger.exception("[resumes/match-score] Scoring failed for job %s", req.job_id)
        raise HTTPException(status_code=502, detail="Match scoring failed. Please try again shortly.") from exc

    return MatchScoreResponse(
        total               = result.total,
        keyword_overlap     = result.keyword_overlap,
        skills_alignment    = result.skills_alignment,
        seniority_alignment = result.seniority_alignment,
        matched_keywords    = result.matched_keywords,
        missing_keywords    = result.missing_keywords,
        matched_skills      = result.matched_skills,
        missing_skills      = result.missing_skills,
        suggestions         = result.suggestions,
        llm_validated       = result.llm_validated,
        culture_delta       = result.culture_delta,
        culture_alignment   = result.culture_alignment,
        culture_category    = result.culture_category,
        culture_note        = result.culture_note,
        bullet_matches      = result.bullet_matches,
    )
