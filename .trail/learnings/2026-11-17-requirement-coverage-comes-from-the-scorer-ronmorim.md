---
title: "Requirement coverage comes from the scorer's per-line verdicts; years lines are summed from role dates in code"
author: RonMorim
date: 2026-11-17
branch: claude/requirement-verdicts
cost: { minutes: 30, tokens: 183729 }
id: l-f1036b0a
scope: repo
status: active
src: agent
touches:
  - CLAUDE.md
  - backend/services/feed_service.py
  - backend/services/match_dimensions.py
  - backend/services/match_score_service.py
  - backend/tests/test_dynamic_matching.py
  - backend/tests/test_scoring_and_ariel_steering.py
  - docs/research/benchmark/README.md
  - docs/research/07-benchmark-results.md
  - backend/tests/test_fit_brief_language.py
---

## Decided
- The scorer call (_llm_dual_score) now gets the JD's requirement lines numbered and the roles numbered with dates, and returns a verdict per line (met / partial / not_met + evidence). For a years line it returns years_required and the role numbers that count; match_dimensions.requirement_credits sums those roles' dates (overlaps counted once) and gives held/required capped at 1. Founder's rule (2026-11-17): years are a plain fact about the person, e.g. 4 years partnerships + 4 years CS = 8 years in the field.
- score_hard_skills takes max(literal skill match, verdict credit), so a wrong not_met can't undo a skill the profile names. "met" with empty evidence counts as partial.
- No extra model call. Thin-JD path unchanged. Verdict failures return {} credits and the old literal behaviour.

## Watch out
- The model must not add up years itself; the prompt says code sums the dates. Role numbers are 1-based in the order shown (most recent first).
- Verdicts are parsed outside the Pydantic model on purpose: a malformed list must never turn the scores into the 60/60 fallback.
- Benchmark 2026-11-17: strong-fit median 72.3 -> 80.6, no-fit 20.3 -> 20.6, B6 passes; rewording stability A2 dropped 12/12 -> 10/12, so the verdicts add some run-to-run noise.
