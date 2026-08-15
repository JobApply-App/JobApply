"""
A4 page-budgeting: fit a CV to exactly one page by measuring, not guessing.

What the measurements showed
------------------------------
Rendering real CVs and reading their natural height against the A4 box:

    sparse  (1 role,  2 bullets)   48.9%   half the page blank
    light   (2 roles, 3 bullets)   58.2%
    typical (3 roles, 4 bullets)   70.3%   a third blank — the COMMON case
    dense   (5 roles, 6 bullets)  103.0%   clipped
    no education / no military     57.7%   nothing reallocated

Two distinct failures, and neither is the one usually assumed:

1. **Silent clipping, not spillover.** The template is `height: 297mm;
   overflow: hidden`, so a CV can never spill onto page 2 — it gets cut off
   instead, invisibly. The candidate's last bullet simply is not in the PDF and
   nothing anywhere says so. That is worse than a second page: a second page is
   visible and fixable, missing content is neither.

2. **Under-fill is the normal state.** A typical CV uses 70% of the page. The
   remaining third reads as a thin candidate, which is the opposite of what the
   document is for. Nobody notices because there is no error — it just looks
   weak.

Approach
--------
Render, measure, adjust, repeat. Bullet count is the lever because it is the
only one that changes content volume without changing content *meaning* —
shrinking type or tightening leading to force a fit produces a cramped document
that reads as desperate, and is the standard way this problem gets solved badly.

Nothing is ever invented to fill space. The budgeter only chooses how many of
the bullets the model ALREADY generated to keep, so under-fill is corrected by
restoring real content that a fixed cap discarded, never by padding. If there
genuinely is not enough material, the page stays short — that is an honest
signal about the profile, and Ariel's intake flow is the right place to fix it.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

# Target band, as a fraction of the A4 content box.
#
# Upper bound is 0.98 rather than 1.0: Chromium's print pagination and its
# on-screen layout disagree by a hair, and a CV measured at exactly 100% can
# still lose its final line in the PDF. The 2% is the margin for that
# disagreement, not aesthetic padding.
#
# Lower bound is 0.88 — below that the whitespace reads as a thin candidate.
TARGET_MIN = 0.88
TARGET_MAX = 0.98

# Bullets per role. The budgeter moves within these; it never goes below MIN
# (a role with one bullet reads as filler) nor above MAX (past this the page is
# a wall of text regardless of how well it fits).
MIN_BULLETS_PRIMARY   = 3
MAX_BULLETS_PRIMARY   = 6
MIN_BULLETS_SUPPORT   = 2
MAX_BULLETS_SUPPORT   = 4

# Render-measure cycles. Each costs a real Chromium layout, so this is a
# latency budget as much as a convergence one; measurements showed the search
# settles within 2-3 steps because each bullet is a large, discrete jump.
MAX_ITERATIONS = 5


@dataclass
class BudgetReport:
    """What the fitter did, for logging and for the human-review step."""
    initial_fill: float = 0.0
    final_fill: float = 0.0
    iterations: int = 0
    converged: bool = False
    action: str = "none"            # trimmed | expanded | none
    bullets_before: int = 0
    bullets_after: int = 0
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "initial_fill": round(self.initial_fill, 3),
            "final_fill": round(self.final_fill, 3),
            "iterations": self.iterations,
            "converged": self.converged,
            "action": self.action,
            "bullets_before": self.bullets_before,
            "bullets_after": self.bullets_after,
            "notes": self.notes,
        }


# Reads the natural (unclipped) height. overflow:hidden makes scrollHeight
# equal clientHeight, so the clip has to be relaxed up the ancestor chain
# before measuring or every document reports a perfect 100% fit — which is
# exactly how the under-fill went unnoticed.
_MEASURE_JS = """() => {
  const page = document.querySelector('.page') || document.body;
  const box = page.getBoundingClientRect().height;
  const saved = [];
  let el = page;
  while (el) {
    saved.push([el, el.style.overflow, el.style.height, el.style.maxHeight]);
    el.style.overflow = 'visible';
    el.style.height = 'auto';
    el.style.maxHeight = 'none';
    el = el.parentElement;
  }
  const natural = page.scrollHeight;
  for (const [e, o, h, m] of saved) {
    e.style.overflow = o; e.style.height = h; e.style.maxHeight = m;
  }
  return { natural, box };
}"""


def _total_bullets(cv_data: dict) -> int:
    return sum(len(e.get("bullets") or []) for e in (cv_data.get("experience") or []))


async def measure_fill(html: str, page=None) -> float:
    """
    Fraction of the A4 content box the document naturally occupies.

    >1.0 means content is being clipped. Accepts an existing Playwright page so
    a fitting loop reuses one browser instead of launching Chromium per
    iteration, which dominates the cost otherwise.
    """
    if page is not None:
        await page.set_content(html, wait_until="networkidle")
        m = await page.evaluate(_MEASURE_JS)
        return (m["natural"] / m["box"]) if m["box"] else 0.0

    from playwright.async_api import async_playwright
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        try:
            pg = await browser.new_page()
            await pg.set_content(html, wait_until="networkidle")
            m = await pg.evaluate(_MEASURE_JS)
            return (m["natural"] / m["box"]) if m["box"] else 0.0
        finally:
            await browser.close()


def _clamp_bullets(cv_data: dict, primary: int, support: int) -> dict:
    """
    Return a copy with bullet counts clamped. Pure and synchronous so the
    search logic is testable without a browser.

    Trims from the END of each role: bullets are emitted strongest-first, so
    the last one is the weakest claim and the cheapest to lose.
    """
    import copy
    out = copy.deepcopy(cv_data)
    for i, exp in enumerate(out.get("experience") or []):
        cap = primary if i == 0 else support
        exp["bullets"] = list(exp.get("bullets") or [])[:cap]
    return out


def plan_adjustment(fill: float, primary: int, support: int) -> Optional[tuple[int, int]]:
    """
    Next (primary, support) bullet caps to try, or None when nothing can move.

    Pure — the search policy is unit-testable without rendering anything.
    Supporting roles move first in both directions: the most recent role is the
    one a recruiter actually reads, so it keeps its depth longest when trimming
    and gains last when expanding.
    """
    if fill > TARGET_MAX:
        if support > MIN_BULLETS_SUPPORT:
            return primary, support - 1
        if primary > MIN_BULLETS_PRIMARY:
            return primary - 1, support
        return None
    if fill < TARGET_MIN:
        if support < MAX_BULLETS_SUPPORT:
            return primary, support + 1
        if primary < MAX_BULLETS_PRIMARY:
            return primary + 1, support
        return None
    return None


async def fit_to_page(
    cv_data: dict,
    *,
    user_id: str,
    template_id: Optional[str] = None,
    max_iterations: int = MAX_ITERATIONS,
) -> tuple[dict, BudgetReport]:
    """
    Adjust bullet counts until the CV fills one A4 page without clipping.

    Returns (cv_data, report). On any failure the ORIGINAL cv_data comes back
    with converged=False: a CV that fits imperfectly is worth far more to the
    user than no CV, so nothing here is allowed to be fatal.
    """
    from backend.services.pdf_builder import render_html

    report = BudgetReport(bullets_before=_total_bullets(cv_data))

    experience = cv_data.get("experience") or []
    if not experience:
        report.notes.append("no experience section — nothing to budget against")
        return cv_data, report

    primary = min(MAX_BULLETS_PRIMARY, max(MIN_BULLETS_PRIMARY, len(experience[0].get("bullets") or [])))
    support = MIN_BULLETS_SUPPORT + 1

    try:
        from playwright.async_api import async_playwright
        async with async_playwright() as pw:
            browser = await pw.chromium.launch()
            try:
                page = await browser.new_page()
                best, best_fill = None, None

                for i in range(max_iterations):
                    candidate = _clamp_bullets(cv_data, primary, support)
                    html = render_html(candidate, template_id=template_id, user_id=user_id)
                    fill = await measure_fill(html, page=page)

                    if i == 0:
                        report.initial_fill = fill

                    # Track the best legal candidate seen: never clipped, and
                    # as full as possible. The loop can overshoot on its last
                    # step, and returning a clipped document because it was
                    # simply the most recent would defeat the purpose.
                    if fill <= TARGET_MAX and (best_fill is None or fill > best_fill):
                        best, best_fill = candidate, fill

                    report.iterations = i + 1
                    report.final_fill = fill

                    if TARGET_MIN <= fill <= TARGET_MAX:
                        report.converged = True
                        best, best_fill = candidate, fill
                        break

                    nxt = plan_adjustment(fill, primary, support)
                    if nxt is None:
                        report.notes.append(
                            f"hit the bullet bounds at fill={fill:.2f} — "
                            f"{'not enough material to fill the page' if fill < TARGET_MIN else 'content still over budget'}"
                        )
                        break
                    primary, support = nxt

                if best is not None:
                    report.final_fill = best_fill or report.final_fill
                    report.bullets_after = _total_bullets(best)
                    report.action = ("trimmed" if report.bullets_after < report.bullets_before
                                     else "expanded" if report.bullets_after > report.bullets_before
                                     else "none")
                    logger.info(
                        "[page-budget] %s: %d -> %d bullets, fill %.1f%% -> %.1f%% in %d iteration(s)%s",
                        report.action, report.bullets_before, report.bullets_after,
                        report.initial_fill * 100, report.final_fill * 100,
                        report.iterations, "" if report.converged else " (did not converge)",
                    )
                    return best, report

                report.notes.append("no non-clipping layout found; returning the original")
                report.bullets_after = report.bullets_before
                return cv_data, report
            finally:
                await browser.close()

    except Exception as exc:
        logger.warning("[page-budget] fitting unavailable (%s) — returning cv unchanged: %s",
                       type(exc).__name__, str(exc)[:160])
        report.notes.append(f"fitting skipped: {type(exc).__name__}")
        report.bullets_after = report.bullets_before
        return cv_data, report
