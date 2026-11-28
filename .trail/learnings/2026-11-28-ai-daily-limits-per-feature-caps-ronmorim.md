---
title: "AI daily limits: per-feature caps plus a spend ceiling summed from llm_usage"
author: RonMorim
date: 2026-11-28
branch: feat/llm-usage-and-caps
cost: { minutes: 15, tokens: 223311 }
id: l-37ca84fc
scope: repo
status: active
src: agent
touches:
  - backend/alembic_app_schema/versions/c7a4e2d9f1b3_add_fit_brief_i18n.py
  - backend/repositories/job_repository.py
  - backend/repositories/profile_repository.py
  - backend/schemas/job.py
  - backend/services/fit_brief_translation.py
  - backend/tests/test_fit_brief_translation.py
  - frontend/src/app/page.tsx
  - frontend/src/components/JobCard.tsx
  - frontend/src/components/JobFeed.tsx
  - frontend/src/components/matches/FocusView.tsx
---

## Decided
- Daily AI limits live in backend/api/deps.py. There are per-feature caps: daily_chat_limit (15), daily_generation_limit (4 CVs) and consume_daily_analysis (10). Behind them sits daily_ai_spend_limit ($2/user/day), which sums llm_usage.cost_usd. That table is written by llm_client for every successful call, background matching included. Every per-route llm_rate_limit route and the outreach POSTs carry it. The public Eliya chat has a per-IP daily cap of 30 (consume_daily_public_chat, kv_store).
- The spend ceiling fails open, with an ERROR log line, when the sum can't be read. It is a backstop, so a fault in the usage log must not take every AI feature down.
- llm_client pauses Gemini for 30 minutes after a 401/402/403/429 refusal. Production returned 402 on every call (Google billing), and each call waited for that failure.

## Tried and ruled out
- An earlier research doc (09-companies-and-costs.md) said there were no daily caps. That was wrong: grep deps.py for DAILY_ before claiming a cap is missing.

## Watch out
- conftest's autouse no_llm_usage_writes no-ops llm_client._write_usage. Without it, every mocked LLM call in the suite queues a real insert on a background thread.
- Prices in llm_client._PRICE_PER_MTOK match by model prefix. An unlisted model logs cost None and is not counted toward the ceiling, so add each new model there.
