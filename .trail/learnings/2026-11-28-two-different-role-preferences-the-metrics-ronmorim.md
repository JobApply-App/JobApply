---
title: "Two different role_preferences: the metrics document's is not the profile's"
author: RonMorim
date: 2026-11-28
branch: feat/company-preferences
cost: { minutes: 34, tokens: 307451 }
id: l-6acf630e
scope: repo
status: active
src: agent
touches:
  - backend/api/routes/profile.py
  - backend/repositories/company_repository.py
  - backend/services/industry_groups.py
  - backend/services/match_score_service.py
  - backend/tests/test_company_preferences.py
  - frontend/src/app/onboarding/page.tsx
  - frontend/src/components/profile/ProfilePage.tsx
  - frontend/src/lib/api.ts
  - frontend/src/lib/profileView.test.ts
  - frontend/src/lib/profileView.ts
---

## Watch out
`master_profile_service.load(user_id)` returns `master_profile["metrics_doc"]`, whose `role_preferences` (work_type, culture_preference) is a different dict from the profile's own `role_preferences` (roles, target_titles, written by POST /api/profile/preferences). No screen writes the metrics one: in production (2026-11-28) all 14 metrics docs held work_type "any" and no culture_preference.

What users actually state lives in the profile's `career_goals`: `work_environment` (onboarding "About you"), and since phase 3 `company_type`, `industries_prefer`, `industries_avoid` (POST /api/profile/company-preferences, onboarding question 5).

## Decided
`_load_culture_prefs` in backend/services/match_score_service.py reads career_goals first. It falls back to the metrics document only for its remote work_type, and for the culture_preference that feedback_service learns from ratings. A stated company_type other than "any" always beats the learned one. Before this, the onboarding work model never reached the match score.
