---
title: "LLM rate limits live at router level in chat.py and outreach.py, per route elsewhere"
author: RonMorim
date: 2026-10-26
branch: main
cost: { minutes: 1, tokens: 0 }
id: l-a6902085
scope: repo
status: active
src: agent
touches:
  - backend/tests/test_llm_routes_rate_limited.py
---

## Decided
- Every route that reaches call_llm needs llm_rate_limit. Otherwise one user can run up the Anthropic bill without limit. chat.py and outreach.py attach it on the APIRouter. jobs.py, ariel.py, profile.py and resumes.py attach it per route. backend/tests/test_llm_routes_rate_limited.py lists the per-route ones, so add any new LLM route to LLM_ROUTES. Otherwise nothing fails when its limit goes missing.

## Tried and ruled out
- Counting `llm_rate_limit` per file to find gaps: this undercounts, because chat.py and outreach.py carry it on the router, not on each route. Check the APIRouter(dependencies=...) line first.

## Watch out
- profile.py's router-level limit is standard_rate_limit, not the LLM one. Because of that, its research and interview routes (message/resume/upload) ran with no LLM limit until #106.
