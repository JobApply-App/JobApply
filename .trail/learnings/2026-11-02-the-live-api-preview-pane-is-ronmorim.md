---
title: "The live-API preview pane is signed in to a real account: pressing Continue writes to production"
author: RonMorim
date: 2026-11-02
branch: design/onboarding-steps
cost: { minutes: 17, tokens: 125146 }
id: l-c30d7018
scope: repo
status: active
src: agent
touches:
  - backend/tests/test_proximity.py
  - backend/api/routes/profile.py
  - backend/api/routes/resumes.py
  - backend/scripts/ingest_pasted_job.py
  - backend/services/feed_service.py
  - backend/services/israel_cities.py
  - backend/services/match_score_service.py
  - backend/services/user_profile.py
  - frontend/src/app/onboarding/page.tsx
  - frontend/src/components/RolePicker.tsx
---

## Watch out
- The `design-branch-live-api` preview talks to the production API, and its browser pane may hold a real session. On 2026-11-02 a scripted click on Continue in onboarding step 2 saved to the signed-in account and cleared its four saved areas.
- Before scripting any click that could save, patch `window.fetch` in the page to reject non-GET requests and assert the patch is there. Only then press the button.
- It got through because the deployed API did not yet return `home_city` or `search_mode`. `prev ?? undefined` left them `undefined`, and `homeCity !== null` then read as "has a city". New response fields can be missing while Vercel and Render deploy apart, so check them with `Boolean()` or `??`, not `!== null`.
