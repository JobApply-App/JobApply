---
title: Next.js 14 has no patched release; security fixes need 15.5.29+ (React 19) plus a postcss override
author: RonMorim
date: 2026-11-23
branch: claude/security-deps-pii-logs
cost: { minutes: 12, tokens: 63429 }
id: l-ce2a19c0
scope: repo
status: active
src: agent
touches:
  - ".github/dependabot.yml"
---

## Decided
- 2026-11-23: frontend moved from next 14.2.35 to 15.5.29 with React 19. Every 14.x release, including the last one (14.2.35), is inside the ranges of 25 Next.js advisories, critical ones among them. 15.5.29 is the first version clear of all of them (16.4.6 is the other option).
- next 15.5.29 pins postcss 8.4.31 internally, and npm audit flags it. package.json `overrides` forces `$postcss` (devDependency pinned exactly to 8.5.32), and also pins nanoid 3.3.19 and source-map-js 1.2.2. These are the oldest fixed versions that were at least two weeks old; `npm audit fix` had picked releases from that same week.
- The React 19 type changes were types only: `useRef<T>(null)` is now `RefObject<T | null>` (useDialogA11y, AllJobsTab useClickOutside), and the global `JSX` became `React.JSX`.

## Watch out
- `next lint` / `next build` on 15 rewrite tsconfig.json (adding target ES2017 and reformatting the whole file). Keep only the target line.
- `npm audit` (dev included) still flags brace-expansion, which comes in through the eslint 8 tooling. It is dev-only and never ships.
- Dependabot (.github/dependabot.yml) now opens weekly PRs. Remove overrides once next stops pinning a vulnerable postcss.
