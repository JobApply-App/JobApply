---
title: "Structural hard-skills dimension scores 0.0 for every job: requirement sentences are compared with single skill terms"
author: RonMorim
date: 2026-11-14
branch: claude/bugs-ui-improvements-31vblx
cost: { minutes: 14, tokens: 188333 }
id: l-a1065861
scope: repo
status: active
src: agent
touches:
  - docs/research/07-benchmark-plan.md
  - docs/research/07-benchmark-results.md
  - docs/research/benchmark/run_benchmark.py
  - docs/research/benchmark/.gitignore
  - docs/research/benchmark/free_checks.py
  - docs/research/benchmark/analyze.py
  - backend/services/match_dimensions.py
---

## Decided
The stage 7 benchmark (docs/research/07-benchmark-results.md) reports this as a finding and does not fix it. No product code was changed.

## Watch out
- `score_hard_skills` in backend/services/match_dimensions.py receives `must_haves` from `_jd_requirements` (match_score_service.py). Both sources, the `jd_structured` JSON and `heuristic_structured_jd`, return whole requirement sentences ("Production experience in Python or Go"). Profile skills are single terms ("python"). `_equivalent` needs equality, a taxonomy match, or all JD tokens inside one profile term, so a sentence never matches.
- Measured 0 of 36 pairs above 0.0 on the benchmark set, strong fits included (docs/research/benchmark/skills_dimension_check.py, model-free).
- Effect: the deterministic 40% of the composite is about 21-24 for a perfect fit, so strong fits top out near 50-62. Order within a person is unaffected because the constant is the same for every job.
- Not yet confirmed on a real production profile.
- The local proxy score in the live path runs on the JD parser's condensed English text, not the raw ad; model-free checks on the raw ad give different local scores for Hebrew ads (44.8 raw, 56.8 live).
