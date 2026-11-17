---
title: "Scoring a profile offline needs a local Postgres and the real upload path; each score is two model calls, Gemini first in production"
author: RonMorim
date: 2026-11-13
branch: claude/bugs-ui-improvements-31vblx
cost: { minutes: 49, tokens: 650536 }
id: l-7de291ee
scope: repo
status: active
src: agent
touches:
  - docs/research/07-benchmark-plan.md
  - docs/research/benchmark/build_sheet.py
  - docs/research/benchmark/people/01-noam-ravid.yaml
  - docs/research/benchmark/people/02-shira-kleiner.yaml
  - docs/research/benchmark/people/03-tomer-elad.yaml
  - docs/research/benchmark/people/04-ruth-avni.yaml
  - docs/research/benchmark/people/05-lior-shemesh.yaml
  - docs/research/benchmark/people/06-maya-dabush.yaml
  - docs/research/benchmark/people/07-gal-peretz.yaml
  - docs/research/benchmark/people/08-yael-zohar.yaml
---

## Decided
- The stage 7 benchmark (docs/research/benchmark/run_benchmark.py) ingests each invented person through backend/api/routes/profile.py `_ingest_cv_full` and scores the way backend/services/feed_service.py does. compute_match_score_async reads the Confidence Matrix, knockout prefs, skill depth and location by user_id, and falls back silently when rows are missing, so a hand-built cv_data dict does not give the score a real user gets.
- It runs on a local Postgres, `jobapply_bench`, built with the CI recipe (docs/research/benchmark/setup_local_db.sh). The runner refuses any database that is not localhost with "bench" in its name.
- Model calls are counted by wrapping `llm_client._call_anthropic` and `_call_gemini`, which `call_llm` resolves at call time. Callers import `call_llm` by name, so patching `call_llm` itself changes nothing.

## Tried and ruled out
- SQLite fallback (no DATABASE_URL): fails at profile_repository.get_or_create with "no such table: public.profiles"; the profile code uses Postgres-only SQL.
- Sharing user ids between dry and live runs: a dry run left stub profiles that a live run then skipped as "already ingested". Dry-run users now get their own ids.

## Watch out
- Production answers with gemini-flash-latest first (GEMINI_API_KEY set on Render); the local backend/.env has that key commented out, so a local run measures Claude, not what users get.
- compute_match_score_async sends every job ad through JDParserAgent (Sonnet, uncached) and applies the 300-character thin-JD cutoff to the parser's condensed text, not to the ad.
- A CV upload starts a background `title_search_terms` model call.
