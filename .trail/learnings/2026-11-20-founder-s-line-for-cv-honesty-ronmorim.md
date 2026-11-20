---
title: "Founder's line for CV honesty: translated titles and stronger verbs are fine; bigger technical claims, re-homed tools and invented activities are not"
author: RonMorim
date: 2026-11-20
branch: claude/benchmark-part-c-honesty
cost: { minutes: 39, tokens: 434621 }
id: l-bb1ec750
scope: repo
status: active
src: agent
touches:
  - backend/agents/tailor.py
  - backend/services/cv_aggregator_service.py
  - backend/services/cv_entry_kind.py
  - backend/services/user_profile.py
  - backend/tests/test_cv_hard_rules.py
  - docs/research/07-benchmark-results.md
  - docs/research/benchmark/build_claims_sheet.py
  - docs/research/benchmark/claims-key.json
  - docs/research/benchmark/claims-sheet.md
  - docs/research/benchmark/run_benchmark.py
---

## Decided
The founder judged 20 claims flagged by the stage 7 part C checker (docs/research/benchmark/claims-sheet-he.md, verdicts in claims-key.json, 2026-11-20). This is the rule for the CV writer (backend/agents/tailor.py _SYSTEM_PROMPT) and for any checker of it.
- **Acceptable:**
  - translating a military or local title into civilian terms ("Company Clerk" to "HR coordinator", "Operations Sergeant" to "Operations Coordinator")
  - a stronger verb for the same act ("ran" to "led")
  - plausible detail on a real activity
- **Not acceptable:**
  - a technical claim larger than the work ("deploy with GitHub Actions" to "built CI/CD pipelines", "writes SQL" to "built SQL pipelines")
  - a tool from the skills list attached to work the profile does not tie it to
  - work moved to another role with an outcome added
  - an invented activity
- Real numbers must be kept; dropping a stated result weakens the CV.

## Tried and ruled out
- Locking job titles, employers and dates to the profile text. The founder accepts translated titles, so this would remove wording he wants.
- Reading the checker's raw counts as the size of the problem. The checker was right outright on 6 of 20 flags (about 30-45% counting borderline), so its 4-5 flags per CV are about 2 real ones.

## Watch out
- Any new honesty check must be calibrated against these verdicts before its counts are quoted.
