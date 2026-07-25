"""
DiscoveryPipeline — automated job discovery using Google Dorking + MatcherAgent.

Primary source: GoogleDorkScraper queries Google for jobs on ATS platforms
(Greenhouse, Lever, Comeet, Workday, Ashby, Workable, Israeli boards).
This completely bypasses LinkedIn authentication and bot-detection — Google
indexes the public ATS pages; we fetch those directly with plain requests.

LinkedIn URLs discovered via Google are treated as thin proxies (no cookie,
no Playwright) — if the public page has a JSON-LD block the scraper extracts
it; if not, the is_valid_job_content gatekeeper marks it failed cleanly.

Interval and credit behaviour are controlled by backend/config.py:
  DISCOVERY_INTERVAL_SECONDS  — how often this cycle runs (set in main.py loop)
  CREDIT_CONSERVATION_MODE    — when True, JD hydration is skipped during
                                 auto-discovery; full descriptions are fetched
                                 only on explicit user action or backfill run.
  TARGET_SEARCH_QUERIES       — job-title search terms forwarded to the dork scraper.
  MAX_RELEVANT_JOBS           — hard cap on new jobs saved per cycle.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone

from backend.agents.matcher import MatcherAgent
from backend.config import (
    CREDIT_CONSERVATION_MODE,
    TARGET_SEARCH_QUERIES,
    MAX_RELEVANT_JOBS,
)
from backend.scrapers.base_scraper import make_tenant_job_id
from backend.scrapers.relevancy import is_title_relevant
from backend.repositories import job_repository as job_store
import backend.services.agent_store as agent_store
from backend.schemas.job import JobMatch, RawJobPosting

# Minimum JD characters required before we attempt structuring + scoring.
# Below this the text is just the title+company header line — not a real JD.
_MIN_JD_FOR_ENRICHMENT = 300

logger = logging.getLogger(__name__)


async def _enrich_job(match: JobMatch, user_id: str) -> None:
    """
    Run JD structuring + LLM composite scoring for a freshly saved discovery job.

    Called immediately after job_store.save() inside run_discovery_cycle().
    On success, flips status 'analysing' → 'new' so the job surfaces in the feed.

    When CREDIT_CONSERVATION_MODE is True the description is empty (just the
    title/company/location header), so there is no usable JD text to structure
    or score.  In that case we log the deferral and return; the job stays
    'analysing' until the user triggers a JD backfill.
    """
    jd_text = (match.jd_text or "").strip()

    if len(jd_text) < _MIN_JD_FOR_ENRICHMENT:
        logger.info(
            "[discovery] enrich DEFERRED — job_id=%s JD too thin (%d chars); "
            "will be enriched after JD backfill (CREDIT_CONSERVATION_MODE=%s)",
            match.job_id, len(jd_text), CREDIT_CONSERVATION_MODE,
        )
        return

    structured_ok = False
    scored_ok     = False

    # ── JD structuring ─────────────────────────────────────────────────────────
    try:
        from backend.services.jd_structure_service import structure_jd, extract_company_from_structured
        structured = await structure_jd(jd_text, user_id=user_id, job_id=match.job_id)
        if structured:
            job_store.update_jd_structured(match.job_id, structured)
            structured_ok = True
            logger.info("[discovery] enrich: JD structured — job_id=%s", match.job_id)
            extracted_company = extract_company_from_structured(structured)
            if extracted_company:
                job_store.update_company(match.job_id, extracted_company)
                logger.info(
                    "[discovery] enrich: company overwritten → '%s' (was '%s') — job_id=%s",
                    extracted_company, match.company, match.job_id,
                )
        else:
            logger.warning(
                "[discovery] enrich: JD structuring returned None — job_id=%s", match.job_id
            )
    except Exception as exc:
        logger.exception(
            "[discovery] ENRICHMENT_FAILURE step=jd_structure job_id=%s "
            "error_type=%s error=%s",
            match.job_id, type(exc).__name__, exc,
        )

    # ── LLM composite scoring ──────────────────────────────────────────────────
    try:
        from backend.services.feed_service import (
            _build_profile_cv_proxy,
            is_substantive_analysis,
        )
        from backend.services.match_score_service import compute_match_score_async
        from backend.services.user_profile import get_profile

        cv_proxy = _build_profile_cv_proxy(get_profile(user_id), user_id=user_id)
        result   = await compute_match_score_async(
            cv_data            = cv_proxy,
            jd_text            = jd_text,
            run_llm_validation = True,
            job_title          = match.title,
            company_name       = match.company or "",
            user_id            = user_id,
        )

        analysis_ok = is_substantive_analysis(result.why_ron)
        # Only mark as fully scored when analysis is real.  A junk why_ron
        # keeps is_proxy=True so the enrichment loop re-attempts it.
        job_store.update_match_score(
            match.job_id, user_id, float(result.total), is_proxy=not analysis_ok
        )

        if analysis_ok:
            job_store.update_why_ron(match.job_id, user_id, result.why_ron)
            scored_ok = True
        else:
            job_store.increment_enrichment_failures(match.job_id)
            logger.warning(
                "[discovery] ENRICHMENT_FAILURE step=analysis job_id=%s "
                "LLM returned non-substantive why_ron=%r — "
                "keeping score_is_proxy=True for enrichment loop retry",
                match.job_id, (result.why_ron or "")[:80],
            )

        # Populate reason tags so the feed card header shows gap badges.
        if result.proficiency_notes:
            try:
                from backend.services.feed_service import _proficiency_reason_tags
                tags = _proficiency_reason_tags(result.proficiency_notes)
                if tags:
                    job_store.update_reasons(match.job_id, user_id, tags)
            except Exception as tag_exc:
                logger.debug(
                    "[discovery] enrich: reason tags failed (non-critical) — job_id=%s: %s",
                    match.job_id, tag_exc,
                )

        logger.info(
            "[discovery] enrich: composite=%.1f analysis=%s — job_id=%s",
            result.total, "✓" if analysis_ok else "∅", match.job_id,
        )
    except Exception as exc:
        job_store.increment_enrichment_failures(match.job_id)
        logger.exception(
            "[discovery] ENRICHMENT_FAILURE step=scoring job_id=%s "
            "error_type=%s error=%s",
            match.job_id, type(exc).__name__, exc,
        )

    # ── Finalise: flip 'analysing' → 'new' only when both steps succeeded ──────
    if structured_ok and scored_ok:
        job_store.update_status(match.job_id, user_id, "new")
        logger.info(
            "[discovery] enrich COMPLETE — job_id=%s '%s' @ '%s' status='new'",
            match.job_id, match.title, match.company,
        )
    else:
        logger.info(
            "[discovery] enrich INCOMPLETE — job_id=%s stays 'analysing' "
            "(structured=%s scored=%s) — enrichment loop will retry",
            match.job_id, structured_ok, scored_ok,
        )


def _category_for_query(query: str) -> str:
    """Map a search query to its feed category."""
    cs_signals = {
        "customer success", "csm", "account manager", "key account",
        "partnership manager", "הצלחת לקוחות", "תיקי לקוחות",
    }
    lower = query.lower()
    return "Customer Success" if any(sig in lower for sig in cs_signals) else "Product"


async def run_discovery_cycle(user_id: str = "default") -> None:
    """
    Run one full discovery cycle: Google Dork → filter → analyse → save.

    Source: GoogleDorkScraper queries Google for jobs posted directly on ATS
    platforms (Greenhouse, Lever, Comeet, Workday, Israeli boards).
    No LinkedIn authentication, no Playwright, no paid proxy.

    Parameters
    ----------
    user_id : str
        Owner UUID assigned to every newly saved job.
    """
    from backend.scrapers.google_dork_scraper import GoogleDorkScraper

    logger.info(
        "━━━ Discovery cycle starting — GoogleDork strategy, cap=%d, user=%r ━━━",
        MAX_RELEVANT_JOBS, user_id,
    )

    agent_store.ensure_user_seeded(user_id)
    agent_store.set_active("s1", f"Google Dorking ATS boards · {len(TARGET_SEARCH_QUERIES)} queries")

    scraper    = GoogleDorkScraper(keywords=TARGET_SEARCH_QUERIES, user_id=user_id)
    agent      = MatcherAgent()
    discovered = 0
    skipped    = 0
    saved      = 0

    try:
        # GoogleDorkScraper.fetch_jobs() runs all queries in a thread pool and
        # returns a de-duplicated list of JobMatch objects with thin JD proxies
        # (Google snippet text).  No LinkedIn auth or Playwright involved.
        dork_jobs: list[JobMatch] = await scraper.fetch_jobs()

        logger.info(
            "[discovery] Google Dork returned %d candidate jobs", len(dork_jobs),
        )

        for job in dork_jobs:
            if saved >= MAX_RELEVANT_JOBS:
                logger.info(
                    "[discovery] Hit MAX_RELEVANT_JOBS=%d — halting.", MAX_RELEVANT_JOBS,
                )
                break

            url   = (job.apply_url or "").strip()
            title = (job.title or "").strip()

            # Deduplication
            if not url or job_store.contains_url(url, user_id):
                logger.debug("[discovery] SKIP (dup) '%s' @ %s", title, job.company)
                skipped += 1
                continue

            # Relevancy gate (already applied inside GoogleDorkScraper, but
            # re-check here in case something slipped through).
            if not is_title_relevant(title):
                logger.debug("[discovery] SKIP (irrelevant) '%s'", title)
                skipped += 1
                continue

            # Optionally hydrate JD from the direct ATS URL (non-LinkedIn only)
            # so the enrichment pipeline has real text to work with.
            # Skip hydration when CREDIT_CONSERVATION_MODE is True — the Google
            # snippet serves as a thin JD proxy; the backfill loop will fill it later.
            jd_text = (job.jd_text or "").strip()  # Google snippet

            if not CREDIT_CONSERVATION_MODE and url:
                host = ""
                try:
                    from urllib.parse import urlparse
                    host = (urlparse(url).hostname or "").lower().removeprefix("www.")
                except Exception:
                    pass
                is_linkedin_url = host == "linkedin.com" or host.endswith(".linkedin.com")
                if not is_linkedin_url:
                    # Fetch JD directly from the ATS URL (unauthenticated requests).
                    try:
                        from backend.scrapers.url_router import scrape_jd_text, is_valid_job_content
                        fetched = await asyncio.to_thread(scrape_jd_text, url)
                        if fetched and is_valid_job_content(fetched):
                            jd_text = fetched
                            logger.info(
                                "[discovery] Hydrated JD: %d chars from %s", len(jd_text), url,
                            )
                    except Exception as hydrate_exc:
                        logger.debug(
                            "[discovery] JD hydration skipped for %s: %s", url, hydrate_exc,
                        )
                else:
                    logger.debug(
                        "[discovery] Skipping authenticated LinkedIn hydration for %s", url,
                    )

            discovered += 1
            category = _category_for_query(title)

            agent_store.set_active("s2", f"Analysing '{title[:40]}' @ {job.company[:30]}")

            raw_text = "\n\n".join(filter(None, [
                f"{title} — {job.company} — {job.location}",
                jd_text,
            ]))

            posting = RawJobPosting(
                id=job.job_id or str(uuid.uuid4()),
                title=title,
                company=job.company or "Unknown Company",
                source_url=url,
                raw_text=raw_text,
                scraped_at=datetime.now(timezone.utc).isoformat(),
            )

            try:
                match = await agent.match(posting)
            except ValueError as exc:
                logger.warning(
                    "[discovery] SKIP (content guard) %s @ %s — %s",
                    posting.title, posting.company, exc,
                )
                skipped += 1
                discovered -= 1
                continue
            except Exception as exc:
                logger.error(
                    "[discovery] ERROR analysing %s @ %s — %s",
                    posting.title, posting.company, exc,
                )
                skipped += 1
                discovered -= 1
                continue

            match.category = category
            match.user_id  = user_id
            # Salt job_id per user — it was built from make_job_id(url) (a
            # hash of the apply URL alone), which collides across tenants
            # scraping the same posting (JOB-92).
            match.job_id   = make_tenant_job_id(match.job_id, user_id)

            agent_store.set_active("s3", f"Writing 'Why apply' brief for '{title[:40]}'")
            agent_store.set_active("s4", f"Verifying claims for '{title[:40]}'")

            job_store.save(match)
            saved += 1
            logger.info(
                "[discovery] saved 'analysing' [%s] — %s @ %s (%s)",
                category, match.title, match.company, match.location,
            )

            try:
                await _enrich_job(match, user_id)
            except Exception as enrich_exc:
                logger.warning(
                    "[discovery] _enrich_job raised for job_id=%s: %s",
                    match.job_id, enrich_exc,
                )

            agent_store.set_idle("s3")
            agent_store.set_idle("s4")

    finally:
        agent_store.set_idle("s1")
        agent_store.set_idle("s2")
        agent_store.set_idle("s3")
        agent_store.set_idle("s4")

    logger.info(
        "━━━ Discovery cycle done — discovered=%d  skipped=%d  saved=%d  cap=%d  user=%r ━━━",
        discovered, skipped, saved, MAX_RELEVANT_JOBS, user_id,
    )
