---
title: "Gemini cost is priced by the served model_version, counts thinking tokens as output, and treats cached tokens as part of the prompt"
author: RonMorim
date: 2026-11-28
branch: fix/gemini-usage-cost
id: l-20b54259
scope: repo
status: active
src: agent
touches:
  - backend/services/llm_client.py
---

## Decided
`backend/services/llm_client.py` prices Gemini with `_GEMINI_PRICE_PER_MTOK`, Google's published paid-tier rates (ai.google.dev/gemini-api/docs/pricing), keyed by the response's `model_version` and not by our `gemini-flash-latest` alias, because Google retargets the alias. Rates are dated tiers, so a published price change goes in as a new tier, not an edit. A Gemini model missing from the table is counted at the dearest listed rate with a one-time warning, never None: `cost_usd` feeds `deps.daily_ai_spend_limit`, and None makes a call free to the ceiling. Streamed Gemini turns are logged like non-streamed ones.

## Tried and ruled out
Backfilling Gemini rows that have no cost. A row written before this change records the alias, not the served model, and leaves out thinking tokens, so any backfilled cost would be a guess. The ceiling only sums the current UTC day, so those rows don't affect it.

## Watch out
`output_tokens` on a Gemini row is candidates + thoughts: thinking is billed at the output rate and is not in `candidates_token_count`. `prompt_token_count` already includes `cached_content_token_count`, so the Anthropic formula in `estimate_cost_usd` (cache billed on top of input) must not be used for Gemini.
