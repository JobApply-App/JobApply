---
title: Session age is counted from the JWT amr claim; iat resets on every Supabase refresh
author: RonMorim
date: 2026-11-23
branch: claude/session-timeout-2h
cost: { minutes: 13, tokens: 240229 }
id: l-a38a2167
scope: repo
status: active
src: agent
touches:
  - backend/core/errors.py
  - backend/services/auth_utils.py
  - backend/tests/test_session_time_limit.py
  - docs/error-catalog.md
  - frontend/src/app/login/page.tsx
  - frontend/src/components/ApplierPreview.tsx
  - frontend/src/contexts/AuthContext.tsx
  - frontend/src/lib/api.ts
  - frontend/src/lib/sessionLimit.test.ts
  - frontend/src/lib/sessionLimit.ts
---

## Decided
- The 2-hour sign-in limit (Ron, 2026-11-23) reads the newest `amr[].timestamp` in the Supabase access token, both in backend/services/auth_utils.py (enforce_session_age) and frontend/src/lib/sessionLimit.ts. `iat`/`exp` are re-issued on every hourly refresh, so they never show when the person signed in.
- A token with no amr timestamp is rejected (fail closed). The backend answers code `session_time_limit`, and api.ts passes that code to AuthContext's auth-error handler.

## Tried and ruled out
- Relying on the old 401 handler alone: it calls getSession(), finds a "valid" Supabase session, refreshes the header and returns. An over-age token then just keeps getting 401s and the user is never signed out. That's why the handler needs the code.

## Watch out
- AuthContext._hardEvict runs localStorage.clear(). Anything that must survive a sign-out (the Live Editor draft, DRAFT_KEY) has to be read before the clear and written back after it.
- Supabase's own "Time-box user sessions" setting is Pro-plan only. The project is on the free plan, so the app code is the only enforcement.
