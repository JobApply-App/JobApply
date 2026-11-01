---
title: Match-reason tags are stored as English phrases; the client translates them by shape
author: RonMorim
date: 2026-11-01
branch: fix/hebrew-coverage
cost: { minutes: 13, tokens: 176223 }
id: l-16e30846
scope: repo
status: active
src: agent
touches:
  - backend/agents/ariel_tools.py
  - backend/api/routes/chat.py
  - backend/api/routes/profile.py
  - backend/tests/test_addressing_form.py
  - frontend/src/app/auth/callback/page.tsx
  - frontend/src/app/auth/complete-profile/page.tsx
  - frontend/src/app/onboarding/page.tsx
  - frontend/src/app/signup/page.tsx
  - frontend/src/components/auth/SignupSteps.tsx
---

## Decided
- `backend/services/feed_service.py` (`_proficiency_reason_tags`) and `backend/agents/matcher.py` build reason tags as finished English phrases ("No Sql exp. (required)", "Python (academic match)", "Fintech domain fit", "Remote"), and they are persisted with the job, so a Hebrew user saw English on every card.
- Translation happens in the browser: `frontend/src/lib/reasonLabel.ts` parses the fixed shapes and fills `job_card.reason_labels` templates. This covers tags already in the DB, which a server-side change would not.

## Watch out
- Adding or rewording a reason template on the server means adding the same shape to `SHAPES` in `reasonLabel.ts`, or that tag shows in English to Hebrew users.
- `ArielInsightButton` must get `reasonSkill(label)`, not the raw label: it searches the capabilities list by skill name, and the full phrase never matched.
