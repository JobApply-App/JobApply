"""
Tests for the Dynamic Matching Score culture-fit integration (JOB-20).

Covers:
  • Alignment calculation between user preferences (JOB-18 baseline shape)
    and the company culture profile (JOB-19 schema).
  • Delta mapping — bounds, neutrality at 50, 1-decimal precision, and the
    Company Legacy clamp (negative deltas waived for prior employers).
  • finalize_composite weight distribution with and without the culture term.
  • REGRESSION GUARANTEE: with culture_delta=None (no signal / unknown
    profile / thin JD) every composite is bit-identical to the pre-culture
    formula.
  • Fallback behavior for unknown/low-confidence culture data.

Pure unit tests — no LLM, no DB.
"""
import pytest

from backend.agents.company_culture import build_profile_from_payload, build_sparse_profile
from backend.services.match_score_service import (
    CULTURE_MAX_ADJUST,
    compute_culture_alignment,
    culture_delta_from_alignment,
    finalize_composite,
)


def _culture(**over):
    payload = {
        "culture_axis":              78.0,
        "culture_category":          "startup",
        "operational_pace":          "fast",
        "formality":                 "casual",
        "work_model":                "onsite",
        "work_life_balance_signals": [],
        "accepted_persona_traits":   [],
        "operational_needs":         [],
        "evidence":                  ["x"],
        "confidence":                "high",
    }
    payload.update(over)
    return build_profile_from_payload("Acme", payload)


REMOTE_ONLY = {"work_model": "remote_only", "culture_preference": "any"}
FLEXIBLE    = {"work_model": None,          "culture_preference": "any"}


# ── Alignment calculation ─────────────────────────────────────────────────────

def test_remote_only_user_vs_company_work_models():
    for wm, expected in (("remote", 100.0), ("flexible", 85.0), ("hybrid", 40.0), ("onsite", 0.0)):
        alignment, note = compute_culture_alignment(_culture(work_model=wm), REMOTE_ONLY)
        assert alignment == expected
        assert wm in note


def test_unknown_work_model_contributes_no_signal():
    alignment, note = compute_culture_alignment(_culture(work_model="unknown"), REMOTE_ONLY)
    assert alignment is None
    assert note == ""


def test_flexible_user_gets_no_work_model_signal():
    alignment, _ = compute_culture_alignment(_culture(work_model="onsite"), FLEXIBLE)
    assert alignment is None


def test_startup_preference_follows_culture_axis():
    prefs = {"work_model": None, "culture_preference": "startup"}
    alignment, note = compute_culture_alignment(_culture(culture_axis=78.0), prefs)
    assert alignment == 78.0
    assert "startup" in note and "78.0" in note


def test_corporate_preference_inverts_culture_axis():
    prefs = {"work_model": None, "culture_preference": "corporate"}
    alignment, _ = compute_culture_alignment(_culture(culture_axis=78.0), prefs)
    assert alignment == 22.0


def test_multiple_signals_average():
    prefs = {"work_model": "remote_only", "culture_preference": "startup"}
    # remote work model (100.0) + axis 78.0 → mean 89.0
    alignment, note = compute_culture_alignment(
        _culture(work_model="remote", culture_axis=78.0), prefs,
    )
    assert alignment == 89.0
    assert ";" in note   # both signals explained


def test_low_confidence_profile_yields_no_alignment():
    prefs = {"work_model": "remote_only", "culture_preference": "startup"}
    assert compute_culture_alignment(_culture(confidence="low"), prefs) == (None, "")
    assert compute_culture_alignment(build_sparse_profile("Acme"), prefs) == (None, "")
    assert compute_culture_alignment(None, prefs) == (None, "")


def test_unknown_category_blocks_axis_signal_only():
    prefs = {"work_model": "remote_only", "culture_preference": "startup"}
    alignment, _ = compute_culture_alignment(
        _culture(culture_category="unknown", work_model="remote"), prefs,
    )
    assert alignment == 100.0   # work-model signal still counts


def test_alignment_is_one_decimal():
    prefs = {"work_model": "remote_only", "culture_preference": "startup"}
    alignment, _ = compute_culture_alignment(
        _culture(work_model="hybrid", culture_axis=66.7), prefs,
    )
    assert alignment == round(alignment, 1) == 53.4   # (40 + 66.7) / 2 = 53.35 → 53.4


# ── Delta mapping ──────────────────────────────────────────────────────────────

def test_delta_bounds_and_neutrality():
    assert culture_delta_from_alignment(100.0) == CULTURE_MAX_ADJUST
    assert culture_delta_from_alignment(0.0) == -CULTURE_MAX_ADJUST
    assert culture_delta_from_alignment(50.0) == 0.0
    assert culture_delta_from_alignment(None) is None


def test_delta_is_one_decimal_and_proportional():
    assert culture_delta_from_alignment(89.0) == 3.9    # (89-50)/50*5 = 3.9
    assert culture_delta_from_alignment(22.0) == -2.8   # (22-50)/50*5 = -2.8


def test_company_legacy_clamps_negative_delta_only():
    # Principle 2: culture may reward, never penalize, a prior employer.
    assert culture_delta_from_alignment(0.0, prior_employer=True) == 0.0
    assert culture_delta_from_alignment(22.0, prior_employer=True) == 0.0
    assert culture_delta_from_alignment(100.0, prior_employer=True) == CULTURE_MAX_ADJUST
    assert culture_delta_from_alignment(89.0, prior_employer=True) == 3.9


# ── finalize_composite: weights and regression guarantee ─────────────────────

def test_composite_unchanged_when_culture_delta_none():
    # The regression guarantee across every existing code path.
    cases = [
        dict(local=80.0, semantic=70.0, management=60.0),
        dict(local=80.0, semantic=70.0, management=60.0, ats_base=55.0),
        dict(local=80.0, semantic=70.0, management=60.0, ats_base=55.0, knockout_failed=True),
        dict(local=94.0, semantic=0.0, management=0.0),   # thin-JD shape
    ]
    for kw in cases:
        assert finalize_composite(**kw) == finalize_composite(**kw, culture_delta=None)


def test_culture_delta_shifts_composite_exactly():
    base = finalize_composite(80.0, 70.0, 60.0, ats_base=55.0)
    assert finalize_composite(80.0, 70.0, 60.0, ats_base=55.0, culture_delta=3.9) == \
           round(base + 3.9, 1)
    assert finalize_composite(80.0, 70.0, 60.0, ats_base=55.0, culture_delta=-2.8) == \
           round(base - 2.8, 1)


def test_existing_weight_distribution_is_untouched():
    # 0.30×local + 0.70×(5/7×sem + 2/7×mgmt), then 0.60/0.40 ATS blend.
    llm = 0.30 * 80.0 + 0.70 * (5 / 7 * 70.0 + 2 / 7 * 60.0)
    assert finalize_composite(80.0, 70.0, 60.0) == round(llm, 1)
    assert finalize_composite(80.0, 70.0, 60.0, ats_base=55.0) == \
           round(0.60 * llm + 0.40 * 55.0, 1)


def test_thin_jd_composite_shape_never_gains_culture():
    # Principle 4: thin path is exactly 0.30 × local — and the pipeline never
    # passes a culture_delta there (culture runs only in the full path).
    assert finalize_composite(94.0, 0.0, 0.0) == round(0.30 * 94.0, 1) == 28.2


def test_knockout_cap_applies_after_culture_delta():
    # A hard-constraint conflict cannot be bought back by good vibes.
    capped = finalize_composite(
        90.0, 95.0, 90.0, ats_base=90.0, knockout_failed=True, culture_delta=5.0,
    )
    assert capped == 40.0


def test_composite_stays_within_bounds_with_delta():
    assert finalize_composite(100.0, 100.0, 100.0, ats_base=100.0, culture_delta=5.0) == 100.0
    assert finalize_composite(0.0, 0.0, 0.0, ats_base=0.0, culture_delta=-5.0) == 0.0


# ── End-to-end fallback contract (no-signal ⇒ no effect) ──────────────────────

def test_unknown_profile_full_chain_produces_no_delta():
    prefs = {"work_model": "remote_only", "culture_preference": "startup"}
    alignment, _ = compute_culture_alignment(build_sparse_profile("Acme"), prefs)
    delta = culture_delta_from_alignment(alignment)
    assert delta is None
    base = finalize_composite(80.0, 70.0, 60.0, ats_base=55.0)
    assert finalize_composite(80.0, 70.0, 60.0, ats_base=55.0, culture_delta=delta) == base


def test_no_preferences_full_chain_produces_no_delta():
    alignment, _ = compute_culture_alignment(_culture(), FLEXIBLE)
    assert culture_delta_from_alignment(alignment) is None
