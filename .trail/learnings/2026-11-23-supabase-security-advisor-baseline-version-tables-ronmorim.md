---
title: "Supabase Security Advisor baseline: version tables need RLS, kv_store/all_jobs 'no policy' is intended"
author: RonMorim
date: 2026-11-23
branch: claude/rls-alembic-version-tables
cost: { minutes: 2, tokens: 31677 }
id: l-8f7f838b
scope: repo
status: active
src: agent
touches:
  - backend/alembic_app_schema/versions/a7c31e5d9b20_rls_on_alembic_version_tables.py
  - backend/core/errors.py
  - backend/services/auth_utils.py
  - backend/tests/test_session_time_limit.py
  - docs/error-catalog.md
  - frontend/src/app/login/page.tsx
  - frontend/src/components/ApplierPreview.tsx
  - frontend/src/contexts/AuthContext.tsx
  - frontend/src/lib/api.ts
  - frontend/src/lib/sessionLimit.test.ts
---

## Decided
- Security Advisor (2026-11-23) showed 2 errors: RLS disabled on `alembic_version` and `alembic_version_app_schema`. Fixed by migration `a7c31e5d9b20`: RLS on, no policies (same as `kv_store` in `e34f0ea56e30`). Without RLS the public anon key could update or delete the version rows and break the next deploy's `alembic upgrade head`.
- The 2 "RLS Enabled No Policy" infos (`kv_store`, `all_jobs`) are intended: backend-only tables, deny all client roles. Don't "fix" them by adding policies.

## Watch out
- No `FORCE ROW LEVEL SECURITY` on the version tables. Alembic writes its own row as the owner; the backend role is `postgres` (BYPASSRLS), but don't rely on that alone for Alembic's own bookkeeping.
- The one remaining warning, Leaked Password Protection, is a Supabase Pro feature; it can't be turned on while the project is on the free plan.
- Migrations are verified offline only (`alembic -c alembic_app_schema.ini upgrade <from>:<to> --sql` with a dummy DATABASE_URL). The single Supabase project is production, so never run them against it from a dev machine; Render applies them on deploy via `docker-entrypoint.sh`.
