---
title: "Depth takes the scorer's verdict credits, weighted per line, and impact is judged by the scorer per job"
author: RonMorim
date: 2026-11-18
branch: claude/depth-impact
cost: { minutes: 4, tokens: 28498 }
id: l-3e2a6cad
scope: repo
status: active
replaces: l-aa0174bc
src: agent
touches:
  - backend/services/match_dimensions.py
  - backend/tests/test_depth_and_impact.py
---

## Decided
- Depth (`score_depth_breadth`, backend/services/match_dimensions.py) uses the scorer's verdict credits for lines the literal skill match can't find. That match only finds tool names, so ability-worded lines left depth on its floor of 15 for about half the jobs.
- Each line's depth is weighted by its credit and divided by all the must-haves. Averaging only the covered lines made one "partly" verdict jump depth from 15 to about 50. Repeats flip verdicts, so A1 dropped from 22 to 15 of 36. With the weighting it is back to 21.
- A skill's years are compared to min(the JD's headline years, `_ESTABLISHED_SKILL_YEARS` = 3).
- Impact is the scorer's `impact_fit` (strong/some/little → 100/70/40). The regex count of $ / % is only the fallback.

## Watch out
- `call_llm` falls back from Gemini to Claude without saying so (402 when out of credit). Check the `models` field before comparing benchmark runs.
