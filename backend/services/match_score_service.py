"""
Match Score Service — Three-Component Composite Scorer
======================================================

Architecture
------------
Scoring is split into two phases that map directly to the pipeline stages:

  Phase A  compute_local_proxy_score()          ← called in s1 (Scraper)
  ─────────────────────────────────────────────────────────────────────
  Pure Python, < 1 ms.  Evaluates job title keyword alignment and
  seniority fit against the candidate's level.  No network calls.
  Returns a 0-100 float that is stored immediately when a job is
  saved so the UI shows something useful before s2 runs.

  Phase B  compute_full_match_score_async()      ← called in s2 (Sourcing Specialist)
  ─────────────────────────────────────────────────────────────────────
  Combines Phase A with two LLM sub-scores via a single claude-haiku call
  (temperature=0.0 for determinism).  Capability-based weighting (rebalanced
  to favour semantic/contextual fit over rigid keyword matching):

    30%  Keyword Matching Score   (Phase A local proxy: title + seniority,
                                    now alias/synonym-aware — see
                                    _CAPABILITY_ALIASES)
    70%  LLM Semantic Capability Score, itself an internal split of:
           50/70 of the bucket → semantic_score   (domain, transferable
                                                     execution, growth trajectory)
           20/70 of the bucket → management_score (tooling, methodology,
                                                     stakeholder management)
         i.e. the original 50:20 emphasis between the two LLM dimensions
         is preserved, just rescaled to sum to the new 70% allocation.

  Final score = 0.30 × local + 0.70 × (5/7 × semantic + 2/7 × management)

  Also runs _phase1() for the rich keyword/skills breakdown used by the
  tag row in the UI (matched_keywords, missing_skills, etc.).

Alias / Synonym Resolution (Phase 1 capability matching)
----------------------------------------------------------
  Before docking points for a "missing" keyword or skill in _phase1(), the
  pure-Python matcher cross-references _CAPABILITY_ALIASES so that, e.g.,
  "Project Manager" credits a CV that says "Customer Success Team Leader",
  "user stories" credits "PRDs" / "specs", and "B2C clients" credits
  "B2B2C" / "end-users".  This only affects the deterministic Phase 1
  component — the LLM semantic layer already evaluates capability
  transferability directly against full CV text and is unaffected.

Backwards Compatibility
-----------------------
compute_match_score_async(cv_data, jd_text, run_llm_validation, skill_proficiencies)
  — preserved signature, used by resumes.py (10+ call sites) and jobs.py.
  When run_llm_validation=True → full 3-component LLM composite.
  When run_llm_validation=False → Phase A + Phase 1 pure Python only (fast).

compute_match_score(cv_data, jd_text, …)
  — synchronous, Phase 1 only (no event loop available).
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
from typing import Any, Optional

from backend.utilities.ai_scrubber import scrub_dict
from dataclasses import dataclass, field
from typing import List, Optional

from pydantic import BaseModel, Field, ValidationError

from backend.agents.jd_parser import JDParserAgent
from backend.services.llm_client import call_llm, LLMCallError

logger = logging.getLogger(__name__)

# ── Candidate anchor ──────────────────────────────────────────────────────────
# The candidate's current seniority band — used as the reference point for all
# seniority alignment calculations.  Update when the candidate's target level
# changes (e.g., post-promotion pivot to senior IC or people-manager track).
_CANDIDATE_SENIORITY_LEVEL = 4   # "manager" = mid-to-senior PM, see _SENIORITY_BANDS

# ── Title keyword tiers ───────────────────────────────────────────────────────
# Controls the title alignment component of compute_local_proxy_score().
# Tier 1 = direct role match (90 pts), Tier 2 = abbreviation/partial (72),
# Tier 3 = adjacent CS/AM domain (68), "product" alone (55), no signal (28).

_TITLE_TIER_1: tuple[str, ...] = (
    "product manager", "product owner", "group product manager",
    "head of product", "vp of product", "vp product",
    "director of product", "product lead", "product operations manager",
    "product operations", "product management",
)
_TITLE_TIER_2: tuple[str, ...] = (
    " pm ", "pm,", "(pm)", "pm/", "pm-", " pm\n",
    "product strategy", "product growth", "digital product",
)
_TITLE_TIER_3: tuple[str, ...] = (
    "customer success", "csm", "account manager", "key account",
    "partnership manager", "client success", "customer experience manager",
)

# ── Seniority bands ───────────────────────────────────────────────────────────
_SENIORITY_BANDS: dict[str, int] = {
    "intern":      1,
    "junior":      2,
    "associate":   2,
    "coordinator": 2,
    "specialist":  3,
    "mid":         3,
    "manager":     4,
    "senior":      4,
    "lead":        5,
    "principal":   6,
    "staff":       6,
    "head":        7,
    "director":    7,
    "vp":          8,
    "vice president": 8,
}
_SENIORITY_ALIGNMENT: dict[int, float] = {0: 1.0, 1: 0.7, 2: 0.4}
_SENIORITY_MISMATCH_FACTOR = 0.1

# ── English stopwords ─────────────────────────────────────────────────────────
_STOPWORDS = frozenset({
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "as", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "need", "must", "ought",
    "we", "you", "they", "he", "she", "it", "i", "our", "your", "their",
    "this", "that", "these", "those", "not", "no", "nor", "so", "yet",
    "both", "either", "neither", "from", "into", "through", "during",
    "including", "until", "against", "among", "throughout", "toward",
    "about", "above", "after", "before", "between", "out", "off", "over",
    "under", "again", "then", "once", "here", "there", "when", "where",
    "why", "how", "all", "each", "every", "few", "more", "most", "other",
    "than", "too", "very", "just", "only", "also", "well", "such",
    "if", "while", "although", "because", "since", "unless",
    "what", "who", "within", "across", "per", "up", "down",
})

# ── AI meta-phrase guard ──────────────────────────────────────────────────────
_AI_META_PREFIXES: tuple[str, ...] = (
    "no documented", "not mentioned", "no evidence", "no direct",
    "lacks", "limited", "unclear", "gap", "missing", "absent",
    "no experience", "no background", "no formal",
    "not demonstrated", "not stated", "not specified",
    "candidate does", "ron does", "ron has no", "ron lacks",
)

# ── Noise words ───────────────────────────────────────────────────────────────
_NOISE_WORDS = frozenset({
    "culture", "confidence", "passion", "passionate", "driven", "drive",
    "impact", "impactful", "ownership", "mindset", "attitude", "mission",
    "vision", "values", "diversity", "inclusion", "inclusive",
    "proactive", "innovative", "innovation", "dynamic", "startup",
    "excellence", "ideal", "thrive", "excited", "care",
    "role", "position", "candidate", "company", "organization", "team",
    "teams", "department", "group", "unit", "level", "track", "band",
    "opportunity", "hire", "hiring", "join", "joining", "looking",
    "seeking", "required", "preferred", "plus", "nice",
    "remote", "hybrid", "onsite", "fulltime", "office",
    "year", "years", "month", "months", "week", "weeks", "day", "days",
    "quarterly", "monthly", "weekly", "annual", "annually",
    # ── Geographic locations (global + Israeli cities) ────────────────────────
    "aviv", "york", "london", "berlin", "israel", "europe",
    "global", "local", "region", "area", "location",
    "herzliya", "raanana", "netanya", "petah", "tikva", "rehovot",
    "haifa", "beersheba", "rishon", "lezion", "ashdod", "ashkelon",
    "holon", "bnei", "brak", "modiin", "kfar", "saba", "hod", "hasharon",
    "givatayim", "ramat", "hasharon", "rosh", "haayin", "yehud",
    "jerusalem", "galilee", "negev", "sharon", "center", "south", "north",
    "dubai", "singapore", "amsterdam", "paris", "toronto", "boston",
    "seattle", "austin", "denver", "chicago", "angeles", "francisco",
    # ── English number words (caught by regex but not t.isnumeric()) ──────────
    "zero", "one", "two", "three", "four", "five", "six", "seven",
    "eight", "nine", "ten", "eleven", "twelve", "hundred", "thousand",
    "first", "second", "third", "fourth", "fifth",
    # ── Generic adjectives / adverbs that slip past the main stopword list ────
    "strong", "excellent", "good", "great", "best", "top",
    "high", "low", "fast", "quick", "new", "current", "full", "part",
    "help", "ensure", "deliver", "provide", "support", "work", "working",
    "make", "build", "develop", "manage", "create", "use", "using",
    "maintain", "improve", "increase", "reduce", "achieve", "meet",
    "process", "processes", "solution", "solutions", "system", "systems",
    "platform", "tool", "tools", "report", "reporting", "data",
    "communication", "language", "written", "verbal",
    "experience", "ability", "skills", "skill", "knowledge", "understanding",
    "customer", "manager", "management", "specialist", "analyst",
    "associate", "coordinator", "executive", "consultant",
})

# ── Skill-signal patterns ─────────────────────────────────────────────────────
_SKILL_SIGNAL_PATTERNS = [
    r"experience\s+(?:with|in|using)\s+([A-Za-z0-9\+\#\.\- ]{2,30})",
    r"proficien(?:t|cy)\s+(?:with|in)\s+([A-Za-z0-9\+\#\.\- ]{2,30})",
    r"knowledge\s+of\s+([A-Za-z0-9\+\#\.\- ]{2,30})",
    r"familiarity\s+with\s+([A-Za-z0-9\+\#\.\- ]{2,30})",
    r"expertise\s+in\s+([A-Za-z0-9\+\#\.\- ]{2,30})",
    r"skilled\s+in\s+([A-Za-z0-9\+\#\.\- ]{2,30})",
    r"(?:must|should)\s+(?:have|know)\s+([A-Za-z0-9\+\#\.\- ]{2,30})",
]

# ── Domain title signals for thin-proxy differentiation ──────────────────────
_DOMAIN_TITLE_SIGNALS: tuple[str, ...] = (
    "product", "manager", "owner", "senior", "lead", "head",
    "customer success", "csm", "account", "vp", "director",
    "group", "principal",
)

# ── Capability alias / synonym dictionary (Phase 1) ──────────────────────────
#
# PURPOSE
#   The keyword/skill matching in _phase1() does literal substring checks
#   against the candidate's experience text. A JD that says "Project Manager"
#   will report that as MISSING for a candidate whose CV says "Customer
#   Success Team Leader" — even though the underlying capability (owning
#   roadmaps, running cross-functional execution, managing stakeholders) is
#   identical. This dictionary closes that gap WITHOUT touching the LLM
#   semantic layer — it is a pure-Python, deterministic equivalence table
#   applied before a term is docked as "missing".
#
# STRUCTURE
#   Each entry is a canonical concept → frozenset of surface-form synonyms
#   (including the canonical term itself). Matching is bidirectional: if the
#   JD term belongs to a group, ANY surface form of that group appearing in
#   the candidate's experience text counts as a match.
#
# SCOPE — THIS DOES NOT REPLACE THE LLM LAYER
#   This only affects Phase 1 (_phase1) keyword_overlap / skills_alignment
#   scoring (0-40 / 0-35 pts) — the pure-Python, deterministic component.
#   It has no effect on semantic_score / management_score, which are scored
#   by the LLM directly against the full CV text and are already capability-
#   aware. This keeps the Exploration Freedom and Company Legacy principles
#   (LLM-prompt level) completely untouched.
_CAPABILITY_ALIASES: tuple[frozenset[str], ...] = (
    frozenset({
        "project manager", "program manager", "operations manager",
        "product owner", "product manager", "customer success team leader",
        "customer success manager", "delivery manager", "scrum master",
    }),
    frozenset({
        "user stories", "user story", "prds", "prd",
        "product requirements", "product requirement", "specs", "spec",
        "specifications", "requirements documents",
    }),
    frozenset({
        "b2c clients", "b2c", "b2b2c", "end-users", "end users",
        "end-user", "end user", "consumer-facing",
    }),
)

# Reverse index: surface form → the full alias group it belongs to.
# Built once at import time; O(1) lookup at scoring time.
_ALIAS_LOOKUP: dict[str, frozenset[str]] = {
    surface: group
    for group in _CAPABILITY_ALIASES
    for surface in group
}


def _term_or_alias_in_text(term: str, text: str) -> bool:
    """
    Return True if `term` — or any of its registered synonyms — appears in
    `text`.  Falls back to a plain substring check when the term has no
    registered alias group (the original behaviour, unchanged).
    """
    term_lower = term.lower().strip()
    if term_lower in text:
        return True
    group = _ALIAS_LOOKUP.get(term_lower)
    if not group:
        return False
    return any(alias in text for alias in group if alias != term_lower)


# ── Proficiency requirement signals ──────────────────────────────────────────
_REQUIRED_SIGNALS: frozenset[str] = frozenset({
    "required", "must have", "must-have", "you must", "expert",
    "professional experience", "strong", "minimum", "years of experience",
    "extensive", "demonstrated", "proven",
})
_PREFERRED_SIGNALS: frozenset[str] = frozenset({
    "nice to have", "nice-to-have", "familiarity", "knowledge of",
    "preferred", "bonus", "ideally", "helpful", "beneficial", "plus",
    "exposure to", "basic understanding", "awareness of",
})


# ── Result dataclasses ────────────────────────────────────────────────────────

@dataclass
class MatchScoreResult:
    """
    Composite match score with full component breakdown.

    Unified weights (when LLM + ATS engine are both available):
      llm   = 0.30 × local_score (Keyword Matching Score)
            + 0.70 × ( 5/7 × semantic_score + 2/7 × management_score )
              \\__________________________________________________/
                       "LLM Semantic Capability Score" bucket
      total = 0.60 × llm + 0.40 × ats_score        (engine base_score)
      total = min(total, 40.0)                     when knockout_failed

    When the ATS engine is unavailable (ats_score=None): total = llm.
    See finalize_composite() — the only place this arithmetic may live.

    The keyword_overlap / skills_alignment / seniority_alignment sub-scores
    come from _phase1() and power the tag row in the UI regardless of whether
    the LLM ran.  _phase1() keyword/skill matching is alias-aware — see
    _CAPABILITY_ALIASES — so synonymous capabilities (e.g. "Customer Success
    Team Leader" ≈ "Project Manager") are not penalised as missing.
    """
    total:               float           # 0-100, 1 decimal
    keyword_overlap:     float           # 0-40  (Phase 1 component)
    skills_alignment:    float           # 0-35  (Phase 1 component)
    seniority_alignment: float           # 0-25  (Phase 1 component)
    matched_keywords:    list[str]       = field(default_factory=list)
    missing_keywords:    list[str]       = field(default_factory=list)
    matched_skills:      list[str]       = field(default_factory=list)
    missing_skills:      list[str]       = field(default_factory=list)
    suggestions:         list[str]       = field(default_factory=list)
    llm_validated:       bool            = False
    proficiency_notes:   list[str]       = field(default_factory=list)
    # ── Composite sub-scores (0-100 each) ─────────────────────────────────────
    local_score:         float           = 0.0   # 30% — Keyword Matching Score (alias-aware)
    semantic_score:      float           = 0.0   # within the 70% LLM bucket (5/7 share)
    management_score:    float           = 0.0   # within the 70% LLM bucket (2/7 share)
    # ── LLM-generated fit brief + conceptual gap list ─────────────────────────
    why_ron:                       Optional[str]   = None  # populated by _llm_dual_score
    missing_critical_capabilities: list[str]        = field(default_factory=list)
    # high-level conceptual capability gaps from the LLM — NOT a low-level
    # missing-word list (that's missing_keywords / missing_skills from Phase 1).
    # ── ATS Match Engine integration (unified scoring) ────────────────────────
    # ats_score is the engine's PRE-knockout composite (base_score); the
    # knockout penalty is applied exactly once, in finalize_composite, as a
    # hard cap on the unified total. None ⇒ engine unavailable for this run
    # (thin JD, entity fetch failure) and total is the pure LLM composite.
    ats_score:            Optional[float] = None   # engine base_score, 0-100
    ats_competency_score: Optional[float] = None   # Layer-1 coverage vs Confidence Matrix
    knockout_failed:      bool            = False  # Layer-0 hard-constraint conflict
    knockout_reasons:     list[str]       = field(default_factory=list)
    ats_gaps:             list[str]       = field(default_factory=list)  # unmet must-haves
    # ── Dynamic Matching Score: culture-fit dimension (JOB-20) ────────────────
    # None across all four fields ⇒ no culture signal for this job (unknown
    # profile, no user preference, thin JD, or fetch failure) and the
    # composite is exactly the pre-culture formula.
    culture_alignment:    Optional[float] = None   # 0-100 preference alignment, 1 dp
    culture_delta:        Optional[float] = None   # applied composite adjustment, ±5.0
    culture_category:     Optional[str]   = None   # startup|scaleup|corporate|agency
    culture_note:         Optional[str]   = None   # specific UI explanation
    # ── Bullet-level skills-gap mapping (CVParser/LiveEditor integration) ─────
    # Computed by _map_bullet_matches() inside _phase1() — always populated,
    # LLM-independent, no cap on length (Principle: no truncation). Addressed
    # by (experience_index, bullet_index), NOT a frontend ParsedBullet.id:
    # that id is a content hash that exists only in the frontend's
    # web_dashboard/src/lib/cv.ts/cvParser.ts and never crosses the wire (the
    # CvData JSON this service consumes carries bullets as plain strings).
    # The frontend resolves position -> stable id via
    # cv.experience[experience_index].bullets[bullet_index].id when it wants
    # to key Ariel's per-bullet analysis off a persistent id.
    bullet_matches:       list[dict]      = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "total":               self.total,
            "keyword_overlap":     self.keyword_overlap,
            "skills_alignment":    self.skills_alignment,
            "seniority_alignment": self.seniority_alignment,
            "matched_keywords":    self.matched_keywords,
            "missing_keywords":    self.missing_keywords,
            "matched_skills":      self.matched_skills,
            "missing_skills":      self.missing_skills,
            "suggestions":         self.suggestions,
            "llm_validated":       self.llm_validated,
            "proficiency_notes":   self.proficiency_notes,
            "local_score":         self.local_score,
            "semantic_score":      self.semantic_score,
            "management_score":    self.management_score,
            "why_ron":             self.why_ron,
            "missing_critical_capabilities": self.missing_critical_capabilities,
            "ats_score":            self.ats_score,
            "ats_competency_score": self.ats_competency_score,
            "knockout_failed":      self.knockout_failed,
            "knockout_reasons":     self.knockout_reasons,
            "ats_gaps":             self.ats_gaps,
            "culture_alignment":    self.culture_alignment,
            "culture_delta":        self.culture_delta,
            "culture_category":     self.culture_category,
            "culture_note":         self.culture_note,
            "bullet_matches":       self.bullet_matches,
        }


# ── Internal helpers ──────────────────────────────────────────────────────────

def _cv_to_text(cv_data: dict) -> str:
    parts: list[str] = [
        cv_data.get("title", ""),
        cv_data.get("summary", ""),
        cv_data.get("volunteering", ""),
    ]
    for exp in cv_data.get("experience", []):
        parts += [exp.get("role", ""), exp.get("company", "")]
        parts += (exp.get("bullets") or [])
    for edu in cv_data.get("education", []):
        parts += [edu.get("degree", ""), edu.get("honors", ""), edu.get("coursework", "")]
    for cat in (cv_data.get("skills") or {}).get("categories", []):
        parts.append(cat.get("label", ""))
        parts += cat.get("items", [])
    for lang in cv_data.get("languages", []):
        parts.append(lang.get("language", ""))
    return " ".join(p for p in parts if p).lower()


def _cv_experience_text(cv_data: dict) -> str:
    parts: list[str] = []
    for exp in cv_data.get("experience", []):
        parts.append(exp.get("role", ""))
        parts.append(exp.get("company", ""))
        parts += (exp.get("bullets") or [])
    return " ".join(p for p in parts if p).lower()


def _cv_declarative_text(cv_data: dict) -> str:
    parts: list[str] = [cv_data.get("title", ""), cv_data.get("summary", "")]
    for cat in (cv_data.get("skills") or {}).get("categories", []):
        parts.append(cat.get("label", ""))
        parts += cat.get("items", [])
    return " ".join(p for p in parts if p).lower()


def _is_experience_backed(term: str, exp_text: str) -> bool:
    if _term_or_alias_in_text(term, exp_text):
        return True
    tokens = [t for t in term.split() if len(t) >= 4]
    return bool(tokens) and any(tok in exp_text for tok in tokens)


def _tokenize(text: str) -> set[str]:
    words = re.findall(r"[A-Za-z][A-Za-z0-9\+\#]{1,24}", text)
    result: set[str] = set()
    for w in words:
        lower = w.lower()
        if lower not in _STOPWORDS:
            result.add(lower)
        if len(w) >= 2 and w.isupper():
            result.add(lower)
    return result


def _extract_company_tokens(jd_text: str) -> set[str]:
    tokens: set[str] = set()
    head = jd_text[:150]
    match = re.search(r"\bat\s+(\S+(?:\s+\S+)?)", head, re.IGNORECASE)
    if match:
        for word in match.group(1).split()[:2]:
            word = re.split(r"[.!?,;]", word)[0]
            clean = re.sub(r"[^a-z0-9]", "", word.lower())
            if clean and len(clean) >= 2:
                tokens.add(clean)
    return tokens


def _is_ai_meta(phrase: str) -> bool:
    p = phrase.lower().strip()
    return any(p.startswith(prefix) for prefix in _AI_META_PREFIXES)


def _clean_phrase(raw: str) -> str:
    phrase = re.sub(r"\(.*?\)", "", raw)
    phrase = phrase.strip().lower().rstrip(".,;:()")
    if _is_ai_meta(phrase):
        return ""
    phrase = re.split(r"\.\s+[a-z]", phrase)[0]
    words = phrase.split()
    while words and (words[-1] in _STOPWORDS or words[-1] in _NOISE_WORDS):
        words.pop()
    return " ".join(words[:3]).strip()


def _extract_jd_skills(jd_text: str) -> list[str]:
    skills: list[str] = []
    seen: set[str] = set()
    lower = jd_text.lower()

    def _add(raw: str) -> None:
        phrase = _clean_phrase(raw)
        if phrase and phrase not in seen and len(phrase) >= 2:
            skills.append(phrase)
            seen.add(phrase)

    for pattern in _SKILL_SIGNAL_PATTERNS:
        for m in re.finditer(pattern, lower):
            _add(m.group(1))

    req_match = re.search(r"Required:\s*([^.!?\n]+)", jd_text, re.IGNORECASE)
    if req_match:
        for chunk in re.split(r"[,;•]", req_match.group(1)):
            _add(chunk)

    return skills


def _extract_jd_keywords(jd_text: str) -> set[str]:
    company_tokens = _extract_company_tokens(jd_text)
    combined_noise = _NOISE_WORDS | _STOPWORDS | company_tokens
    keywords: set[str] = set()

    def _is_clean(token: str) -> bool:
        t = token.lower().strip()
        return (
            len(t) >= 2
            and not t.isnumeric()
            and t not in combined_noise
            and not _is_ai_meta(t)
        )

    for m in re.finditer(r"\b[A-Z][A-Z0-9]{1,9}\b", jd_text):
        token = m.group(0).lower()
        if _is_clean(token):
            keywords.add(token)

    req_match = re.search(r"Required:\s*([^.!?\n]+)", jd_text, re.IGNORECASE)
    if req_match:
        for chunk in re.split(r"[,;•]", req_match.group(1)):
            phrase = _clean_phrase(chunk)
            if phrase and _is_clean(phrase.split()[0]):
                keywords.add(phrase)

    for skill in _extract_jd_skills(jd_text):
        words = skill.lower().split()
        clean_words: list[str] = []
        for w in words:
            if w in combined_noise or w in _STOPWORDS or "." in w:
                break
            clean_words.append(w)
        phrase = " ".join(clean_words[:3]).strip()
        if phrase and _is_clean(phrase.split()[0]):
            keywords.add(phrase)

    words = re.findall(r"\b[a-z][a-z0-9]{3,24}\b", jd_text.lower())
    freq: dict[str, int] = {}
    for w in words:
        if _is_clean(w):
            freq[w] = freq.get(w, 0) + 1
    for w, count in freq.items():
        if count >= 3:
            keywords.add(w)

    return keywords


def _extract_cv_skills(cv_data: dict) -> list[str]:
    skills: list[str] = []
    for cat in (cv_data.get("skills") or {}).get("categories", []):
        for item in cat.get("items", []):
            if item:
                skills.append(item.lower().strip())
    return skills


def _detect_seniority(text: str) -> int:
    lower = text.lower()
    for keyword, level in sorted(_SENIORITY_BANDS.items(), key=lambda x: -x[1]):
        if keyword in lower:
            return level
    return 3


def _detect_jd_requirement_level(keyword: str, jd_text: str) -> str:
    lower_jd = jd_text.lower()
    kw_lower  = keyword.lower()
    required_hits = preferred_hits = 0
    start = 0
    while True:
        pos = lower_jd.find(kw_lower, start)
        if pos == -1:
            break
        window = lower_jd[max(0, pos - 150): pos + 80]
        for sig in _REQUIRED_SIGNALS:
            if sig in window:
                required_hits += 1
        for sig in _PREFERRED_SIGNALS:
            if sig in window:
                preferred_hits += 1
        start = pos + 1
    return "preferred" if preferred_hits > required_hits else "required"


def _proficiency_weight(user_level: str, jd_level: str) -> tuple[float, str]:
    if user_level in ("professional", "unknown", ""):
        return 1.0, ""
    if user_level == "academic":
        if jd_level == "preferred":
            return 0.9, "Academic (meets familiarity req.)"
        return 0.4, "Academic vs. Professional req."
    if user_level == "none":
        if jd_level == "preferred":
            return 0.3, "No exp. (preferred only)"
        return 0.0, "No exp. (required)"
    return 1.0, ""


def _resolve_proficiency(skill: str, proficiencies: dict[str, str]) -> tuple[str, str]:
    if not proficiencies:
        return "", ""
    if skill in proficiencies:
        return proficiencies[skill], skill
    skill_words = skill.lower().split()
    for tok in skill_words:
        if tok in proficiencies:
            return proficiencies[tok], tok
    for stored_skill, level in proficiencies.items():
        stored_words = set(stored_skill.lower().split())
        if stored_words & set(skill_words):
            overlap = stored_words & set(skill_words)
            return level, next(iter(overlap))
    return "", ""


# ── Confidence-Matrix skill scorer ───────────────────────────────────────────
#
# Replaces the binary matched/missing check with a graduated, confidence-
# weighted alternative when the Active Confidence Matrix is populated.
#
# Feature-flag pattern: if engine or user_id are None the function returns
# (None, None, None) and _phase1() falls back to the original binary logic.
# This keeps the scoring pipeline stable during the rollout period.

def _confidence_weighted_skill_score(
    jd_skills: list[str],
    engine,
    user_id: str | None,
    max_points: float = 35.0,
) -> tuple[float | None, list[str] | None, list[str] | None]:
    """
    Score the skills_alignment component using confidence scores from
    profile_entities instead of a binary matched/missing check.

    Algorithm
    ---------
    For each JD skill:
      1. Look up the entity in profile_entities by normalized_name.
         If not found, try a prefix fuzzy-match (first token of the skill name).
      2. credit = confidence_score / 100   (0.0–1.0)
         Missing entity → credit = 0.0
      3. score = (Σ credit / len(jd_skills)) × max_points

    The display labels include the confidence percentage so the UI can show
    "sprint prioritization (74%)" rather than a bare boolean match.

    Parameters
    ----------
    jd_skills : list[str]
        Skill phrases extracted from the JD by _extract_jd_skills().
    engine : sqlalchemy.engine.Engine | None
        The shared ENGINE from db.py.  None → returns (None, None, None).
    user_id : str | None
        Owning user.  None → returns (None, None, None).
    max_points : float
        Upper bound of the component (mirrors the binary path's 35 pts).

    Returns
    -------
    (score, matched_labels, missing_labels) — or (None, None, None) when
    the Confidence Matrix is unavailable (feature flag off / no DB).
    """
    if not engine or not user_id or not jd_skills:
        return None, None, None

    try:
        from sqlalchemy import text as _text
        matched: list[str] = []
        missing: list[str] = []
        credit_sum = 0.0

        with engine.connect() as conn:
            for skill in jd_skills:
                normalized = skill.strip().lower().replace(" ", "_").replace("-", "_")

                # Exact normalized match
                row = conn.execute(
                    _text(
                        "SELECT confidence_score FROM profile_entities "
                        "WHERE user_id = :u AND normalized_name = :n "
                        "LIMIT 1"
                    ),
                    {"u": user_id, "n": normalized},
                ).fetchone()

                # Prefix fuzzy match (first token, e.g. "sprint" from "sprint_prioritization")
                if not row:
                    first_token = normalized.split("_")[0]
                    if len(first_token) >= 4:
                        row = conn.execute(
                            _text(
                                "SELECT confidence_score FROM profile_entities "
                                "WHERE user_id = :u AND normalized_name LIKE :pat "
                                "ORDER BY confidence_score DESC LIMIT 1"
                            ),
                            {"u": user_id, "pat": f"%{first_token}%"},
                        ).fetchone()

                if row and float(row[0]) > 0:
                    conf   = float(row[0])
                    credit = conf / 100.0
                    credit_sum += credit
                    matched.append(f"{skill} ({conf:.0f}%)")
                else:
                    missing.append(skill)

        denom = max(len(jd_skills), 1)
        score = round((credit_sum / denom) * max_points, 1)
        return score, matched, missing

    except Exception as exc:
        logger.warning(
            "match_score: _confidence_weighted_skill_score failed (%s) — "
            "falling back to binary skill check",
            exc,
        )
        return None, None, None


# ── Bullet-level skills-gap mapping ───────────────────────────────────────────

def _map_bullet_matches(
    cv_data: dict,
    jd_keywords: set[str],
    jd_skills: list[str],
    jd_seniority: int,
) -> list[dict]:
    """
    Skills Gap Analysis at bullet granularity: for every bullet in the CV,
    find which JD keywords/skills it evidences and whether its own seniority
    signal meets the JD's required level — "critical for Ariel's analysis"
    per the CVParser/LiveEditor integration (bullet_matches on MatchScoreResult).

    Pure-Python, deterministic, no network calls — runs unconditionally
    alongside the rest of Phase 1, independent of whether the LLM ran.

    No cap on the returned list: every bullet that evidences at least one JD
    term is included (Architectural Principle: no truncation — this mirrors
    why matched_critical_capabilities/ats_gaps are never sliced).
    """
    all_terms = sorted(set(jd_keywords) | {s for s in jd_skills if s})
    if not all_terms:
        return []

    matches: list[dict] = []
    for exp_idx, exp in enumerate(cv_data.get("experience") or []):
        for bullet_idx, bullet_text in enumerate(exp.get("bullets") or []):
            if not bullet_text or not bullet_text.strip():
                continue
            bullet_lower  = bullet_text.lower()
            bullet_tokens = _tokenize(bullet_text)
            matched_terms = [
                term for term in all_terms
                if term in bullet_tokens or (" " in term and term in bullet_lower)
            ]
            if not matched_terms:
                continue
            matches.append({
                "experience_index":  exp_idx,
                "bullet_index":      bullet_idx,
                "matched_terms":     matched_terms,
                # Experience Weighting: does this specific bullet's own
                # seniority signal meet the JD's required level? Informational
                # (feeds Ariel's explanation of WHICH bullets carry the match),
                # not a re-weighting of the composite score — the existing
                # seniority_alignment component (title-level, 0-25 pts) is the
                # only place seniority affects the numeric total; see
                # finalize_composite()'s single-source-of-truth guard above.
                "seniority_aligned": _detect_seniority(bullet_text) >= jd_seniority,
            })
    return matches


# ── Phase 1: pure-Python keyword/skills/seniority scoring ────────────────────

def _phase1(
    cv_data: dict,
    jd_text: str,
    skill_proficiencies: dict[str, str] | None = None,
    # ── Confidence Matrix integration (optional) ─────────────────────────────
    # When both are provided, the skills_alignment component uses verified
    # confidence scores instead of binary matching.  Pass None (default) to
    # keep the original behaviour during the rollout period.
    cm_engine=None,      # sqlalchemy.engine.Engine from db.ENGINE
    cm_user_id: str | None = None,
) -> MatchScoreResult:
    """
    Pure Python scoring — no network calls, < 5 ms for typical inputs.

    Produces the keyword/skills/seniority breakdown used by the UI tag row.
    Also powers the fallback total when run_llm_validation=False.

    Components:
      keyword_overlap     0-40 pts
      skills_alignment    0-35 pts  (confidence-weighted when cm_engine + cm_user_id set)
      seniority_alignment 0-25 pts
    """
    exp_text = _cv_experience_text(cv_data)
    jd_keywords = _extract_jd_keywords(jd_text)

    if len(jd_keywords) < 3:
        logger.warning(
            "match_score Phase1: thin proxy — only %d keyword(s) extracted "
            "from %d chars of JD text.",
            len(jd_keywords), len(jd_text),
        )

    profs: dict[str, str] = skill_proficiencies or {}
    proficiency_notes: list[str] = []

    # ── Component 1: Keyword Overlap (40 pts) ─────────────────────────────────
    matched_kw: list[str] = []
    missing_kw: list[str] = []
    kw_weight_sum = 0.0

    for kw in sorted(jd_keywords):
        if not _term_or_alias_in_text(kw, exp_text):
            missing_kw.append(kw)
            continue
        user_level, matched_tok = _resolve_proficiency(kw, profs)
        if user_level and user_level not in ("professional", "unknown"):
            jd_level      = _detect_jd_requirement_level(kw, jd_text)
            weight, label = _proficiency_weight(user_level, jd_level)
            if label:
                note = f"{matched_tok or kw}: {label}"
                if note not in proficiency_notes:
                    proficiency_notes.append(note)
            if weight >= 0.5:
                matched_kw.append(kw)
            else:
                missing_kw.append(kw)
            kw_weight_sum += weight
        else:
            matched_kw.append(kw)
            kw_weight_sum += 1.0

    kw_denom = max(len(jd_keywords), 1)
    score_1   = round((kw_weight_sum / kw_denom) * 40, 1)

    # ── Component 2: Skills Alignment (35 pts) ────────────────────────────────
    jd_skills  = _extract_jd_skills(jd_text)

    # ── Confidence Matrix path (active when cm_engine + cm_user_id supplied) ──
    # This replaces the binary matched/missing check with a graduated score
    # derived from the user's verified confidence in each skill.
    _cm_score, _cm_matched, _cm_missing = _confidence_weighted_skill_score(
        jd_skills, cm_engine, cm_user_id
    )
    if _cm_score is not None:
        # Confidence Matrix available — use its output directly.
        score_2        = _cm_score
        matched_skills = _cm_matched or []
        missing_skills = _cm_missing or []
        logger.debug(
            "match_score Phase1 Component2: confidence-matrix path "
            "score=%.1f matched=%d missing=%d",
            score_2, len(matched_skills), len(missing_skills),
        )
    else:
        # ── Binary fallback (original behaviour) ─────────────────────────────
        cv_skills  = _extract_cv_skills(cv_data)
        cv_skill_tokens: set[str] = {
            tok for cs in cv_skills
            for tok in cs.split()
            if len(tok) >= 2 and tok not in _STOPWORDS
        }
        skill_targets: list[str] = list(jd_skills)
        if len(skill_targets) < 3:
            extra = [kw for kw in sorted(jd_keywords) if kw not in {s.split()[0] for s in skill_targets}]
            skill_targets = list(jd_skills) + extra

        matched_skills: list[str] = []
        missing_skills: list[str] = []
        skill_weight_sum = 0.0

        for js in skill_targets:
            js_tokens = set(js.split())
            js_base   = js.split()[0]
            if not _is_experience_backed(js, exp_text):
                missing_skills.append(js)
                continue
            if any(js == cs for cs in cv_skills):
                base_weight = 1.0; matched_skills.append(js)
            elif any(js in cs or cs in js for cs in cv_skills):
                base_weight = 0.8; matched_skills.append(js)
            elif js_tokens & cv_skill_tokens:
                base_weight = 0.6; matched_skills.append(js)
            elif js in exp_text:
                base_weight = 0.4; matched_skills.append(js)
            else:
                missing_skills.append(js); continue
            user_level, matched_tok = _resolve_proficiency(js, profs)
            if user_level and user_level not in ("professional", "unknown"):
                jd_level      = _detect_jd_requirement_level(js, jd_text)
                prof_w, label = _proficiency_weight(user_level, jd_level)
                if label:
                    note = f"{matched_tok or js_base}: {label}"
                    if note not in proficiency_notes:
                        proficiency_notes.append(note)
                skill_weight_sum += base_weight * prof_w
            else:
                skill_weight_sum += base_weight

        skills_denom = max(len(skill_targets), 1)
        score_2      = round((skill_weight_sum / skills_denom) * 35, 1)
    # ── end Component 2 ───────────────────────────────────────────────────────

    # ── Component 3: Seniority Alignment (25 pts) ─────────────────────────────
    jd_title_block  = jd_text[:200]
    cv_title        = cv_data.get("title", "")
    cv_recent_role  = (cv_data.get("experience") or [{}])[0].get("role", "")
    jd_seniority    = _detect_seniority(jd_title_block)
    cv_seniority    = _detect_seniority(f"{cv_title} {cv_recent_role}")
    delta           = abs(jd_seniority - cv_seniority)
    factor          = _SENIORITY_ALIGNMENT.get(delta, _SENIORITY_MISMATCH_FACTOR)
    score_3         = round(factor * 25, 1)

    total = round(min(100.0, score_1 + score_2 + score_3), 1)

    # ── Post-processing: thin-proxy differentiation ───────────────────────────
    jd_has_rich_signal = len(jd_keywords) >= 3
    if not jd_has_rich_signal:
        total = min(total, 70.0)
        title_lower  = jd_title_block.lower()
        title_hits   = sum(1 for sig in _DOMAIN_TITLE_SIGNALS if sig in title_lower)
        title_bonus  = min(4.0, float(title_hits))
        total        = min(70.0, round(total + title_bonus, 1))
        _fp          = int(hashlib.md5(jd_text[:80].encode("utf-8", errors="ignore")).hexdigest()[:4], 16)
        variance     = round((_fp % 51 - 25) / 10, 1)
        total        = min(70.0, max(50.0, round(total + variance, 1)))
        logger.debug(
            "match_score: thin-proxy cap=70.0 title_bonus=+%.1f variance=%+.1f → %.1f",
            title_bonus, variance, total,
        )
    else:
        if "product" in jd_title_block.lower():
            total = min(100.0, round(total + 5.0, 1))

    _SENIOR_CONFLICT_THRESHOLD = 5
    if jd_seniority >= _SENIOR_CONFLICT_THRESHOLD and cv_seniority < _SENIOR_CONFLICT_THRESHOLD:
        total = max(0.0, round(total - 10.0, 1))

    total = round(min(100.0, max(0.0, total)), 1)

    bullet_matches = _map_bullet_matches(cv_data, jd_keywords, jd_skills, jd_seniority)

    logger.debug(
        "match_score Phase1: kw=%.1f/40 skills=%.1f/35 seniority=%.1f/25 → %.1f "
        "bullet_matches=%d",
        score_1, score_2, score_3, total, len(bullet_matches),
    )

    return MatchScoreResult(
        total               = total,
        keyword_overlap     = float(score_1),
        skills_alignment    = float(score_2),
        seniority_alignment = float(score_3),
        matched_keywords    = matched_kw[:20],
        missing_keywords    = missing_kw[:20],
        matched_skills      = matched_skills,
        missing_skills      = missing_skills,
        suggestions         = [
            f"Consider adding: {s}"
            for s in missing_skills[:5]
            if not _is_ai_meta(s)
        ],
        llm_validated       = False,
        proficiency_notes   = proficiency_notes,
        bullet_matches      = bullet_matches,
    )


# ── Phase A: Local proxy score (30% component) ───────────────────────────────

def compute_local_proxy_score(job_title: str, jd_text: str = "") -> float:
    """
    Fast pure-Python proxy score — the 30% local component of the composite.

    Evaluates two signals:
      60%  Title keyword alignment — does the job title match PM/CS tiers?
      40%  Seniority alignment    — does the role level fit the candidate's band?

    Returns 0-100.  Completes in < 1 ms.

    Called by MatcherAgent in s1 so jobs enter the DB with a meaningful initial
    score before the s2 LLM enrichment runs.  The candidate anchor level is
    _CANDIDATE_SENIORITY_LEVEL = 4 ("manager" / mid-senior PM).
    """
    title_lower = job_title.lower().strip()

    # ── 60%: Title keyword alignment ─────────────────────────────────────────
    if any(sig in title_lower for sig in _TITLE_TIER_1):
        title_score = 90.0
    elif any(sig in title_lower for sig in _TITLE_TIER_2):
        title_score = 72.0
    elif any(sig in title_lower for sig in _TITLE_TIER_3):
        title_score = 68.0
    elif "product" in title_lower:
        title_score = 55.0
    else:
        title_score = 28.0

    # ── 40%: Seniority alignment ──────────────────────────────────────────────
    probe_text       = f"{job_title} {jd_text[:200]}"
    jd_seniority     = _detect_seniority(probe_text)
    delta            = abs(jd_seniority - _CANDIDATE_SENIORITY_LEVEL)
    seniority_factor = _SENIORITY_ALIGNMENT.get(delta, _SENIORITY_MISMATCH_FACTOR)
    seniority_score  = round(seniority_factor * 100.0, 1)

    local = round(0.60 * title_score + 0.40 * seniority_score, 1)
    result = min(100.0, max(0.0, local))

    logger.debug(
        "local_proxy: title='%s' → tier_score=%.0f seniority=%d→factor=%.1f → %.1f",
        job_title, title_score, jd_seniority, seniority_factor, result,
    )
    return result


# ── Phase B LLM sub-scorer: semantic + management (within the 70% bucket) ────

class LLMCapabilityScore(BaseModel):
    """
    Strict output schema for the capability-based LLM scorer.

    Enforced via Pydantic so a malformed or partial LLM response fails
    validation explicitly (caught by _llm_dual_score's except block) rather
    than silently propagating wrong types (e.g. a string where a float is
    expected) into the composite-score arithmetic.
    """
    semantic_score:   float = Field(ge=0, le=100,
        description="Overall capability alignment, transferable execution "
                     "skills, and growth trajectory vs. the role.")
    management_score: float = Field(ge=0, le=100,
        description="Tooling (Jira/Monday/etc.), methodology, and "
                     "stakeholder-management fit.")
    why_ron: str = Field(default="",
        description="Detailed contextual justification of the candidate's "
                     "core strengths relative to the role.")
    missing_critical_capabilities: List[str] = Field(default_factory=list,
        description="High-level, conceptual capability gaps — NOT a "
                     "low-level list of missing keywords.")


_LLM_SYSTEM_SCORER = (
    "You are a precise capability-based evaluation engine. "
    "Output ONLY a valid, complete JSON object — no markdown fences, no prose, no explanation. "
    "The entire response must be parseable by json.loads(). "
    "Keep the 'why_ron' field under 250 characters to avoid truncation."
)

_LLM_SCORER_TEMPLATE = """\
Score this JOB vs. CANDIDATE across two independent capability dimensions.
Return ONLY valid JSON — no markdown, no extra text.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
BILINGUAL & RTL PROCESSING (HEBREW/ENGLISH)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
You must seamlessly comprehend mixed syntax, such as Hebrew sentences containing English technical terms or acronyms, without losing context or introducing translation artifacts.
Regardless of the input language (Hebrew, English, or mixed), all returned JSON structures MUST use English keys exclusively. Values may be in the source language, but keys must always be English.

JOB TITLE: {job_title}
HIRING COMPANY: {company_name}

JOB DESCRIPTION (first 800 chars):
{jd_excerpt}

CANDIDATE SUMMARY:
{cv_summary}

CANDIDATE SKILLS:
{cv_skills}

CANDIDATE EXPERIENCE (most recent first):
{cv_experience}
{company_legacy_note}
Return this exact JSON object:
{{
  "semantic_score": <integer 0-100>,
  "management_score": <integer 0-100>,
  "why_ron": "<concise, contextual fit rationale — max 250 characters>",
  "missing_critical_capabilities": ["<high-level conceptual gap>", ...]
}}

WHY_RON RULES:
  • Plain text, no markdown, no bullet symbols, no newlines.
  • One or two sentences: state the strongest fit signal and the main gap (if any).
  • Direct and factual — no filler ("great opportunity", "excited to").
  • Hard limit: ≤ 250 characters total. Truncate rather than exceed.

MISSING_CRITICAL_CAPABILITIES RULES:
  • List CONCEPTUAL capability gaps, not individual missing keywords.
    Good:  "No direct people-management experience"
    Bad:   "missing word: 'Jira'"
  • Empty list if there are no meaningful gaps. Max 5 items.

══════════════════════════════════════════════════════════
MANDATORY ARCHITECTURAL PRINCIPLES — override all defaults
══════════════════════════════════════════════════════════

1. EXPLORATION FREEDOM
   DO NOT penalize the candidate for exploring a different career direction or
   for a title mismatch between their current/most-recent role and this JD.
   Evaluate TRANSFERABLE CAPABILITIES across the FULL experience history.
   If the underlying skill exists anywhere in their record, credit it fully.
   This includes role-title synonyms: e.g. a "Customer Success Team Leader"
   who owns PRDs, manages enterprise stakeholders, and drives execution is
   functionally equivalent to a "Project Manager" / "Product Owner" — do not
   penalize for the title string not matching literally.

2. SENIORITY SCALING
   Overqualification is NEVER a penalty — treat it as a positive signal.
   If the candidate has MORE seniority or MORE years of experience than the JD
   requires (e.g., Team Lead applying for an IC role; 3+ years when 1–2 are
   asked), score that at the SAME level as an exact match or HIGHER.
   Never discount a score because the candidate is "too senior".

3. COMPANY LEGACY  (see CRITICAL override block above if present)
   Any prior employment at the target company is the strongest possible fit
   signal — validated culture, domain, product, and org-chart knowledge.
   Prior employer history must result in a top-tier score for both dimensions.

══════════════════════════════════════════════════════════
SCORING CRITERIA
══════════════════════════════════════════════════════════

COMPANY CONTEXT — factor this into semantic_score
  Use the HIRING COMPANY field above to assess environment fit:
  • Stage fit: hyper-growth startup, scale-up, enterprise, or public company?
    The candidate's background is strongest in high-growth B2B SaaS / scale-up
    environments (Series B–D, 100–1000 employees, fast iteration culture).
    Matching that profile is a positive signal; large-enterprise or regulated-
    industry contexts (banks, telcos, government) should slightly lower the score
    unless the JD content itself shows the company operates in an agile way.
  • Domain fit: B2B SaaS, marketplace, fintech, e-commerce — weight positively.
  • Culture signals inferred from the company name may inform the why_ron brief
    but should not be the primary score driver — JD content takes precedence.

semantic_score  — capability alignment, transferable execution, growth trajectory
  Evaluate domain alignment (SaaS / Fintech / E-commerce / B2B / B2B2C) AND
  hard-skill / capability overlap with JD requirements across the candidate's
  ENTIRE record — not literal keyword matches, but the underlying capability
  (e.g. "owns PRDs and drives R&D execution" satisfies a "Project Manager" JD
  even without that exact phrase appearing in the CV).
  Factor in company stage/culture fit (see COMPANY CONTEXT above).
  Career-pivot exploration must NOT lower this score — focus on transferability.
  90-100 = exceptional capability + domain fit (or validated prior employer).
  70-89  = strong transferable match, minor gaps.
  50-69  = solid partial match, bridgeable with ramp-up.
  30-49  = limited alignment, notable gaps.
  0-29   = poor fit, fundamental mismatch.

management_score  — tooling, methodology, and stakeholder-management fit
  Does the candidate's record show leadership, people management,
  cross-functional ownership, or tooling/methodology fit (Jira, Monday,
  Scrum/Agile, stakeholder management) — regardless of whether the JD
  requires it explicitly?
  Higher seniority than required = ASSET, score it at the top of the band.
  90-100 = clear leadership/tooling match (demonstrated and/or required).
  70-89  = good trajectory signals, minor gap.
  50-69  = some leadership/tooling evidence, partial match.
  30-49  = limited evidence or JD is IC-only.
  0-29   = no leadership/tooling evidence whatsoever.
"""


def _find_prior_employer(cv_data: dict, target_company: str) -> Optional[str]:
    """
    Return the first company from cv_data experience whose core name matches
    the target job's company name (case-insensitive whole-word), or None.

    Scope: compares ONLY against `target_company` (the job's company field),
    NOT against the full JD body.  Searching the body was the root cause of
    false positives — e.g. "River" (past restaurant job) matching inside Wolt's
    JD because the word "river" appeared in the description text.

    Matching rules:
      • Strips trailing parenthetical / dash suffixes before testing
        (e.g. "GO-OUT (Startup)" → "GO-OUT").
      • Uses regex word boundaries (\\b) so "River" does NOT match "Riverside".
      • re.escape() treats hyphens, dots, etc. as literals, not regex operators.
      • Minimum core length of 4 characters to skip short abbreviations.
    """
    if not target_company or not target_company.strip():
        return None

    for exp in cv_data.get("experience", []):
        company = (exp.get("company") or "").strip()
        if len(company) < 4:
            continue
        # Strip parenthetical/dash suffixes: "GO-OUT (Startup)" → "GO-OUT"
        core = re.split(r"\s*[\(\[–—]", company)[0].strip()
        if len(core) < 4:
            continue
        # Word-boundary match against the target company name only —
        # this prevents "River" from firing on Wolt's JD text.
        pattern = r"\b" + re.escape(core) + r"\b"
        if re.search(pattern, target_company, re.IGNORECASE):
            return company
    return None


def _parse_json_robust(raw: str, job_title: str = "") -> dict | None:
    """
    Parse the LLM JSON response, attempting progressively more aggressive
    repair strategies before giving up.

    Truncation pattern: the model fills `max_tokens` mid-string, producing
    something like:
        {"semantic_score": 72, "management_score": 65,
         "why_ron": "🟢 Core Strengths:\\n• Led product at GO-OUT
    (no closing quote, comma, or brace)

    Repair order:
      1. Direct parse — succeeds for well-formed responses.
      2. Close open string + object  →  append  '"}
      3. Close object only           →  append  }
      4. Extract scores with regex, drop why_ron / missing_critical_capabilities.
      5. Return None  — caller uses (60, 60, "", []) fallback.
    """
    # 1. Direct
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # 2. Close open string + object
    try:
        return json.loads(raw + '"}')
    except json.JSONDecodeError:
        pass

    # 3. Close object only
    try:
        return json.loads(raw + "}")
    except json.JSONDecodeError:
        pass

    # 4. Regex extraction — scores only, no why_ron / capability gaps
    sem_m  = re.search(r'"semantic_score"\s*:\s*(\d+)',   raw)
    mgmt_m = re.search(r'"management_score"\s*:\s*(\d+)', raw)
    if sem_m or mgmt_m:
        logger.warning(
            "match_score LLM: truncated JSON repaired via regex for title='%s' — "
            "scores recovered but why_ron/missing_critical_capabilities lost. raw=%r",
            job_title, raw[:200],
        )
        return {
            "semantic_score":   int(sem_m.group(1))  if sem_m  else 60,
            "management_score": int(mgmt_m.group(1)) if mgmt_m else 60,
            "why_ron": "",
            "missing_critical_capabilities": [],
        }

    # 5. Unrecoverable
    logger.warning(
        "match_score LLM: unrecoverable JSON for title='%s' — raw=%r",
        job_title, raw[:300],
    )
    return None


async def _llm_dual_score(
    cv_data: dict,
    jd_text: str,
    job_title: str = "",
    company_name: str = "",
    user_id: Optional[str] = None,
    job_id: Optional[str] = None,
) -> tuple[float, float, str, list[str]]:
    """
    Single claude-haiku-4-5 call returning
    (semantic_score, management_score, why_ron, missing_critical_capabilities).

    The response is validated against LLMCapabilityScore (Pydantic) so a
    malformed payload — wrong types, out-of-range scores — is caught
    explicitly rather than propagating bad data into the composite formula.

    temperature=0.0 guarantees identical output for identical inputs (determinism).
    Falls back to (60.0, 60.0, "", []) on any API, parse, or validation error
    so the composite still gets a reasonable score and the pipeline never crashes.
    """
    _FALLBACK: tuple[float, float, str, list[str]] = (60.0, 60.0, "", [])

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        logger.warning(
            "match_score LLM: ANTHROPIC_API_KEY not set — returning neutral fallback scores"
        )
        return _FALLBACK

    # ── Compact CV fields for the prompt ─────────────────────────────────────
    cv_summary = (cv_data.get("summary") or "")[:400]
    cv_skills  = ", ".join(
        item
        for cat in (cv_data.get("skills") or {}).get("categories", [])
        for item in cat.get("items", [])
    )[:300]

    # ── Experience: most-recent-first, full list, with brief bullet context ───
    # FIX: previously sliced to [:5] (oldest entries only) — all entries are now
    # included in reverse-chronological order so the LLM always sees the most
    # relevant recent roles first, regardless of how many entries exist.
    exp_lines: list[str] = []
    for e in reversed(cv_data.get("experience", [])):
        role    = e.get("role", "").strip()
        company = e.get("company", "").strip()
        bullets = e.get("bullets") or []
        line    = f"{role} @ {company}"
        if bullets and bullets[0]:
            # First 90 chars of the top bullet gives domain context without bloat
            snippet = bullets[0].strip()[:90].rstrip()
            line   += f" — {snippet}"
        exp_lines.append(line)
    cv_experience = "\n".join(exp_lines)

    # ── Company Legacy detection ──────────────────────────────────────────────
    # If the target company appears in the candidate's experience, inject a
    # mandatory high-priority override so the LLM correctly weights prior
    # employment as the strongest possible fit signal.
    prior_employer = _find_prior_employer(cv_data, company_name)
    if prior_employer:
        company_legacy_note = (
            "\n╔══════════════════════════════════════════════════════════╗\n"
            "║  CRITICAL — COMPANY LEGACY OVERRIDE (mandatory)          ║\n"
            "╚══════════════════════════════════════════════════════════╝\n"
            f"The candidate has PRIOR EMPLOYMENT at [{prior_employer}] — the EXACT\n"
            "company in this job posting. This is the strongest possible fit signal:\n"
            "  • Validated cultural fit (they already know the org, the people,\n"
            "    the mission, and the operating style).\n"
            "  • Validated domain fit (product, market, tech stack, client base).\n"
            "  • Zero onboarding ramp-up on context that external candidates spend\n"
            "    months acquiring.\n"
            "YOU MUST score semantic_score ≥ 85 AND\n"
            "management_score ≥ 80 unless there is an explicit,\n"
            "disqualifying hard-skill gap stated in the JD.\n"
        )
        logger.info(
            "match_score LLM: Company-Legacy override active — prior employer '%s' "
            "detected in JD for title='%s'",
            prior_employer, job_title,
        )
    else:
        company_legacy_note = ""

    prompt = _LLM_SCORER_TEMPLATE.format(
        job_title           = job_title or "Unknown Role",
        company_name        = company_name or "Unknown",
        jd_excerpt          = jd_text[:800].strip(),
        cv_summary          = cv_summary,
        cv_skills           = cv_skills,
        cv_experience       = cv_experience,
        company_legacy_note = company_legacy_note,
    )

    logger.debug(
        "match_score LLM: firing request for title='%s' company='%s' "
        "(jd_len=%d prompt_len=%d)",
        job_title, company_name, len(jd_text), len(prompt),
    )
    try:
        result_llm = await call_llm(
            model       = "claude-haiku-4-5-20251001",
            max_tokens  = 450,   # headroom for why_ron + missing_critical_capabilities list
            temperature = 0.0,   # deterministic — same input → same output every time
            system      = _LLM_SYSTEM_SCORER,
            messages    = [{"role": "user", "content": prompt}],
            purpose     = "match_score_dual_score",
            user_id     = user_id,
            job_id      = job_id,
        )
        raw = result_llm.text.strip()
        logger.debug(
            "match_score LLM: raw response received for title='%s' (len=%d)",
            job_title, len(raw),
        )

        # Strip optional markdown fences
        if raw.startswith("```"):
            lines = raw.splitlines()
            raw   = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:]).strip()

        payload = _parse_json_robust(raw, job_title)
        if payload is None:
            return _FALLBACK

        payload = scrub_dict(payload)

        # ── Strict Pydantic validation ────────────────────────────────────────
        # Catches wrong types / missing required fields explicitly rather than
        # letting a malformed payload silently corrupt the composite formula.
        try:
            validated = LLMCapabilityScore.model_validate(payload)
        except ValidationError as exc:
            logger.warning(
                "match_score LLM: schema validation failed for title='%s' (%s) — "
                "payload=%r — using fallback 60/60",
                job_title, exc, payload,
            )
            return _FALLBACK

        semantic   = validated.semantic_score
        management = validated.management_score
        why_ron    = validated.why_ron.strip()
        gaps       = validated.missing_critical_capabilities[:5]

        logger.info(
            "match_score LLM: semantic=%.0f  management=%.0f  why_ron_len=%d  "
            "gaps=%d  title='%s'",
            semantic, management, len(why_ron), len(gaps), job_title,
        )
        return semantic, management, why_ron, gaps

    except json.JSONDecodeError as exc:
        logger.warning(
            "match_score LLM: JSON parse failed for title='%s' (%s) — raw_len=%d — using fallback 60",
            job_title, exc, len(raw) if 'raw' in dir() else -1,
        )
        return _FALLBACK
    except LLMCallError as exc:
        logger.warning(
            "match_score LLM: LLM call failed for title='%s': %s",
            job_title, exc,
        )
        return _FALLBACK
    except Exception as exc:
        logger.warning(
            "match_score LLM: API call failed for title='%s': %s (%s)",
            job_title, type(exc).__name__, exc,
        )
        return _FALLBACK


# ── Public API ────────────────────────────────────────────────────────────────

def compute_match_score(
    cv_data: dict,
    jd_text: str,
    run_llm_validation: bool = True,
    skill_proficiencies: dict[str, str] | None = None,
) -> MatchScoreResult:
    """
    Synchronous entry point — Phase 1 pure Python only (no event loop).

    Use compute_match_score_async inside async route handlers for the full
    3-component LLM composite.
    """
    return _phase1(cv_data, jd_text, skill_proficiencies)


# ── Unified composite — single source of truth ────────────────────────────────
#
# The ATS Match Engine (ats_match_engine.py) is no longer shadow-only: its
# Layer-0 KnockoutResult and Layer-1 competency coverage feed the production
# Match Score. Every code path that (re)derives a composite from sub-scores
# MUST go through finalize_composite() — never inline the arithmetic — so the
# knockout cap and the ATS blend can never be silently dropped (this exact
# drift previously existed in feed_service's local_stored rebuild branch).
#
# Blend rationale:
#   • The LLM semantic composite keeps the MAJORITY share because Principles
#     2 & 3 (company legacy, exploration freedom) are enforced at the prompt
#     level — the semantic scorer is where pivots and legacy get their credit.
#   • The ATS base_score (evidence-backed coverage + impact + local) gets a
#     strong minority share, so a profile with no evidence for the JD's
#     must-haves can no longer show 90+ while the ATS panel shows 45.
#   • A Layer-0 knockout failure caps the unified total outright: a provable
#     hard-constraint conflict (work model / language / minimum years) is an
#     "explicit, disqualifying gap" in the sense of Principle 2, so the cap
#     legitimately overrides even a company-legacy floor.

_LOCAL_WEIGHT      = 0.30
_LLM_BUCKET_WEIGHT = 0.70
_SEMANTIC_SHARE    = 5 / 7   # within the 70% bucket — was 50/(50+20)
_MANAGEMENT_SHARE  = 2 / 7   # within the 70% bucket — was 20/(50+20)

_LLM_BLEND_WEIGHT  = 0.60    # unified: share of the LLM semantic composite
_ATS_BLEND_WEIGHT  = 0.40    # unified: share of the ATS engine base_score
KNOCKOUT_SCORE_CAP = 40.0    # hard ceiling when Layer-0 knockout fails

# ── Dynamic Matching Score: culture-fit adjustment (JOB-20) ───────────────────
# Culture fit enters the composite as a BOUNDED POST-BLEND DELTA, never as a
# re-weighting of the existing terms. Rationale (Future-Mandate review):
#   • With no culture signal (delta=None) the composite is bit-identical to
#     the pre-culture formula — regression-safe by construction.
#   • ±5 points cannot inflate a thin JD (the thin path never computes a
#     delta) and cannot turn a mid-tier match into a top match on vibe alone.
#   • Company Legacy: culture_delta_from_alignment() clamps negative deltas
#     to 0 for prior employers, so culture can never undercut the legacy
#     floor enforced at the prompt level.
#   • Exploration Freedom: alignment derives ONLY from the user's explicit
#     stated preferences vs the company profile — candidate titles, history,
#     and seniority never enter the calculation.
CULTURE_MAX_ADJUST = 5.0     # |delta| ceiling, in composite points

# Work-model alignment for a remote-only user, per company work_model value.
_REMOTE_ONLY_WM_ALIGNMENT: dict[str, float] = {
    "remote":   100.0,
    "flexible":  85.0,
    "hybrid":    40.0,
    "onsite":     0.0,
}


def compute_culture_alignment(culture_profile, user_prefs: dict) -> tuple[Optional[float], str]:
    """
    Alignment (0-100, 1 decimal) between the user's explicit preferences and
    a CompanyCultureProfile, plus a specific human-readable note for the UI.

    Signals (each only when both sides carry real data — no signal, no score):
      • work model  — user's remote_only hard constraint vs the company's
                      stated work_model ("unknown" contributes nothing).
      • culture axis — user's culture_preference ("startup"/"corporate") vs
                      the company's 0-100 startup axis.

    Returns (None, "") when the profile is missing/low-confidence or neither
    signal exists — the fallback contract: no signal must mean no effect.
    """
    if culture_profile is None or getattr(culture_profile, "confidence", "low") == "low":
        return None, ""

    signals: list[float] = []
    notes:   list[str]   = []

    wm = getattr(culture_profile, "work_model", "unknown")
    if user_prefs.get("work_model") == "remote_only" and wm in _REMOTE_ONLY_WM_ALIGNMENT:
        score = _REMOTE_ONLY_WM_ALIGNMENT[wm]
        signals.append(score)
        notes.append(f"remote-only requirement vs company work model '{wm}'")

    pref = str(user_prefs.get("culture_preference", "any")).lower()
    category = getattr(culture_profile, "culture_category", "unknown")
    if pref in ("startup", "corporate") and category != "unknown":
        axis  = float(getattr(culture_profile, "culture_axis", 50.0))
        score = axis if pref == "startup" else 100.0 - axis
        signals.append(score)
        notes.append(f"'{pref}' preference vs culture axis {axis:.1f}/100 ({category})")

    if not signals:
        return None, ""
    return round(sum(signals) / len(signals), 1), "; ".join(notes)


def culture_delta_from_alignment(
    alignment: Optional[float],
    prior_employer: bool = False,
) -> Optional[float]:
    """
    Map alignment (0-100) to a bounded composite delta in
    [-CULTURE_MAX_ADJUST, +CULTURE_MAX_ADJUST]; 50 is neutral (0.0).

    prior_employer=True clamps negative deltas to 0.0 — the Company Legacy
    principle: culture fit may reward, never penalize, a validated prior
    employer. None in → None out (no signal, no effect).
    """
    if alignment is None:
        return None
    delta = (float(alignment) - 50.0) / 50.0 * CULTURE_MAX_ADJUST
    delta = round(min(max(delta, -CULTURE_MAX_ADJUST), CULTURE_MAX_ADJUST), 1)
    if prior_employer and delta < 0.0:
        return 0.0
    return delta


def finalize_composite(
    local: float,
    semantic: float,
    management: float,
    ats_base: float | None = None,
    knockout_failed: bool = False,
    culture_delta: float | None = None,
) -> float:
    """
    Compose the final 0-100 Match Score from its parts. Pure and deterministic.

      llm_composite = 0.30 × local + 0.70 × (5/7 × semantic + 2/7 × management)
      unified       = 0.60 × llm_composite + 0.40 × ats_base   (when ATS ran)
      adjusted      = unified + culture_delta                   (when culture ran;
                      bounded ±CULTURE_MAX_ADJUST, see culture_delta_from_alignment)
      capped        = min(adjusted, 40.0)                       (knockout failed)

    ats_base must be the engine's PRE-knockout base_score — the knockout
    penalty is applied here, once, as a cap (never also via the engine's
    0.35 multiplier, which would double-penalise). The knockout cap is applied
    AFTER the culture delta so a hard-constraint conflict can never be bought
    back by good vibes.

    Thin-JD callers (Principle 4) do not use this function's ATS or culture
    paths: they zero semantic/management and pass no ats_base and no
    culture_delta, preserving exactly 0.30 × local.
    """
    llm_bucket    = _SEMANTIC_SHARE * semantic + _MANAGEMENT_SHARE * management
    llm_composite = _LOCAL_WEIGHT * local + _LLM_BUCKET_WEIGHT * llm_bucket

    composite = llm_composite
    if ats_base is not None:
        composite = _LLM_BLEND_WEIGHT * llm_composite + _ATS_BLEND_WEIGHT * ats_base
    if culture_delta is not None:
        composite += culture_delta
    if knockout_failed:
        composite = min(composite, KNOCKOUT_SCORE_CAP)
    return round(min(100.0, max(0.0, composite)), 1)


def _run_ats_engine(
    cv_data: dict,
    jd_text: str,
    company_name: str,
    local: float,
    user_id: str,
    entity_scores: "list | None" = None,
) -> "object | None":
    """
    Run the ATS Match Engine against the caller's data. Returns AtsMatchResult
    or None when the engine cannot run (thin JD, entity fetch failure, …).

    user_id is REQUIRED and must come from the caller's verified context
    (JWT or per-user pipeline loop) — tenancy invariant, never a global lookup.

    entity_scores : optional pre-fetched get_entity_breakdown(user_id, ENGINE)
        result. Callers that score many jobs for the SAME user in one batch
        (feed_service.refresh_user_scores) fetch this once per batch instead
        of once per job — the Confidence Matrix does not change mid-batch, so
        re-querying profile_entities/evidence_records per job was a pure N+1
        (JOB-6). Pass None (default) to fetch it here as before — single-job
        callers (e.g. POST /api/jobs/analyze) are unaffected.

    None means "degrade gracefully to the pure LLM composite" — scoring a job
    must never crash the feed because the Confidence Matrix was unreachable.
    """
    try:
        from backend.services.ats_match_engine import (
            ThinJdError, compute_ats_match, heuristic_structured_jd,
        )

        if entity_scores is None:
            from backend.services.confidence_matrix_service import get_entity_breakdown
            from backend.core.database import ENGINE
            entities = get_entity_breakdown(user_id, ENGINE)   # list[EntityScore] dicts
        else:
            entities = entity_scores

        # Prefer knockout prefs from the master profile when available.
        try:
            from backend.services.master_profile_service import get_knockout_prefs
            prefs = get_knockout_prefs(user_id)
        except Exception:
            prefs = {}

        structured = heuristic_structured_jd(jd_text)
        return compute_ats_match(
            jd_text=jd_text,
            structured_jd=structured,
            cv_data=cv_data,
            entity_scores=list(entities),
            local_score=local,
            target_company=company_name,
            user_prefs=prefs,
        )
    except ThinJdError:
        return None   # Principle-4 territory — caller keeps the 0.30 × local path
    except Exception as exc:
        logger.warning("[ats-engine] engine unavailable (non-fatal, LLM-only composite): %s", exc)
        return None


def _load_culture_prefs(user_id: str) -> dict:
    """
    The user-side inputs for culture alignment, from role_preferences:
      work_model         — "remote_only" only for an explicit remote-only user
                           (same mapping as get_knockout_prefs)
      culture_preference — "startup" | "corporate" | "any" (default "any" ⇒
                           the axis signal contributes nothing)
    Non-fatal: any load failure returns preference-free defaults, which
    produce alignment=None ⇒ no composite effect.
    """
    try:
        from backend.services.master_profile_service import load
        prefs = (load(user_id) or {}).get("role_preferences", {}) or {}
        work  = str(prefs.get("work_type", "any")).lower()
        return {
            "work_model":         "remote_only" if work == "remote" else None,
            "culture_preference": str(prefs.get("culture_preference", "any")).lower(),
        }
    except Exception as exc:
        logger.warning("[culture-fit] prefs load failed for user=%s: %s", user_id, exc)
        return {"work_model": None, "culture_preference": "any"}


async def _compute_culture_fit(
    cv_data: dict,
    jd_text: str,
    company_name: str,
    user_id: str,
) -> tuple[Optional[float], Optional[float], Optional[str], Optional[str]]:
    """
    Fetch the company culture profile (cached per company) and compute the
    bounded composite delta. Returns (alignment, delta, category, note) —
    all None on any failure or absence of signal. Never raises: culture fit
    is additive-only and must never break or block scoring.

    Runs ONLY from the full-composite path of compute_match_score_async —
    the thin-JD early return precedes it, so thin JDs can never gain
    (or lose) points from culture (Principle 4).
    """
    if not company_name or not company_name.strip():
        return None, None, None, None
    try:
        from backend.agents.company_culture import get_culture_profile
        profile = await get_culture_profile(company_name, jd_text=jd_text)
        if profile is None:
            return None, None, None, None

        alignment, note = compute_culture_alignment(profile, _load_culture_prefs(user_id))
        prior = _find_prior_employer(cv_data, company_name) is not None
        delta = culture_delta_from_alignment(alignment, prior_employer=prior)
        if delta is None:
            return None, None, None, None
        if prior and delta == 0.0 and alignment is not None and alignment < 50.0:
            note = (note + " — negative adjustment waived (prior employer)") if note else note
        category = profile.culture_category if profile.culture_category != "unknown" else None
        return alignment, delta, category, (note or None)
    except Exception as exc:
        logger.warning("[culture-fit] unavailable for %r (non-fatal): %s", company_name, exc)
        return None, None, None, None


def _persist_score_audit(
    job_title: str,
    company_name: str,
    llm_composite: float,
    unified: float,
    ats: "object",
    user_id: str,
) -> None:
    """
    Persist the LLM-only vs ATS vs unified scores for calibration review.
    Guaranteed non-fatal — the production path never depends on this succeeding.
    """
    try:
        import json as _json
        from datetime import datetime, timezone

        from backend.repositories import shadow_score_repository

        shadow_score_repository.insert(
            user_id        = user_id,
            job_title      = job_title[:200],
            company        = company_name[:200],
            existing_score = llm_composite,
            ats_score      = ats.final_score,
            breakdown_json = _json.dumps({
                "unified":    unified,
                "ats_base":   ats.base_score,
                "competency": ats.competency_score,
                "impact":     ats.impact.score,
                "local":      ats.local_score,
                "knockout_failed":  not ats.knockout.passed,
                "knockout_reasons": ats.knockout.reasons,
                "legacy_company":   ats.legacy_company,
                "gaps":             ats.gap_analysis,
                "must_have_count":  sum(
                    1 for m in ats.competency_detail
                    if m.competency.tier.value == "must_have"
                ),
            }, ensure_ascii=False),
            created_at = datetime.now(timezone.utc).isoformat(),
        )
    except Exception as exc:
        logger.warning("[ats-audit] score audit persist failed (non-fatal): %s", exc)


async def compute_match_score_async(
    cv_data: dict,
    jd_text: str,
    run_llm_validation: bool = True,
    skill_proficiencies: dict[str, str] | None = None,
    job_title: str = "",
    company_name: str = "",
    *,
    user_id: str,
    entity_scores: "list | None" = None,
    job_id: Optional[str] = None,
) -> MatchScoreResult:
    """
    Async composite scorer — primary entry point for route handlers.

    When run_llm_validation=True (default):
      Runs Phase 1 for keyword breakdown (now alias/synonym-aware — see
      _CAPABILITY_ALIASES), then the LLM dual-scorer for the 70% "LLM
      Semantic Capability Score" bucket (semantic_score + management_score).
      final = 0.30 × local  +  0.70 × (5/7 × semantic + 2/7 × management)

      The 5/7 : 2/7 split inside the 70% bucket preserves the original
      50:20 relative emphasis between semantic fit and management/tooling
      fit — only the OUTER local-vs-LLM ratio changed (was 30/50/20 across
      three independent weights, now 30/70 with semantic+management sharing
      the 70% allocation in their original ratio).

    When run_llm_validation=False:
      Phase 1 only — fast, no API calls.  Suitable for live-editor re-scores,
      force_rescore_all, and any latency-sensitive path.

    Parameters
    ----------
    cv_data : dict
        Structured CV in the standard format (title, experience, skills, …).
    jd_text : str
        Raw job description text.
    run_llm_validation : bool
        Whether to run the LLM sub-scorers.  Default True.
    skill_proficiencies : dict | None
        Optional {skill: level} map from master_profile_service.
    job_title : str
        Job title string — improves LLM prompt context and local proxy accuracy.
        If omitted, extracted from the first 60 chars of jd_text.
    user_id : str  (keyword-only, REQUIRED)
        Owner of the CV / Confidence Matrix being scored. Must originate from
        a verified JWT (route handlers) or the per-user pipeline loop — the
        tenancy invariant forbids resolving it from any global registry.
    company_name : str
        Target company name — used by _find_prior_employer to detect Company
        Legacy matches.  Must be passed from the job object, NOT derived from
        jd_text, to prevent false positives from body-text substring matches.
    entity_scores : list | None  (keyword-only, optional)
        Pre-fetched get_entity_breakdown(user_id, ENGINE) result, forwarded
        to _run_ats_engine. Batch callers scoring many jobs for the same user
        in one pass (feed_service.refresh_user_scores) fetch this once and
        pass it through to avoid re-querying the Confidence Matrix per job
        (JOB-6 N+1 fix). None (default) preserves the original per-call fetch.
    job_id : str | None  (keyword-only, optional)
        Stable job identifier. When provided AND the computed score qualifies
        (llm_validated, semantic signal present, total >= HIGH_MATCH_THRESHOLD),
        a fire-and-forget high-match trigger is scheduled via
        match_trigger_service.schedule_match_trigger (JOB-43) — exactly once
        per (user, job), never blocking this scorer. None (default) disables
        trigger evaluation, e.g. for preview scoring of unsaved jobs.
    """
    if not run_llm_validation:
        # Fast path — Phase 1 only
        return _phase1(cv_data, jd_text, skill_proficiencies)

    # ── Parse Noisy JDs ───────────────────────────────────────────────────────
    # Pass the raw scraped JD through the JDParserAgent first. It strips noise,
    # structures the output, and extracts the company name.
    # The output string must be used for the 300-char thin-JD check and scoring.
    parser = JDParserAgent()
    parsed_jd = await parser.parse_and_format_jd(jd_text)
    jd_text = parsed_jd.formatted_text

    if parsed_jd.company_name and (not company_name or not company_name.strip() or company_name.strip().lower() in ("unknown", "n/a")):
        company_name = parsed_jd.company_name

    # Safety net: refuse to call the LLM on a placeholder / un-hydrated JD.
    # Sending "Title at Company in Location" to Claude wastes tokens and
    # produces a meaningless 60/60 fallback.  feed_service._enrich_one should
    # have fetched the real JD before reaching this point; this guard is the
    # last line of defence.
    #
    # MANDATORY ARCHITECTURAL RULE — Strict Fallback for Thin JDs (CLAUDE.md §4)
    # ───────────────────────────────────────────────────────────────────────
    # Threshold is 300 characters (NOT a smaller value) and the fallback MUST
    # zero out semantic_score and management_score — never substitute a flat
    # magic-number cap (e.g. a hardcoded 28.2). The anti-pattern this guards
    # against: returning _phase1().total directly, which can reach 94+ for an
    # exact title match ("Senior Product Manager") even when jd_text is only
    # a title stub — that false positive floats empty jobs to the top of the
    # feed. Composite = 0.30 × local with semantic=management=0 naturally
    # caps near ~28-30 for a strong title match and lower otherwise, keeping
    # un-hydrated jobs near the bottom of the list without discarding the
    # local/keyword breakdown the UI tag row needs. Any future change to this
    # threshold or fallback formula must be reviewed against CLAUDE.md §4
    # before merging.
    _LLM_MIN_JD_CHARS = 300
    if len(jd_text.strip()) < _LLM_MIN_JD_CHARS:
        inferred_title = job_title or jd_text[:60].split("\n")[0].strip()
        local          = compute_local_proxy_score(inferred_title, jd_text)
        # semantic=0, management=0, no ATS blend → exactly 0.30 × local
        composite      = finalize_composite(local, 0.0, 0.0)
        p1             = _phase1(cv_data, jd_text, skill_proficiencies)
        logger.warning(
            "match_score LLM: jd_text too thin (%d chars) — semantic=0 management=0 "
            "→ composite capped at %.1f (was incorrectly %.1f via Phase-1 only)",
            len(jd_text.strip()), composite, p1.total,
        )
        return MatchScoreResult(
            total               = composite,
            keyword_overlap     = p1.keyword_overlap,
            skills_alignment    = p1.skills_alignment,
            seniority_alignment = p1.seniority_alignment,
            matched_keywords    = p1.matched_keywords,
            missing_keywords    = p1.missing_keywords,
            matched_skills      = p1.matched_skills,
            missing_skills      = p1.missing_skills,
            suggestions         = p1.suggestions,
            llm_validated       = False,
            proficiency_notes   = p1.proficiency_notes,
            local_score         = local,
            semantic_score      = 0.0,
            management_score    = 0.0,
            why_ron             = None,
            missing_critical_capabilities = [],
            # bullet_matches is a Phase-1, LLM-independent signal — the thin-JD
            # fallback zeroes the LLM-derived score components but must not
            # drop it too (it's still honest, still useful for Ariel).
            bullet_matches      = p1.bullet_matches,
        )

    # ── Full unified composite ────────────────────────────────────────────────
    #
    # 1) LLM semantic composite:
    #      30% local proxy + 70% LLM bucket (5/7 semantic : 2/7 management)
    # 2) ATS Match Engine (Layer 0 knockouts + Layer 1 coverage + Layer 2 impact)
    #    blended in at 40%, and its KnockoutResult applied as a hard 40-pt cap.
    # All arithmetic lives in finalize_composite() — the single source of truth
    # shared with feed_service's local_stored rebuild branch.

    inferred_title = job_title or jd_text[:60].split("\n")[0].strip()
    local = compute_local_proxy_score(inferred_title, jd_text)

    # LLM dual scorer (single haiku call, temperature=0.0, Pydantic-validated)
    semantic, management, why_ron, missing_caps = await _llm_dual_score(
        cv_data, jd_text, inferred_title, company_name,
        user_id=user_id, job_id=job_id,
    )

    # ATS Match Engine — None ⇒ degrade gracefully to the pure LLM composite.
    ats = _run_ats_engine(cv_data, jd_text, company_name, local, user_id, entity_scores)

    # Culture fit (JOB-20) — bounded ±5 post-blend delta; all-None when there
    # is no real signal, leaving the composite bit-identical to pre-culture.
    culture_alignment, culture_delta, culture_category, culture_note = (
        await _compute_culture_fit(cv_data, jd_text, company_name, user_id)
    )

    llm_composite   = finalize_composite(local, semantic, management)
    knockout_failed = bool(ats and not ats.knockout.passed)
    composite       = finalize_composite(
        local, semantic, management,
        ats_base        = ats.base_score if ats else None,
        knockout_failed = knockout_failed,
        culture_delta   = culture_delta,
    )

    if culture_delta is not None:
        logger.info(
            "match_score culture-fit: alignment=%.1f delta=%+.1f category=%s title='%s'",
            culture_alignment, culture_delta, culture_category, inferred_title,
        )

    # Phase 1 for rich keyword/skills breakdown (populates UI tag row)
    p1 = _phase1(cv_data, jd_text, skill_proficiencies)

    if ats:
        logger.info(
            "match_score unified: llm=%.1f(×%.2f) + ats_base=%.1f(×%.2f)%s → %.1f  "
            "[local=%.1f sem=%.1f mgmt=%.1f | ats C=%.1f I=%.1f K=%s]  title='%s'",
            llm_composite, _LLM_BLEND_WEIGHT, ats.base_score, _ATS_BLEND_WEIGHT,
            f" capped@{KNOCKOUT_SCORE_CAP:.0f} (knockout)" if knockout_failed else "",
            composite, local, semantic, management,
            ats.competency_score, ats.impact.score,
            "FAIL" if knockout_failed else "pass", inferred_title,
        )
        # Calibration audit trail (non-fatal) — LLM-only vs ATS vs unified.
        _persist_score_audit(inferred_title, company_name, llm_composite, composite, ats, user_id)
    else:
        logger.info(
            "match_score composite (LLM-only, ATS engine unavailable): "
            "local=%.1f sem=%.1f mgmt=%.1f → %.1f  title='%s'",
            local, semantic, management, composite, inferred_title,
        )

    result = MatchScoreResult(
        total               = composite,
        keyword_overlap     = p1.keyword_overlap,
        skills_alignment    = p1.skills_alignment,
        seniority_alignment = p1.seniority_alignment,
        matched_keywords    = p1.matched_keywords,
        missing_keywords    = p1.missing_keywords,
        matched_skills      = p1.matched_skills,
        missing_skills      = p1.missing_skills,
        suggestions         = p1.suggestions,
        llm_validated       = True,
        proficiency_notes   = p1.proficiency_notes,
        local_score         = local,
        semantic_score      = semantic,
        management_score    = management,
        why_ron             = why_ron or None,
        missing_critical_capabilities = missing_caps,
        ats_score            = ats.base_score if ats else None,
        ats_competency_score = ats.competency_score if ats else None,
        knockout_failed      = knockout_failed,
        knockout_reasons     = list(ats.knockout.reasons) if ats else [],
        ats_gaps             = list(ats.gap_analysis) if ats else [],
        culture_alignment    = culture_alignment,
        culture_delta        = culture_delta,
        culture_category     = culture_category,
        culture_note         = culture_note,
        bullet_matches       = p1.bullet_matches,
    )

    # ── High-match trigger (JOB-43) — fire-and-forget, never blocks scoring ───
    # Only evaluated on the full LLM-validated path with a stable job_id; the
    # thin-JD early return above never reaches here, and schedule_match_trigger
    # itself re-checks llm_validated + semantic_score as defence in depth.
    if job_id:
        from backend.services.match_trigger_service import schedule_match_trigger
        schedule_match_trigger(
            job_id, user_id, result.as_dict(),
            job_title    = inferred_title,
            company_name = company_name,
        )

    return result
