---
title: user_title_terms.source_titles must read career_goals.target_roles and top-level experience (cv_claims)
author: RonMorim
date: 2026-10-28
branch: fix/title-terms-sources
cost: { minutes: 20, tokens: 122510 }
id: l-f3ff6b88
scope: repo
status: active
src: agent
touches:
  - frontend/src/app/globals.css
  - frontend/src/app/layout.tsx
  - frontend/src/components/AccessibilityMenu.tsx
  - frontend/src/lib/a11yPrefs.test.ts
  - frontend/src/lib/a11yPrefs.ts
  - frontend/src/locales/en.ts
  - frontend/src/locales/he.ts
  - frontend/src/locales/types.ts
  - backend/tests/test_user_title_terms.py
  - frontend/src/app/auth/callback/page.tsx
---

## Decided
- backend/services/user_title_terms.py source_titles reads picked roles from role_preferences.target_titles (onboarding) OR career_goals.target_roles (Ariel's update_career_goals / update_profile_base). It reads CV titles from cv_data.experiences (old uploads) OR the top-level "experience" list (cv_claims, via profile_repository._read_cv).

## Watch out
- user_preferences.target_titles is filled by profile_repository.save from EITHER key, so "roles_count > 0" in SQL does not mean role_preferences exists in the profile JSON. Production 2026-10-28: 4 users with a CV or a role had no title_search_terms because of this, the founder among them.
- A user with no terms silently gets the global TARGET_SEARCH_QUERIES list. Check has_search_terms with the SQL in the PR (#121) before trusting per-user matching.
