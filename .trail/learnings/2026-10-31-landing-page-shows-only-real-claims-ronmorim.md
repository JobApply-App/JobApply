---
title: "Landing page shows only real claims; view it logged out via 127.0.0.1, not localhost"
author: RonMorim
date: 2026-10-31
branch: design/landing
cost: { minutes: 14, tokens: 484967 }
id: l-d433aed6
scope: repo
status: active
src: agent
touches:
  - frontend/src/app/page.tsx
  - frontend/src/components/landing/LandingPage.tsx
  - frontend/src/locales/en.ts
  - frontend/src/locales/he.ts
  - frontend/src/locales/types.ts
  - docs/design-redesign.md
---

## Decided
- The public landing (frontend/src/components/landing/LandingPage.tsx) carries only real figures: ~10,000 LinkedIn jobs, daily limits 10 analyses / 4 tailored CVs / 40 Ariel messages. The old page's AllJobs/Drushim sources, "24/7" and the 95% interview rate were dropped as unsupported by the product.
- Example content (jobs, Maya's CV) must not contradict the page: the tailored CV line may only rephrase the original, since the page says "No facts were added".
- One dark surface per page (docs/design-redesign.md): the Ariel band is it; the closing box is light.
- Ariel's chat on the landing uses the product's colours (user teal-50, Ariel white + slate-100 border); violet is only her avatar/identity.

## Watch out
- `/` shows the landing only when signed out. To check it without signing Ron out, open http://127.0.0.1:3000 instead of localhost:3000: it's a separate origin, so the Supabase session in localStorage isn't there.
- Logged out, I18nContext calls /api/settings/locales and gets 401s in the console. That's pre-existing and not caused by the landing.
- Animate list re-ordering with transform: translateY. Changing `top` jumps, even with a transition on transform.
