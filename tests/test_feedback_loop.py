"""
Tests for the User Feedback Loop (JOB-57).

Proves:
  • Feedback recording — upsert semantics (re-rating updates, never
    duplicates), snapshot capture with/without cached culture data.
  • Evidence math — consistent downvoting of corporate jobs accumulates
    startup evidence; mixed ratings cancel; neutral-culture jobs contribute
    almost nothing.
  • Anti-overfitting — no adjustment below MIN_CULTURE_EVENTS rated jobs,
    regardless of how strong a single event is; weak mean evidence below
    EVIDENCE_THRESHOLD changes nothing.
  • Preference safety — explicit user preferences are never overwritten;
    learned preferences update and revert as evidence changes; hard
    constraints (work_type) are never touched.
  • Multi-event convergence — the acceptance scenario end-to-end: a user
    with no explicit preference who consistently downvotes corporate jobs
    drifts to a learned "startup" preference, readable by the match
    pipeline's role_preferences location.

All tests run on an isolated SQLite engine — no LLM, no production DB.
"""
import json
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.agents.company_culture import build_profile_from_payload, save_cached_profile
from backend.core.database import Base
from backend.models.application import JobFeedbackRow
from backend.models.profile import MasterProfileRow
from backend.models import application, ariel, job, kv, matching, profile  # noqa: F401
from backend.services.feedback_service import (
    EVIDENCE_THRESHOLD,
    MIN_CULTURE_EVENTS,
    apply_preference_learning,
    build_job_snapshot,
    culture_evidence,
    fetch_feedback_rows,
    preference_from_evidence,
    record_feedback,
)

USER = "user-1"


@pytest.fixture
def engine(tmp_path):
    eng = create_engine(f"sqlite:///{tmp_path / 'feedback_test.db'}")
    Base.metadata.create_all(eng)
    return eng


def _job(job_id="j1", company="Acme", title="PM", score=82.3):
    return SimpleNamespace(job_id=job_id, title=title, company=company, score=score)


def _cache_culture(engine, company: str, axis: float, category: str = None):
    """Seed the company_culture cache so feedback picks up culture signal."""
    if category is None:
        category = "startup" if axis >= 50 else "corporate"
    profile = build_profile_from_payload(company, {
        "culture_axis": axis, "culture_category": category,
        "operational_pace": "fast" if axis >= 50 else "structured",
        "formality": "casual", "work_model": "hybrid",
        "evidence": ["x"], "confidence": "high",
    })
    save_cached_profile(profile, engine=engine)


def _feedback_row(feedback_type: str, axis, category="corporate") -> dict:
    return {
        "feedback_type": feedback_type,
        "snapshot": {"culture_axis": axis, "culture_category": category},
    }


def _prefs(engine, user_id=USER) -> dict:
    with Session(engine) as s:
        row = s.get(MasterProfileRow, user_id)
        if row is None:
            return {}
        return dict((row.master_profile.get("metrics_doc") or {}).get("role_preferences") or {})


def _set_explicit_prefs(engine, user_id=USER, **prefs):
    with Session(engine) as s:
        row = s.get(MasterProfileRow, user_id)
        if row is None:
            row = MasterProfileRow(
                user_id=user_id, onboarding_status="complete",
                master_profile={}, created_at="2026-01-01", updated_at="2026-01-01",
            )
            s.add(row)
        merged = dict(row.master_profile or {})
        doc = dict(merged.get("metrics_doc") or {"version": 1})
        doc["role_preferences"] = {**(doc.get("role_preferences") or {}), **prefs}
        merged["metrics_doc"] = doc
        row.master_profile = merged
        s.commit()


# ── Recording & upsert semantics ──────────────────────────────────────────────

def test_record_feedback_persists_row_and_snapshot(engine):
    _cache_culture(engine, "Acme", axis=22.0, category="corporate")
    result = record_feedback(USER, "j1", "thumbs_down", "too corporate for me",
                             job=_job(), engine=engine)
    rows = fetch_feedback_rows(USER, engine)
    assert len(rows) == 1
    assert rows[0]["feedback_type"] == "thumbs_down"
    assert rows[0]["reason"] == "too corporate for me"
    assert rows[0]["snapshot"]["culture_axis"] == 22.0
    assert rows[0]["snapshot"]["culture_category"] == "corporate"
    assert rows[0]["snapshot"]["match_score"] == 82.3   # 1-decimal
    assert result["preference_learning"]["culture_preference"] is None  # 1 event only


def test_rerating_updates_in_place_latest_wins(engine):
    record_feedback(USER, "j1", "thumbs_down", job=_job(), engine=engine)
    record_feedback(USER, "j1", "thumbs_up", job=_job(), engine=engine)
    rows = fetch_feedback_rows(USER, engine)
    assert len(rows) == 1
    assert rows[0]["feedback_type"] == "thumbs_up"
    with Session(engine) as s:
        assert s.query(JobFeedbackRow).count() == 1


def test_feedback_without_cached_culture_has_no_culture_signal(engine):
    record_feedback(USER, "j1", "thumbs_up", job=_job(company="NoCacheCo"), engine=engine)
    rows = fetch_feedback_rows(USER, engine)
    assert rows[0]["snapshot"]["culture_axis"] is None
    assert rows[0]["snapshot"]["culture_category"] is None


def test_invalid_feedback_type_rejected(engine):
    with pytest.raises(ValueError, match="feedback_type"):
        record_feedback(USER, "j1", "meh", job=_job(), engine=engine)


def test_unknown_job_rejected(engine):
    with pytest.raises(ValueError, match="not found"):
        record_feedback(USER, "missing", "thumbs_up", job=None, engine=engine)


def test_low_confidence_culture_profile_gives_no_signal():
    from backend.agents.company_culture import build_sparse_profile
    snap = build_job_snapshot(_job(), build_sparse_profile("Acme"))
    assert snap["culture_axis"] is None


# ── Evidence math ──────────────────────────────────────────────────────────────

def test_downvoting_corporate_jobs_accumulates_startup_evidence():
    rows = [_feedback_row("thumbs_down", axis=20.0) for _ in range(5)]
    evidence, n = culture_evidence(rows)
    assert n == 5
    assert evidence == 0.6            # −1 × (20−50)/50 = +0.6 each
    assert preference_from_evidence(evidence) == "startup"


def test_upvoting_corporate_jobs_accumulates_corporate_evidence():
    rows = [_feedback_row("thumbs_up", axis=20.0) for _ in range(5)]
    evidence, _ = culture_evidence(rows)
    assert evidence == -0.6
    assert preference_from_evidence(evidence) == "corporate"


def test_mixed_ratings_cancel_out():
    rows = (
        [_feedback_row("thumbs_down", axis=20.0) for _ in range(3)]   # +0.6 each
        + [_feedback_row("thumbs_up", axis=20.0) for _ in range(3)]   # −0.6 each
    )
    evidence, n = culture_evidence(rows)
    assert n == 6
    assert evidence == 0.0
    assert preference_from_evidence(evidence) == "any"


def test_neutral_culture_jobs_contribute_almost_nothing():
    rows = [_feedback_row("thumbs_down", axis=48.0) for _ in range(10)]
    evidence, _ = culture_evidence(rows)
    assert evidence == 0.04            # tiny — never crosses the threshold
    assert preference_from_evidence(evidence) == "any"


def test_jobs_without_culture_signal_are_excluded():
    rows = (
        [_feedback_row("thumbs_down", axis=None, category=None) for _ in range(10)]
        + [_feedback_row("thumbs_down", axis=20.0)] * 2
    )
    evidence, n = culture_evidence(rows)
    assert evidence is None            # only 2 signals < MIN_CULTURE_EVENTS
    assert n == 2


# ── Anti-overfitting gates ─────────────────────────────────────────────────────

def test_below_min_events_no_learning_even_with_extreme_signal():
    rows = [_feedback_row("thumbs_down", axis=0.0)] * (MIN_CULTURE_EVENTS - 1)
    evidence, _ = culture_evidence(rows)
    assert evidence is None
    assert preference_from_evidence(evidence) is None   # no change AT ALL


def test_single_event_changes_nothing_end_to_end(engine):
    _cache_culture(engine, "MegaCorp", axis=5.0, category="corporate")
    record_feedback(USER, "j1", "thumbs_down", job=_job(company="MegaCorp"), engine=engine)
    assert _prefs(engine).get("culture_preference") is None


def test_weak_mean_evidence_below_threshold_learns_any():
    # 5 events but weak/inconsistent — evidence below threshold → "any"
    rows = [_feedback_row("thumbs_down", axis=40.0)] * 5   # +0.2 each
    evidence, _ = culture_evidence(rows)
    assert evidence == 0.2 < EVIDENCE_THRESHOLD
    assert preference_from_evidence(evidence) == "any"


def test_threshold_boundary_is_inclusive():
    assert preference_from_evidence(EVIDENCE_THRESHOLD) == "startup"
    assert preference_from_evidence(-EVIDENCE_THRESHOLD) == "corporate"
    assert preference_from_evidence(EVIDENCE_THRESHOLD - 0.001) == "any"


# ── Preference safety ──────────────────────────────────────────────────────────

def test_explicit_preference_is_never_overwritten(engine):
    _set_explicit_prefs(engine, culture_preference="corporate")   # no source ⇒ explicit
    _cache_culture(engine, "MegaCorp", axis=10.0, category="corporate")
    for i in range(8):
        record_feedback(USER, f"j{i}", "thumbs_down",
                        job=_job(job_id=f"j{i}", company="MegaCorp"), engine=engine)
    prefs = _prefs(engine)
    assert prefs["culture_preference"] == "corporate"             # untouched
    assert prefs.get("culture_preference_source") != "learned"


def test_hard_constraints_are_never_touched(engine):
    _set_explicit_prefs(engine, work_type="remote", languages=["hebrew", "english"])
    _cache_culture(engine, "MegaCorp", axis=10.0, category="corporate")
    for i in range(8):
        record_feedback(USER, f"j{i}", "thumbs_down",
                        job=_job(job_id=f"j{i}", company="MegaCorp"), engine=engine)
    prefs = _prefs(engine)
    assert prefs["work_type"] == "remote"                          # hard constraint intact
    assert prefs["languages"] == ["hebrew", "english"]
    assert prefs["culture_preference"] == "startup"                # soft pref learned
    assert prefs["culture_preference_source"] == "learned"


def test_learned_preference_reverts_when_evidence_fades(engine):
    _cache_culture(engine, "MegaCorp", axis=10.0, category="corporate")
    _cache_culture(engine, "ScrappyCo", axis=90.0, category="startup")
    # Phase 1: consistent anti-corporate signal → learned "startup"
    for i in range(5):
        record_feedback(USER, f"down{i}", "thumbs_down",
                        job=_job(job_id=f"down{i}", company="MegaCorp"), engine=engine)
    assert _prefs(engine)["culture_preference"] == "startup"
    # Phase 2: user starts loving corporate jobs — evidence collapses
    for i in range(5):
        record_feedback(USER, f"up{i}", "thumbs_up",
                        job=_job(job_id=f"up{i}", company="MegaCorp"), engine=engine)
    prefs = _prefs(engine)
    assert prefs["culture_preference"] in ("any", "corporate")     # no stale "startup"
    assert prefs["culture_preference_source"] == "learned"


# ── Acceptance scenario: gradual multi-event convergence ─────────────────────

def test_consistent_corporate_downvotes_gradually_learn_startup(engine):
    """
    The issue's core scenario: no explicit preference; user downvotes
    corporate jobs one by one. Nothing moves until MIN_CULTURE_EVENTS, then
    the soft preference lands on "startup" — in the exact role_preferences
    location the match pipeline (_load_culture_prefs) reads, with a
    version-carrying metrics_doc so master_profile_service.load() preserves it.
    """
    _cache_culture(engine, "BigBank", axis=15.0, category="corporate")

    for i in range(MIN_CULTURE_EVENTS - 1):
        record_feedback(USER, f"j{i}", "thumbs_down",
                        job=_job(job_id=f"j{i}", company="BigBank"), engine=engine)
        assert _prefs(engine).get("culture_preference") is None   # not yet — no overfit

    result = record_feedback(USER, "j-final", "thumbs_down",
                             job=_job(job_id="j-final", company="BigBank"), engine=engine)

    assert result["preference_learning"]["culture_preference"] == "startup"
    assert result["preference_learning"]["status"] == "updated"
    prefs = _prefs(engine)
    assert prefs["culture_preference"] == "startup"
    assert prefs["culture_preference_source"] == "learned"

    with Session(engine) as s:
        doc = s.get(MasterProfileRow, USER).master_profile["metrics_doc"]
    assert doc.get("version")   # load() recognises the doc → match path sees the pref


def test_learning_is_idempotent_over_repeated_runs(engine):
    _cache_culture(engine, "BigBank", axis=15.0, category="corporate")
    for i in range(6):
        record_feedback(USER, f"j{i}", "thumbs_down",
                        job=_job(job_id=f"j{i}", company="BigBank"), engine=engine)
    first = _prefs(engine)
    out = apply_preference_learning(USER, engine=engine)
    assert out["status"] == "unchanged"
    assert _prefs(engine) == first
