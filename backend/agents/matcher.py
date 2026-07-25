"""
MatcherAgent — s1 Local Proxy Scorer
=====================================

Two-phase pipeline architecture
---------------------------------
s1  (Scraper)             → MatcherAgent.match()
                             Computes the 30% local proxy score (title keyword
                             alignment + seniority fit) in pure Python, < 1 ms.
                             Saves the job to the DB immediately so the UI shows
                             a meaningful initial score without blocking on LLM.
                             Sets why_ron=None as the "needs enrichment" signal.

s2  (Sourcing Specialist) → feed_service.refresh_user_scores()
                             Finds all jobs where why_ron IS NULL (locally scored
                             but not yet LLM-enriched), batches them behind
                             asyncio.Semaphore(5), and runs the 50% semantic +
                             20% management LLM sub-scores via claude-haiku
                             (temperature=0.0).  Updates match_score with the
                             full composite and sets why_ron to the LLM brief.

No Anthropic API calls in this module.  The LLM lives in match_score_service
_llm_dual_score() and is orchestrated by feed_service in the s2 stage.

DEV_MODE
--------
When backend/config.py has DEV_MODE=True, match() returns a deterministic mock
(seeded by posting.id) without touching any external API.  The mock produces
realistic-looking scores in the 55-82 range and correctly sets why_ron to a
non-None string so s2 does not re-process DEV jobs.
"""
from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timezone

from backend.schemas.job import DetailedAnalysis, JobMatch, RawJobPosting, ReasonTag
from backend.services.match_score_service import compute_local_proxy_score
from backend.config import DEV_MODE

logger = logging.getLogger(__name__)


# ── cv_claims skill-overlap scorer ────────────────────────────────────────────

def _tokenize(text: str) -> set[str]:
    """Lower-case word tokens — used for whole-word skill matching."""
    return set(re.findall(r"[a-z0-9#+.\-]{2,}", text.lower()))


def _cv_claims_skill_score(jd_text: str, claimed_skills: list[str]) -> float:
    """
    Measure how many of the candidate's *claimed* skills appear in the JD.

    Algorithm
    ---------
    For each claimed skill, test whether every significant token in that
    skill phrase appears somewhere in the JD token set.  Multi-word skills
    like "Product Management" require both "product" and "management" to be
    present — single-word skills like "SQL" require an exact token match.

    Score is mapped onto 20-95:
        0 % coverage → 20   (some baseline; candidate has skills, just none match this JD)
       50 % coverage → 57
      100 % coverage → 95   (perfect overlap — every claimed skill is demanded)

    Returns 50.0 when no claimed skills are available (neutral / no penalty).
    """
    if not claimed_skills:
        return 50.0  # no cv_claims uploaded — fall back to neutral

    jd_tokens = _tokenize(jd_text)

    # Ignore very short filler tokens that appear in almost every JD
    _STOPWORDS = {"and", "or", "the", "with", "in", "of", "to", "a", "an",
                  "for", "on", "at", "by", "is", "be", "as", "from"}

    hits = 0
    for skill in claimed_skills:
        skill_tokens = _tokenize(skill) - _STOPWORDS
        if not skill_tokens:
            continue
        if skill_tokens.issubset(jd_tokens):
            hits += 1

    coverage = hits / len(claimed_skills)
    score    = round(20.0 + coverage * 75.0, 1)   # 20 … 95
    logger.debug(
        "[MatcherAgent] cv_claims skill overlap: %d/%d skills matched → %.1f",
        hits, len(claimed_skills), score,
    )
    return score


def _load_cv_claims_skills(user_id: str) -> list[str]:
    """
    Load the candidate's claimed skills from the user's profile store.
    Returns an empty list silently on any failure (non-fatal).
    """
    try:
        from backend.services.user_profile_store import load as profile_load
        profile = profile_load(user_id)
        skills  = profile.get("cv_claims", {}).get("skills", [])
        return [s for s in skills if isinstance(s, str) and s.strip()]
    except Exception as exc:
        logger.debug("[MatcherAgent] Could not load cv_claims for user=%s: %s", user_id, exc)
        return []


def _extract_location(posting: RawJobPosting) -> str:
    """
    Best-effort location extraction from the first line of raw_text.

    discovery.py and all board scrapers build raw_text with the first line:
        "Title — Company — Location"
    Fall back to "Israel" when the pattern is absent or the location slot
    is empty — all scrapers target the Israeli job market by default.
    """
    first_line = posting.raw_text.strip().split("\n")[0]
    parts      = [p.strip() for p in first_line.split(" — ")]
    if len(parts) >= 3 and parts[2]:
        return parts[2]
    return "Israel"


class MatcherAgent:
    """
    s1 fast-path matcher.

    match() computes a local proxy score and returns a minimal JobMatch.
    No API keys required; no async I/O performed.

    The full LLM enrichment (semantic + management LLM sub-scores) is the
    responsibility of feed_service.refresh_user_scores() in s2.
    """

    # ── DEV_MODE mock ─────────────────────────────────────────────────────────
    #
    # Returns a deterministic JobMatch without calling any external service.
    # Score is seeded by MD5(posting.id) → stable across pipeline reruns.
    # why_ron is set to a non-None string so s2 skips re-enriching DEV jobs.

    def _mock_match(self, posting: RawJobPosting) -> JobMatch:
        """Deterministic DEV mock — no API call, no content guards."""
        seed  = int(hashlib.md5(posting.id.encode("utf-8", errors="ignore")).hexdigest()[:4], 16)
        score = round(55.0 + (seed % 28), 1)   # 55.0 – 82.0

        title_lower = posting.title.lower()
        is_pm   = any(kw in title_lower for kw in ("product", "pm ", "owner"))
        is_cs   = any(kw in title_lower for kw in ("success", "account", "csm"))
        is_snr  = any(kw in title_lower for kw in ("senior", "lead", "head", "vp"))
        is_eng  = any(kw in title_lower for kw in ("engineer", "developer", "architect", "backend", "frontend"))
        is_data = any(kw in title_lower for kw in ("data", "analyst", "analytics", "bi", "scientist"))
        domain  = "PM" if is_pm else ("CS" if is_cs else ("Engineering" if is_eng else ("Data" if is_data else "General")))
        snr_tag = "senior" if is_snr else "mid-level"

        _WHY_RON_TEMPLATES: dict[str, str] = {
            "PM": (
                f"Strong alignment with {posting.title} at {posting.company}: the candidate's "
                f"track record in roadmap ownership, cross-functional stakeholder management, and "
                f"data-driven prioritization maps directly to the core requirements of this role. "
                f"Previous experience driving B2C product growth and owning OKR cycles makes this "
                f"a high-confidence match at {snr_tag} seniority."
            ),
            "CS": (
                f"The candidate's background in enterprise customer success and retention strategy "
                f"aligns well with the {posting.title} role at {posting.company}. Experience "
                f"managing complex customer portfolios, driving QBRs, and collaborating with "
                f"product and sales teams translates directly to the expectations of this position."
            ),
            "Engineering": (
                f"Technical profile is well-suited for {posting.title} at {posting.company}. "
                f"The candidate's hands-on experience with scalable system design, CI/CD pipelines, "
                f"and agile delivery aligns with the engineering culture described in the JD. "
                f"A {snr_tag} trajectory with measurable delivery ownership strengthens this match."
            ),
            "Data": (
                f"Strong fit for {posting.title} at {posting.company} based on the candidate's "
                f"analytical background and experience translating data insights into product and "
                f"business decisions. Familiarity with SQL, dashboarding, and cross-team "
                f"collaboration on growth metrics is directly relevant to this role."
            ),
            "General": (
                f"Solid candidate-to-role alignment for {posting.title} at {posting.company}. "
                f"The candidate's demonstrated ability to operate in fast-paced environments, "
                f"manage competing priorities, and deliver cross-functional outcomes maps well "
                f"to the expectations outlined in this job description."
            ),
        }

        why_ron_text = _WHY_RON_TEMPLATES.get(domain, _WHY_RON_TEMPLATES["General"])

        logger.info(
            "[MatcherAgent] DEV_MODE mock → score=%.1f  domain=%s  '%s' @ '%s'",
            score, domain, posting.title, posting.company,
        )

        return JobMatch(
            job_id   = posting.id,
            title    = posting.title,
            company  = posting.company,
            location = _extract_location(posting),
            score    = score,
            match_score          = score,
            confidence_score     = 62,
            culture_fit_score    = 65,
            trajectory_alignment = (
                f"{snr_tag.capitalize()} role — maps to candidate's {domain} background."
            ),
            company_dna_inference = (
                f"Growth-stage company profile inferred for '{posting.company}'."
            ),
            detailed_analysis = DetailedAnalysis(
                strengths        = [f"{domain} background aligns with role domain"],
                critical_gaps    = [],
                strategic_advice = ["Consider quantifying recent impact metrics before applying"],
            ),
            investigation_points = ["Confirm seniority expectations match candidate's target level"],
            reasons  = [ReasonTag(kind="skill", label=f"{domain} domain fit")],
            apply_url = posting.source_url,
            is_new   = True,
            posted_at = "just now",
            # Non-None why_ron prevents s2 from re-enriching DEV mock rows.
            why_ron  = why_ron_text,
            scoring_rationale = (
                f"seed={seed % 28}/27  domain={domain}  "
                f"seniority={snr_tag}  score={score}"
            ),
            jd_text = posting.raw_text[:5000],
        )

    # ── Production path ───────────────────────────────────────────────────────

    async def match(
        self,
        posting: RawJobPosting,
        user_id: str,
    ) -> JobMatch:
        """
        Compute an initial proxy score and return a minimal JobMatch for DB storage.

        DEV_MODE → deterministic mock (see _mock_match above).

        Production scoring (two components blended):
          60%  compute_local_proxy_score() — title keyword + seniority alignment.
          40%  cv_claims skill-overlap     — fraction of the candidate's *claimed*
               skills (from uploaded CVs) that appear in the JD text.

        When no cv_claims have been uploaded for the user, the skill-overlap
        component returns a neutral 50.0 and the local proxy is used at full weight,
        preserving the existing behaviour.

        The skill-overlap component prevents inflated 90+ scores from a title-only
        match when the actual JD requirements don't align with the candidate's
        documented skills.

        why_ron is set to None — the signal for s2 (feed_service.refresh_user_scores)
        to run the full LLM composite scorer (semantic + management sub-scores).
        """
        if DEV_MODE:
            return self._mock_match(posting)

        # ── Proxy scoring DISABLED ────────────────────────────────────────────
        # The old local proxy (title + seniority + cv-claims overlap) produced
        # premature high scores (e.g. 94.0) that surfaced jobs at the top of the
        # feed before any real analysis ran — a false positive.  We now persist
        # the job with a NULL (0.0) score flagged as a proxy and defer ALL
        # scoring to the LLM-backed compute_match_score_async(), which the
        # orchestrating workflow runs as the *primary* (and only) scoring method.
        #
        # Until that finalised composite score lands, the job is presentationally
        # gated as 'analysing' and does not surface as a ranked result.
        location = _extract_location(posting)

        logger.info(
            "[MatcherAgent] persist NULL score (proxy disabled) — deferring to "
            "LLM composite scorer for '%s' @ '%s'",
            posting.title, posting.company,
        )

        return JobMatch(
            job_id   = posting.id,
            title    = posting.title,
            company  = posting.company,
            location = location,
            score    = 0.0,                # NULL placeholder; set by LLM composite
            match_score          = 0.0,    # NULL placeholder; set by LLM composite
            score_is_proxy       = True,   # gates the job as 'analysing' until finalised
            status               = "analysing",  # consistent DB state; never show before enrichment
            confidence_score     = 50,     # placeholder
            culture_fit_score    = 50,     # placeholder
            trajectory_alignment  = "",    # populated by LLM enrichment
            company_dna_inference = "",    # populated by LLM enrichment
            detailed_analysis = DetailedAnalysis(
                strengths=[], critical_gaps=[], strategic_advice=[]
            ),
            investigation_points = [],
            reasons   = [],
            apply_url = posting.source_url,
            is_new    = True,
            posted_at = "just now",
            why_ron   = None,              # None = "needs LLM enrichment"
            scoring_rationale = (
                "Proxy scoring disabled — score deferred to LLM composite "
                "(compute_match_score_async). Job gated 'analysing' until finalised."
            ),
            jd_text = posting.raw_text[:5000],
        )
