---
title: "Render's Docker Command replaces the image ENTRYPOINT, so migrations need the entrypoint called explicitly"
author: RonMorim
date: 2026-10-31
branch: fix/migrations-run-on-render
cost: { minutes: 54, tokens: 435896 }
id: l-9d549d34
scope: repo
status: active
src: agent
touches:
  - backend/core/migrations.py
  - backend/main.py
  - backend/tests/test_analyze_async_and_workday.py
  - backend/tests/test_schema_status.py
  - render.yaml
  - backend/api/routes/chat.py
  - backend/tests/test_eliya_support.py
  - frontend/src/components/landing/LandingPage.tsx
  - frontend/src/locales/en.ts
  - frontend/src/locales/he.ts
---

## Decided
render.yaml dockerCommand is `/usr/local/bin/docker-entrypoint.sh uvicorn backend.main:app --host 0.0.0.0 --port $PORT`. The entrypoint (backend/scripts/docker-entrypoint.sh) is what runs `alembic -c alembic_app_schema.ini upgrade head`; on Postgres, core/migrations.init_db() creates nothing.

## Tried and ruled out
`dockerCommand: uvicorn ...` on the assumption it replaces CMD only. On Render it replaces the ENTRYPOINT too: from 2026-10-17 (jobapply-backend-sg created) to 2026-10-31 no migration ran in production. No `[entrypoint]` line appears in any deploy log.

## Watch out
- jobapply-backend-sg is not blueprint-managed: editing render.yaml does not change the live service; the Docker Command must be set in the Render dashboard.
- A missing table does not show as an error to users: support_message_repository calls are wrapped in _support_store(), which logs and swallows, and the route still returns 200. Check `/health` "schema" (core/migrations.schema_status()) or `alembic current` after a deploy that adds a migration, not a 200 from the route.
