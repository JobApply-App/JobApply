"""
patch_mint_direct.py
====================
1. Verifies jd_text is injected into the Mint PM job (patches if missing).
2. Flags score_is_proxy=1 + clears why_ron so _needs_enrichment() picks it up.
3. Clears all LinkedIn block keys from kv_store.
4. Directly calls compute_match_score_async with the full LLM pipeline and
   writes the resulting match_score + why_ron + score_is_proxy=0 back to the DB.

Exact column names verified from backend/models/*.py:
  table  : jobs
  PK     : job_id  (String)
  JD text: jd_text (Text)
  flags  : score_is_proxy (Boolean), enrichment_failures (Integer)
  kv_store PK: key (String)
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Load backend/.env so ANTHROPIC_API_KEY and other secrets are available
from dotenv import load_dotenv  # noqa: E402
load_dotenv(ROOT / "backend" / ".env")

# ── Job description ───────────────────────────────────────────────────────────
MINT_JD = """\
Company Description
Mint is an Israeli digital agency building B2C websites and apps for the \
country's leading brands — Bank Hapoalim, Ashtrom, Delek Motors, Histadrut, and more.

Overview
Looking for a rockstar Project Manager — early in their product journey.

About the Role
- Lead digital projects end-to-end — from the first client brief through launch
- Serve as the main professional point of contact for clients: managing \
expectations, running status meetings, documenting decisions
- Write PRDs, specs, and user stories at a level that lets development run \
without getting stuck
- Work closely with development, design, and QA teams — translating client \
needs into clear work plans
- Identify product opportunities and manage scope changes in a structured way

Qualifications — Experience
- 1-3 years of experience managing digital projects (websites / apps / web systems)
- Proven experience working directly with clients, ideally large organizations
- Experience writing specs / PRDs / user stories
- Proficiency with project management tools (Jira / Monday / Asana)
- Experience working with both in-house and external development teams
- Experience with B2C clients

Qualifications — Mindset
- A genuine love for clients — not patience, love. Real curiosity about their business
- Backbone: the ability to say no to clients when needed and protect the team
- Emerging product mindset — curiosity about the why behind user behavior, \
not just the what
- Obsessive organization — if something falls through the cracks, it will keep \
you up at night
- Initiative and ownership — does not wait to be told what to do

Nice to Have
- Experience at a digital agency or software house
- Familiarity with Umbraco

Why Join Us
- Clear growth path to Product Manager within the team
- Exposure to a wide variety of clients, industries, and technologies
- A team that believes a great PM is half the success of any project — not \
the person who updates Jira
"""

BLOCK_KEYS = [
    "linkedin_scraper_status",
    "linkedin_redirect_error_count",
    "linkedin_scraper_blocked_at",
    "linkedin_cookie_status",
    "linkedin_scraper_paused",
]

MINT_JOB_ID = "ace28755-d81c-41d5-a30a-c8a0b3ba089e"


async def main() -> None:
    from sqlalchemy.orm import Session
    from backend.core.database import ENGINE
    from backend.models.job import JobRow
    from backend.models.kv import KVRow
    from backend.services.match_score_service import compute_match_score_async
    from backend.services.feed_service import _build_profile_cv_proxy
    from backend.services.user_profile import USER_PROFILE

    # ── 1. Patch jd_text + reset flags to force re-enrichment ────────────────
    print("\n── Step 1: Patch jd_text and reset enrichment flags ─────────────────")
    with Session(ENGINE) as db:
        job = db.get(JobRow, MINT_JOB_ID)
        if job is None:
            sys.exit(f"  ERROR: job_id {MINT_JOB_ID} not found in jobs table.")

        print(f"  Found   : {job.title!r} @ {job.company!r}")
        print(f"  Before  : match_score={job.match_score}  score_is_proxy={job.score_is_proxy}  "
              f"jd_len={len(job.jd_text or '')}  enrichment_failures={job.enrichment_failures}")

        job.jd_text            = MINT_JD
        job.score_is_proxy     = True   # mark as needing LLM re-score
        job.why_ron            = None   # clear stale LLM output
        job.enrichment_failures = 0
        db.commit()
        print(f"  Patched : jd_text={len(MINT_JD)} chars, score_is_proxy=True, "
              "why_ron=None, enrichment_failures=0")

    # ── 2. Clear LinkedIn block keys ──────────────────────────────────────────
    print("\n── Step 2: Clear LinkedIn block keys ────────────────────────────────")
    with Session(ENGINE) as db:
        for key in BLOCK_KEYS:
            row = db.get(KVRow, key)
            if row:
                print(f"  Deleted : {key:<45s} (was: {row.value!r})")
                db.delete(row)
            else:
                print(f"  (absent): {key}")
        db.commit()

    # ── 3. Direct LLM re-score ────────────────────────────────────────────────
    print("\n── Step 3: Running full LLM re-score (this may take 10-20s) ─────────")
    cv_data = _build_profile_cv_proxy(USER_PROFILE)

    result = await compute_match_score_async(
        cv_data=cv_data,
        jd_text=MINT_JD,
        run_llm_validation=True,
        user_id="default",   # legacy single-user dev script
    )

    new_score = result.total
    print(f"  New match_score : {new_score}")
    print(f"  why_ron         : {(result.why_ron or '')[:120]}...")
    print(f"  missing_caps    : {result.missing_critical_capabilities}")

    # ── 4. Write score back to DB ─────────────────────────────────────────────
    print("\n── Step 4: Writing new score to DB ──────────────────────────────────")
    with Session(ENGINE) as db:
        job = db.get(JobRow, MINT_JOB_ID)
        job.match_score         = new_score
        job.score               = new_score
        job.score_is_proxy      = False
        job.why_ron             = result.why_ron
        job.enrichment_failures = 0
        db.commit()
        print(f"  match_score={job.match_score}  score={job.score}  "
              f"score_is_proxy={job.score_is_proxy}")

    print("\n── Done ─────────────────────────────────────────────────────────────")


if __name__ == "__main__":
    asyncio.run(main())
