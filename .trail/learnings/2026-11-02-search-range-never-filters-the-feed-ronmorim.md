---
title: Search range never filters the feed; proximity is a hidden 0-3 score factor
author: RonMorim
date: 2026-11-02
branch: design/onboarding-steps
cost: { minutes: 12, tokens: 263198 }
id: l-b9ee7bda
scope: repo
status: active
src: agent
touches:
  - frontend/src/app/login/page.tsx
  - frontend/src/app/signup/page.tsx
  - frontend/src/components/auth/AuthLayout.tsx
  - frontend/src/components/auth/PhoneInput.tsx
  - frontend/src/components/auth/authStyles.ts
  - frontend/src/components/landing/LandingPage.tsx
  - frontend/src/components/landing/Ring.tsx
  - frontend/src/locales/en.ts
  - frontend/src/locales/he.ts
  - frontend/src/locales/types.ts
---

## Decided
- Ron (2026-11-02): jobs outside the user's search range stay in the feed and only gain nothing. The range does not hide jobs.
- Ron chose up to 3.0 points falling with distance (10 km 3.0, 25 km 2.0, 50 km 1.0), as a factor inside the match score, not a labelled bonus. So the UI shows no separate proximity line.
- It is a post-blend `proximity_delta` in `finalize_composite`, like culture: absent signal leaves the score bit-identical, the thin-JD path never computes it, it is never negative, and the knockout cap lands after it. Reweighting would have moved every score and penalised users without a city.
- Back from step 2 goes to `/onboarding?step=account` (edit name and phone), because the account already exists after step 1.

## Watch out
- Before this, `career_goals.preferred_locations` was stored but no matching or feed code read it, so the old area question had no effect.
- The factor applies at LLM scoring time only (`job_location=` on `compute_match_score_async`). Stored scores do not change when a user sets or changes their home city until the job is rescored.
- `backend/services/israel_cities.py` coordinates are city centres written by hand, not from a dataset. District-only locations other than Tel Aviv, Jerusalem and Haifa resolve to None on purpose.
