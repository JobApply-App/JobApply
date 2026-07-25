"""
Tests for the deep user-profiling baseline (JOB-18).

Covers:
  • Source weighting — reliability ordering and recency decay, including the
    headline requirement: a recently-confirmed chat answer outweighs a stale
    resume line.
  • Per-skill confidence blending (corroboration, 1-decimal precision).
  • Explicit constraints vs inferred skills (proficiency overrides, knockout
    prefs) — including conflicting-constraint edge cases.
  • Degradation states — honest partial scores for incomplete profiles.
  • cv_data strict schema conformance for match_score_service, with the
    Data Completeness principle verified (no truncation, order preserved).
  • Baseline persistence — non-destructive merge into master_profiles.

All build_user_baseline tests inject their data sources — no production DB,
no LLM calls.
"""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.core.database import Base
from backend.models.profile import MasterProfileRow
from backend.models import application, ariel, job, kv, matching, profile  # noqa: F401
from backend.services.profile_baseline_service import (
    apply_proficiency_override,
    assess_completeness,
    blend_skill_confidence,
    build_cv_data,
    build_user_baseline,
    persist_baseline_snapshot,
    source_weight,
)

NOW = datetime(2026, 7, 10, tzinfo=timezone.utc)


def _iso(days_ago: int) -> str:
    return (NOW - timedelta(days=days_ago)).isoformat()


def _metric(value: str, days_ago: int) -> dict:
    return {
        "value":      value,
        "source":     "supplemental",
        "confidence": "high",
        "created_at": _iso(days_ago),
        "updated_at": _iso(days_ago),
    }


def _profile(**over) -> dict:
    base = {
        "personal":     {"name": "Ron", "title": "Product Manager"},
        "summary":      "PM with B2B SaaS background.",
        "education":    [{"degree": "B.Sc.", "field": "Industrial Engineering"}],
        "experience": [
            {"company": "Acme", "role": "Product Manager",
             "period": "2023 - 2026", "details": "Owned roadmap and PRDs."},
            {"company": "Globex", "role": "CS Team Lead",
             "period": "2020 - 2023", "details": "Led team of 5."},
        ],
        "skills":       ["Python", "SQL", "Jira"],
        "career_goals": {"preferred_locations": ["Tel Aviv"], "work_environment": "hybrid"},
    }
    base.update(over)
    return base


# ── Source weighting: reliability × recency ───────────────────────────────────

def test_fresh_chat_answer_outweighs_stale_resume_line():
    # The JOB-18 headline requirement, verified numerically.
    fresh_chat   = source_weight("chat_answer", age_days=0)
    stale_resume = source_weight("resume",      age_days=730)   # 2-year-old CV line
    assert fresh_chat > stale_resume
    assert fresh_chat == pytest.approx(0.85)
    assert stale_resume < 0.25


def test_reliability_ordering_at_equal_freshness():
    order = [
        source_weight("verified_evidence",     age_days=0),
        source_weight("explicit_confirmation", age_days=0),
        source_weight("chat_answer",           age_days=0),
        source_weight("resume",                age_days=0),
        source_weight("inferred",              age_days=0),
    ]
    assert order == sorted(order, reverse=True)


def test_recency_decay_is_monotonic():
    weights = [source_weight("chat_answer", age_days=d) for d in (0, 90, 270, 540, 1080)]
    assert weights == sorted(weights, reverse=True)
    assert weights[2] == pytest.approx(weights[0] / 2, abs=0.01)   # one half-life


def test_verified_evidence_is_never_double_decayed():
    # Confidence-Matrix scores arrive pre-decayed; age must not reduce them.
    assert source_weight("verified_evidence", age_days=1000) == \
           source_weight("verified_evidence", age_days=0)


def test_strength_scales_partial_signals():
    full    = source_weight("verified_evidence", strength=1.0)
    partial = source_weight("verified_evidence", strength=0.62)
    assert partial == pytest.approx(full * 0.62)


# ── Confidence blending ────────────────────────────────────────────────────────

def test_corroborating_sources_raise_confidence():
    resume_only = blend_skill_confidence([("resume", 1.0, 0.0)])
    corroborated = blend_skill_confidence([
        ("resume", 1.0, 0.0), ("chat_answer", 1.0, 0.0),
    ])
    assert corroborated > resume_only
    assert corroborated <= 100.0


def test_blend_precision_is_one_decimal():
    score = blend_skill_confidence([("resume", 1.0, 100.0), ("chat_answer", 0.7, 33.0)])
    assert score == round(score, 1)


def test_blend_empty_signals_is_zero():
    assert blend_skill_confidence([]) == 0.0


# ── Explicit constraints beat inferred skills ─────────────────────────────────

def test_explicit_none_zeroes_resume_claim():
    # Conflict: resume claims the skill, user explicitly said "no experience".
    inferred = blend_skill_confidence([("resume", 1.0, 0.0)])
    assert inferred > 0
    assert apply_proficiency_override(inferred, "none") == 0.0


def test_academic_statement_dampens_score():
    assert apply_proficiency_override(80.0, "academic") == 36.0


def test_unknown_and_professional_levels_do_not_dampen():
    assert apply_proficiency_override(77.7, "professional") == 77.7
    assert apply_proficiency_override(77.7, None) == 77.7


# ── Degradation states ─────────────────────────────────────────────────────────

def test_full_profile_is_not_degraded():
    strength = assess_completeness(
        _profile(), {"any_answer": _metric("yes", 1)},
        [{"score": 55.0}],
    )
    assert strength["tier"] == "full"
    assert strength["degradation_factor"] == 1.0
    assert strength["is_degraded"] is False
    assert strength["missing_sections"] == []


def test_empty_profile_is_minimal_and_honest():
    strength = assess_completeness({}, {}, [])
    assert strength["tier"] == "minimal"
    assert strength["is_degraded"] is True
    assert strength["coverage_pct"] == 0.0
    assert set(strength["missing_sections"]) == {
        "experience", "skills", "summary", "education",
        "chat_answers", "verified_evidence",
    }


def test_partial_profile_reports_what_is_missing():
    strength = assess_completeness(
        {"experience": [{"role": "PM"}], "skills": ["python"], "summary": "x"},
        {}, [],
    )
    assert strength["tier"] == "partial"
    assert strength["degradation_factor"] == 0.85
    assert "chat_answers" in strength["missing_sections"]
    assert "verified_evidence" in strength["missing_sections"]


def test_degradation_caps_skill_confidence():
    # Same signals, sparser profile → lower (honest) confidence.
    rich = build_user_baseline(
        "u1", profile=_profile(),
        metrics_doc={"metrics": {"verify_python_usage_context":
                                 _metric("professional experience at work", 5)},
                     "last_updated": _iso(5)},
        entity_scores=[{"name": "Python", "score": 70.0}],
        now=NOW,
    )
    sparse = build_user_baseline(
        "u2", profile={"skills": ["Python"]},
        metrics_doc={"metrics": {}, "last_updated": _iso(0)},
        entity_scores=[],
        now=NOW,
    )
    assert rich["profile_strength"]["tier"] == "full"
    assert sparse["profile_strength"]["tier"] == "minimal"
    assert sparse["skill_confidences"]["python"] < rich["skill_confidences"]["python"]
    # Sparse profile's fresh resume-only claim, degraded: 55.0 × 0.6 = 33.0
    assert sparse["skill_confidences"]["python"] == 33.0


# ── cv_data schema conformance (match_score_service input) ────────────────────

def test_cv_data_matches_matcher_schema_exactly():
    cv = build_cv_data(_profile(), user_id="test-user")
    assert set(cv.keys()) == {"title", "summary", "experience", "skills"}
    assert isinstance(cv["title"], str)
    assert isinstance(cv["summary"], str)
    assert isinstance(cv["experience"], list)
    for e in cv["experience"]:
        assert set(e.keys()) == {"role", "company", "bullets"}
        assert isinstance(e["bullets"], list)
    assert set(cv["skills"].keys()) == {"categories"}
    assert cv["skills"]["categories"][0]["label"] == "Skills"
    assert cv["skills"]["categories"][0]["items"] == ["Python", "SQL", "Jira"]


def test_cv_data_never_truncates_experience():
    # Data Completeness principle: 30 entries in, 30 entries out, order kept.
    many = _profile(experience=[
        {"company": f"Co{i}", "role": f"Role{i}", "details": f"d{i}"}
        for i in range(30)
    ])
    cv = build_cv_data(many, user_id="test-user")
    assert len(cv["experience"]) == 30
    assert [e["company"] for e in cv["experience"]] == [f"Co{i}" for i in range(30)]


def test_cv_data_flattens_nested_roles():
    prof = _profile(experience=[{
        "company": "MegaCorp",
        "role":    "Manager",
        "roles": [
            {"title": "Senior PM", "details": "Led product."},
            {"title": "PM",        "details": "Shipped features."},
        ],
    }])
    cv = build_cv_data(prof, user_id="test-user")
    assert len(cv["experience"]) == 2
    assert cv["experience"][0] == {
        "role": "Senior PM", "company": "MegaCorp", "bullets": ["Led product."],
    }


def test_cv_data_missing_fields_do_not_crash():
    cv = build_cv_data({}, user_id="test-user")
    assert cv["experience"] == []
    assert cv["skills"]["categories"][0]["items"] == []


# ── build_user_baseline end-to-end (injected sources) ─────────────────────────

def test_rich_chat_sparse_resume_is_sensible():
    baseline = build_user_baseline(
        "u1",
        profile={"skills": [], "experience": [], "summary": "", "education": []},
        metrics_doc={
            "metrics": {
                "verify_python_usage_context": _metric("professional experience at work", 3),
                "team_size_context":           _metric("led a team of 5", 10),
            },
            "last_updated": _iso(3),
        },
        entity_scores=[{"name": "Python", "score": 68.0}],
        now=NOW,
    )
    python = baseline["skill_confidences"]["python"]
    assert 0.0 < python <= 100.0
    assert python == round(python, 1)
    # Chat-derived facts registered as sources even with an empty resume
    assert "explicit_confirmation" in baseline["sources_used"]
    assert "verified_evidence" in baseline["sources_used"]
    assert baseline["profile_strength"]["is_degraded"] is True   # honest: no resume


def test_sparse_chat_rich_resume_is_sensible():
    baseline = build_user_baseline(
        "u1", profile=_profile(),
        metrics_doc={"metrics": {}, "last_updated": _iso(2)},
        entity_scores=[],
        now=NOW,
    )
    assert baseline["skill_confidences"]["python"] > 0.0
    assert baseline["sources_used"] == ["resume"]
    # No chat answers and no verified evidence → honest partial, not full
    assert baseline["profile_strength"]["tier"] == "partial"


def test_conflicting_constraint_explicit_none_wins_end_to_end():
    baseline = build_user_baseline(
        "u1",
        profile=_profile(skills=["Python"]),   # resume claims Python
        metrics_doc={
            "metrics": {"verify_python_usage_context":
                        _metric("no experience, never used professionally or otherwise", 1)},
            "last_updated": _iso(1),
        },
        entity_scores=[],
        now=NOW,
    )
    assert baseline["skill_confidences"]["python"] == 0.0
    assert baseline["constraints"]["soft_proficiencies"]["python"] == "none"


def test_hard_constraints_are_separated_from_inferred_skills():
    baseline = build_user_baseline(
        "u1", profile=_profile(),
        metrics_doc={
            "metrics": {},
            "last_updated": _iso(1),
            "role_preferences": {
                "work_type":           "remote",
                "languages":           ["Hebrew", "English"],
                "salary_min_usd":      120000,
                "preferred_locations": ["Tel Aviv"],
            },
        },
        entity_scores=[],
        now=NOW,
    )
    hard = baseline["constraints"]["hard"]
    assert hard["work_model"] == "remote_only"
    assert hard["languages"] == ["hebrew", "english"]
    assert hard["salary_min_usd"] == 120000
    assert hard["preferred_locations"] == ["Tel Aviv"]


def test_flexible_work_type_never_becomes_a_knockout():
    for work_type in ("any", "hybrid", "onsite"):
        baseline = build_user_baseline(
            "u1", profile=_profile(),
            metrics_doc={"metrics": {}, "last_updated": _iso(1),
                         "role_preferences": {"work_type": work_type}},
            entity_scores=[],
            now=NOW,
        )
        assert baseline["constraints"]["hard"]["work_model"] is None


def test_all_baseline_scores_are_one_decimal():
    baseline = build_user_baseline(
        "u1", profile=_profile(),
        metrics_doc={
            "metrics": {
                "verify_sql_usage_context": _metric("used at work in production", 40),
                "jira_context":             _metric("daily driver for 3 years", 200),
            },
            "last_updated": _iso(7),
        },
        entity_scores=[{"name": "SQL", "score": 61.3}],
        now=NOW,
    )
    for skill, score in baseline["skill_confidences"].items():
        assert score == round(score, 1), f"{skill} not 1-decimal: {score}"
    assert baseline["profile_strength"]["coverage_pct"] == \
           round(baseline["profile_strength"]["coverage_pct"], 1)


# ── Baseline persistence (central User Profile update) ───────────────────────

@pytest.fixture
def engine(tmp_path):
    eng = create_engine(f"sqlite:///{tmp_path / 'baseline_test.db'}")
    Base.metadata.create_all(eng)
    return eng


def test_persist_snapshot_is_non_destructive(engine):
    # Pre-existing row with onboarding data that must survive the merge.
    with Session(engine) as s:
        s.add(MasterProfileRow(
            user_id="u1",
            onboarding_status="complete",
            master_profile={"skills": ["Python"], "metrics_doc": {"version": 1}},
            created_at=_iso(30), updated_at=_iso(30),
        ))
        s.commit()

    baseline = build_user_baseline(
        "u1", profile=_profile(),
        metrics_doc={"metrics": {}, "last_updated": _iso(1)},
        entity_scores=[], now=NOW,
    )
    assert persist_baseline_snapshot("u1", baseline, engine=engine) is True

    with Session(engine) as s:
        row = s.get(MasterProfileRow, "u1")
        mp = row.master_profile
        # Existing keys untouched
        assert mp["skills"] == ["Python"]
        assert mp["metrics_doc"] == {"version": 1}
        # Snapshot written, cv_data intentionally excluded
        snap = mp["baseline_snapshot"]
        assert "cv_data" not in snap
        assert snap["profile_strength"]["tier"] == "partial"
        assert snap["skill_confidences"]


def test_persist_snapshot_creates_row_for_new_user(engine):
    baseline = build_user_baseline(
        "new-user", profile=_profile(),
        metrics_doc={"metrics": {}, "last_updated": _iso(1)},
        entity_scores=[], now=NOW,
    )
    assert persist_baseline_snapshot("new-user", baseline, engine=engine) is True
    with Session(engine) as s:
        row = s.get(MasterProfileRow, "new-user")
        assert row is not None
        assert "baseline_snapshot" in row.master_profile


def test_persist_snapshot_failure_is_swallowed():
    class ExplodingEngine:
        pass   # Session(engine) will fail on use

    baseline = {"skill_confidences": {}, "profile_strength": {"tier": "minimal"}}
    assert persist_baseline_snapshot("u1", baseline, engine=ExplodingEngine()) is False
