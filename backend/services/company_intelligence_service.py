"""
Company Intelligence Agent — research layer that dictates CV generation strategy.

For a target company, produces a CompanyProfile capturing its CURRENT reality:
financial vibe (hypergrowth vs lean/layoffs), hiring culture/persona, and
strategic focus. The tailoring pipeline uses this to decide WHICH VerifiedFacts
to foreground and HOW to frame them — e.g. efficiency metrics for a company in
cost-cutting mode, scaling metrics for a hypergrowth startup.

ZERO-HALLUCINATION BOUNDARY
───────────────────────────
The CompanyProfile is intelligence ABOUT THE COMPANY, used exclusively for
fact SELECTION and narrative FRAMING. It is never a source of claims about
the candidate: every bullet still traces to VerifiedFact records, and the
cv_assembly_engine validation gate remains in the write path. A wrong or
stale company profile can mis-prioritise which true facts lead — it cannot
put an untrue fact on the CV.

Research strategy:
  1. Claude + the web_search server tool (web_search_20260209) — grounded in
     current news. Runs entirely server-side on Anthropic infra.
  2. If web search is unavailable (org not enabled, tool error), fall back to
     model knowledge with confidence="low" and an explicit knowledge-cutoff
     caveat recorded in the profile.

Caching (company_intel table):
  • Fresh hit  (< 30 days)  → returned instantly, no API call.
  • Stale hit  (≥ 30 days)  → returned instantly + background refresh task
                              so the NEXT tailoring run sees recent events.
  • Miss                    → researched synchronously, then cached.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from pydantic import BaseModel, Field

from backend.services.llm_client import call_llm

logger = logging.getLogger(__name__)

_RESEARCH_MODEL   = "claude-opus-4-8"
_MAX_TOKENS       = 2000
_STALE_AFTER      = timedelta(days=30)
_MAX_CONTINUATIONS = 3     # pause_turn safety ceiling for the server-tool loop

FINANCIAL_VIBES = ("hypergrowth", "growth", "stable", "lean", "turnaround", "unknown")


class CompanyProfile(BaseModel):
    company_key:     str
    display_name:    str
    financial_vibe:  str = "unknown"          # one of FINANCIAL_VIBES
    hiring_persona:  str = ""                 # culture + what their recruiters reward
    strategic_focus: list[str] = Field(default_factory=list)
    recent_signals:  list[str] = Field(default_factory=list)  # layoffs, acquisitions, launches
    confidence:      str = "low"              # low | medium | high
    source:          str = "model_knowledge"  # web_search | model_knowledge
    researched_at:   str = ""


def _company_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── Cache layer ────────────────────────────────────────────────────────────────

def _load_cached(key: str) -> Optional[CompanyProfile]:
    from backend.repositories import company_intel_repository

    row = company_intel_repository.get(key)
    if row is None:
        return None
    try:
        return CompanyProfile(**json.loads(row.profile_json))
    except Exception as exc:
        logger.warning("[company-intel] corrupt cache row for %s (%s) — treating as miss", key, exc)
        return None


def _save_cached(profile: CompanyProfile) -> None:
    from backend.repositories import company_intel_repository

    company_intel_repository.upsert(
        profile.company_key, profile.display_name,
        profile.model_dump_json(), profile.researched_at,
    )


def _is_stale(profile: CompanyProfile) -> bool:
    try:
        ts = datetime.fromisoformat(profile.researched_at)
    except ValueError:
        return True
    return _now() - ts >= _STALE_AFTER


# ── Research agent ─────────────────────────────────────────────────────────────

_RESEARCH_SYSTEM = """\
You are a company-intelligence researcher for a CV tailoring platform. Given a
company name, produce a compact strategic profile of the company AS IT IS TODAY.

Research priorities (most decision-relevant first):
1. Financial trajectory: funding, layoffs, hiring freezes, profitability push,
   expansion, acquisition activity — anything from the last 12 months.
2. Hiring culture / persona: what this company's recruiters visibly reward
   (scrappy generalists vs deep specialists, mission language, pace).
3. Strategic focus: the 2-4 bets the company is publicly making right now.

HONESTY RULES:
• Only state what your sources (or, without search, your training knowledge)
  actually support. Where the picture is unclear, say "unknown" — a wrong
  vibe misleads a job seeker more than no vibe.
• recent_signals must be concrete, dated-where-possible events, not vibes.
• Set confidence to: high (multiple recent sources agree), medium (some recent
  signal), low (training knowledge only or conflicting signals).

Respond with ONLY a JSON object (no markdown fences, no prose):
{
  "financial_vibe": "hypergrowth|growth|stable|lean|turnaround|unknown",
  "hiring_persona": "<1-2 sentences>",
  "strategic_focus": ["<focus 1>", "..."],
  "recent_signals": ["<concrete recent event>", "..."],
  "confidence": "low|medium|high"
}"""


def _extract_json(raw: str) -> dict:
    text = re.sub(r"```(?:json)?", "", raw).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        return json.loads(text[start:end + 1])
    raise ValueError(f"No JSON object in research response: {raw[:200]}")


def _profile_from_dict(company: str, data: dict, source: str) -> CompanyProfile:
    vibe = str(data.get("financial_vibe", "unknown")).lower().strip()
    if vibe not in FINANCIAL_VIBES:
        vibe = "unknown"
    conf = str(data.get("confidence", "low")).lower().strip()
    if conf not in ("low", "medium", "high"):
        conf = "low"
    return CompanyProfile(
        company_key     = _company_key(company),
        display_name    = company,
        financial_vibe  = vibe,
        hiring_persona  = str(data.get("hiring_persona", ""))[:500],
        strategic_focus = [str(x)[:200] for x in data.get("strategic_focus", [])][:6],
        recent_signals  = [str(x)[:300] for x in data.get("recent_signals", [])][:8],
        confidence      = conf,
        source          = source,
        researched_at   = _now().isoformat(),
    )


async def _research_company(company: str) -> Optional[CompanyProfile]:
    """
    Run the research agent. Web-search grounded when available; model-knowledge
    fallback otherwise. Returns None only on total failure (nothing cached).
    """
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        logger.warning("[company-intel] ANTHROPIC_API_KEY not set — skipping research")
        return None

    user_msg = f"Company to research: {company}"

    # ── Attempt 1: web-search-grounded ────────────────────────────────────────
    try:
        messages: list[dict] = [{"role": "user", "content": user_msg}]
        response = None
        for _ in range(_MAX_CONTINUATIONS + 1):
            result_llm = await call_llm(
                system     = _RESEARCH_SYSTEM,
                messages   = messages,
                model      = _RESEARCH_MODEL,
                max_tokens = _MAX_TOKENS,
                tools      = [{"type": "web_search_20260209", "name": "web_search", "max_uses": 4}],
                purpose    = "company_intel_research_web_search",
            )
            response = result_llm.raw
            if response.stop_reason != "pause_turn":
                break
            # Server-side tool loop paused — re-send to resume where it left off.
            messages = [
                {"role": "user", "content": user_msg},
                {"role": "assistant", "content": response.content},
            ]

        text = "".join(b.text for b in (response.content if response else []) if b.type == "text")
        profile = _profile_from_dict(company, _extract_json(text), source="web_search")
        logger.info(
            "[company-intel] researched %r via web_search: vibe=%s confidence=%s signals=%d",
            company, profile.financial_vibe, profile.confidence, len(profile.recent_signals),
        )
        return profile
    except Exception as exc:
        logger.warning("[company-intel] web-search research failed for %r (%s) — model-knowledge fallback", company, exc)

    # ── Attempt 2: model knowledge only, honest low confidence ────────────────
    try:
        result_llm = await call_llm(
            system     = _RESEARCH_SYSTEM,
            messages   = [{
                "role": "user",
                "content": (
                    f"{user_msg}\n\n(Web search unavailable — answer from training "
                    f"knowledge only, set confidence to 'low', and prefer 'unknown' "
                    f"over guessing recent events.)"
                ),
            }],
            model      = _RESEARCH_MODEL,
            max_tokens = _MAX_TOKENS,
            purpose    = "company_intel_research_fallback",
        )
        text = "".join(b.text for b in result_llm.raw.content if b.type == "text")
        data = _extract_json(text)
        data["confidence"] = "low"   # enforce regardless of what the model said
        profile = _profile_from_dict(company, data, source="model_knowledge")
        logger.info("[company-intel] researched %r from model knowledge (low confidence)", company)
        return profile
    except Exception as exc:
        logger.warning("[company-intel] research fully failed for %r: %s", company, exc)
        return None


# ── Public API ─────────────────────────────────────────────────────────────────

_inflight_refreshes: set[str] = set()   # de-dupes concurrent background refreshes


async def _background_refresh(company: str, key: str) -> None:
    try:
        fresh = await _research_company(company)
        if fresh:
            _save_cached(fresh)
            logger.info("[company-intel] background refresh completed for %r", company)
    except Exception as exc:
        logger.warning("[company-intel] background refresh failed for %r: %s", company, exc)
    finally:
        _inflight_refreshes.discard(key)


async def get_company_profile(company: str) -> Optional[CompanyProfile]:
    """
    Cached-first CompanyProfile lookup.

      fresh cache  → instant return
      stale cache  → instant return of the stale profile + fire-and-forget
                     background refresh (next caller gets current news)
      miss         → synchronous research, cached on success
      failure      → None; callers MUST degrade gracefully (tailor without
                     company intelligence rather than blocking or fabricating)
    """
    company = (company or "").strip()
    if not company:
        return None
    key = _company_key(company)
    if not key:
        return None

    cached = _load_cached(key)
    if cached is not None:
        if _is_stale(cached) and key not in _inflight_refreshes:
            _inflight_refreshes.add(key)
            asyncio.create_task(_background_refresh(company, key))
            logger.info("[company-intel] serving stale profile for %r; refresh scheduled", company)
        return cached

    profile = await _research_company(company)
    if profile:
        _save_cached(profile)
    return profile


def format_for_prompt(profile: CompanyProfile) -> str:
    """Render the profile as a compact prompt block for the tailoring LLM."""
    lines = [
        f"Company: {profile.display_name}",
        f"Financial vibe: {profile.financial_vibe} (confidence: {profile.confidence}, source: {profile.source})",
    ]
    if profile.hiring_persona:
        lines.append(f"Hiring persona: {profile.hiring_persona}")
    if profile.strategic_focus:
        lines.append("Strategic focus: " + "; ".join(profile.strategic_focus))
    if profile.recent_signals:
        lines.append("Recent signals:")
        lines.extend(f"  • {s}" for s in profile.recent_signals)
    if profile.source == "model_knowledge":
        lines.append("(Training-knowledge only — may miss recent events. Weight accordingly.)")
    return "\n".join(lines)
