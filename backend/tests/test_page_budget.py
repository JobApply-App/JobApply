"""
A4 page-budgeting search policy (backend/services/page_budget_service.py).

The pure half — which bullet counts to try next, and how a candidate is
clamped. Kept browser-free so the policy is testable in CI; the
render-and-measure half is exercised against real Chromium separately.

Measured baseline that motivated this, from real renders:
    sparse   48.9%   |  typical  70.3%  |  dense 103.0% (clipped)
Under-fill is the normal state and clipping is silent, so both directions of
the search matter.
"""
from __future__ import annotations

import pytest

from backend.services.page_budget_service import (
    MAX_BULLETS_PRIMARY,
    MAX_BULLETS_SUPPORT,
    MIN_BULLETS_PRIMARY,
    MIN_BULLETS_SUPPORT,
    TARGET_MAX,
    TARGET_MIN,
    BudgetReport,
    _clamp_bullets,
    _total_bullets,
    plan_adjustment,
)


def _cv(n_roles=3, bullets=4):
    return {
        "header": {"target_title": "PM"},
        "experience": [
            {"role": f"PM {i}", "company": f"Co {i}", "dates": "2020 - 2024",
             "bullets": [f"Bullet {j}" for j in range(bullets)]}
            for i in range(n_roles)
        ],
    }


# ── Clamping ─────────────────────────────────────────────────────────────────

def test_clamp_applies_different_caps_to_primary_and_supporting_roles():
    out = _clamp_bullets(_cv(3, 6), primary=4, support=2)
    assert len(out["experience"][0]["bullets"]) == 4   # most recent keeps depth
    assert len(out["experience"][1]["bullets"]) == 2
    assert len(out["experience"][2]["bullets"]) == 2


def test_clamp_trims_from_the_end():
    """Bullets are emitted strongest-first, so the last is cheapest to lose."""
    out = _clamp_bullets(_cv(1, 5), primary=3, support=3)
    assert out["experience"][0]["bullets"] == ["Bullet 0", "Bullet 1", "Bullet 2"]


def test_clamp_never_invents_bullets():
    """A cap above what exists cannot manufacture content."""
    out = _clamp_bullets(_cv(2, 2), primary=6, support=4)
    assert len(out["experience"][0]["bullets"]) == 2
    assert len(out["experience"][1]["bullets"]) == 2


def test_clamp_does_not_mutate_the_input():
    original = _cv(2, 5)
    _clamp_bullets(original, primary=2, support=2)
    assert len(original["experience"][0]["bullets"]) == 5


def test_total_bullets_counts_across_roles():
    assert _total_bullets(_cv(3, 4)) == 12
    assert _total_bullets({"experience": []}) == 0
    assert _total_bullets({}) == 0


# ── Search policy ────────────────────────────────────────────────────────────

def test_in_band_needs_no_adjustment():
    for fill in (TARGET_MIN, 0.93, TARGET_MAX):
        assert plan_adjustment(fill, 4, 3) is None


def test_over_budget_trims_supporting_roles_first():
    """The most recent role is what a recruiter reads; it keeps depth longest."""
    assert plan_adjustment(1.03, 4, 3) == (4, 2)


def test_over_budget_falls_back_to_the_primary_role_once_support_bottoms_out():
    assert plan_adjustment(1.03, 4, MIN_BULLETS_SUPPORT) == (3, MIN_BULLETS_SUPPORT)


def test_over_budget_gives_up_at_the_floor_rather_than_gutting_the_cv():
    """Below the minimums the document stops being a CV; clipping is the lesser
    evil and the caller keeps the best non-clipping candidate instead."""
    assert plan_adjustment(1.20, MIN_BULLETS_PRIMARY, MIN_BULLETS_SUPPORT) is None


def test_under_budget_expands_supporting_roles_first():
    assert plan_adjustment(0.70, 4, 3) == (4, 4)


def test_under_budget_then_expands_the_primary_role():
    assert plan_adjustment(0.70, 4, MAX_BULLETS_SUPPORT) == (5, MAX_BULLETS_SUPPORT)


def test_under_budget_gives_up_at_the_ceiling():
    """Past the ceiling the page is a wall of text however well it fits."""
    assert plan_adjustment(0.50, MAX_BULLETS_PRIMARY, MAX_BULLETS_SUPPORT) is None


@pytest.mark.parametrize("fill", [0.0, 0.5, 0.87, 0.99, 1.5])
def test_policy_never_proposes_counts_outside_the_bounds(fill):
    for primary in range(MIN_BULLETS_PRIMARY, MAX_BULLETS_PRIMARY + 1):
        for support in range(MIN_BULLETS_SUPPORT, MAX_BULLETS_SUPPORT + 1):
            nxt = plan_adjustment(fill, primary, support)
            if nxt is None:
                continue
            p, s = nxt
            assert MIN_BULLETS_PRIMARY <= p <= MAX_BULLETS_PRIMARY
            assert MIN_BULLETS_SUPPORT <= s <= MAX_BULLETS_SUPPORT


def test_target_band_leaves_headroom_below_a_full_page():
    """
    TARGET_MAX is under 1.0 on purpose: Chromium's print pagination and its
    on-screen layout disagree slightly, and a CV measured at exactly 100% can
    still lose its last line in the PDF.
    """
    assert TARGET_MAX < 1.0
    assert TARGET_MIN < TARGET_MAX


# ── Report ───────────────────────────────────────────────────────────────────

def test_report_serialises_for_review():
    r = BudgetReport(initial_fill=1.03, final_fill=0.916, iterations=3,
                     converged=True, action="trimmed", bullets_before=30, bullets_after=22)
    d = r.as_dict()
    assert d["initial_fill"] == 1.03 and d["final_fill"] == 0.916
    assert d["action"] == "trimmed" and d["converged"] is True


@pytest.mark.asyncio
async def test_fit_is_a_noop_without_experience():
    """No experience means nothing to budget against — and must not error."""
    from backend.services.page_budget_service import fit_to_page
    cv = {"header": {"target_title": "PM"}, "experience": []}
    out, report = await fit_to_page(cv, user_id="u", template_id="t2_modern")
    assert out == cv
    assert not report.converged
    assert any("nothing to budget" in n for n in report.notes)
