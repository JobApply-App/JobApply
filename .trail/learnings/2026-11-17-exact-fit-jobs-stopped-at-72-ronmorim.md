---
title: "Exact-fit jobs stopped at 72 because years lines counted as missing skills and a profile-blind title score had 18% weight"
author: RonMorim
date: 2026-11-17
branch: claude/score-years-and-local
cost: { minutes: 17, tokens: 293453 }
id: l-9b3a35bc
scope: repo
status: active
src: agent
touches:
  - backend/services/feed_service.py
  - backend/services/match_dimensions.py
  - backend/services/match_score_service.py
  - backend/tests/test_dynamic_matching.py
  - backend/tests/test_scoring_and_ariel_steering.py
  - docs/research/benchmark/cv_prompts.py
  - docs/research/benchmark/run_benchmark.py
  - CLAUDE.md
  - backend/services/ats_match_engine.py
  - backend/agents/tailor.py
---

## Decided
- 2026-11-17, founder's call: the local proxy (`compute_local_proxy_score`) has no weight once the LLM has read the JD. `finalize_composite(..., thin_jd=True)` is the only path that uses it (0.30 x local, CLAUDE.md principle 4). It scores titles against fixed product-manager tiers, so for every other user it pulled scores to the middle.
- A requirement line that only states years ("8+ years of backend development") and names no profile skill is not counted as a missing skill (`_is_years_only` in `match_dimensions.py`). Years are judged once, in depth.

## Watch out
- When both providers fail, `_llm_dual_score` returns 60/60 with `llm_validated` True. Only the empty `fit_brief` tells it apart. The benchmark runner now checks that; anything else reading `llm_validated` alone counts fallbacks as real scores.
- `_compute_structural` reads `cv_data["domains"]`, which `_build_profile_cv_proxy` never sets, so the domain dimension is 50.0 for every job. Not fixed yet.
- Depth compares each skill's own years with the job's total-years number. Not fixed yet.
- Certificate and degree lines ("Type 3 Bookkeeping certification") still count as missing skills.
