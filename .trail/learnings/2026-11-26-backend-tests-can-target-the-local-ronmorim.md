---
title: Backend tests can target the local jobapply_test DB without editing backend/.env by stubbing load_dotenv
author: RonMorim
date: 2026-11-26
branch: claude/redesign-phase0-fixes
cost: { minutes: 5, tokens: 81244 }
id: l-8fd65e8f
scope: repo
status: active
src: agent
touches:
  - backend/config.py
---

## Decided
backend/config.py loads backend/.env with override=True, so a shell `DATABASE_URL=...` prefix is ignored and the conftest guard refuses the remote Supabase URL. Instead of editing .env, run pytest through a wrapper that disables load_dotenv first, pointing at the local `jobapply_test` database (Postgres on localhost:5432, socket /tmp):

DATABASE_URL="postgresql+psycopg2://ronmorim@localhost:5432/jobapply_test" .venv/bin/python -c "import dotenv,sys; dotenv.load_dotenv=lambda *a,**k: False; import pytest; sys.exit(pytest.main(['backend/tests/<file>.py','-q','-p','no:cacheprovider']))"

## Watch out
With load_dotenv stubbed, no other key from backend/.env is loaded either (ANTHROPIC_API_KEY, SUPABASE_*). That is fine for unit tests that mock the LLM; tests that need those keys will skip or fail. The undo in this session was only the dev-server lockfile churn already covered by l-edb863e1, nothing else was ruled out.
