---
title: "Depth takes the scorer's verdict credits, and impact is judged by the scorer per job"
author: RonMorim
date: 2026-11-18
branch: claude/depth-impact
cost: { minutes: 25, tokens: 321795 }
id: l-aa0174bc
scope: repo
status: active
src: agent
touches:
  - CLAUDE.md
  - backend/services/match_score_service.py
  - backend/tests/test_role_order.py
  - backend/services/match_dimensions.py
  - backend/services/profile_baseline_service.py
  - backend/tests/test_domain_fit.py
  - backend/tests/test_fit_brief_language.py
  - backend/tests/test_profile_baseline.py
  - backend/tests/test_requirement_verdicts.py
  - backend/tests/test_depth_and_impact.py
---

## Decided
- Depth (`score_depth_breadth` in backend/services/match_dimensions.py) earns 1.0 per must-have line on a literal skill hit, otherwise the scorer's verdict credit for that line (the same credits hard skills uses). The literal match only finds tool names inside a line, so ability-worded lines ("owning a product area with an engineering squad") matched nothing and depth sat on its floor of 15 for about half the benchmark jobs.
- A skill's own years are compared to min(JD headline years, `_ESTABLISHED_SKILL_YEARS` = 3). "8+ years of backend" describes a career, not 8 years of Kafka.
- Impact is the scorer's `impact_fit` (strong/some/little → 100/70/40, `_IMPACT_FIT_SCORE`), asked in `_LLM_SCORER_TEMPLATE` in match_score_service.py. The old regex count of $ / % / "N users" / "led team of N" is only the fallback when the scorer gives no valid answer. The count was the same for every job per person and 0 for CVs whose results are not numbers ("designing 40 packages", "Lead a team of 4").
- The bullet snippet sent to the scorer is 200 chars (was 90), so it can see the result at the end of a bullet.

## Watch out
- `_llm_dual_score` now returns a 7-tuple ending `domain_fit, impact_fit`; tests unpack with `*_, ...`.
- "little" maps to 40, not 0, so no-fit jobs rose 2–7 points in the benchmark while the gaps between fit levels held.
- `call_llm` tries Gemini first. When the Gemini key ran out of credit (402) mid-benchmark, rows silently came from Haiku/Sonnet; check the `models` field before comparing runs.
