"""
Profile Baseline Service — Deep User Profiling for the Matching Engine (JOB-18)
===============================================================================

Assembles the user's baseline profile for the matching engine from EVERY
available data source — not just the most recent resume upload:

  • Resume / experience history   (master_profiles onboarding row, via
                                   user_profile.get_profile — FULL history,
                                   never truncated, most-recent-first)
  • Master Profile chat answers   (metrics_doc["metrics"], written by
                                   merge_answers / update_profile_from_interaction)
  • Explicit confirmations        (verify_* metric entries + Confidence-Matrix
                                   entity scores from confidence_matrix_service)
  • Explicit hard constraints     (role_preferences → knockout prefs: work
                                   model, languages, salary floor, locations)

Source weighting  (reliability × recency)
-----------------------------------------
Each signal's effective weight is  RELIABILITY[source] × strength × decay,
with exponential recency decay  0.5 ** (age_days / HALF_LIFE[source]):

  source                 reliability  half-life   rationale
  ─────────────────────  ───────────  ─────────   ─────────────────────────────
  verified_evidence         1.00      (none)      Confidence-Matrix entity score;
                                                  already source-weighted AND
                                                  freshness-decayed by
                                                  confidence_matrix_service —
                                                  never decay it a second time.
  explicit_confirmation     0.95      365 d       User confirmed the fact in a
                                                  verify/chat interaction
                                                  (verify_* metric entries).
  chat_answer               0.85      270 d       Stated directly to Ariel in
                                                  chat (Master Profile metrics).
  resume                    0.55      540 d       Parsed from CV text — a stated,
                                                  unvalidated claim.
  inferred                  0.35      180 d       Derived from adjacent signals.

This ordering implements the JOB-18 requirement directly: a chat answer
confirmed today (0.85) outweighs a two-year-old resume line
(0.55 × 0.5^(730/540) ≈ 0.22).

Per-skill baseline confidence
-----------------------------
Corroborating signals combine via noisy-OR — score = 100 × (1 − ∏(1 − wᵢ)) —
so multiple independent sources raise confidence without any single source
being double-counted. Explicit proficiency statements then override:
"none" zeroes the skill outright (an explicit user statement always beats an
inferred resume claim), "academic" dampens to 45%.

Degradation states (honest partial scores)
------------------------------------------
Profile completeness is assessed across six sections; incomplete profiles get
a documented degradation factor and an explicit `missing_sections` list so the
UI can say WHY the score is partial instead of showing false confidence:

  tier      sections present   factor
  full            ≥ 5           1.00
  partial         ≥ 3           0.85
  minimal         < 3           0.60

All scores are 1-decimal precision (global .ai_rules).

CLAUDE.md compliance: cv_data preserves the FULL experience history in the
profile's most-recent-first order (Data Completeness — no truncation), and
this module never touches the LLM scoring prompts (Exploration Freedom /
Seniority Scaling remain enforced at the prompt level).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# ── Source weighting model ────────────────────────────────────────────────────

SOURCE_RELIABILITY: dict[str, float] = {
    "verified_evidence":     1.00,
    "explicit_confirmation": 0.95,
    "chat_answer":           0.85,
    "resume":                0.55,
    "inferred":              0.35,
}

# Recency half-life per source, in days. verified_evidence is intentionally
# absent: Confidence-Matrix scores arrive pre-decayed (freshness_factor in
# confidence_math) and must not be decayed twice.
SOURCE_HALF_LIFE_DAYS: dict[str, float] = {
    "explicit_confirmation": 365.0,
    "chat_answer":           270.0,
    "resume":                540.0,
    "inferred":              180.0,
}

# Explicit proficiency statements override inferred signals.
PROFICIENCY_FACTOR: dict[str, float] = {
    "none":         0.0,    # "I have no experience with X" — explicit, absolute
    "academic":     0.45,   # used in studies only, not professionally
    "professional": 1.0,
    "unknown":      1.0,
}

# Degradation tiers: (min sections present, factor)
_TIER_FULL_MIN     = 5
_TIER_PARTIAL_MIN  = 3
DEGRADATION_FACTOR: dict[str, float] = {
    "full":    1.0,
    "partial": 0.85,
    "minimal": 0.60,
}

_PROFILE_SECTIONS = (
    "experience", "skills", "summary", "education",
    "chat_answers", "verified_evidence",
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_dt(value) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        dt = datetime.fromisoformat(str(value))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def source_weight(source: str, age_days: float = 0.0, strength: float = 1.0) -> float:
    """
    Effective weight of one signal: reliability × strength × recency decay.

    `strength` ∈ [0, 1] scales partial signals (e.g. a Confidence-Matrix
    entity score of 62.0 → strength 0.62). verified_evidence never decays
    here — see SOURCE_HALF_LIFE_DAYS.
    """
    reliability = SOURCE_RELIABILITY.get(source, SOURCE_RELIABILITY["inferred"])
    strength    = min(max(float(strength), 0.0), 1.0)
    half_life   = SOURCE_HALF_LIFE_DAYS.get(source)
    decay = 1.0 if half_life is None else 0.5 ** (max(float(age_days), 0.0) / half_life)
    return reliability * strength * decay


def blend_skill_confidence(signals: list[tuple[str, float, float]]) -> float:
    """
    Noisy-OR blend of (source, strength, age_days) signals → 0-100, 1 decimal.

    Corroboration raises confidence; no single source is counted twice
    because each contributes its own independent (1 − w) complement factor.
    """
    if not signals:
        return 0.0
    complement = 1.0
    for source, strength, age_days in signals:
        w = source_weight(source, age_days=age_days, strength=strength)
        complement *= 1.0 - min(max(w, 0.0), 1.0)
    return round(min(max(100.0 * (1.0 - complement), 0.0), 100.0), 1)


def apply_proficiency_override(score: float, level: str | None) -> float:
    """
    Apply an explicit user proficiency statement to an inferred score.
    An explicit "none" always wins over any resume-derived claim.
    """
    factor = PROFICIENCY_FACTOR.get((level or "unknown").lower(), 1.0)
    return round(score * factor, 1)


# ── Degradation / completeness assessment ────────────────────────────────────

def assess_completeness(
    profile: dict,
    metrics: dict,
    entity_scores: list[dict],
) -> dict:
    """
    Honest completeness assessment across the six profile sections.

    Returns:
      {
        "tier": "full" | "partial" | "minimal",
        "coverage_pct": float (1 decimal),
        "missing_sections": [str, ...],
        "degradation_factor": float,
        "is_degraded": bool,
      }
    """
    present = {
        "experience":        bool(profile.get("experience")),
        "skills":            bool(profile.get("skills")),
        "summary":           bool((profile.get("summary") or "").strip()),
        "education":         bool(profile.get("education")),
        "chat_answers":      bool(metrics),
        "verified_evidence": any(float(e.get("score", 0.0)) > 0.0 for e in entity_scores),
    }
    count = sum(present.values())
    if count >= _TIER_FULL_MIN:
        tier = "full"
    elif count >= _TIER_PARTIAL_MIN:
        tier = "partial"
    else:
        tier = "minimal"

    return {
        "tier":               tier,
        "coverage_pct":       round(100.0 * count / len(_PROFILE_SECTIONS), 1),
        "missing_sections":   [s for s in _PROFILE_SECTIONS if not present[s]],
        "degradation_factor": DEGRADATION_FACTOR[tier],
        "is_degraded":        tier != "full",
    }


# ── cv_data assembly (strict match_score_service input schema) ───────────────

def build_cv_data(profile: dict, user_id: str = "default") -> dict:
    """
    Convert a get_profile()-shaped dict into the exact cv_data structure
    consumed by compute_match_score_async:

      {
        "title":      str,
        "summary":    str,                       # includes the USER'S OWN
                                                 # chat-derived supplemental
                                                 # facts (per-user, not the
                                                 # legacy 'default' singleton)
        "experience": [{"role", "company", "bullets": [str]}],   # FULL history
        "skills":     {"categories": [{"label", "items": [str]}]},
      }

    Data Completeness: every experience entry (including nested roles) is
    emitted in the profile's most-recent-first order — no slicing, no caps.
    """
    experience: list[dict] = []
    for exp in profile.get("experience", []):
        company = exp.get("company", exp.get("unit", ""))
        role    = exp.get("role", "")
        details = exp.get("details", "")

        nested_roles = exp.get("roles", [])
        if nested_roles:
            for nr in nested_roles:
                nr_details = nr.get("details", "")
                experience.append({
                    "role":    nr.get("title", role),
                    "company": company,
                    "bullets": [nr_details] if nr_details else [],
                })
        else:
            experience.append({
                "role":    role,
                "company": company,
                "bullets": [details] if details else [],
            })

    skills_list = [str(s).strip() for s in profile.get("skills", []) if str(s).strip()]

    # Per-user supplemental corpus — resume summary + chat-derived facts.
    # (Previously this called build_full_text() with no user_id, which always
    # returned the legacy 'default' singleton: real users' chat answers never
    # reached the matcher.)
    supplemental_text = ""
    try:
        from backend.services.user_profile import build_full_text
        supplemental_text = build_full_text(user_id)
    except Exception:
        logger.warning("[profile_baseline] build_full_text failed for user=%s", user_id)

    title = ""
    personal = profile.get("personal")
    if isinstance(personal, dict):
        title = personal.get("title", "") or ""

    return {
        "title":      title,
        "summary":    supplemental_text,
        "experience": experience,
        "skills": {
            "categories": [{"label": "Skills", "items": skills_list}]
        },
    }


# ── Skill-signal assembly ─────────────────────────────────────────────────────

def _normalize(name: str) -> str:
    return name.strip().lower().replace("-", " ").replace("_", " ")


def _collect_skill_signals(
    profile: dict,
    metrics: dict,
    entity_scores: list[dict],
    now: Optional[datetime] = None,
) -> dict[str, list[tuple[str, float, float]]]:
    """
    Gather every (source, strength, age_days) signal per normalized skill.

      • profile["skills"]        → "resume" signal, aged by the metrics doc's
                                   last_updated (per-skill timestamps don't
                                   exist; the doc timestamp is the honest
                                   upper bound on freshness).
      • metrics verify_* entries → "explicit_confirmation", aged by updated_at.
      • other metrics entries    → "chat_answer", aged by updated_at.
      • entity_scores            → "verified_evidence", strength = score/100,
                                   age 0 (pre-decayed by the Confidence Matrix).
    """
    now = now or _now()
    signals: dict[str, list[tuple[str, float, float]]] = {}

    def _add(skill: str, source: str, strength: float, age_days: float) -> None:
        key = _normalize(skill)
        if len(key) < 2:
            return
        signals.setdefault(key, []).append((source, strength, age_days))

    # Resume-declared skills
    doc_updated = _parse_dt(metrics.get("__doc_last_updated__")) if metrics else None
    resume_age = (now - doc_updated).days if doc_updated else 0.0
    for skill in profile.get("skills", []):
        s = str(skill).strip()
        if s:
            _add(s, "resume", 1.0, float(max(resume_age, 0)))

    # Chat answers + explicit confirmations from the Master Profile metrics
    for key, entry in (metrics or {}).items():
        if key.startswith("__") or not isinstance(entry, dict):
            continue
        updated = _parse_dt(entry.get("updated_at"))
        age = float(max((now - updated).days, 0)) if updated else 0.0
        if key.startswith("verify_"):
            # "verify_python_usage_context" → skill "python …" (stop-word trim
            # mirrors master_profile_service.get_skill_proficiencies)
            remainder = key[len("verify_"):].replace("_", " ")
            _add(remainder, "explicit_confirmation", 1.0, age)
        else:
            _add(key.replace("_", " "), "chat_answer", 1.0, age)

    # Confidence-Matrix verified entities (already weighted + decayed)
    for e in entity_scores or []:
        name  = str(e.get("name") or "")
        score = float(e.get("score") or 0.0)
        if name and score > 0.0:
            _add(name, "verified_evidence", score / 100.0, 0.0)

    return signals


# ── Baseline orchestrator ─────────────────────────────────────────────────────

def build_user_baseline(
    user_id: str,
    *,
    profile: Optional[dict] = None,
    metrics_doc: Optional[dict] = None,
    entity_scores: Optional[list[dict]] = None,
    now: Optional[datetime] = None,
) -> dict:
    """
    Assemble the complete matching-engine baseline for `user_id`.

    All loaders are injectable for tests; defaults read the production stores:
      profile       ← user_profile.get_profile(user_id)
      metrics_doc   ← master_profile_service.load(user_id)
      entity_scores ← confidence_matrix_service.get_entity_breakdown(user_id, ENGINE)

    Returns:
      {
        "user_id", "generated_at",
        "profile_strength":  assess_completeness() output,
        "skill_confidences": {normalized_skill: 0-100 (1 dp)},
        "cv_data":           strict match_score_service input schema,
        "constraints": {
          "hard": {work_model, languages, salary_min_usd, preferred_locations},
          "soft_proficiencies": {skill: level},
        },
        "sources_used": [str, ...],
      }
    """
    if profile is None:
        from backend.services.user_profile import get_profile
        profile = get_profile(user_id)
    if metrics_doc is None:
        from backend.services.master_profile_service import load
        metrics_doc = load(user_id)
    if entity_scores is None:
        try:
            from backend.services.confidence_matrix_service import get_entity_breakdown
            from backend.core.database import ENGINE
            entity_scores = get_entity_breakdown(user_id, ENGINE)
        except Exception as exc:
            logger.warning("[profile_baseline] entity breakdown unavailable: %s", exc)
            entity_scores = []

    metrics = dict((metrics_doc or {}).get("metrics", {}) or {})
    if metrics_doc and metrics_doc.get("last_updated"):
        metrics["__doc_last_updated__"] = metrics_doc["last_updated"]

    strength = assess_completeness(profile, {k: v for k, v in metrics.items()
                                             if not k.startswith("__")}, entity_scores)

    # Per-skill confidences: blend → proficiency override → degradation factor.
    # Proficiencies are parsed from the metrics we already hold — no second
    # store round-trip (keeps the whole builder injectable for tests).
    from backend.services.master_profile_service import extract_skill_proficiencies
    proficiencies = extract_skill_proficiencies(
        {k: v for k, v in metrics.items() if not k.startswith("__")}
    )

    signals = _collect_skill_signals(profile, metrics, entity_scores, now=now)
    skill_confidences: dict[str, float] = {}
    for skill, sigs in signals.items():
        score = blend_skill_confidence(sigs)
        level = proficiencies.get(skill) or proficiencies.get(skill.split()[0] if skill.split() else "")
        score = apply_proficiency_override(score, level)
        skill_confidences[skill] = round(score * strength["degradation_factor"], 1)

    # Hard constraints (explicit user statements — knockout-grade) vs
    # soft inferred proficiencies. Hard constraints are enforced by the ATS
    # knockout layer and are never diluted by inferred skill signals.
    prefs = (metrics_doc or {}).get("role_preferences", {}) or {}
    goals = profile.get("career_goals", {}) or {}
    # Same mapping as master_profile_service.get_knockout_prefs, computed from
    # the document already in hand: only an explicit "remote" becomes a
    # knockout-grade constraint; "any"/"hybrid"/"onsite" stay flexible (None).
    work = str(prefs.get("work_type", "any")).lower()
    knockout = {
        "work_model": "remote_only" if work == "remote" else None,
        "languages":  [str(l).lower() for l in prefs.get("languages", []) if str(l).strip()],
    }

    constraints = {
        "hard": {
            **knockout,
            "salary_min_usd":      prefs.get("salary_min_usd"),
            "preferred_locations": list(
                prefs.get("preferred_locations")
                or goals.get("preferred_locations")
                or []
            ),
        },
        "soft_proficiencies": proficiencies,
    }

    sources_used = sorted({src for sigs in signals.values() for src, _, _ in sigs})

    return {
        "user_id":           user_id,
        "generated_at":      (now or _now()).isoformat(),
        "profile_strength":  strength,
        "skill_confidences": skill_confidences,
        "cv_data":           build_cv_data(profile, user_id),
        "constraints":       constraints,
        "sources_used":      sources_used,
    }


# ── Persistence (central User Profile update rule) ───────────────────────────

def persist_baseline_snapshot(user_id: str, baseline: dict, engine=None) -> bool:
    """
    Store the computed baseline under master_profiles.master_profile
    ["baseline_snapshot"] — a non-destructive merge that never touches the
    onboarding fields or metrics_doc sharing the same JSON column.

    Returns True on success. Never raises: profiling must not break the
    interaction that triggered it.
    """
    if engine is None:
        from backend.core.database import ENGINE
        engine = ENGINE
    try:
        from sqlalchemy.orm import Session

        from backend.repositories import master_profile_repository

        # cv_data is rebuilt on demand by the pipeline; persisting it would
        # just duplicate the profile row's own contents.
        snapshot = {k: v for k, v in baseline.items() if k != "cv_data"}

        with Session(engine) as s:
            row, _created = master_profile_repository.get_or_create(
                s, user_id, now=_now().isoformat(),
            )
            merged = dict(row.master_profile or {})
            merged["baseline_snapshot"] = snapshot
            row.master_profile = merged
            row.updated_at     = _now().isoformat()
            s.commit()
        logger.info(
            "[profile_baseline] snapshot persisted user=%s tier=%s skills=%d",
            user_id, snapshot.get("profile_strength", {}).get("tier"),
            len(snapshot.get("skill_confidences", {})),
        )
        return True
    except Exception as exc:
        logger.warning("[profile_baseline] snapshot persist failed user=%s: %s", user_id, exc)
        return False


def refresh_baseline_snapshot(user_id: str) -> bool:
    """
    Rebuild and persist the baseline after a profiling interaction — the
    hook ariel_tools calls so every profile edit updates the central User
    Profile record (CLAUDE.md global rule). Best-effort, never raises.
    """
    try:
        return persist_baseline_snapshot(user_id, build_user_baseline(user_id))
    except Exception as exc:
        logger.warning("[profile_baseline] refresh failed user=%s: %s", user_id, exc)
        return False
