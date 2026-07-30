"""
ResearcherAgent — bridges the gap between a dry CV and real-world market context.

For each key entity (company or project) found in the candidate's profile this
agent performs a two-step research cycle:

  Step A — Domain identification
    Search: "<entity> Israel official website" → extract business domain via
    Claude Haiku. Deliberately not tech-biased — most entities in an Israeli
    candidate's history are ordinary local businesses, not startups.

  Step B — Terminology gap analysis
    Search: "<domain> industry terminology <role>" → identify standard vocabulary
    that exists in the domain but is absent from the candidate's CV text.

Verification:
  If external evidence is found   → entity.verified = True
  If no evidence and high-impact  → entity.verified = False + clarification_request

Ground truth: an entity previously saved with source="user_provided_ground_truth"
(a human-confirmed correction — see docs on the manual-override path) is skipped
on a normal auto-extract research() run, so re-running research never silently
clobbers a verified-by-the-actual-employee record. Pass force=True to override.

Every web_search.search() call this agent makes is cached (see web_search.py) —
re-running research for an unchanged entity set costs 0 ScraperAPI credits.

Output: list[EnrichedEntity]  (also persisted to master_profile.json)

Public API
----------
ResearcherAgent().research(entities) -> list[EnrichedEntity]   (async)
extract_profile_entities()           -> list[dict]             (sync helper)
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

from backend.services.llm_client import call_llm
from backend.services.web_search import search, SearchResult
from backend.services.user_profile import USER_PROFILE, build_full_text, resolve_profile

load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=True)

logger = logging.getLogger(__name__)

_MODEL      = "claude-haiku-4-5-20251001"
_MAX_TOKENS = 1024

# ── Entity schema ─────────────────────────────────────────────────────────────

@dataclass
class ClarificationRequest:
    id:       str
    question: str
    context:  str


@dataclass
class EnrichedEntity:
    name:                  str
    entity_type:           str           # "company" | "project" | "institution"
    verified:              bool
    domain:                str           # e.g. "B2B SaaS / Live Events Technology"
    industry_keywords:     list[str]     # standard vocabulary in that domain
    cv_vocabulary_gap:     list[str]     # specific terms absent from the CV
    evidence_urls:         list[str]
    clarification_requests: list[ClarificationRequest] = field(default_factory=list)
    researched_at:         str = ""
    # Provenance. "researcher_agent" (default) = automated web+LLM pipeline.
    # "user_provided_ground_truth" = a human-confirmed correction entered
    # directly (see research()'s ground-truth skip guard, which reads this).
    source:                str = "researcher_agent"

    def as_dict(self) -> dict:
        d = asdict(self)
        # Convert nested dataclasses that asdict already handles
        return d


# ── Entity extraction from the active user's profile ─────────────────────────

# High-impact flags: if these entity names appear in the profile's achievements,
# failure to verify them triggers a clarification request
_HIGH_IMPACT_MARKERS = {"go-out", "goout", "go out"}


def extract_profile_entities(user_id: str) -> list[dict]:
    """
    Extract key entities worth researching from user_id's profile.
    Returns a list of dicts with keys: name, entity_type, is_high_impact.

    Passing a real user_id is REQUIRED for correctness — the results are
    persisted against that user and later injected into their CV prompt as
    ENTITY_INTELLIGENCE, so extracting from the legacy singleton would research
    the wrong employers and store them under the wrong account.
    """
    entities: list[dict] = []
    seen: set[str] = set()

    for exp in resolve_profile(user_id).get("experience", []):
        company = (exp.get("company") or exp.get("unit") or "").strip()
        if not company:
            continue
        key = company.lower()
        if key in seen:
            continue
        seen.add(key)
        entities.append({
            "name":           company,
            "entity_type":    "company",
            "is_high_impact": any(m in key for m in _HIGH_IMPACT_MARKERS),
        })

    # Projects / side ventures — extend this list as the profile grows
    for project_name in _extract_project_names(user_id):
        key = project_name.lower()
        if key not in seen:
            seen.add(key)
            entities.append({
                "name":           project_name,
                "entity_type":    "project",
                "is_high_impact": True,
            })

    return entities


def _extract_project_names(user_id: str) -> list[str]:
    """
    Scan user_id's profile achievements for explicitly named projects.
    Uses a simple regex heuristic on the full profile text.
    """
    import re
    seen: set[str] = set()
    projects: list[str] = []
    all_text = build_full_text(user_id)

    # Look for capitalised project names after "Project:" or "built the"
    # Require at least 2 words so we don't match single-word role titles
    for m in re.finditer(
        r"(?:Project:\s*|built the\s+)([A-Z][A-Za-z]{2,}(?:\s+[A-Z][A-Za-z]{2,})+)",
        all_text,
    ):
        name = m.group(1).strip()
        key  = name.lower()
        if key not in seen and len(name.split()) <= 4:
            seen.add(key)
            projects.append(name)

    return projects[:3]


# ── LLM synthesis helpers ─────────────────────────────────────────────────────

_DOMAIN_SYSTEM = """\
You are a business intelligence analyst. Given web search results about a company
or project, extract the business domain and up to 10 industry-standard keywords.

The candidate is based in Israel and many entities are small local businesses
(restaurants, retail, local insurance/financial agencies) — NOT tech startups.
Do not default to a technology/SaaS framing just because other entities in this
candidate's history are tech companies. A local business with a normal web
presence (its own site, a Google/Facebook business listing, a local news
mention) is exactly as "verified" as a tech company with an English-language
press writeup — judge by whether the results describe a real, currently or
formerly operating business, not by how much English-language coverage exists.

Search results may be in Hebrew. Read and use them the same as English results
— do not mark an entity unverified merely because the evidence is in Hebrew.

Name-collision guard: a result can describe a DIFFERENT company that merely
shares part of the entity's name (e.g. a search for a small local business
returning an unrelated, similarly-named tech company). Only use a result as
evidence if it plausibly matches the entity's actual nature — if every result
is clearly about something else, set "verified": false and "domain":
"Unknown domain" rather than reporting the unrelated company's domain.

Return ONLY this JSON — no prose, no fences:
{
  "domain": "<concise domain label, e.g. 'B2B SaaS / Live Events Technology'>",
  "verified": <true if the entity is clearly a real business/project, false otherwise>,
  "industry_keywords": ["<standard industry term>", ...],
  "evidence_url": "<most credible URL from the results, or empty string>"
}
"""

_GAP_SYSTEM = """\
You are a resume strategist. Given the candidate's CV vocabulary and a list of
industry-standard terms for their domain, identify the terminology gap.

Return ONLY this JSON — no prose, no fences:
{
  "cv_vocabulary_gap": [
    "<exact industry term that is absent or underused in the CV>",
    ...
  ]
}

Rules:
- Only include terms that are genuinely standard in this industry.
- Only include terms that are NOT already present in the CV text.
- Cap at 12 terms. Sort by relevance (most impactful first).
"""


# ── Agent ─────────────────────────────────────────────────────────────────────

class ResearcherAgent:
    """
    Performs active market research for each key entity in the candidate's profile
    and returns enriched data including domain, industry keywords, and vocabulary gaps.
    """

    def __init__(self, user_id: str) -> None:
        """
        user_id scopes the CV text that cv_vocabulary_gap is computed against,
        and the default entity extraction.
        """
        if not os.getenv("ANTHROPIC_API_KEY"):
            raise ValueError("ANTHROPIC_API_KEY not set")
        self.user_id  = user_id
        self._cv_text = build_full_text(self.user_id).lower()

    async def research(
        self,
        entities: Optional[list[dict]] = None,
        force: bool = False,
    ) -> list[EnrichedEntity]:
        """
        Research all provided entities (or auto-extract from this agent's
        user's profile).  Returns a list of EnrichedEntity objects.

        force=True bypasses both the web_search result cache AND the
        ground-truth skip guard below, forcing a fresh web+LLM pass for every
        entity. Default False for both auto-extract and explicit-entity_names
        calls — a caller that names entities explicitly is presumed to want
        them researched regardless (e.g. retrying just the ones that came back
        unverified), so ground-truth entities named directly ARE still skipped
        unless force=True; only the caller passing force gets them re-run.

        Ground-truth guard: entities previously saved with
        source="user_provided_ground_truth" (see master_profile_service /
        the manual-correction path) are skipped on an auto-extract run —
        research() would otherwise silently overwrite a human-verified record
        with a fresh, possibly wrong, automated one on the very next run.
        """
        if entities is None:
            entities = extract_profile_entities(self.user_id)

        if not entities:
            logger.info("[researcher] No entities to research")
            return []

        if not force:
            from backend.services.master_profile_service import get_enriched_entity
            filtered = []
            for entity in entities:
                existing = get_enriched_entity(entity["name"], self.user_id)
                if existing and existing.get("source") == "user_provided_ground_truth":
                    logger.info(
                        "[researcher] Skipping %r — has a user-provided ground-truth "
                        "record; pass force=True to override it.",
                        entity["name"],
                    )
                    continue
                filtered.append(entity)
            entities = filtered

        if not entities:
            logger.info("[researcher] No entities to research (all skipped as ground-truth)")
            return []

        logger.info("[researcher] Starting research for %d entities", len(entities))
        results: list[EnrichedEntity] = []

        for entity in entities:
            try:
                enriched = await self._research_entity(
                    name=entity["name"],
                    entity_type=entity.get("entity_type", "company"),
                    is_high_impact=entity.get("is_high_impact", False),
                    force=force,
                )
                results.append(enriched)
            except Exception as exc:
                logger.warning(
                    "[researcher] Failed to research entity %r: %s",
                    entity["name"], exc,
                )

        logger.info(
            "[researcher] Research complete: %d/%d entities processed",
            len(results), len(entities),
        )
        return results

    # ── Two-step research cycle ───────────────────────────────────────────────

    async def _research_entity(
        self,
        name: str,
        entity_type: str,
        is_high_impact: bool,
        force: bool = False,
    ) -> EnrichedEntity:
        """
        Step A: Identify domain by searching for the entity.
        Step B: Identify vocabulary gap by searching for domain terminology.
        """
        logger.info("[researcher] Step A — domain search: %r", name)

        # ── Step A: Domain identification ─────────────────────────────────────
        # Deliberately NOT "technology platform" — most entities in an Israeli
        # candidate's history are ordinary local businesses (restaurants,
        # insurance agencies, retail), and biasing every query toward tech
        # framing pulls in unrelated tech-company hits for them (observed:
        # "Restaurant River" returned an unrelated food-tech startup
        # acquisition story). "official website" is a neutral qualifier that
        # helps surface a small local business's own site or listing.
        search_query_a = f"{name} Israel official website"
        results_a = await search(search_query_a, max_results=5, force=force)

        if not results_a:
            # Fallback: broader query, still no tech-specific framing
            results_a = await search(f"{name} company Israel", max_results=5, force=force)

        domain_data = await self._synthesise_domain(name, results_a)

        verified     = domain_data.get("verified", len(results_a) > 0)
        domain       = domain_data.get("domain", "Unknown domain")
        industry_kws = domain_data.get("industry_keywords", [])
        evidence_url = domain_data.get("evidence_url", "")
        evidence_urls = [evidence_url] if evidence_url else [r.url for r in results_a[:2] if r.url]

        # ── Step B: Vocabulary gap analysis ───────────────────────────────────
        cv_vocab_gap: list[str] = []
        if domain and domain != "Unknown domain":
            logger.info("[researcher] Step B — terminology search for domain: %r", domain)
            search_query_b = f"{domain} industry terminology keywords professional"
            results_b = await search(search_query_b, max_results=5, force=force)
            cv_vocab_gap = await self._synthesise_gap(domain, industry_kws, results_b)

        # ── Verification & clarification ──────────────────────────────────────
        clarification_requests: list[ClarificationRequest] = []
        if not verified and is_high_impact:
            clarification_requests.append(ClarificationRequest(
                id=f"verify_{name.lower().replace(' ', '_').replace('-', '_')}",
                question=(
                    f"We couldn't find public information about {name}. "
                    f"Can you share the company website, a LinkedIn page, or a brief "
                    f"description of what {name} does? This helps us use the right "
                    f"industry terminology in your CV."
                ),
                context=(
                    f"External verification for {name} returned no results. "
                    f"A brief description enables accurate domain keyword injection."
                ),
            ))

        return EnrichedEntity(
            name=name,
            entity_type=entity_type,
            verified=verified,
            domain=domain,
            industry_keywords=industry_kws,
            cv_vocabulary_gap=cv_vocab_gap,
            evidence_urls=evidence_urls,
            clarification_requests=clarification_requests,
            researched_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
        )

    # ── LLM synthesis methods ─────────────────────────────────────────────────

    async def _synthesise_domain(
        self,
        entity_name: str,
        results: list[SearchResult],
    ) -> dict:
        """
        Use Claude Haiku to extract domain + keywords from search snippets.
        Returns safe defaults on any failure.
        """
        if not results:
            return {"domain": "Unknown domain", "verified": False, "industry_keywords": [], "evidence_url": ""}

        snippets = "\n".join(
            f"[{i+1}] {r.title}\n{r.snippet}\nURL: {r.url}"
            for i, r in enumerate(results)
        )
        user_msg = (
            f"Entity: {entity_name}\n\n"
            f"Web search results:\n{snippets}\n\n"
            f"Return the JSON object now."
        )

        try:
            result = await call_llm(
                system=_DOMAIN_SYSTEM,
                messages=[{"role": "user", "content": user_msg}],
                model=_MODEL,
                max_tokens=_MAX_TOKENS,
                temperature=0.0,
                purpose="researcher_synthesise_domain",
            )
            raw = _strip_fences(result.text)
            return json.loads(raw)
        except Exception as exc:
            logger.warning("[researcher] Domain synthesis failed for %r: %s", entity_name, exc)
            return {
                "domain":            "Unknown domain",
                "verified":          len(results) > 0,
                "industry_keywords": [],
                "evidence_url":      results[0].url if results else "",
            }

    async def _synthesise_gap(
        self,
        domain: str,
        industry_kws: list[str],
        results: list[SearchResult],
    ) -> list[str]:
        """
        Use Claude Haiku to identify vocabulary present in the domain but absent
        from the candidate's CV text. Returns empty list on failure.
        """
        snippets = "\n".join(
            f"[{i+1}] {r.title}\n{r.snippet}"
            for i, r in enumerate(results)
        )
        user_msg = (
            f"Domain: {domain}\n\n"
            f"Known industry keywords for this domain:\n"
            + ", ".join(industry_kws) + "\n\n"
            f"Industry terminology found in search results:\n{snippets}\n\n"
            f"Candidate CV text (lowercased excerpt, first 3000 chars):\n"
            f"{self._cv_text[:3000]}\n\n"
            f"Return the JSON object now."
        )

        try:
            result = await call_llm(
                system=_GAP_SYSTEM,
                messages=[{"role": "user", "content": user_msg}],
                model=_MODEL,
                max_tokens=_MAX_TOKENS,
                temperature=0.0,
                purpose="researcher_synthesise_gap",
            )
            raw = _strip_fences(result.text)
            payload = json.loads(raw)
            return [str(t) for t in payload.get("cv_vocabulary_gap", [])][:12]
        except Exception as exc:
            logger.warning("[researcher] Gap synthesis failed for domain %r: %s", domain, exc)
            return []


# ── Utility ───────────────────────────────────────────────────────────────────

def _strip_fences(text: str) -> str:
    """Strip markdown code fences and extract the JSON object."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()[1:]
        while lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    start = text.find("{")
    end   = text.rfind("}")
    if start != -1 and end != -1:
        return text[start : end + 1]
    return text
