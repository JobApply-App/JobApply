"""
Ariel Steering Agent + structural match-scoring dimensions.

Split by what each test actually needs:

  • Pure tests (the majority) construct their inputs directly and touch no
    database. match_dimensions.py was written to make this possible — every
    scoring input is a parameter, so the whole deterministic half of the match
    score is testable without Postgres, an LLM, or a live profile.

  • DB-backed tests use the `disposable_qa_account` fixture (see conftest.py):
    a real, brand-new Supabase account, cascade-deleted on teardown. They never
    touch a pre-existing account's rows.

Why the inferred-skill tests matter more than they look
---------------------------------------------------------
An LLM-inferred capability is a hypothesis. Printing a hypothesis onto a CV the
user sends to an employer is a fabrication, not a ranking imprecision — so
`test_inferred_skill_*` guards a correctness boundary, not a preference. There
are two independent locks on that door (profile_repository._read_cv's origin
filter for the CV path, _skill_depth_map's for the scoring path) and both are
tested here, because a single lock that silently stops working is exactly the
kind of failure nobody notices until it is in someone's resume.
"""
from __future__ import annotations

import pytest

from backend.services import ariel_steering_service as steering
from backend.services.match_dimensions import (
    LEGACY_FLOOR,
    TRANSFERABLE_DEPTH_FLOOR,
    TRANSFERABLE_SKILL_FLOOR,
    blend_structural,
    compute_dimensions,
    score_depth_breadth,
    score_domain_context,
    score_hard_skills,
    _equivalent,
    _norm,
    _recency_factor,
    _seniority_fit,
)


# ═════════════════════════════════════════════════════════════════════════════
# Scoring — skill equivalence
# ═════════════════════════════════════════════════════════════════════════════

def test_exact_skill_match_scores_full():
    score, matched, missing, equivalences = score_hard_skills(
        must_haves=["Python", "SQL"],
        nice_haves=[],
        profile_skills=["Python", "SQL"],
    )
    assert score == 100.0
    assert set(matched) == {"Python", "SQL"}
    assert missing == []
    assert equivalences == []  # exact matches are not reported as equivalences


def test_taxonomy_equivalent_skill_counts_as_a_match():
    """'ReactJS' in the JD must be satisfied by 'React' on the profile."""
    equivalence = {"reactjs": {"react", "reactjs", "react js"}, "react": {"react", "reactjs", "react js"}}
    score, matched, missing, equivalences = score_hard_skills(
        must_haves=["ReactJS"],
        nice_haves=[],
        profile_skills=["React"],
        equivalence=equivalence,
    )
    assert score == 100.0
    assert matched == ["ReactJS"]
    assert missing == []
    assert equivalences == ["ReactJS ≈ react"]


def test_equivalence_is_reported_but_exact_match_is_not():
    equivalence = {"k8s": {"kubernetes", "k8s"}, "kubernetes": {"kubernetes", "k8s"}}
    _, _, _, equivalences = score_hard_skills(
        must_haves=["Python", "K8s"],
        nice_haves=[],
        profile_skills=["Python", "Kubernetes"],
        equivalence=equivalence,
    )
    assert equivalences == ["K8s ≈ kubernetes"]


def test_must_haves_outweigh_nice_to_haves():
    """Covering the required skill must beat covering three optional ones."""
    required_only, _, _, _ = score_hard_skills(
        must_haves=["Python"], nice_haves=["Go", "Rust", "Elixir"],
        profile_skills=["Python"],
    )
    optional_only, _, _, _ = score_hard_skills(
        must_haves=["Python"], nice_haves=["Go", "Rust", "Elixir"],
        profile_skills=["Go", "Rust", "Elixir"],
    )
    assert required_only > optional_only


def test_token_containment_does_not_match_substrings():
    """'react' must not be satisfied by 'reaction' — whole tokens only."""
    assert _equivalent("react", {"reaction planning"}, {}) is None
    assert _equivalent("product", {"product management"}) is not None


def test_transferable_floor_applies_only_with_adjacent_signal():
    """A related-but-partial profile floors; a wholly unrelated one does not."""
    adjacent, _, _, _ = score_hard_skills(
        must_haves=["Python", "SQL", "Go", "Rust", "Scala", "Elixir"],
        nice_haves=[],
        profile_skills=["Python"],   # 1 of 6 — below the floor, but real overlap
    )
    assert adjacent == TRANSFERABLE_SKILL_FLOOR

    unrelated, _, _, _ = score_hard_skills(
        must_haves=["Python", "SQL", "Go"],
        nice_haves=[],
        profile_skills=["Woodworking", "Pottery"],
    )
    assert unrelated == 0.0   # no adjacency — the floor must not rescue this


def test_jd_with_no_stated_requirements_scores_neutral_not_zero():
    """Missing information is not evidence of a bad match."""
    score, _, _, _ = score_hard_skills([], [], ["Python"])
    assert score == 50.0


# ═════════════════════════════════════════════════════════════════════════════
# Scoring — depth vs breadth (the case the ticket calls out by name)
# ═════════════════════════════════════════════════════════════════════════════

def test_deep_partial_coverage_beats_shallow_complete_coverage():
    """
    The ticket's own example: 5 years across 70% of the required skills should
    outrank 1 year across 100% of them, for a role demanding 5 years.
    """
    must = ["python", "sql", "aws", "docker", "kubernetes",
            "terraform", "go", "kafka", "spark", "airflow"]

    deep_profile = must[:7]                       # 70% breadth
    deep_depth = {s: {"years": 5.0, "last_used_year": 2026} for s in deep_profile}

    broad_profile = list(must)                    # 100% breadth
    broad_depth = {s: {"years": 1.0, "last_used_year": 2026} for s in broad_profile}

    deep_score, _ = score_depth_breadth(
        must, deep_profile, deep_depth, required_years=5.0, now_year=2026,
    )
    broad_score, _ = score_depth_breadth(
        must, broad_profile, broad_depth, required_years=5.0, now_year=2026,
    )
    assert deep_score > broad_score, (
        f"deep-but-narrow ({deep_score}) should outrank shallow-but-complete "
        f"({broad_score}) for a 5-year role"
    )


def test_full_coverage_with_full_depth_beats_both():
    must = ["python", "sql", "aws"]
    depth = {s: {"years": 6.0, "last_used_year": 2026} for s in must}
    best, _ = score_depth_breadth(must, must, depth, required_years=5.0, now_year=2026)

    partial_depth = {s: {"years": 1.0, "last_used_year": 2026} for s in must}
    worse, _ = score_depth_breadth(must, must, partial_depth, required_years=5.0, now_year=2026)
    assert best > worse


def test_overqualification_is_never_penalised():
    """CLAUDE.md Principle 3 — more experience must never score lower."""
    assert _seniority_fit(candidate_years=3.0, required_years=3.0) == 1.0
    assert _seniority_fit(candidate_years=10.0, required_years=3.0) == 1.0
    assert _seniority_fit(candidate_years=30.0, required_years=3.0) == 1.0

    must = ["python"]
    exact, _ = score_depth_breadth(must, must, {"python": {"years": 3.0}}, required_years=3.0)
    over, _  = score_depth_breadth(must, must, {"python": {"years": 20.0}}, required_years=3.0)
    assert over == exact


def test_under_experience_scales_down_but_never_to_zero():
    assert _seniority_fit(1.0, 10.0) == pytest.approx(0.35)   # clamped at the floor
    assert 0.35 < _seniority_fit(4.0, 5.0) < 1.0


def test_unknown_years_is_neutral_not_a_penalty():
    """Missing years-of-experience is a gap in our data, not in their career."""
    must = ["python", "sql"]
    known, _   = score_depth_breadth(must, must, {"python": {"years": 5.0}, "sql": {"years": 5.0}},
                                     required_years=5.0)
    unknown, _ = score_depth_breadth(must, must, {}, required_years=5.0)
    # Unknown is damped by coverage_confidence but must stay in the same league,
    # never collapse toward zero.
    assert unknown >= known * 0.8


def test_recency_decays_gently_and_never_to_zero():
    assert _recency_factor(2026, now_year=2026) == 1.0
    assert _recency_factor(2024, now_year=2026) == 1.0          # inside grace window
    recent, stale = _recency_factor(2023, 2026), _recency_factor(2005, 2026)
    assert recent > stale >= 0.55
    assert _recency_factor(None) == 1.0                          # unknown ≠ stale


def test_no_overlap_floors_only_when_profile_has_skills():
    floored, _ = score_depth_breadth(["python"], ["woodworking"], {})
    assert floored == TRANSFERABLE_DEPTH_FLOOR
    empty, _ = score_depth_breadth(["python"], [], {})
    assert empty == 0.0


# ═════════════════════════════════════════════════════════════════════════════
# Scoring — domain context & prior employer
# ═════════════════════════════════════════════════════════════════════════════

def test_prior_employer_applies_the_legacy_floor():
    score, legacy, _ = score_domain_context(
        jd_text="We are hiring a PM",
        target_company="Monday.com",
        profile_domains=["Fintech"],
        experience=[{"company": "Monday.com", "role": "PM"}],
    )
    assert score == LEGACY_FLOOR
    assert legacy == "Monday.com"


def test_prior_employer_match_is_word_boundary_not_substring():
    """The documented 'River' ⊄ 'Riverside' guard (CLAUDE.md Principle 2)."""
    _, legacy, _ = score_domain_context(
        jd_text="",
        target_company="Riverside Technologies",
        profile_domains=[],
        experience=[{"company": "River", "role": "Server"}],
    )
    assert legacy is None


def test_domain_overlap_scores_above_no_overlap():
    hit, _, _ = score_domain_context(
        "We build B2B SaaS for fintech", "Acme", ["Fintech"], [],
    )
    miss, _, _ = score_domain_context(
        "We build agricultural equipment", "Acme", ["Fintech"], [],
    )
    assert hit > miss


# ═════════════════════════════════════════════════════════════════════════════
# Scoring — blend & principle compliance
# ═════════════════════════════════════════════════════════════════════════════

def test_structural_weights_sum_to_one():
    assert blend_structural(100.0, 100.0, 100.0, 100.0) == 100.0
    assert blend_structural(0.0, 0.0, 0.0, 0.0) == 0.0


def test_compute_dimensions_end_to_end():
    dims = compute_dimensions(
        must_haves=["Product Management", "SQL"],
        nice_haves=["Figma"],
        profile_skills=["Product Management", "SQL", "Figma"],
        skill_depth={"product management": {"years": 6.0, "last_used_year": 2026},
                     "sql": {"years": 4.0, "last_used_year": 2026}},
        profile_domains=["B2B SaaS"],
        experience=[{"company": "Acme Corp", "role": "PM"}],
        jd_text="Senior PM for our B2B SaaS platform. 4+ years required.",
        target_company="Globex",
        required_years=4.0,
        impact=70.0,
        now_year=2026,
    )
    assert dims.hard_skills == 100.0
    assert dims.missing_must_haves == []
    assert dims.legacy_company is None
    assert 0.0 < dims.structural <= 100.0


def test_thin_jd_path_still_yields_exactly_030_x_local():
    """
    CLAUDE.md Principle 4 must survive the structural rewrite: with no
    structural term and zeroed LLM scores, the composite is exactly 0.30×local.
    """
    from backend.services.match_score_service import finalize_composite
    assert finalize_composite(94.0, 0.0, 0.0) == pytest.approx(28.2)


def test_structural_supersedes_ats_base_when_both_supplied():
    from backend.services.match_score_service import finalize_composite
    with_ats  = finalize_composite(80.0, 70.0, 60.0, ats_base=10.0)
    with_both = finalize_composite(80.0, 70.0, 60.0, ats_base=10.0, structural=90.0)
    only_struct = finalize_composite(80.0, 70.0, 60.0, structural=90.0)
    assert with_both == only_struct != with_ats


def test_ats_base_still_honoured_when_structural_absent():
    """feed_service's rebuild branch must keep producing its previous score."""
    from backend.services.match_score_service import finalize_composite
    assert finalize_composite(80.0, 70.0, 60.0, ats_base=55.0) == \
           finalize_composite(80.0, 70.0, 60.0, ats_base=55.0, structural=None)


def test_knockout_cap_survives_the_structural_term():
    from backend.services.match_score_service import finalize_composite
    assert finalize_composite(
        100.0, 100.0, 100.0, structural=100.0, knockout_failed=True,
    ) == 40.0


# ═════════════════════════════════════════════════════════════════════════════
# Ariel — identity hard block
# ═════════════════════════════════════════════════════════════════════════════

def test_identity_gate_blocks_when_required_fields_missing(monkeypatch):
    monkeypatch.setattr(steering, "_read_identity",
                        lambda uid, eng=None: {"full_name": "", "email": "", "phone": ""})
    result = steering.check_identity_gate("user-1")
    assert result.blocked is True
    assert set(result.missing_required) == {"full_name", "email"}
    assert "your full name" in result.prompt and "an email address" in result.prompt


def test_identity_gate_passes_when_required_present_even_if_recommended_missing():
    """Recommended fields are reported, never blocking."""
    import backend.services.ariel_steering_service as mod
    original = mod._read_identity
    try:
        mod._read_identity = lambda uid, eng=None: {
            "full_name": "Ron", "email": "r@example.com",
            "phone": "", "location": "", "linkedin_url": "",
        }
        result = mod.check_identity_gate("user-1")
        assert result.blocked is False
        assert result.prompt == ""
        assert set(result.missing_recommended) == {"phone", "location", "linkedin_url"}
    finally:
        mod._read_identity = original


# ═════════════════════════════════════════════════════════════════════════════
# Ariel — conditional scoring
# ═════════════════════════════════════════════════════════════════════════════

def test_score_readiness_blocks_only_when_no_experience_at_all():
    empty = steering.assess_score_readiness({"experience": [], "skills": ["Python"]})
    assert empty.can_score is False
    assert empty.disclaimer and "no work experience" in empty.disclaimer.lower()


def test_thin_profile_scores_with_a_disclaimer_rather_than_being_blocked():
    thin = steering.assess_score_readiness({
        "experience": [{"company": "Acme", "role": "PM"}],   # no dates, no summary
        "skills": ["Python"],
        "professional_summary": "",
    })
    assert thin.can_score is True
    assert thin.disclaimer is not None
    assert thin.caveats
    assert thin.completeness < 1.0


def test_complete_profile_has_no_disclaimer():
    complete = steering.assess_score_readiness({
        "experience": [
            {"company": "Acme", "role": "PM", "start": "2020", "end": "2023", "summary": "Led X"},
            {"company": "Globex", "role": "APM", "start": "2018", "end": "2020", "summary": "Did Y"},
        ],
        "skills": ["Python", "SQL", "Roadmapping", "Figma"],
        "professional_summary": "x" * 120,
    })
    assert complete.can_score is True
    assert complete.disclaimer is None
    assert complete.completeness == 1.0


def test_score_readiness_accepts_the_categorised_skills_shape():
    """tailor.py's {"categories":[{"items":[...]}]} shape must not read as 0 skills."""
    r = steering.assess_score_readiness({
        "experience": [{"company": "A", "role": "PM", "start": "2020", "summary": "s"}],
        "skills": {"categories": [{"items": ["Python", "SQL", "Go"]}]},
        "professional_summary": "x" * 100,
    })
    assert not any("skill" in c.lower() for c in r.caveats)


# ═════════════════════════════════════════════════════════════════════════════
# Ariel — re-pivot composition
# ═════════════════════════════════════════════════════════════════════════════

def _deferral(**kw):
    base = dict(deferral_id="d1", topic="identity.phone",
                question="What's the best number to reach you on?",
                status="deferred", repivot_count=0)
    base.update(kw)
    return steering.Deferral(**base)


def test_repivot_answers_first_then_returns_to_the_question():
    out = steering.build_repivot("Yes — the salary range is listed as 30-35k.", _deferral())
    assert out.startswith("Yes — the salary range is listed as 30-35k.")
    assert out.rstrip().endswith("What's the best number to reach you on?")
    assert out.index("salary") < out.index("number")   # answer strictly precedes the pivot


def test_repivot_wording_escalates_on_the_second_ask():
    first  = steering.build_repivot("Answer.", _deferral(repivot_count=0))
    second = steering.build_repivot("Answer.", _deferral(repivot_count=1))
    assert "Circling back" in first
    assert "Still need to pin this down" in second


def test_repivot_stops_after_max_repivots():
    """Past the limit, continuing to ask is its own kind of not listening."""
    out = steering.build_repivot("Answer.", _deferral(repivot_count=steering.MAX_REPIVOTS))
    assert out == "Answer."


def test_repivot_is_a_noop_without_an_open_deferral():
    assert steering.build_repivot("Answer.", None) == "Answer."
    assert steering.build_repivot("Answer.", _deferral(status="answered")) == "Answer."


def test_repivot_returns_the_question_when_there_is_no_answer_to_give():
    out = steering.build_repivot("", _deferral())
    assert out == "What's the best number to reach you on?"


# ═════════════════════════════════════════════════════════════════════════════
# Ariel — communication style normalisation
# ═════════════════════════════════════════════════════════════════════════════

def test_communication_style_defaults():
    assert steering.normalize_communication_style(None) == {
        "mode": "one_by_one", "tone": "neutral", "responsiveness": "normal",
    }


def test_communication_style_accepts_valid_mode():
    assert steering.normalize_communication_style({"mode": "batch"})["mode"] == "batch"


def test_unknown_mode_falls_back_to_default_rather_than_raising():
    """A bad stored value must degrade, never break a live conversation."""
    assert steering.normalize_communication_style({"mode": "telepathy"})["mode"] == "one_by_one"


def test_communication_style_preserves_free_text_fields():
    out = steering.normalize_communication_style(
        {"mode": "batch", "tone": "blunt", "responsiveness": "terse"}
    )
    assert out == {"mode": "batch", "tone": "blunt", "responsiveness": "terse"}


# ═════════════════════════════════════════════════════════════════════════════
# DB-backed — preference persistence, deferral ledger, inferred-skill exclusion
# ═════════════════════════════════════════════════════════════════════════════

def test_communication_style_round_trips(disposable_qa_account):
    uid = disposable_qa_account
    assert steering.get_communication_style(uid)["mode"] == "one_by_one"   # default

    saved = steering.set_communication_style(uid, mode="batch", tone="blunt")
    assert saved["mode"] == "batch" and saved["tone"] == "blunt"
    assert steering.get_communication_style(uid)["mode"] == "batch"
    assert steering.batch_size_for(uid) > 1

    # Partial update must merge, not clobber the fields it wasn't given.
    steering.set_communication_style(uid, responsiveness="terse")
    after = steering.get_communication_style(uid)
    assert after["mode"] == "batch" and after["tone"] == "blunt"
    assert after["responsiveness"] == "terse"


def test_deferral_ledger_records_and_increments(disposable_qa_account):
    uid = disposable_qa_account
    assert steering.get_deferrals(uid) == []

    first = steering.record_deferral(uid, topic="identity.phone", question="Your number?")
    assert first.repivot_count == 0
    assert len(steering.get_deferrals(uid)) == 1

    # Same topic again bumps the counter rather than creating a second row.
    second = steering.record_deferral(uid, topic="identity.phone", question="Your number?")
    assert second.repivot_count == 1
    assert len(steering.get_deferrals(uid)) == 1

    # A different topic is a separate deferral.
    steering.record_deferral(uid, topic="experience.dates", question="When did you start?")
    assert len(steering.get_deferrals(uid)) == 2


def test_resolving_a_deferral_closes_it(disposable_qa_account):
    uid = disposable_qa_account
    steering.record_deferral(uid, topic="identity.phone", question="Your number?")

    assert steering.resolve_deferral(uid, "identity.phone") is True
    assert steering.get_deferrals(uid) == []                       # no longer open
    assert len(steering.get_deferrals(uid, include_closed=True)) == 1
    assert steering.resolve_deferral(uid, "identity.phone") is False   # nothing left to close


def test_resolve_deferral_rejects_an_unknown_status(disposable_qa_account):
    with pytest.raises(ValueError):
        steering.resolve_deferral(disposable_qa_account, "x", status="maybe")


def test_inferred_skill_is_excluded_from_the_tailored_cv(disposable_qa_account):
    """
    The correctness boundary: an unverified inferred capability must not reach
    the profile document that feeds CV generation. Verifying it lets it through.
    """
    import uuid as _uuid
    from datetime import datetime, timezone

    from sqlalchemy import text

    from backend.core.database import ENGINE
    from backend.repositories import profile_repository

    uid = disposable_qa_account
    now = datetime.now(timezone.utc).isoformat()
    doc_id = str(_uuid.uuid4())

    with ENGINE.begin() as conn:
        conn.execute(text("""
            INSERT INTO public.cv_documents (id, user_id, summary, uploaded_at)
            VALUES (CAST(:d AS uuid), CAST(:u AS uuid), 'test cv', now())
        """), {"d": doc_id, "u": uid})

        for name, origin, status in (
            ("HonestSkill",   "cv_parse", "unverified"),
            ("GuessedSkill",  "inferred", "unverified"),
            ("ProvenGuess",   "inferred", "verified"),
        ):
            conn.execute(text("""
                INSERT INTO public.profile_entities
                    (entity_id, user_id, entity_type, name, normalized_name,
                     confidence_score, verification_status, origin,
                     source_document_id, created_at, updated_at)
                VALUES
                    (:eid, CAST(:u AS uuid), 'skill', :n, :nn,
                     50.0, :st, :o, CAST(:d AS uuid), :now, :now)
            """), {
                "eid": f"e-{_uuid.uuid4().hex[:10]}", "u": uid, "n": name,
                "nn": name.lower(), "st": status, "o": origin,
                "d": doc_id, "now": now,
            })

    skills = profile_repository.get_profile_json(uid).get("skills") or []

    assert "HonestSkill" in skills, "a CV-parsed skill must reach the CV"
    assert "GuessedSkill" not in skills, (
        "an unverified INFERRED skill reached the tailored-CV profile — this is "
        "the fabrication guard failing"
    )
    assert "ProvenGuess" in skills, "verification must let an inferred skill through"


def test_inferred_skill_is_excluded_from_scoring_depth(disposable_qa_account):
    """
    Second lock, independent of the CV path: inferred depth must not inflate
    the depth-vs-breadth dimension either.
    """
    import uuid as _uuid
    from datetime import datetime, timezone

    from sqlalchemy import text

    from backend.core.database import ENGINE
    from backend.services.match_score_service import _skill_depth_map

    uid = disposable_qa_account
    now = datetime.now(timezone.utc).isoformat()

    with ENGINE.begin() as conn:
        for name, origin, status, years in (
            ("RealDepth",    "cv_parse", "unverified", 7.0),
            ("GuessedDepth", "inferred", "unverified", 9.0),
        ):
            conn.execute(text("""
                INSERT INTO public.profile_entities
                    (entity_id, user_id, entity_type, name, normalized_name,
                     confidence_score, verification_status, origin,
                     years_of_experience, created_at, updated_at)
                VALUES
                    (:eid, CAST(:u AS uuid), 'skill', :n, :nn,
                     50.0, :st, :o, :yrs, :now, :now)
            """), {
                "eid": f"e-{_uuid.uuid4().hex[:10]}", "u": uid, "n": name,
                "nn": name.lower(), "st": status, "o": origin,
                "yrs": years, "now": now,
            })

    depth = _skill_depth_map(uid)
    assert _norm("RealDepth") in depth
    assert _norm("GuessedDepth") not in depth, (
        "inferred years-of-experience leaked into scoring depth"
    )


def test_provenance_check_constraint_rejects_a_bad_origin(disposable_qa_account):
    """Migration a7c91e40b3f2 — a typo'd origin must fail loudly, not persist."""
    import uuid as _uuid
    from datetime import datetime, timezone

    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError

    from backend.core.database import ENGINE

    now = datetime.now(timezone.utc).isoformat()
    with pytest.raises(IntegrityError):
        with ENGINE.begin() as conn:
            conn.execute(text("""
                INSERT INTO public.profile_entities
                    (entity_id, user_id, entity_type, name, normalized_name,
                     confidence_score, verification_status, origin, created_at, updated_at)
                VALUES
                    (:eid, CAST(:u AS uuid), 'skill', 'X', 'x',
                     0.0, 'unverified', 'cv-parse', :now, :now)
            """), {"eid": f"e-{_uuid.uuid4().hex[:10]}", "u": disposable_qa_account, "now": now})
