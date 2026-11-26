---
title: next dev rewrites package-lock.json and next-env.d.ts; revert them before committing
author: RonMorim
date: 2026-11-26
branch: claude/redesign-phase0-fixes
cost: { minutes: 4, tokens: 44744 }
id: l-edb863e1
scope: repo
status: active
src: agent
touches:
  - docs/redesign-plan-2026-11.md
  - frontend/package-lock.json
  - frontend/next-env.d.ts
---

## Watch out
Starting the frontend dev server (`npm run dev`, e.g. the `frontend-live-api` launch config) prints "Found lockfile missing swc dependencies, patching..." and modifies `frontend/package-lock.json` (adds @next/swc entries) and `frontend/next-env.d.ts`. These are side effects of running the server, not part of any change. Run `git checkout -- frontend/package-lock.json frontend/next-env.d.ts` before committing so unrelated lockfile churn doesn't land in a PR.
