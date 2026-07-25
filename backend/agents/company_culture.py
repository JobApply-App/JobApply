"""
Company Culture Agent — company vibe, operational needs, accepted personas (JOB-19)
===================================================================================

Researches and profiles the HIRING COMPANY itself — distinct from both the
candidate-side scoring (match_score_service) and the financial-vibe research
layer (company_intelligence_service, which feeds CV tailoring). This agent
answers: does this company skew startup/scrappy or corporate/structured, at
what pace does it operate, and what candidate persona does it typically
accept?

Inputs
------
  • company_name   — from the job object / JD Parsing Agent (never derived by
                     substring-matching the JD body; see _find_prior_employer's
                     false-positive history).
  • jd_text        — the posting text; tone, benefits language, and team-size
                     hints carry most of the culture signal.
  • about_text     — optional scraped "About Us" / career-page copy.
  • source/apply_url — scraper source metadata. An ATS-hosted posting
                     (Comeet/Greenhouse/Lever) correlates with company size and
                     maturity differently than a job-board or agency listing;
                     the hint is passed to the LLM as weak context, never as a
                     hard rule.

Output schema (STABLE — consumed by Dynamic Matching Score, JOB-20)
-------------------------------------------------------------------
CompanyCultureProfile.as_dict() keys:

  company_key, display_name,
  culture_axis        float 0-100, 1 decimal — 0 = corporate/structured,
                                               100 = startup/scrappy
  culture_category    startup | scaleup | corporate | agency | unknown
  operational_pace    fast | moderate | structured | unknown
  formality           casual | balanced | formal | unknown
  work_model          remote | hybrid | onsite | flexible | unknown
  work_life_balance_signals  [str]   — concrete signals, not vibes
  accepted_persona_traits    [str]   — what this company's hiring rewards
  operational_needs          [str]   — needs implied by the JD
  evidence                   [str]   — quotes/signals grounding the profile
  confidence          low | medium | high
  source_hint         ats | job_board | agency | unknown
  researched_at       ISO 8601 UTC

`work_model` maps directly onto the user's hard constraints from the profiling
baseline (JOB-18: constraints.hard.work_model == "remote_only"), and
accepted_persona_traits / operational_pace map onto soft preferences —
see constraint_conflicts().

Scoring-principles compliance (CLAUDE.md Future Mandate review)
---------------------------------------------------------------
This agent is ADDITIVE RESEARCH ONLY and is not wired into the composite
score (that integration is JOB-20's scope, to be reviewed separately):
  1. Data Completeness   — no candidate data flows through this agent at all.
  2. Company Legacy      — untouched; profiles describe the company, never
                           override the prior-employer boost.
  3. Exploration Freedom — a culture profile must never be used to penalize a
                           candidate's title/pivot; it describes the company.
  4. Thin-JD Fallback    — mirrored here: sparse input (< _MIN_INPUT_CHARS of
                           usable text) skips the LLM and returns an honest
                           low-confidence "unknown" profile rather than a
                           fabricated vibe.
  5. Future Mandate      — culture_axis is a company attribute, not a score
                           bonus; JOB-20 must re-review before blending it.

Caching: one row per company in the company_culture table (30-day staleness),
so repeat postings from the same employer never re-trigger research.
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from pydantic import BaseModel, Field, ValidationError

from backend.services.llm_client import call_llm

logger = logging.getLogger(__name__)

_CULTURE_MODEL   = "claude-haiku-4-5-20251001"
_MAX_TOKENS      = 1000   # 600 truncated real responses mid-list (verified live)
_STALE_AFTER     = timedelta(days=30)

# Below this many characters of combined JD + about text, the LLM is skipped
# entirely (Principle-4 mirror): an honest "unknown" beats a fabricated vibe.
_MIN_INPUT_CHARS = 200

CULTURE_CATEGORIES = ("startup", "scaleup", "corporate", "agency", "unknown")
PACE_VALUES        = ("fast", "moderate", "structured", "unknown")
FORMALITY_VALUES   = ("casual", "balanced", "formal", "unknown")
WORK_MODELS        = ("remote", "hybrid", "onsite", "flexible", "unknown")
SOURCE_HINTS       = ("ats", "job_board", "agency", "unknown")

# ── Scraper-source → maturity hint ────────────────────────────────────────────
# Weak prior only: passed to the LLM as context, never applied as a rule.
_ATS_SOURCES       = ("comeet", "greenhouse", "lever")
_JOB_BOARD_SOURCES = ("linkedin", "alljobs", "drushim", "jobmaster", "indeed", "glassdoor")
_AGENCY_SOURCES    = ("gotfriends", "nisha", "ethosia", "dialog")


def infer_source_hint(source: str = "", apply_url: str = "") -> str:
    """
    Classify the posting's origin from scraper source metadata and/or the
    apply URL. ATS-hosted ⇒ the company runs its own pipeline (size/maturity
    signal); agency ⇒ the poster is an intermediary, tone reflects the agency.
    """
    haystack = f"{source} {apply_url}".lower()
    if any(s in haystack for s in _ATS_SOURCES):
        return "ats"
    if any(s in haystack for s in _AGENCY_SOURCES):
        return "agency"
    if any(s in haystack for s in _JOB_BOARD_SOURCES):
        return "job_board"
    return "unknown"


# ── Output schema ─────────────────────────────────────────────────────────────

class CompanyCultureProfile(BaseModel):
    company_key:               str
    display_name:              str
    culture_axis:              float = 50.0        # 0 corporate ←→ 100 startup, 1 dp
    culture_category:          str = "unknown"
    operational_pace:          str = "unknown"
    formality:                 str = "unknown"
    work_model:                str = "unknown"
    work_life_balance_signals: list[str] = Field(default_factory=list)
    accepted_persona_traits:   list[str] = Field(default_factory=list)
    operational_needs:         list[str] = Field(default_factory=list)
    evidence:                  list[str] = Field(default_factory=list)
    confidence:                str = "low"          # low | medium | high
    source_hint:               str = "unknown"
    researched_at:             str = ""

    def as_dict(self) -> dict:
        return self.model_dump()


class _LLMCulturePayload(BaseModel):
    """Strict validation of the raw LLM response before normalization."""
    culture_axis:              float = Field(ge=0, le=100)
    culture_category:          str
    operational_pace:          str
    formality:                 str
    work_model:                str
    work_life_balance_signals: list[str] = Field(default_factory=list)
    accepted_persona_traits:   list[str] = Field(default_factory=list)
    operational_needs:         list[str] = Field(default_factory=list)
    evidence:                  list[str] = Field(default_factory=list)
    confidence:                str = "low"


def _company_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (name or "").lower()).strip("_")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _clean_enum(value, allowed: tuple[str, ...]) -> str:
    v = str(value or "").lower().strip()
    return v if v in allowed else "unknown"


def build_profile_from_payload(
    company_name: str,
    payload: dict,
    source_hint: str = "unknown",
    now: Optional[datetime] = None,
) -> CompanyCultureProfile:
    """
    Normalize a validated LLM payload (or any compatible dict) into the
    stable output schema: enums cleaned to their allowed sets, culture_axis
    clamped to 0-100 at 1-decimal precision, list lengths capped.
    """
    axis = round(min(max(float(payload.get("culture_axis", 50.0)), 0.0), 100.0), 1)
    conf = str(payload.get("confidence", "low")).lower().strip()
    if conf not in ("low", "medium", "high"):
        conf = "low"
    return CompanyCultureProfile(
        company_key               = _company_key(company_name),
        display_name              = company_name,
        culture_axis              = axis,
        culture_category          = _clean_enum(payload.get("culture_category"), CULTURE_CATEGORIES),
        operational_pace          = _clean_enum(payload.get("operational_pace"), PACE_VALUES),
        formality                 = _clean_enum(payload.get("formality"), FORMALITY_VALUES),
        work_model                = _clean_enum(payload.get("work_model"), WORK_MODELS),
        work_life_balance_signals = [str(x)[:200] for x in payload.get("work_life_balance_signals", [])][:6],
        accepted_persona_traits   = [str(x)[:200] for x in payload.get("accepted_persona_traits", [])][:6],
        operational_needs         = [str(x)[:200] for x in payload.get("operational_needs", [])][:6],
        evidence                  = [str(x)[:300] for x in payload.get("evidence", [])][:8],
        confidence                = conf,
        source_hint               = _clean_enum(source_hint, SOURCE_HINTS),
        researched_at             = (now or _now()).isoformat(),
    )


def build_sparse_profile(
    company_name: str,
    source_hint: str = "unknown",
    now: Optional[datetime] = None,
) -> CompanyCultureProfile:
    """
    Honest degradation profile for sparse input — every dimension "unknown",
    confidence "low", neutral culture_axis. Mirrors the Thin-JD principle:
    never fabricate a vibe the data cannot support.
    """
    return CompanyCultureProfile(
        company_key   = _company_key(company_name),
        display_name  = company_name,
        source_hint   = _clean_enum(source_hint, SOURCE_HINTS),
        confidence    = "low",
        researched_at = (now or _now()).isoformat(),
    )


# ── Constraint mapping (bridge to the JOB-18 profiling baseline) ──────────────

def constraint_conflicts(profile: CompanyCultureProfile, hard_constraints: dict) -> list[str]:
    """
    Compare a culture profile against the user's hard constraints
    (profile_baseline_service baseline["constraints"]["hard"]) and return
    human-readable conflicts. Empty list = no detected conflict.

    Only ever fires on POSITIVE evidence of a conflict: "unknown" or
    "flexible" company values never conflict, mirroring get_knockout_prefs'
    rule that a flexible candidate can never be knocked out.
    """
    conflicts: list[str] = []
    if hard_constraints.get("work_model") == "remote_only" and profile.work_model == "onsite":
        conflicts.append(
            f"User requires remote-only but {profile.display_name} appears onsite-only"
        )
    return conflicts


# ── LLM prompt ────────────────────────────────────────────────────────────────

_CULTURE_SYSTEM = (
    "You are a precise company-culture analyst. "
    "Output ONLY a valid, complete JSON object — no markdown fences, no prose. "
    "The entire response must be parseable by json.loads()."
)

_CULTURE_TEMPLATE = """\
Profile the HIRING COMPANY's culture from the posting below.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
BILINGUAL & RTL PROCESSING (HEBREW/ENGLISH)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
You must seamlessly comprehend mixed syntax, such as Hebrew sentences containing English technical terms or acronyms, without losing context or introducing translation artifacts.
Regardless of the input language (Hebrew, English, or mixed), all returned JSON structures MUST use English keys exclusively. Values may be in the source language, but keys must always be English.

COMPANY: {company_name}
POSTING ORIGIN: {source_hint} (weak prior only — ats = company runs its own
hiring pipeline; agency = text written by an intermediary, discount its tone;
job_board = neutral)

JOB DESCRIPTION:
{jd_text}

ABOUT / CAREER-PAGE TEXT (may be empty):
{about_text}

Return this exact JSON object:
{{
  "culture_axis": <number 0-100: 0 = corporate/structured, 100 = startup/scrappy>,
  "culture_category": "startup|scaleup|corporate|agency|unknown",
  "operational_pace": "fast|moderate|structured|unknown",
  "formality": "casual|balanced|formal|unknown",
  "work_model": "remote|hybrid|onsite|flexible|unknown",
  "work_life_balance_signals": ["<concrete signal from the text>", ...],
  "accepted_persona_traits": ["<trait this company's hiring visibly rewards>", ...],
  "operational_needs": ["<operational need implied by the JD>", ...],
  "evidence": ["<short quote or concrete signal grounding your answers>", ...],
  "confidence": "low|medium|high"
}}

HONESTY RULES:
• Ground every dimension in the provided text. Where the text does not
  support a judgment, return "unknown" — a wrong vibe misleads a job seeker
  more than no vibe. Never guess from the company name alone.
• evidence must contain the concrete phrases you relied on (either language).
• Every list item must be ONE plain JSON string — put any commentary INSIDE
  the quotes (e.g. "Tel-Aviv office (onsite location)"), never after them.
• work_model: only set remote/hybrid/onsite when the text states it;
  "flexible" only when the text explicitly offers a choice.
• confidence: high = multiple explicit signals agree; medium = some signal;
  low = thin or conflicting signal.
"""


def _extract_json(raw: str) -> dict:
    """
    Parse the LLM response, attempting progressively more aggressive repair
    before giving up — mirrors match_score_service._parse_json_robust. The
    dominant failure mode is max_tokens truncation mid-string or mid-list,
    so the repair ladder closes an open string, then list, then object.
    """
    text = re.sub(r"```(?:json)?", "", raw).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Observed live malformation: annotation escapes the string quotes —
    #   "Tel-Aviv office" (onsite location specified)"
    # Fold the parenthetical back inside the string and retry.
    repaired = re.sub(r'"([^"\n]*)"\s*(\([^)\n]*\))"', r'"\1 \2"', text)
    if repaired != text:
        try:
            return json.loads(repaired)
        except json.JSONDecodeError:
            text = repaired   # keep the repair for the later ladder steps

    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            pass

    if start != -1:
        fragment = text[start:].rstrip().rstrip(",")
        for suffix in ('"]}', '"}', "]}", "}"):
            try:
                return json.loads(fragment + suffix)
            except json.JSONDecodeError:
                continue

    raise ValueError(f"No JSON object in culture response: {raw[:200]}")


# ── Cache layer (company_culture table) ───────────────────────────────────────

def load_cached_profile(company_name: str, engine=None) -> Optional[CompanyCultureProfile]:
    key = _company_key(company_name)
    if not key:
        return None
    try:
        from backend.repositories import company_culture_repository

        row = company_culture_repository.get(key, engine=engine)
        if row is None:
            return None
        return CompanyCultureProfile(**json.loads(row.profile_json))
    except Exception as exc:
        logger.warning("[company-culture] corrupt/unreadable cache for %r (%s) — miss", key, exc)
        return None


def save_cached_profile(profile: CompanyCultureProfile, engine=None) -> bool:
    try:
        from backend.repositories import company_culture_repository

        company_culture_repository.upsert(
            profile.company_key, profile.display_name,
            profile.model_dump_json(), profile.researched_at,
            engine=engine,
        )
        return True
    except Exception as exc:
        logger.warning("[company-culture] cache save failed for %r: %s", profile.company_key, exc)
        return False


def is_stale(profile: CompanyCultureProfile, now: Optional[datetime] = None) -> bool:
    try:
        ts = datetime.fromisoformat(profile.researched_at)
    except (ValueError, TypeError):
        return True
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return (now or _now()) - ts >= _STALE_AFTER


# ── Agent ─────────────────────────────────────────────────────────────────────

class CompanyCultureAgent:
    """
    LLM-backed culture profiler. Follows the same conventions as the other
    agents (async Anthropic client, temperature 0.0 for determinism, strict
    Pydantic validation, graceful degradation on every failure path).
    """

    def __init__(self, model: str = _CULTURE_MODEL):
        self.model = model

    async def analyze(
        self,
        company_name: str,
        jd_text: str,
        about_text: str = "",
        source: str = "",
        apply_url: str = "",
    ) -> CompanyCultureProfile:
        """
        Produce a CompanyCultureProfile from the posting text. Never raises:
        sparse input, missing API key, API errors, and malformed responses all
        degrade to an honest low-confidence "unknown" profile.
        """
        source_hint = infer_source_hint(source, apply_url)
        usable = f"{(jd_text or '').strip()}\n{(about_text or '').strip()}".strip()

        # Principle-4 mirror: never ask the LLM to profile from nothing.
        if len(usable) < _MIN_INPUT_CHARS:
            logger.info(
                "[company-culture] sparse input for %r (%d chars) — honest unknown profile",
                company_name, len(usable),
            )
            return build_sparse_profile(company_name, source_hint)

        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            logger.warning("[company-culture] ANTHROPIC_API_KEY not set — unknown profile")
            return build_sparse_profile(company_name, source_hint)

        prompt = _CULTURE_TEMPLATE.format(
            company_name = company_name or "Unknown",
            source_hint  = source_hint,
            jd_text      = (jd_text or "")[:4000],
            about_text   = (about_text or "")[:2000] or "(none)",
        )

        try:
            result  = await call_llm(
                system      = _CULTURE_SYSTEM,
                messages    = [{"role": "user", "content": prompt}],
                model       = self.model,
                max_tokens  = _MAX_TOKENS,
                temperature = 0.0,
                purpose     = "company_culture_analyze",
            )
            raw     = result.text.strip()
            payload = _extract_json(raw)
            _LLMCulturePayload.model_validate(payload)   # strict schema gate
            profile = build_profile_from_payload(company_name, payload, source_hint)
            logger.info(
                "[company-culture] profiled %r: axis=%.1f category=%s pace=%s "
                "work_model=%s confidence=%s",
                company_name, profile.culture_axis, profile.culture_category,
                profile.operational_pace, profile.work_model, profile.confidence,
            )
            return profile
        except (ValidationError, ValueError, json.JSONDecodeError) as exc:
            logger.warning(
                "[company-culture] invalid LLM payload for %r (%s) — unknown profile",
                company_name, exc,
            )
            return build_sparse_profile(company_name, source_hint)
        except Exception as exc:
            logger.warning(
                "[company-culture] research failed for %r: %s (%s) — unknown profile",
                company_name, type(exc).__name__, exc,
            )
            return build_sparse_profile(company_name, source_hint)


# ── Public cached-first entry point ──────────────────────────────────────────

async def get_culture_profile(
    company_name: str,
    jd_text: str = "",
    about_text: str = "",
    source: str = "",
    apply_url: str = "",
    engine=None,
    force_refresh: bool = False,
) -> Optional[CompanyCultureProfile]:
    """
    Cached-first culture lookup — the integration point for the pipeline.

      fresh cache → returned instantly, no LLM call (most companies post
                    multiple roles; one research run serves them all)
      stale/miss  → analyze() runs, result cached (sparse "unknown" profiles
                    are NOT cached, so a later posting with richer text can
                    still upgrade the company)
      no company  → None; callers degrade gracefully
    """
    company_name = (company_name or "").strip()
    if not company_name or not _company_key(company_name):
        return None

    if not force_refresh:
        cached = load_cached_profile(company_name, engine=engine)
        if cached is not None and not is_stale(cached):
            return cached

    profile = await CompanyCultureAgent().analyze(
        company_name, jd_text, about_text=about_text,
        source=source, apply_url=apply_url,
    )
    # Only cache profiles that carry real signal — an "unknown" produced by a
    # sparse posting must not block a richer posting from re-researching.
    if profile.confidence != "low" or profile.culture_category != "unknown":
        save_cached_profile(profile, engine=engine)
    return profile
