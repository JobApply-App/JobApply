"""
JOB-121: skills injection cap in tailor.py.

_inject_static_sections() used to hard-cap injected skills at a flat [:12],
tuned for the legacy singleton's 6-skill profile — a real DB profile can run
well past that (36 skills on one real account, per the ticket), so only the
first 12 (in whatever order the profile happened to store them) ever reached
the CV. Raised to _SKILLS_CAP (20) and made relevance-aware: skills are
stable-sorted so ones mentioned in the JD come first, so when a profile
still has more skills than fit, the ones kept are the JD-relevant ones, not
an arbitrary prefix.

Deliberately no DB: _resolve_profile is monkeypatched, so these tests stay
runnable anywhere (CI included) and isolate the ranking/cap logic itself
from profile resolution (covered elsewhere).
"""
from __future__ import annotations

import backend.agents.tailor as tailor_module
from backend.agents.tailor import (
    _SKILLS_CAP,
    _inject_static_sections,
    _rank_skills_by_jd_relevance,
)
from backend.services.pdf_builder import _SKILLS_ITEMS_PER_CATEGORY_CAP, _build_skills


# ── _rank_skills_by_jd_relevance — pure function ─────────────────────────────

def test_jd_relevant_skills_sort_first():
    skills = ["Python", "Excel", "Kubernetes", "PowerPoint"]
    jd = "We need someone strong in Python and Kubernetes for this role."
    ranked = _rank_skills_by_jd_relevance(skills, jd)
    assert ranked[:2] == ["Python", "Kubernetes"] or ranked[:2] == ["Kubernetes", "Python"]
    assert set(ranked[:2]) == {"Python", "Kubernetes"}
    assert set(ranked[2:]) == {"Excel", "PowerPoint"}


def test_relative_order_preserved_within_each_relevance_bucket():
    """Stable sort: among equally-(ir)relevant skills, profile order holds."""
    skills = ["Excel", "Python", "PowerPoint", "Kubernetes"]
    jd = "Looking for Python and Kubernetes experience."
    ranked = _rank_skills_by_jd_relevance(skills, jd)
    assert ranked == ["Python", "Kubernetes", "Excel", "PowerPoint"]


def test_empty_jd_text_leaves_profile_order_untouched():
    skills = ["Zebra", "Apple", "Mango"]
    assert _rank_skills_by_jd_relevance(skills, "") == skills
    assert _rank_skills_by_jd_relevance(skills, None) == skills


def test_word_boundary_prevents_substring_false_positive():
    """'Java' must not count as relevant just because 'JavaScript' is in the
    JD — that's a real substring, wrong skill."""
    skills = ["Java", "JavaScript"]
    jd = "5+ years of JavaScript required."
    ranked = _rank_skills_by_jd_relevance(skills, jd)
    assert ranked[0] == "JavaScript"
    assert ranked[1] == "Java"


def test_case_insensitive_match():
    """'python' (profile) vs 'PYTHON' (JD) must still count as a match —
    proven by checking it actually sorts ahead of an unrelated skill, not
    just that a single-item list stays in place either way."""
    skills = ["Excel", "python"]
    jd = "Must know PYTHON."
    ranked = _rank_skills_by_jd_relevance(skills, jd)
    assert ranked == ["python", "Excel"]


def test_no_skills_matched_returns_original_order():
    skills = ["Cobol", "Fortran"]
    jd = "We use modern cloud tooling."
    assert _rank_skills_by_jd_relevance(skills, jd) == skills


# ── _inject_static_sections — cap + ranking applied end-to-end ──────────────

def _patch_profile(monkeypatch, skills):
    monkeypatch.setattr(
        tailor_module, "_resolve_profile",
        lambda user_id: {"skills": skills, "education": [], "experience": []},
    )


def test_skills_under_cap_are_all_kept(monkeypatch):
    skills = [f"Skill{i}" for i in range(_SKILLS_CAP - 1)]
    _patch_profile(monkeypatch, skills)
    result = _inject_static_sections({}, user_id="u1")
    items = result["skills"]["categories"][0]["items"]
    assert len(items) == _SKILLS_CAP - 1
    assert set(items) == set(skills)


def test_skills_at_exact_cap_boundary_are_all_kept(monkeypatch):
    skills = [f"Skill{i}" for i in range(_SKILLS_CAP)]
    _patch_profile(monkeypatch, skills)
    result = _inject_static_sections({}, user_id="u1")
    assert len(result["skills"]["categories"][0]["items"]) == _SKILLS_CAP


def test_skills_over_cap_are_truncated_to_cap(monkeypatch):
    """The real-world JOB-121 scenario: more skills than fit."""
    skills = [f"Skill{i}" for i in range(_SKILLS_CAP + 16)]  # e.g. 36 for a cap of 20
    _patch_profile(monkeypatch, skills)
    result = _inject_static_sections({}, user_id="u1")
    assert len(result["skills"]["categories"][0]["items"]) == _SKILLS_CAP


def test_over_cap_keeps_jd_relevant_skills_not_an_arbitrary_prefix(monkeypatch):
    """The whole point of ranking before capping: a JD-relevant skill near
    the end of a long profile must still survive the cut."""
    filler = [f"Filler{i}" for i in range(_SKILLS_CAP)]
    skills = filler + ["Kubernetes"]  # relevant skill listed LAST in the profile
    _patch_profile(monkeypatch, skills)
    jd = "Must have deep Kubernetes expertise."
    result = _inject_static_sections({}, user_id="u1", jd_text=jd)
    items = result["skills"]["categories"][0]["items"]
    assert len(items) == _SKILLS_CAP
    assert "Kubernetes" in items


def test_no_jd_text_over_cap_keeps_profile_prefix(monkeypatch):
    """Without a JD to rank against, capping falls back to keeping the
    profile's own first _SKILLS_CAP entries — documented, not a silent
    behavior change from before this ticket."""
    skills = [f"Skill{i}" for i in range(_SKILLS_CAP + 10)]
    _patch_profile(monkeypatch, skills)
    result = _inject_static_sections({}, user_id="u1")  # jd_text omitted
    assert result["skills"]["categories"][0]["items"] == skills[:_SKILLS_CAP]


# ── pdf_builder._build_skills — rendering cap stays in lock-step ────────────

def test_build_skills_renders_up_to_the_matching_cap():
    items = [f"Skill{i}" for i in range(_SKILLS_ITEMS_PER_CATEGORY_CAP + 5)]
    html = _build_skills({"categories": [{"label": "Core Skills", "items": items}]})
    rendered_count = sum(1 for i in items[:_SKILLS_ITEMS_PER_CATEGORY_CAP] if i in html)
    assert rendered_count == _SKILLS_ITEMS_PER_CATEGORY_CAP
    # anything past the cap must not have made it into the rendered HTML
    for extra in items[_SKILLS_ITEMS_PER_CATEGORY_CAP:]:
        assert extra not in html


def test_pdf_and_tailor_caps_stay_in_lock_step():
    """Regression guard for the exact class of bug this ticket is about:
    raising one cap without the other either silently re-truncates a
    carefully-ranked selection, or renders more than tailor.py ever selected.
    """
    assert _SKILLS_ITEMS_PER_CATEGORY_CAP >= _SKILLS_CAP
