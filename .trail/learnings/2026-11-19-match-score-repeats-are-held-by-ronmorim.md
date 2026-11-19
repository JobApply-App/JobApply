---
title: "Match score repeats are held by reusing the first answer per prompt hash, because the scorer moves up to 10 points on an identical prompt"
author: RonMorim
date: 2026-11-19
branch: claude/adjacent-titles
cost: { minutes: 96, tokens: 703811 }
id: l-76ae33e5
scope: repo
status: active
src: agent
touches:
  - backend/agents/jd_parser.py
  - backend/repositories/shadow_score_repository.py
  - backend/services/match_score_service.py
  - backend/tests/test_same_input_same_score.py
  - backend/services/user_title_terms.py
  - backend/services/match_dimensions.py
  - backend/tests/test_depth_and_impact.py
  - backend/tests/test_domain_fit.py
  - backend/tests/test_requirement_verdicts.py
  - docs/research/07-benchmark-results.md
---

## Decided
- Same input keeps its first score (founder's call, 2026-11-18). `_llm_dual_score` in backend/services/match_score_service.py hashes its system prompt and prompt, then reuses the oldest valid answer for that user from shadow_match_scores (`shadow_score_repository.first_answer`). A changed CV, profile or ad gives a new hash, and so a new answer.
- Every scoring is history. breakdown_json in shadow_match_scores records:
  - job_id
  - the sub-scores and dimensions
  - prompt_hash and the full answer
  - the model
  - whether the answer was reused
  No migration was needed: the table existed, is user-linked, has RLS on and a user_id index (2 ms lookup on the server).
- The JD parser (backend/agents/jd_parser.py) runs at temperature 0, and the first valid parse of an ad is kept in kv_store under `jd_parse:` + sha256(system prompt + ad).

## Tried and ruled out
- Caching only the JD parse. Repeats then shared one prompt (242 rows on 98 hashes in the stage 7 benchmark), but semantic and management still moved by up to 10 points on that identical prompt. A1 went from 21/36 to 18/36, which is noise. The scorer itself is not repeatable at temperature 0 (gemini-flash-latest).
- Averaging 2 or 3 calls. It doubles or triples the cost and still does not repeat.

## Watch out
- The benchmark must run with MATCH_SCORE_REUSE=0, which run_benchmark.py now sets. Otherwise A1 measures the cache and reads as a perfect 0 spread.
- Any change to `_LLM_SYSTEM_SCORER`, the prompt template or the parser's system prompt changes every hash, so every job is scored afresh once. That is intended.
- A benchmark run can hang forever if the Mac sleeps during a model call (no timeout). Run it under `caffeinate -i`. The runner skips rows already written, so a restart costs nothing twice.
