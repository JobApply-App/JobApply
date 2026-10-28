---
title: "Returning Google sign-ins always land on /discover, and the onboarding role step never loads saved roles"
author: RonMorim
date: 2026-10-28
branch: fix/pause-board-discovery
cost: { minutes: 2, tokens: 286283 }
id: l-ffdb3e91
scope: repo
status: active
src: agent
touches:
  - frontend/src/app/auth/callback/page.tsx
  - frontend/src/app/onboarding/page.tsx
  - frontend/src/app/accessibility/page.tsx
---

## Watch out
- frontend/src/app/auth/callback/page.tsx sends EVERY Google OAuth sign-in to /discover (the "complete your profile" banner page) or /auth/complete-profile. It never checks whether onboarding is already done. Email/password login (login/page.tsx) goes to "/" instead. So returning Google users look like they must redo onboarding.
- frontend/src/app/onboarding/page.tsx starts the role picker with `selected = []` and never calls fetchRolePreferences (GET /api/profile/preferences). Roles ARE persisted server-side (master_profile.role_preferences.target_titles via POST /api/profile/preferences), but re-entering shows an empty picker, so users press Skip.
- The accessibility statement exists at /accessibility (frontend/src/app/accessibility/page.tsx), but its only link is in components/Footer.tsx. Footer renders only on app/page.tsx (landing), ats-preview and analytics, so signed-in users on desktop or mobile can't reach it.
- "Onboarded" has three separate signals: Supabase user_metadata.profile_completed (UI), profiles.onboarding_status='complete' (pipeline, tenant_registry), and the presence of saved roles. Fix routing against the backend ones, not the metadata flag alone.
