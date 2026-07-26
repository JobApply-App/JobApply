"""
ingest_pasted_job.py

Ingest a single job from manually-pasted title/company/location/description
text instead of a live scrape — for when POST /api/jobs/analyze can't reach
the source (e.g. RapidAPI's LinkedIn-lookup monthly quota exhausted, per
backend/scrapers/url_router.py's LinkedInRapidApiQuotaError).

Mirrors analyze_job()'s steps 3-6 exactly (backend/api/routes/jobs.py):
MatcherAgent match -> jd_structure_service.structure_jd() -> compute_match_
score_async() -> job_store.save(). Only step 2 (scrape) is skipped, since
the caller already has the raw text. No network calls to LinkedIn or any
scraper are made; the LLM calls (JD structuring + ATS scoring) are the same
ones any other successful /analyze run would make.

Usage
-----
    python -m backend.scripts.ingest_pasted_job \\
        --title "Customer Success Manager" \\
        --company "Classiq" \\
        --location "Tel Aviv-Yafo, Tel Aviv District, Israel" \\
        --url "https://www.linkedin.com/jobs/view/4438264852/" \\
        --description-file /path/to/jd.txt

--user-id is optional and defaults to the sole real (non-'default',
non-'handler-*', non-QA-test-email) row in master_profiles — i.e. the one
actual logged-in account in this single-tenant dev setup, resolved via
_resolve_active_user_id() below. GET /api/jobs/feed's user_id comes from
the real Supabase JWT `sub` claim (backend/api/deps.py's get_current_user),
NOT the literal string "default" — a job saved under user_id="default"
(this script's old hardcoded default) is invisible to a real logged-in
browser session. Pass --user-id explicitly to override (e.g. for a QA test
account) or if auto-resolution can't find exactly one candidate.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# Rows created by this repo's own scaffolding, never a real logged-in
# account — excluded when auto-resolving "the" active user.
_NON_ACCOUNT_USER_ID_PREFIXES = ("default", "handler-update-", "handler-compose-")
_QA_TEST_EMAIL_MARKERS = ("qa-test", "qa.test", "@example.com")


def _resolve_active_user_id() -> str:
    """
    The one real logged-in account in this single-tenant dev setup, i.e. the
    sole master_profiles row that isn't a scaffolding placeholder or a QA
    test account. Raises with a clear candidate list if that's not unique —
    callers should pass --user-id explicitly in that case.
    """
    from sqlalchemy import text
    from backend.core.database import ENGINE

    with ENGINE.connect() as conn:
        rows = conn.execute(text("SELECT user_id, email FROM master_profiles")).fetchall()

    candidates = [
        (uid, email) for uid, email in rows
        if not uid.startswith(_NON_ACCOUNT_USER_ID_PREFIXES)
        and email
        and not any(marker in email.lower() for marker in _QA_TEST_EMAIL_MARKERS)
    ]

    if len(candidates) == 1:
        uid, email = candidates[0]
        logger.info("Auto-resolved active user: %s (%s)", uid, email)
        return uid

    logger.error(
        "Could not auto-resolve a single active user (found %d candidate(s): %s). "
        "Pass --user-id explicitly.",
        len(candidates), candidates,
    )
    sys.exit(1)


async def run(title: str, company: str, location: str, url: str, description: str, user_id: str) -> None:
    import backend.repositories.job_repository as job_store
    from backend.agents.matcher import MatcherAgent
    from backend.schemas.job import RawJobPosting
    from backend.services.feed_service import _build_profile_cv_proxy, is_substantive_analysis
    from backend.services.jd_structure_service import extract_company_from_structured, structure_jd
    from backend.services.match_score_service import compute_match_score_async
    from backend.services.user_profile import get_profile

    jd_text = description.strip()
    if len(jd_text) < 200:
        logger.error("Description is only %d chars — too thin for reliable scoring (need >=200).", len(jd_text))
        sys.exit(1)

    cached = job_store.get_by_url(url, user_id)
    if cached is not None:
        logger.info("Cache hit — job_id=%s already exists, skipping re-ingestion.", cached.job_id)
        return

    posting = RawJobPosting(
        id=str(uuid.uuid4()),
        title=title,
        company=company,
        source_url=url,
        raw_text=jd_text,
        scraped_at=datetime.now(timezone.utc).isoformat(),
    )

    agent = MatcherAgent()
    match = await agent.match(posting, user_id=user_id)
    match = match.model_copy(update={"location": location or match.location})

    logger.info("Structuring JD...")
    structured_json = await structure_jd(jd_text, user_id=user_id, job_id=match.job_id)
    if not structured_json:
        logger.error("JD structuring failed (LLM returned no usable output). Aborting — job not saved.")
        sys.exit(1)

    extracted_company = extract_company_from_structured(structured_json)
    if extracted_company:
        match = match.model_copy(update={"company": extracted_company})

    logger.info("Scoring...")
    cv_proxy = _build_profile_cv_proxy(get_profile(user_id), user_id=user_id)
    result = await compute_match_score_async(
        cv_data=cv_proxy,
        jd_text=jd_text,
        run_llm_validation=True,
        job_title=match.title,
        company_name=match.company or "",
        user_id=user_id,
    )
    final_score = round(float(result.total), 1)
    analysis_ok = is_substantive_analysis(result.why_ron)

    is_linkedin = "linkedin.com" in url.lower()
    match = match.model_copy(update={
        "source": "manual",
        "source_type": "linkedin" if is_linkedin else "other",
        "is_open": True,
        "user_id": user_id,
        "status": "new",
        "match_score": final_score,
        "score_is_proxy": not analysis_ok,
        "jd_structured": structured_json,
        "jd_text": jd_text,
        "why_ron": result.why_ron if analysis_ok else None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })

    job_store.save(match)
    if analysis_ok:
        job_store.update_why_ron(match.job_id, user_id, result.why_ron)

    logger.info(
        "Done — job_id=%s title=%r company=%r match_score=%.1f%s",
        match.job_id, match.title, match.company, final_score,
        "" if analysis_ok else " (proxy — LLM analysis was non-substantive)",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest a single job from pasted text (no live scrape)")
    parser.add_argument("--title", required=True)
    parser.add_argument("--company", required=True)
    parser.add_argument("--location", default="")
    parser.add_argument("--url", required=True, help="apply_url / dedup key for this posting")
    parser.add_argument(
        "--user-id", default=None,
        help="Owner to save under. Omit to auto-resolve the sole real logged-in account.",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--description", help="Raw JD text inline")
    group.add_argument("--description-file", help="Path to a file containing the raw JD text")
    args = parser.parse_args()

    description = args.description
    if args.description_file:
        description = Path(args.description_file).read_text(encoding="utf-8")

    user_id = args.user_id or _resolve_active_user_id()
    asyncio.run(run(args.title, args.company, args.location, args.url, description, user_id))


if __name__ == "__main__":
    main()
