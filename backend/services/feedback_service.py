"""
Feedback Service — User Feedback Loop on Job Matches (JOB-57)
=============================================================

Captures thumbs-up / thumbs-down feedback on job matches and slowly adapts
the user's SOFT preferences from consistent patterns, improving future match
scoring without the user filling in a settings form.

What gets learned (and what never does)
---------------------------------------
The only value this module ever writes is the soft `culture_preference`
("startup" | "corporate" | "any") in role_preferences — the same key the
Dynamic Matching Score reads via _load_culture_prefs() (JOB-20). Provenance
is tracked in `culture_preference_source`:

  "explicit" (or any value with no source marker) — set by the user; the
              learner NEVER overwrites it.
  "learned"  — written by this module; may be updated or reverted to "any"
               as the evidence changes.

Hard constraints (work_type / remote-only, languages, salary floor) are
never touched: they are knockout-grade user statements, not preferences to
be second-guessed by a rating pattern.

Anti-overfitting design
-----------------------
  • MIN_CULTURE_EVENTS (5) rated jobs WITH culture signal are required
    before any adjustment — one angry downvote changes nothing.
  • Evidence is the MEAN signed signal across all rated jobs, so direction
    must be consistent: mixed ratings cancel out.
  • EVIDENCE_THRESHOLD (0.35) on the mean — weak leanings don't move the
    preference; and because the culture axis scales each event by how
    startup/corporate the job actually was (|axis−50|/50), ratings on
    neutral-culture jobs contribute almost nothing.
  • The learned value is categorical via thresholds, so repeated feedback
    saturates instead of compounding — the adjustment is bounded by design.
  • Evidence that later drops below threshold reverts a learned preference
    to "any" (only learned ones — explicit prefs are out of reach).

Evidence math
-------------
For each rated job with a known culture profile:

    signal = direction × (culture_axis − 50) / 50
    direction = +1 (thumbs_up) | −1 (thumbs_down)

so downvoting a corporate job (axis 20 → signal −1 × −0.6 = +0.6) and
upvoting a startup job (axis 80 → +0.6) both accumulate startup evidence.

    evidence = mean(signals)          (None until MIN_CULTURE_EVENTS signals)
    evidence ≥ +0.35 → "startup"
    evidence ≤ −0.35 → "corporate"
    otherwise        → "any" (revert if previously learned)

Every feedback interaction also updates the central User Profile record
(the .ai_rules global rule) through the learned-preference write and the
persisted feedback row itself.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

VALID_FEEDBACK_TYPES = ("thumbs_up", "thumbs_down")

MIN_CULTURE_EVENTS  = 5      # rated jobs with culture signal before any learning
EVIDENCE_THRESHOLD  = 0.35   # |mean signal| required to set a preference


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Job characteristics snapshot ──────────────────────────────────────────────

def build_job_snapshot(job, culture_profile=None) -> dict:
    """
    Freeze the rated job's characteristics. `job` is a JobMatch (duck-typed:
    title/company/score); `culture_profile` is the company's cached
    CompanyCultureProfile or None — feedback on companies without culture
    data is still stored (for audit/skills use) but carries no culture signal.
    """
    snap = {
        "title":            getattr(job, "title", "") or "",
        "company":          getattr(job, "company", "") or "",
        "match_score":      round(float(getattr(job, "score", 0.0) or 0.0), 1),
        "culture_axis":     None,
        "culture_category": None,
        "operational_pace": None,
        "work_model":       None,
    }
    if culture_profile is not None and getattr(culture_profile, "confidence", "low") != "low":
        category = getattr(culture_profile, "culture_category", "unknown")
        if category != "unknown":
            snap["culture_axis"]     = float(getattr(culture_profile, "culture_axis", 50.0))
            snap["culture_category"] = category
            snap["operational_pace"] = getattr(culture_profile, "operational_pace", "unknown")
            snap["work_model"]       = getattr(culture_profile, "work_model", "unknown")
    return snap


def _fetch_culture_profile_cached(company: str, engine=None):
    """Cached-only lookup — feedback recording must never trigger LLM research."""
    if not (company or "").strip():
        return None
    try:
        from backend.agents.company_culture import load_cached_profile
        return load_cached_profile(company, engine=engine)
    except Exception as exc:
        logger.warning("[feedback] culture cache lookup failed for %r: %s", company, exc)
        return None


# ── Pure learning functions ───────────────────────────────────────────────────

def culture_evidence(feedback_rows: list[dict]) -> tuple[Optional[float], int]:
    """
    Mean signed startup-vs-corporate signal across rated jobs.

    Returns (evidence, n_signals). evidence is None until MIN_CULTURE_EVENTS
    jobs with real culture signal have been rated — the no-single-event-
    overfitting gate. Positive evidence leans startup, negative corporate.
    """
    signals: list[float] = []
    for row in feedback_rows:
        snap = row.get("snapshot") or {}
        axis = snap.get("culture_axis")
        cat  = snap.get("culture_category")
        if axis is None or cat in (None, "unknown"):
            continue
        direction = 1.0 if row.get("feedback_type") == "thumbs_up" else -1.0
        signals.append(direction * (float(axis) - 50.0) / 50.0)

    if len(signals) < MIN_CULTURE_EVENTS:
        return None, len(signals)
    return round(sum(signals) / len(signals), 3), len(signals)


def preference_from_evidence(evidence: Optional[float]) -> Optional[str]:
    """
    Map evidence to a target soft preference. None ⇒ not enough data,
    make no change at all (distinct from "any", which actively reverts a
    previously learned preference).
    """
    if evidence is None:
        return None
    if evidence >= EVIDENCE_THRESHOLD:
        return "startup"
    if evidence <= -EVIDENCE_THRESHOLD:
        return "corporate"
    return "any"


# ── Persistence ───────────────────────────────────────────────────────────────

def _upsert_feedback_row(
    user_id: str,
    job_id: str,
    feedback_type: str,
    reason: Optional[str],
    snapshot: dict,
    engine,
) -> None:
    from backend.repositories import job_feedback_repository

    # Latest opinion wins; snapshot refreshes with the current job state.
    job_feedback_repository.upsert(
        user_id       = user_id,
        job_id        = job_id,
        feedback_type = feedback_type,
        reason        = (reason or "").strip() or None,
        snapshot_json = json.dumps(snapshot, ensure_ascii=False),
        now           = _now_iso(),
        engine        = engine,
    )


def fetch_feedback_rows(user_id: str, engine) -> list[dict]:
    from backend.repositories import job_feedback_repository

    return job_feedback_repository.fetch_for_user(user_id, engine=engine)


def _write_learned_preference(user_id: str, preference: str, engine) -> str:
    """
    Write the learned soft culture_preference into the SAME location the
    match pipeline reads (master_profiles → metrics_doc → role_preferences),
    with provenance, via a non-destructive merge.

    Returns one of:
      "updated"            — learned preference written/changed
      "unchanged"          — already at this value
      "explicit_untouched" — user set an explicit preference; never overwrite

    Hard constraints (work_type, languages, salary_min_usd) are read-only to
    this function by construction — it only ever touches culture_preference
    and culture_preference_source.
    """
    from sqlalchemy.orm import Session

    from backend.repositories import master_profile_repository

    with Session(engine) as s:
        row, _created = master_profile_repository.get_or_create(s, user_id, now=_now_iso())

        merged      = dict(row.master_profile or {})
        metrics_doc = dict(merged.get("metrics_doc") or {})
        if not metrics_doc.get("version"):
            # Full scaffold so master_profile_service.load() recognises the
            # doc and doesn't overwrite our write with a fresh template.
            from backend.services.master_profile_service import _empty_profile
            scaffold = _empty_profile()
            scaffold.update(metrics_doc)
            metrics_doc = scaffold
        prefs = dict(metrics_doc.get("role_preferences") or {})

        current = str(prefs.get("culture_preference") or "").lower() or None
        source  = str(prefs.get("culture_preference_source") or "").lower() or None

        # Any pre-existing value not marked as learned is treated as explicit.
        if current and source != "learned":
            return "explicit_untouched"
        if current == preference:
            return "unchanged"

        prefs["culture_preference"]        = preference
        prefs["culture_preference_source"] = "learned"
        metrics_doc["role_preferences"]    = prefs
        metrics_doc["last_updated"]        = _now_iso()
        merged["metrics_doc"]              = metrics_doc
        row.master_profile                 = merged
        row.updated_at                     = _now_iso()
        s.commit()
        return "updated"


# ── Learning orchestrator ─────────────────────────────────────────────────────

def apply_preference_learning(user_id: str, engine=None) -> dict:
    """
    Re-derive the learned soft culture_preference from the user's full
    feedback history. Idempotent: same history ⇒ same outcome.
    """
    if engine is None:
        from backend.core.database import ENGINE
        engine = ENGINE

    rows = fetch_feedback_rows(user_id, engine)
    evidence, n_signals = culture_evidence(rows)
    target = preference_from_evidence(evidence)

    if target is None:
        return {
            "culture_evidence":  evidence,
            "events_with_signal": n_signals,
            "culture_preference": None,
            "status": f"insufficient_data ({n_signals}/{MIN_CULTURE_EVENTS} culture-rated jobs)",
        }

    status = _write_learned_preference(user_id, target, engine)
    if status == "updated":
        logger.info(
            "[feedback] learned culture_preference=%r for user=%s "
            "(evidence=%.3f over %d rated jobs)",
            target, user_id, evidence, n_signals,
        )
    return {
        "culture_evidence":   evidence,
        "events_with_signal": n_signals,
        "culture_preference": target,
        "status":             status,
    }


# ── Public entry point ────────────────────────────────────────────────────────

def record_feedback(
    user_id: str,
    job_id: str,
    feedback_type: str,
    reason: Optional[str] = None,
    *,
    job=None,
    engine=None,
) -> dict:
    """
    Persist one thumbs-up/down event and run preference learning over the
    updated history. `job` may be passed by the route (already fetched for
    auth/404 handling); when None it is loaded from job_store.

    Raises ValueError for an invalid feedback_type or unknown job — routes
    translate these to 422/404.
    """
    if feedback_type not in VALID_FEEDBACK_TYPES:
        raise ValueError(
            f"Invalid feedback_type {feedback_type!r} — must be one of {VALID_FEEDBACK_TYPES}"
        )
    if engine is None:
        from backend.core.database import ENGINE
        engine = ENGINE

    if job is None:
        from backend.repositories import job_repository as job_store
        job = job_store.get_by_id(job_id, user_id)
    if job is None:
        raise ValueError(f"Job {job_id!r} not found for this user")

    culture_profile = _fetch_culture_profile_cached(getattr(job, "company", "") or "", engine=engine)
    snapshot = build_job_snapshot(job, culture_profile)
    _upsert_feedback_row(user_id, job_id, feedback_type, reason, snapshot, engine)

    learning = apply_preference_learning(user_id, engine)
    logger.info(
        "[feedback] user=%s job=%s %s (culture_signal=%s) → learning=%s",
        user_id, job_id, feedback_type,
        snapshot["culture_category"] or "none", learning["status"],
    )
    return {
        "job_id":              job_id,
        "feedback_type":       feedback_type,
        "snapshot":            snapshot,
        "preference_learning": learning,
    }
