"""
Match Dimensions — the structural (non-LLM) half of the composite match score.

This module replaces the flat `0.40 × ats_base` term that used to sit beside
the LLM composite in match_score_service.finalize_composite(). The ATS engine
is still the source of the impact-density and knockout signals; what it did not
have was any notion of skill *equivalence*, of experience *depth* as distinct
from coverage, or of domain continuity. Those are the three dimensions added
here, and together with the ATS impact term they form `structural_score`.

    structural = 0.35 × hard_skills      (taxonomy-equivalent coverage)
               + 0.30 × depth_breadth    (seniority & scope depth)
               + 0.20 × domain_context   (domain overlap + prior employer)
               + 0.15 × impact           (ATS engine impact density, passed in)

Work constraints (location / remote / language) are deliberately NOT a term in
that sum. A constraint conflict is not "a few points worse" — an on-site-only
role is not 8% less suitable for someone who cannot relocate, it is unsuitable.
Those stay where they already were: the ATS engine's Layer-0 knockout, applied
once by finalize_composite as a hard cap. Modelling them additively would let a
strong skills match quietly buy back a disqualifying conflict.

Compliance with the CLAUDE.md scoring principles
--------------------------------------------------
1. Data completeness — nothing here slices the experience list. depth_breadth
   walks the full history.
2. Company legacy — domain_context applies a hard floor (_LEGACY_FLOOR) when a
   prior employer matches, mirroring the LLM prompt's own override.
3. Exploration freedom & seniority scaling — no term in this module can be
   reduced by a title mismatch, a career pivot, or by the candidate exceeding
   what the JD asks for. `_seniority_fit` is explicitly capped at 1.0 from
   below only: more experience than required scores exactly as well as an
   exact match, never worse. Verified by test.
4. Thin JDs — this module is never called on the thin-JD path; that early
   return in compute_match_score_async precedes it and still yields exactly
   0.30 × local.

Transferable-skill floors
--------------------------
Every dimension has a non-zero floor for a candidate with genuinely related
experience. A profile that shares no *exact* JD keyword but sits in the same
skill family should not score 0 — that reading is what buries career-changers
whose capabilities transfer perfectly well. The floors only apply when there is
real adjacent signal (at least one taxonomy-equivalent or same-family match);
an entirely unrelated profile still scores near 0, as it should.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ── Structural sub-weights ────────────────────────────────────────────────────
W_HARD_SKILLS   = 0.35
W_DEPTH_BREADTH = 0.30
W_DOMAIN        = 0.20
W_IMPACT        = 0.15

# ── Floors ────────────────────────────────────────────────────────────────────
# Applied only when adjacent signal exists — see module docstring.
TRANSFERABLE_SKILL_FLOOR = 20.0
TRANSFERABLE_DEPTH_FLOOR = 15.0
LEGACY_FLOOR             = 85.0   # prior employer — mirrors the LLM prompt override

# Split of the hard-skills score between the two requirement tiers, used only
# when the JD states both. Fixed shares rather than per-item weights: with
# per-item weighting, a JD listing one must-have and four nice-to-haves lets
# the optional pile outvote the mandatory requirement, so a candidate missing
# the one thing the role actually requires outscores one who has it. Capping
# nice-to-haves at a fixed 20% makes that arithmetically impossible.
_MUST_SHARE = 0.80
_NICE_SHARE = 0.20

# Recency: a skill last used long ago still counts, just less. Never zero —
# "I did this five years ago" is not the same as never having done it.
_RECENCY_FULL_YEARS = 3      # within this many years → no decay
_RECENCY_MIN_FACTOR = 0.55   # floor of the decay curve


@dataclass
class DimensionScores:
    """All four structural dimensions plus the blended structural score."""
    hard_skills:    float = 0.0
    depth_breadth:  float = 0.0
    domain_context: float = 0.0
    impact:         float = 0.0
    structural:     float = 0.0

    matched_must_haves:  list[str] = field(default_factory=list)
    missing_must_haves:  list[str] = field(default_factory=list)
    equivalent_matches:  list[str] = field(default_factory=list)  # "JD term ≈ profile term"
    legacy_company:      Optional[str] = None
    notes:               list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "hard_skills":        self.hard_skills,
            "depth_breadth":      self.depth_breadth,
            "domain_context":     self.domain_context,
            "impact":             self.impact,
            "structural":         self.structural,
            "matched_must_haves": self.matched_must_haves,
            "missing_must_haves": self.missing_must_haves,
            "equivalent_matches": self.equivalent_matches,
            "legacy_company":     self.legacy_company,
            "notes":              self.notes,
        }


# ═════════════════════════════════════════════════════════════════════════════
# Equivalence resolution
# ═════════════════════════════════════════════════════════════════════════════

def _norm(term: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace."""
    return re.sub(r"[^a-z0-9+#]+", " ", str(term or "").lower()).strip()


def build_equivalence_map(skill_names: list[str], engine=None) -> dict[str, set[str]]:
    """
    {normalized skill name: {every equivalent surface form, normalized}}.

    Read-only against skills_taxonomy. Deliberately NOT
    skills_taxonomy_service.resolve_skill(), which inserts a new taxonomy row
    when a name doesn't resolve — correct for an ingest choke point, wrong for
    scoring. Scoring a job must never mutate the global taxonomy; a thousand
    JD terms scored today would otherwise become a thousand junk canonical
    skills tomorrow.

    Degrades to an empty map on SQLite or any DB error: callers fall back to
    exact-name matching, which is exactly the pre-taxonomy behaviour.
    """
    if not skill_names:
        return {}
    try:
        from backend.core.database import ENGINE
        from sqlalchemy import text as _sql

        eng = engine or ENGINE
        if eng.dialect.name != "postgresql":
            return {}

        mapping: dict[str, set[str]] = {}
        with eng.connect() as conn:
            for name in skill_names:
                cleaned = str(name or "").strip()
                if not cleaned:
                    continue
                row = conn.execute(_sql("""
                    SELECT canonical_name, synonyms FROM public.skills_taxonomy
                    WHERE lower(canonical_name) = lower(:name)
                       OR lower(:name) = ANY(SELECT lower(s) FROM unnest(synonyms) AS s)
                    LIMIT 1
                """), {"name": cleaned}).fetchone()
                if row is None:
                    continue
                forms = {_norm(row.canonical_name)} | {_norm(s) for s in (row.synonyms or [])}
                mapping[_norm(cleaned)] = {f for f in forms if f}
        return mapping
    except Exception:
        logger.debug("[match-dimensions] equivalence lookup failed — exact-match fallback",
                     exc_info=True)
        return {}


def _equivalent(
    jd_term: str,
    profile_terms: set[str],
    equivalence: Optional[dict[str, set[str]]] = None,
) -> Optional[str]:
    """
    Return the profile term matching *jd_term* (exactly or via taxonomy), else None.

    Match order — strictest first, so an exact match is never reported as a
    mere equivalence:
      1. exact normalized equality
      2. shared taxonomy canonical/synonym form
      3. whole-token containment ("product management" ⊃ "product")
    """
    equivalence = equivalence or {}
    jd_norm = _norm(jd_term)
    if not jd_norm:
        return None

    if jd_norm in profile_terms:
        return jd_norm

    jd_forms = equivalence.get(jd_norm, {jd_norm})
    for profile_term in profile_terms:
        if profile_term in jd_forms:
            return profile_term
        if jd_norm in equivalence.get(profile_term, set()):
            return profile_term
        if jd_forms & equivalence.get(profile_term, set()):
            return profile_term

    # Token containment, whole tokens only — guards against "react" matching
    # "reaction" the way a bare substring test would.
    jd_tokens = set(jd_norm.split())
    if jd_tokens:
        for profile_term in profile_terms:
            if jd_tokens <= set(profile_term.split()):
                return profile_term
    return None


# ═════════════════════════════════════════════════════════════════════════════
# Dimension 1 — hard skills (taxonomy-equivalent coverage)
# ═════════════════════════════════════════════════════════════════════════════

def score_hard_skills(
    must_haves: list[str],
    nice_haves: list[str],
    profile_skills: list[str],
    equivalence: Optional[dict[str, set[str]]] = None,
) -> tuple[float, list[str], list[str], list[str]]:
    """
    Weighted coverage of the JD's stated requirements.

    Returns (score 0-100, matched must-haves, missing must-haves, equivalences).

    Must-haves dominate (_MUST_HAVE_WEIGHT vs _NICE_HAVE_WEIGHT) because a
    nice-to-have is, by the JD's own admission, optional — treating the two
    alike lets a pile of bonus skills paper over a missing core requirement.

    When the JD lists no requirements at all the result is a neutral 50, not 0:
    an unparseable JD is missing information, and missing information is not
    evidence of a bad match.
    """
    equivalence = equivalence or {}
    profile_terms = {_norm(s) for s in profile_skills if _norm(s)}

    if not must_haves and not nice_haves:
        return 50.0, [], [], []

    matched_must: list[str] = []
    missing_must: list[str] = []
    equivalences: list[str] = []
    matched_nice = 0

    for term in must_haves:
        hit = _equivalent(term, profile_terms, equivalence)
        if hit:
            matched_must.append(term)
            if hit != _norm(term):
                equivalences.append(f"{term} ≈ {hit}")
        else:
            missing_must.append(term)

    for term in nice_haves:
        hit = _equivalent(term, profile_terms, equivalence)
        if hit:
            matched_nice += 1
            if hit != _norm(term):
                equivalences.append(f"{term} ≈ {hit}")

    must_coverage = (len(matched_must) / len(must_haves)) if must_haves else None
    nice_coverage = (matched_nice / len(nice_haves)) if nice_haves else None

    if must_coverage is not None and nice_coverage is not None:
        score = 100.0 * (_MUST_SHARE * must_coverage + _NICE_SHARE * nice_coverage)
    elif must_coverage is not None:
        score = 100.0 * must_coverage          # no optional tier stated — musts are the whole score
    else:
        score = 100.0 * (nice_coverage or 0.0)  # JD listed only optional items

    score = round(score, 1)

    # Transferable floor — only when something genuinely adjacent matched.
    if score < TRANSFERABLE_SKILL_FLOOR and (matched_must or equivalences):
        score = TRANSFERABLE_SKILL_FLOOR

    return score, matched_must, missing_must, equivalences


# ═════════════════════════════════════════════════════════════════════════════
# Dimension 2 — seniority & scope depth (depth vs breadth)
# ═════════════════════════════════════════════════════════════════════════════

def _recency_factor(last_used_year: Optional[int], now_year: Optional[int] = None) -> float:
    """Gentle decay for skills not used recently, floored at _RECENCY_MIN_FACTOR."""
    if not last_used_year:
        return 1.0   # unknown recency is not evidence of staleness
    current = now_year or datetime.now(timezone.utc).year
    gap = current - int(last_used_year)
    if gap <= _RECENCY_FULL_YEARS:
        return 1.0
    # Lose 7 points of factor per year past the grace window, floored.
    return max(_RECENCY_MIN_FACTOR, 1.0 - 0.07 * (gap - _RECENCY_FULL_YEARS))


def _seniority_fit(candidate_years: float, required_years: Optional[float]) -> float:
    """
    0-1 fit between experience held and experience demanded.

    Asymmetric by design, per CLAUDE.md Principle 3 (Seniority Scaling):
    exceeding the requirement returns exactly 1.0 — never more, never less.
    Being under it scales down proportionally but never to 0, since years are a
    proxy for capability, not capability itself.
    """
    if not required_years or required_years <= 0:
        return 1.0
    if candidate_years >= required_years:
        return 1.0                                   # overqualification is NEVER a penalty
    return max(0.35, candidate_years / required_years)


def score_depth_breadth(
    must_haves: list[str],
    profile_skills: list[str],
    skill_depth: dict[str, dict],
    required_years: Optional[float] = None,
    equivalence: Optional[dict[str, set[str]]] = None,
    now_year: Optional[int] = None,
) -> tuple[float, list[str]]:
    """
    Score the depth-vs-breadth trade-off the ticket calls out directly:
    five years across 70% of the required skills, versus one year across 100%.

    breadth = fraction of must-haves covered at all.
    depth   = mean recency-adjusted seniority fit across the skills that ARE
              covered, from profile_entities.years_of_experience /
              last_used_year (passed in via *skill_depth*, keyed by normalized
              skill name).

    The two are combined multiplicatively-ish rather than as a flat average:

        score = 100 × (0.45 × breadth + 0.55 × depth) × coverage_confidence

    Depth carries the larger share because breadth without depth is the more
    dangerous failure mode — a candidate who has touched every listed
    technology for a month each reads as a perfect keyword match and is
    usually not one, whereas deep expertise in most of the stack is the normal
    shape of a strong senior hire. `coverage_confidence` then damps the whole
    thing when depth is being inferred from very few known-duration skills, so
    a single well-documented skill cannot masquerade as proven depth across
    the board.

    Returns (score 0-100, notes).
    """
    equivalence = equivalence or {}
    notes: list[str] = []
    profile_terms = {_norm(s) for s in profile_skills if _norm(s)}

    if not must_haves:
        # Nothing stated to be deep in. Fall back to overall seniority fit
        # against total tenure, which is the only signal available.
        total_years = sum(
            float(d.get("years") or 0.0) for d in skill_depth.values()
        )
        return round(100.0 * _seniority_fit(total_years, required_years), 1), [
            "JD states no explicit requirements — depth scored on overall tenure."
        ]

    covered: list[str] = []
    for term in must_haves:
        hit = _equivalent(term, profile_terms, equivalence)
        if hit:
            covered.append(hit)

    breadth = len(covered) / len(must_haves)

    if not covered:
        # No overlap at all → no depth to measure. Floor only if the profile
        # has *some* skill data (adjacent signal), else genuinely near-zero.
        floor = TRANSFERABLE_DEPTH_FLOOR if profile_terms else 0.0
        return floor, ["No required skills matched — depth could not be assessed."]

    fits: list[float] = []
    known_duration = 0
    for term in covered:
        detail = skill_depth.get(term) or {}
        years = detail.get("years")
        if years is None:
            # Unknown duration → neutral 1.0 rather than a penalty. Absence of
            # a recorded year count is a gap in our data, not in their career.
            fits.append(1.0)
            continue
        known_duration += 1
        fit = _seniority_fit(float(years), required_years)
        fits.append(fit * _recency_factor(detail.get("last_used_year"), now_year))

    depth = sum(fits) / len(fits)

    # Damp when depth rests on very little recorded duration data.
    coverage_confidence = 1.0 if known_duration >= 2 else (0.9 if known_duration == 1 else 0.85)
    if known_duration == 0:
        notes.append("No recorded years-of-experience on matched skills — depth is estimated.")

    score = 100.0 * (0.45 * breadth + 0.55 * depth) * coverage_confidence
    score = max(TRANSFERABLE_DEPTH_FLOOR, min(100.0, score))

    if breadth < 1.0:
        notes.append(
            f"Covers {len(covered)} of {len(must_haves)} required skills "
            f"({breadth:.0%} breadth), depth factor {depth:.2f}."
        )
    return round(score, 1), notes


# ═════════════════════════════════════════════════════════════════════════════
# Dimension 3 — domain context & prior employer
# ═════════════════════════════════════════════════════════════════════════════

def score_domain_context(
    jd_text: str,
    target_company: str,
    profile_domains: list[str],
    experience: list[dict],
) -> tuple[float, Optional[str], list[str]]:
    """
    Domain continuity, with a hard floor for prior employment at the target.

    Returns (score 0-100, legacy company or None, notes).

    The prior-employer floor is CLAUDE.md Principle 2 expressed structurally:
    the LLM prompt already carries a mandatory override for this case, and the
    deterministic half of the score must not then drag the composite back down
    and undo it. Matching is word-boundary against the company NAME only —
    never the JD body, which is what produced the "River" ⊂ "Riverside"
    false positives the principle was written about.
    """
    notes: list[str] = []

    legacy = _find_prior_employer(experience, target_company)
    if legacy:
        notes.append(f"Prior employment at {legacy} — strongest available fit signal.")
        return LEGACY_FLOOR, legacy, notes

    jd_norm = _norm(jd_text)
    if not profile_domains or not jd_norm:
        return 50.0, None, ["No domain signal available — scored neutral."]

    hits = [d for d in profile_domains if _norm(d) and _norm(d) in jd_norm]
    if not hits:
        # Adjacent-but-unnamed domains are common; a miss here is weak evidence.
        return 40.0, None, ["No explicit domain overlap with the JD."]

    ratio = len(hits) / max(1, len(profile_domains))
    score = 55.0 + 45.0 * min(1.0, ratio * 2.0)
    notes.append(f"Domain overlap: {', '.join(hits[:4])}.")
    return round(min(100.0, score), 1), None, notes


def _find_prior_employer(experience: list[dict], target_company: str) -> Optional[str]:
    """
    Word-boundary company match against the target company name only.

    Mirrors match_score_service._find_prior_employer exactly — same 4-char
    minimum, same parenthetical/dash stripping, same re.escape word-boundary
    test. Duplicated rather than imported to keep this module free of a
    circular import back into match_score_service, which imports *this* one.
    """
    if not target_company or not target_company.strip():
        return None
    for exp in experience or []:
        if not isinstance(exp, dict):
            continue
        company = (exp.get("company") or "").strip()
        if len(company) < 4:
            continue
        core = re.split(r"\s*[\(\[–—]", company)[0].strip()
        if len(core) < 4:
            continue
        if re.search(r"\b" + re.escape(core) + r"\b", target_company, re.IGNORECASE):
            return company
    return None


# ═════════════════════════════════════════════════════════════════════════════
# Blend
# ═════════════════════════════════════════════════════════════════════════════

def blend_structural(
    hard_skills: float,
    depth_breadth: float,
    domain_context: float,
    impact: float,
) -> float:
    """The structural sub-composite. Pure; weights are module constants."""
    return round(
        W_HARD_SKILLS   * hard_skills
        + W_DEPTH_BREADTH * depth_breadth
        + W_DOMAIN        * domain_context
        + W_IMPACT        * impact,
        1,
    )


def compute_dimensions(
    *,
    must_haves: list[str],
    nice_haves: list[str],
    profile_skills: list[str],
    skill_depth: dict[str, dict],
    profile_domains: list[str],
    experience: list[dict],
    jd_text: str,
    target_company: str,
    required_years: Optional[float] = None,
    impact: float = 0.0,
    equivalence: Optional[dict[str, set[str]]] = None,
    now_year: Optional[int] = None,
) -> DimensionScores:
    """
    Compute all four dimensions and their blend. Pure — every input is passed
    in, so the whole structural half of the score is testable without a
    database, an LLM, or a live profile.
    """
    equivalence = equivalence or {}

    skills_score, matched, missing, equivalences = score_hard_skills(
        must_haves, nice_haves, profile_skills, equivalence,
    )
    depth_score, depth_notes = score_depth_breadth(
        must_haves, profile_skills, skill_depth, required_years, equivalence, now_year,
    )
    domain_score, legacy, domain_notes = score_domain_context(
        jd_text, target_company, profile_domains, experience,
    )

    return DimensionScores(
        hard_skills        = skills_score,
        depth_breadth      = depth_score,
        domain_context     = domain_score,
        impact             = round(impact, 1),
        structural         = blend_structural(skills_score, depth_score, domain_score, impact),
        matched_must_haves = matched,
        missing_must_haves = missing,
        equivalent_matches = equivalences,
        legacy_company     = legacy,
        notes              = depth_notes + domain_notes,
    )
