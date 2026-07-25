"""
Feed-level services: batch ATS scoring and profile-to-cv-proxy conversion.

refresh_user_scores(user_id)
─────────────────────────────
Idempotent enrichment pass (s2).  Validates every job's JD integrity before
scoring — if the stored text is thin, it hydrates first.  The trigger
condition is intentionally broad:

    len(jd_text) < _JD_MIN_CHARS   OR   why_ron IS NULL

This means a job that carries a why_ron string from a previous DEV mock but
still holds a thin placeholder JD is treated as un-enriched and re-processed.

hydrate_job(job)
────────────────
Single gateway for all live JD fetching.  Uses unauthenticated requests only —
no cookies, no Playwright, no ScraperAPI.  On failure it writes
_HYDRATE_FAILED_SENTINEL to the jd_text column so the job is permanently
excluded from retry loops without requiring a schema change.
LinkedIn challenge/redirect errors are treated as transient (no penalty).

force_rescore_all(user_id)
───────────────────────────
Re-runs local proxy scoring for every job that is NOT fully enriched.
"Fully enriched" means: why_ron IS NOT NULL  AND  jd_text IS rich.
A job with why_ron set but thin text is NOT considered fully enriched and
is re-scored here (local proxy only — LLM is not called from s4).
"""
from __future__ import annotations

import asyncio
import logging
import random
import re
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse

from backend.schemas.job import JobMatch
from backend.repositories import job_repository as job_store
from backend.services.match_score_service import compute_match_score_async
from backend.config import DEV_MODE

logger = logging.getLogger(__name__)

# ── JD integrity threshold ────────────────────────────────────────────────────
# Text shorter than this is considered a thin scraper placeholder (title +
# company line only) and requires live hydration before LLM scoring.
_JD_MIN_CHARS = 250

# Sentinel written to jd_text when hydration fails irrecoverably (HTTP 403/404,
# content too short after scraping, login wall, etc.).  Prevents infinite retry
# loops by making _is_thin() return False so the job is never re-queued.
# We reuse the existing jd_text column to avoid a schema migration.
_HYDRATE_FAILED_SENTINEL = "__hydrate_failed__"

# ── DEV_MODE JD Overrides ─────────────────────────────────────────────────────
# Hard-coded real JD text for specific jobs so the semantic scorer can be
# tested locally without running heavy scrapers.  These overrides are ONLY
# applied when DEV_MODE is True; they are completely ignored in production.
# Matching is done on company/title strings only — never on job_id.

_DEV_JD_OVERRIDES: dict[str, str] = {
    "go-out-account-manager": """\
Our amazing Ops and Commercial team is growing, and we are looking for a \
rockstar Account Manager to join us in our Tel-Aviv office!
If you are a people person, a natural problem solver, and thrive in a \
fast-paced environment, this is for you.

About GO-OUT
GO-OUT is a live ticketing and event technology platform handling real users, \
real transactions, and high-load event days. The stack spans backend services, \
payments, real-time scanning and seating, mobile apps, admin tools, and the \
infrastructure underneath all of it. The environment is fast-moving, and the \
engineering surface area is broad.

What you'll do:
Own the relationships with our key B2B organizers and producers, ensuring \
they get the absolute best out of our platform.
Onboard new clients and guide them through our systems and product features.
Collaborate closely with our Product, Support, and Tech teams to solve \
challenges from the ground up and streamline operations.
Analyze client performance and identify growth opportunities.

Who you are:
1-2 years of experience in Account Management, Customer Success, or a similar \
B2B operations role (SaaS/Startup experience is a huge plus!).
Exceptional communication and relationship-building skills.
Fast learner, highly organized, and able to juggle multiple tasks like a pro.
Fluent in Hebrew and English.
Thrive in a fast-growing startup: We are growing at a crazy pace, which means \
things move fast! Since we power the events and entertainment world, our \
ecosystem is alive and dynamic. We are looking for a true partner with a high \
sense of ownership who thrives in a dynamic environment and brings the \
flexibility needed to support our clients.
""",
}


# ── Pure helpers ──────────────────────────────────────────────────────────────

# Maximum enrichment attempts before a job is permanently retired.
# Exposed to the frontend via the enrichment_failures field so the UI can
# show a hard-failure state instead of an infinite skeleton.
ENRICHMENT_MAX_FAILURES = 3

# Backoff delays (seconds) between successive enrichment attempts.
# Index = failures already recorded.  Once failures >= len, the job is retired.
_ENRICHMENT_BACKOFF_SECS = [0, 30, 120]


def _is_thin(jd_text: str | None) -> bool:
    """
    Return True when the stored JD text is too thin for reliable LLM scoring.

    The failure sentinel written by hydrate_job() on irrecoverable errors is
    excluded — it looks thin by length but must not trigger re-fetching.
    """
    text = (jd_text or "").strip()
    if text == _HYDRATE_FAILED_SENTINEL:
        return False          # already tried; permanent skip
    return len(text) < _JD_MIN_CHARS


def is_substantive_analysis(text: str | None) -> bool:
    """
    Return True when an LLM-produced why_ron string contains real analysis.

    Shared by feed_service (enrichment pass), discovery (inline enrichment),
    and jobs.analyze (synchronous pipeline) so all three code paths apply the
    same standard.  Exported with a public name so routes can import it.

    Two conditions must both hold:
      1. len >= 50  — rules out bare stubs like "🟢 Core Strengths:" (18 chars)
         or empty strings.
      2. The full string is not a header-only line — catches responses like
         "Key strengths:\n" where the model produced a section title but no
         bullets.  re.match anchors to the start; $ anchors to the end of the
         full string (not just the first line), so a valid multi-line analysis
         that *starts* with "🟢 Core Strengths:" is NOT rejected here.

    Note: a previous third condition checked whether the first line matched
    "core strengths:" — that incorrectly rejected all valid analyses that use
    the mandatory "🟢 Core Strengths:\\n• ..." template format.  It has been
    removed; condition 1 is sufficient to block bare stubs.
    """
    s = (text or "").strip()
    return (
        len(s) >= 50
        and not re.match(r'^[^\w]*[\w\s]+:\s*$', s)
    )


def _is_linkedin_url(url: str | None) -> bool:
    """Return True when the URL points to a linkedin.com host."""
    return bool(url and "linkedin.com" in url.lower())


def _needs_enrichment(job: JobMatch) -> bool:
    """
    Source-of-truth predicate for enrichment eligibility.

    A job needs enrichment if ANY of the following are true:
      • JD text is thin (< _JD_MIN_CHARS, not the failure sentinel)
      • why_ron is None — never received a real LLM evaluation
      • score_is_proxy=True — LLM scoring didn't complete cleanly last time

    LinkedIn jobs are permanently excluded from JD hydration — the
    unauthenticated scraper produces 999/redirect errors on most pages.
    They are still scored via the thin-proxy fallback (title + company).

    A job is permanently retired once enrichment_failures >= ENRICHMENT_MAX_FAILURES.
    """
    if job.enrichment_failures >= ENRICHMENT_MAX_FAILURES:
        return False   # hard stop — show "Manual analysis required" in UI
    if _is_linkedin_url(job.apply_url) and _is_thin(job.jd_text):
        # LinkedIn JD cannot be hydrated — skip enrichment for thin rows.
        # If why_ron or score_is_proxy need fixing, fall through to scoring
        # only when the JD text is already rich enough (i.e. not thin).
        return False
    return _is_thin(job.jd_text) or job.why_ron is None or job.score_is_proxy


def _dev_jd_override(job: JobMatch) -> str | None:
    """
    Return the hardcoded JD text for a DEV override job, or None.

    Matching is done on company and title strings only — never on job_id,
    which can collide across scraper runs or environments.
    GO-OUT detection accepts both "GO-OUT" and "GO_OUT" spellings.
    """
    if not DEV_MODE:
        return None

    company_upper = (getattr(job, "company_name", "") or getattr(job, "company", "")).upper()
    title_upper   = (getattr(job, "job_title",    "") or getattr(job, "title",   "")).upper()

    if "GO-OUT" in company_upper or "GO_OUT" in company_upper or "GO-OUT" in title_upper:
        return _DEV_JD_OVERRIDES["go-out-account-manager"]

    return None


def _build_profile_cv_proxy(profile: dict, user_id: str = "default") -> dict:
    """
    Convert a USER_PROFILE dict into the cv_data structure accepted by
    compute_match_score_async.  Delegates to profile_baseline_service (JOB-18)
    so the matcher input is assembled by the same deep-profiling logic that
    powers the baseline snapshot — including the USER'S OWN chat-derived
    supplemental facts (pass user_id; the old zero-arg build_full_text() call
    always returned the legacy 'default' singleton).
    """
    from backend.services.profile_baseline_service import build_cv_data
    return build_cv_data(profile, user_id=user_id)


def _match_skill_tags(matched_skills: list[str]) -> list[dict]:
    """
    Convert the top matched skills from a MatchScoreResult into positive
    ReasonTag-shaped dicts (kind="skill").  Limits output to 2 tags.
    """
    tags: list[dict] = []
    seen: set[str] = set()
    for skill in matched_skills:
        label = skill.strip().title()
        if not label or len(label) < 2:
            continue
        key = label.lower()
        if key in seen:
            continue
        seen.add(key)
        if len(label) > 22:
            label = label[:22].rstrip()
        tags.append({"kind": "skill", "label": label})
        if len(tags) >= 2:
            break
    return tags


def _proficiency_reason_tags(proficiency_notes: list[str]) -> list[dict]:
    """
    Convert proficiency_notes into ReasonTag-shaped dicts.

    Mapping:
      "Academic vs. Professional req." → kind="neg",   label="Academic <Skill> (Prof. Req.)"
      "Academic (meets familiarity …)"  → kind="skill", label="<Skill> (academic match)"
      "No exp. (required)"              → kind="neg",   label="No <Skill> exp. (required)"
      "No exp. (preferred only)"        → kind="neg",   label="No <Skill> exp. (preferred)"
    """
    tags: list[dict] = []
    for note in proficiency_notes:
        skill, _, desc = note.partition(": ")
        skill_title = skill.strip().title()
        desc_lower  = desc.lower()
        if "academic vs" in desc_lower or "professional req" in desc_lower:
            tags.append({"kind": "neg",   "label": f"Academic {skill_title} (Prof. Req.)"})
        elif "familiarity" in desc_lower or "meets familiarity" in desc_lower:
            tags.append({"kind": "skill", "label": f"{skill_title} (academic match)"})
        elif "no exp" in desc_lower and "required" in desc_lower:
            tags.append({"kind": "neg",   "label": f"No {skill_title} exp. (required)"})
        elif "no exp" in desc_lower and "preferred" in desc_lower:
            tags.append({"kind": "neg",   "label": f"No {skill_title} exp. (preferred)"})
    return tags


# ── JD hydration gateway ──────────────────────────────────────────────────────

async def hydrate_job(job: JobMatch) -> str | None:
    """
    Single gateway for all live JD fetching.

    Scrapes the full employer JD from job.apply_url and persists it via
    job_store.update_jd_text().  Runs the synchronous scraper in a thread
    pool so it does not block the event loop.

    Returns
    -------
    str   — the fetched JD text on success (≥ _JD_MIN_CHARS).
    None  — on any failure (network error, HTTP 4xx, content too short).
            _HYDRATE_FAILED_SENTINEL is written to jd_text so the job is
            permanently excluded from retry loops without a schema change.

    This function is intentionally not gated on _is_thin(): the caller decides
    when hydration is warranted; hydrate_job() only handles the I/O and
    persistence.
    """
    if not job.apply_url:
        logger.debug(
            "[feed_service] hydrate_job: job %s has no apply_url — skipping",
            job.job_id,
        )
        return None

    if _is_linkedin_url(job.apply_url):
        logger.debug(
            "[feed_service] hydrate_job: LinkedIn URL bypassed for job %s (%s @ %s) "
            "— unauthenticated scraper produces 999/redirect errors; "
            "job will use thin-proxy scoring",
            job.job_id, job.title, job.company,
        )
        return None

    logger.info(
        "[feed_service] hydrate_job: fetching JD for job %s (%s @ %s) from %s",
        job.job_id, job.title, job.company, job.apply_url,
    )

    try:
        from backend.scrapers.url_router import (
            scrape_jd_text_async as _scrape,
            LinkedInAuthWallError,
            LinkedInRedirectError,
            LinkedInChallengeError,
        )
        fetched = await _scrape(job.apply_url)
        fetched = fetched.strip()

        if len(fetched) >= _JD_MIN_CHARS:
            job_store.update_jd_text(job.job_id, fetched)
            logger.info(
                "[feed_service] hydrate_job: ✓ saved %d chars for job %s (%s @ %s)",
                len(fetched), job.job_id, job.title, job.company,
            )
            return fetched

        if len(fetched) == 0:
            # Transient: empty body — rate-limit or bot-check on this attempt.
            # Do not burn an enrichment_failures count; retry next cycle.
            logger.warning(
                "[feed_service] hydrate_job: empty body for job %s (%s @ %s) "
                "— transient, skipping without penalty",
                job.job_id, job.title, job.company,
            )
            return None

        logger.warning(
            "[feed_service] hydrate_job: content too short (%d chars) for job %s "
            "(%s @ %s) — marking as failed",
            len(fetched), job.job_id, job.title, job.company,
        )

    except (LinkedInChallengeError, LinkedInRedirectError) as exc:
        # Transient bot-check or redirect loop — no penalty, retry next cycle.
        logger.warning(
            "[feed_service] hydrate_job: LinkedIn transient block for job %s "
            "(%s @ %s) — skipping without penalty. Error: %s",
            job.job_id, job.title, job.company, exc,
        )
        return None

    except LinkedInAuthWallError as exc:
        # The page requires a login — permanently inaccessible via unauthenticated
        # requests.  Mark as failed so the enrichment loop stops retrying it.
        logger.warning(
            "[feed_service] hydrate_job: LinkedIn login wall for job %s (%s @ %s) "
            "— page requires authentication, marking as failed. Error: %s",
            job.job_id, job.title, job.company, exc,
        )

    except Exception as exc:
        logger.warning(
            "[feed_service] hydrate_job: fetch failed for job %s (%s @ %s): %s "
            "— marking as failed to prevent retry loops",
            job.job_id, job.title, job.company, exc,
        )

    # Generic/permanent failure — mark so the enrichment loop stops retrying.
    job_store.update_jd_text(job.job_id, _HYDRATE_FAILED_SENTINEL)
    return None


# ── s2: Validation-based LLM enrichment ──────────────────────────────────────

async def refresh_user_scores(user_id: str) -> int:
    """
    s2 — Idempotent LLM enrichment pass.

    STRATEGY
    ────────
    Three passes per cycle:

    Pass A — Identify candidates
        All jobs where _needs_enrichment() is True:
          • jd_text thin (< 250 chars, not a failure sentinel)  ← catches DEV
            mock rows whose why_ron was set but JD is still a placeholder
          • why_ron IS NULL  ← never received a real LLM evaluation

    Pass B — Hydrate thin jobs
        For each candidate whose jd_text is thin, hydrate_job() fetches the
        real employer JD from apply_url before the LLM sees it.  On failure,
        _HYDRATE_FAILED_SENTINEL is persisted and the job is removed from the
        enrichment batch for this cycle (it will be re-evaluated next cycle
        only if _needs_enrichment still returns True — which it won't for the
        sentinel, preventing an infinite retry loop).

    Pass C — Score with Claude
        compute_match_score_async(run_llm_validation=True) computes the full
        3-component composite (30% local + 50% semantic + 20% management).
        If jd_text is still thin after hydration (sentinel or empty), the
        match_score_service LLM guard fires and only Phase 1 runs — no wasted
        API call.

    CONCURRENCY
    ────────────
    LinkedIn jobs are processed ONE AT A TIME with a 5–12 s random jitter
    between requests to avoid triggering rate-limits.
    Non-LinkedIn jobs run concurrently, gated by asyncio.Semaphore(5) on
    Anthropic API calls only.

    Returns the number of jobs successfully LLM-enriched this cycle.
    """
    from backend.services.user_profile import get_profile  # lazy import avoids circular deps
    from backend.services.master_profile_service import get_skill_proficiencies

    # ── Pass A: Identify candidates ───────────────────────────────────────────
    all_feed = job_store.get_feed(user_id)
    pending  = [j for j in all_feed if _needs_enrichment(j)]
    retired  = [j for j in all_feed if j.enrichment_failures >= ENRICHMENT_MAX_FAILURES]

    if retired:
        logger.warning(
            "[feed_service] s2: %d job(s) permanently retired (enrichment_failures>=%d) "
            "for user=%s — reset enrichment_failures in the DB to retry. "
            "Titles: %s",
            len(retired), ENRICHMENT_MAX_FAILURES, user_id,
            [f"{j.title} @ {j.company}" for j in retired[:5]],
        )

    if not pending:
        logger.info(
            "[feed_service] s2: nothing to enrich for user=%s "
            "(total=%d enriched=%d retired=%d)",
            user_id, len(all_feed),
            len(all_feed) - len(retired) - sum(1 for j in all_feed if _is_thin(j.jd_text) or j.score_is_proxy),
            len(retired),
        )
        return 0

    logger.info(
        "[feed_service] s2: %d/%d jobs need enrichment for user=%s (retired=%d)",
        len(pending), len(all_feed), user_id, len(retired),
    )

    cv_proxy      = _build_profile_cv_proxy(get_profile(user_id), user_id=user_id)
    proficiencies = get_skill_proficiencies(user_id)
    if proficiencies:
        logger.info("[feed_service] s2 proficiency context: %s", list(proficiencies.keys()))

    # Fetch the Confidence Matrix once for this batch instead of once per job.
    # It does not change mid-batch, so re-querying profile_entities /
    # evidence_records inside compute_match_score_async for every pending job
    # was a pure N+1 (JOB-6) — up to len(pending) redundant identical query
    # pairs per enrichment cycle. Falls back to per-job fetching (entity_scores
    # stays None) if the lookup itself fails, matching the previous behavior.
    try:
        from backend.services.confidence_matrix_service import get_entity_breakdown
        from backend.core.database import ENGINE
        entity_scores = list(get_entity_breakdown(user_id, ENGINE))
    except Exception as exc:
        logger.warning(
            "[feed_service] s2: batch entity_breakdown prefetch failed for user=%s "
            "(falling back to per-job fetch): %s", user_id, exc,
        )
        entity_scores = None

    enriched = 0
    sem      = asyncio.Semaphore(5)   # gates concurrent Anthropic calls only

    async def _enrich_one(job: JobMatch) -> None:
        nonlocal enriched
        _why = ""   # always defined so log/except paths can reference it safely

        try:
            logger.info(
                "[feed_service] s2: attempting enrichment for job %s (%s @ %s) "
                "failures=%d score_is_proxy=%s why_ron=%s jd_len=%d",
                job.job_id, job.title, job.company,
                job.enrichment_failures, job.score_is_proxy,
                "null" if job.why_ron is None else f"'{job.why_ron[:40]}…'",
                len(job.jd_text or ""),
            )

            # ── Resolve JD text (Pass B for thin rows / sentinel reset) ──────
            # DEV override has absolute priority — inject hardcoded JD if matched.
            override_jd = _dev_jd_override(job)
            if override_jd is not None:
                jd_text = override_jd.strip()
                logger.info(
                    "[feed_service] s2: DEV override applied for job %s (%s @ %s)",
                    job.job_id, job.title, job.company,
                )
            elif (job.jd_text or "").strip() == _HYDRATE_FAILED_SENTINEL:
                # Previous hydration wrote the failure sentinel — try again now.
                # The sentinel is not "thin" so _is_thin() skips it, but we
                # must not silently score the sentinel string as the JD.
                # Re-attempt hydration; if it still fails, skip without burning
                # an enrichment_failures count (credentials may just be stale).
                logger.info(
                    "[feed_service] s2: re-attempting hydration for job %s (%s @ %s) "
                    "— previous attempt wrote FAILED sentinel",
                    job.job_id, job.title, job.company,
                )
                hydrated = await hydrate_job(job)
                if hydrated is not None:
                    jd_text = hydrated
                else:
                    logger.warning(
                        "[feed_service] s2: hydration still failing for job %s (%s @ %s) "
                        "— page may be behind a login wall or have been removed. "
                        "Skipping without incrementing enrichment_failures.",
                        job.job_id, job.title, job.company,
                    )
                    return   # don't increment failures — this is a credentials problem
            elif _is_thin(job.jd_text):
                # Pass B — hydrate before scoring
                hydrated = await hydrate_job(job)
                if hydrated is not None:
                    jd_text = hydrated
                else:
                    # Hydration failed — fall back to synthetic title+company proxy.
                    # The match_score_service LLM guard will block the API call for
                    # this thin text; only local Phase 1 scoring will run.
                    jd_text = " ".join(p for p in [job.title, job.company] if p)
                    logger.info(
                        "[feed_service] s2: hydration failed for job %s — "
                        "scoring with thin proxy fallback",
                        job.job_id,
                    )
            else:
                # Rich text already in DB — score directly.
                jd_text = (job.jd_text or "").strip()

            if not jd_text:
                logger.debug("[feed_service] s2: skipping job %s — no usable JD text", job.job_id)
                return

            # ── Pass C: LLM scoring (gated by semaphore) ──────────────────────
            async with sem:
                local_stored = job.match_score if job.match_score > 0.0 else None

                result = await compute_match_score_async(
                    cv_data             = cv_proxy,
                    jd_text             = jd_text,
                    run_llm_validation  = True,
                    skill_proficiencies = proficiencies,
                    user_id             = user_id,
                    job_title           = job.title,
                    company_name        = job.company or "",
                    entity_scores       = entity_scores,
                    job_id              = job.job_id,   # enables high-match trigger (JOB-43)
                )

                # Re-use the s1 local proxy score when available to avoid
                # score fluctuation from re-computing on the same (possibly
                # thin) jd_text. MUST go through finalize_composite so the
                # ATS blend and knockout cap are never dropped by this
                # rebuild (inlining 0.30/0.50/0.20 here previously bypassed
                # the unified pipeline).
                if local_stored is not None and result.local_score == 0.0:
                    from backend.services.match_score_service import finalize_composite
                    composite = finalize_composite(
                        local_stored,
                        result.semantic_score,
                        result.management_score,
                        ats_base        = result.ats_score,
                        knockout_failed = result.knockout_failed,
                        culture_delta   = result.culture_delta,   # JOB-20: never drop the culture term on rebuild
                    )
                    result = type(result)(
                        **{**result.__dict__,
                           "total":       composite,
                           "local_score": local_stored}
                    )

                # Only mark score_is_proxy=False when the LLM actually produced
                # analysis text.  If why_ron is empty (LLM fallback or timeout),
                # keep is_proxy=True so the feed gate holds the job back and the
                # enrichment pass re-attempts it on the next s2 cycle.
                _why         = (result.why_ron or "").strip()
                has_analysis = is_substantive_analysis(_why)

                skill_tags = _match_skill_tags(result.matched_skills)
                prof_tags  = _proficiency_reason_tags(result.proficiency_notes)

                # Single SELECT + UPDATE for this job's whole enrichment outcome
                # instead of 3 separate round trips (JOB-6 write N+1 fix).
                fail_count = job_store.update_enrichment_result(
                    job.job_id, user_id,
                    score             = float(result.total),
                    is_proxy          = not has_analysis,
                    reasons           = skill_tags + prof_tags,
                    why_ron           = result.why_ron if has_analysis else None,
                    culture_delta     = result.culture_delta,
                    culture_alignment = result.culture_alignment,
                    culture_category  = result.culture_category,
                    culture_note      = result.culture_note,
                    increment_failure = not has_analysis,
                )

                if not has_analysis:
                    logger.warning(
                        "[feed_service] s2: job %s (%s @ %s) scored but LLM returned "
                        "non-substantive analysis (why_ron=%r, len=%d) — "
                        "keeping score_is_proxy=True, enrichment_failures now %d",
                        job.job_id, job.title, job.company,
                        _why[:80], len(_why), fail_count,
                    )

                enriched += 1
                logger.info(
                    "[feed_service] s2: enriched job %s (%s @ %s) → %.1f "
                    "[local=%.0f sem=%.0f mgmt=%.0f why_ron=%s]%s",
                    job.job_id, job.title, job.company, result.total,
                    result.local_score, result.semantic_score, result.management_score,
                    "✓" if has_analysis else "∅",
                    f"  profs={result.proficiency_notes}" if result.proficiency_notes else "",
                )

        except Exception as exc:
            fail_count = job_store.increment_enrichment_failures(job.job_id)
            # logger.exception prints the full stack trace — critical audit trail
            # for diagnosing timeout / JSON parse / API-key-rejection failures.
            logger.exception(
                "[feed_service] s2: ENRICHMENT_FAILURE job=%s (%s @ %s) "
                "failure_count=%d/%d  error_type=%s  error=%s",
                job.job_id, job.title, job.company,
                fail_count, ENRICHMENT_MAX_FAILURES,
                type(exc).__name__, exc,
            )

    # ── Dispatch: LinkedIn sequentially with jitter; others concurrently ─────
    def _is_linkedin_job(job: JobMatch) -> bool:
        """True when the job's apply_url points to a linkedin.com host."""
        if not job.apply_url:
            return False
        try:
            host = urlparse(job.apply_url).hostname or ""
            return host == "linkedin.com" or host.endswith(".linkedin.com")
        except Exception:
            return False

    linkedin_jobs = [j for j in pending if _is_linkedin_job(j)]
    other_jobs    = [j for j in pending if not _is_linkedin_job(j)]

    logger.info(
        "[feed_service] s2: dispatch — %d LinkedIn (sequential+jitter) "
        "+ %d other (concurrent) for user=%s",
        len(linkedin_jobs), len(other_jobs), user_id,
    )

    # Non-LinkedIn: run concurrently (semaphore gates Anthropic calls).
    if other_jobs:
        await asyncio.gather(*(_enrich_one(j) for j in other_jobs))

    # LinkedIn: strictly sequential with a 5–12 s jitter to stay under rate limits.
    for idx, job in enumerate(linkedin_jobs):
        if idx > 0:
            jitter = random.uniform(5.0, 12.0)
            logger.debug(
                "[feed_service] s2: LinkedIn jitter %.1fs before job %s (%s @ %s)",
                jitter, job.job_id, job.title, job.company,
            )
            await asyncio.sleep(jitter)
        await _enrich_one(job)

    logger.info(
        "[feed_service] s2 complete — user=%s enriched=%d/%d candidates",
        user_id, enriched, len(pending),
    )
    return enriched


# ── s4: Local proxy rescore ───────────────────────────────────────────────────

async def force_rescore_all(user_id: str) -> int:
    """
    Re-compute and persist the local proxy ATS score for all jobs that are NOT
    fully enriched.

    "Fully enriched" = why_ron IS NOT NULL  AND  jd_text is rich (≥ _JD_MIN_CHARS).
    Both conditions must hold.  A job with why_ron set but thin text (e.g. a
    DEV mock row) is NOT considered fully enriched and IS re-scored here.

    This function uses run_llm_validation=False (pure Python, no API calls) so
    it is fast and safe to call as a final pipeline step after s3 JD backfill.

    Returns the number of jobs successfully re-scored.
    """
    from backend.services.user_profile import get_profile
    from backend.services.master_profile_service import get_skill_proficiencies

    all_jobs = job_store.get_feed(user_id)
    if not all_jobs:
        logger.info("[feed_service] s4: no jobs for user_id=%s", user_id)
        return 0

    cv_proxy      = _build_profile_cv_proxy(get_profile(user_id), user_id=user_id)
    proficiencies = get_skill_proficiencies(user_id)
    if proficiencies:
        logger.info("[feed_service] s4 proficiency context: %s", proficiencies)
    scored = 0

    for job in all_jobs:
        jd_stored = (job.jd_text or "").strip()

        # Skip jobs that are genuinely fully enriched — both the LLM brief AND
        # rich JD text are present.  Overwriting would silently downgrade the
        # composite score to a local-only estimate.
        if job.why_ron is not None and not _is_thin(jd_stored):
            logger.debug(
                "[feed_service] s4: skipping fully enriched job %s (%s)",
                job.job_id, job.title,
            )
            continue

        # Never rescore sentinel rows — hydration failed permanently.
        if jd_stored == _HYDRATE_FAILED_SENTINEL:
            logger.debug(
                "[feed_service] s4: skipping hydration-failed job %s (%s)",
                job.job_id, job.title,
            )
            continue

        # Use real JD if available; fall back to synthetic title+company proxy.
        jd_text = jd_stored if not _is_thin(jd_stored) else " ".join(
            p for p in [job.title, job.company] if p
        )
        if not jd_text:
            continue

        try:
            result = await compute_match_score_async(
                cv_proxy, jd_text,
                run_llm_validation  = False,
                skill_proficiencies = proficiencies,
                user_id             = user_id,
            )
            job_store.update_match_score(job.job_id, user_id, float(result.total), is_proxy=False)
            skill_tags = _match_skill_tags(result.matched_skills)
            prof_tags  = _proficiency_reason_tags(result.proficiency_notes)
            job_store.update_reasons(job.job_id, user_id, skill_tags + prof_tags)
            scored += 1
            logger.info(
                "[feed_service] s4: scored job %s (%.1f)%s",
                job.job_id, result.total,
                f" notes={result.proficiency_notes}" if result.proficiency_notes else "",
            )
        except Exception as exc:
            logger.warning(
                "[feed_service] s4: failed for job %s: %s", job.job_id, exc
            )

    logger.info(
        "[feed_service] s4 complete — user=%s scored=%d/%d",
        user_id, scored, len(all_jobs),
    )
    return scored
