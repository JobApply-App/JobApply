---
title: "Screens style themselves inline, so the redesign lands through Tailwind tokens, not shared components"
author: RonMorim
date: 2026-10-30
branch: design/foundation
cost: { minutes: 71, tokens: 734396 }
id: l-c5400638
scope: repo
status: active
src: agent
touches:
  - DESIGN_SYSTEM.md
  - docs/design-redesign.md
  - frontend/src/app/globals.css
  - frontend/src/components/Header.tsx
  - frontend/tailwind.config.ts
---

## Decided
- Almost every screen hand-rolls its Tailwind classes; `src/components/ui/Button.tsx` had zero imports (Oct 2026). Shared leverage lives in `tailwind.config.ts`: the `shadow-elevation-1/2`, `shadow-floating`, `shadow-card` tokens (~40 uses), `animate-modal-in` (11 modals) and the DEFAULT transition curve. Changing those reaches every screen at once; phase 1 of `docs/design-redesign.md` did exactly that.
- Palette, fonts and `ui/Logo.tsx` are locked by Ron. Ariel's chat keeps the product's colours: user bubble teal-50, Ariel bubble white with slate-100 border, violet only for her identity (avatar gradient, header, input focus). A prototype with violet answer bubbles was corrected by Ron.

## Tried and ruled out
- A blanket `prefers-reduced-motion` rule forcing `animation-iteration-count: 1` on `*` (the pattern `a11y-no-animation` uses) freezes infinite spinners and makes loading look stuck. The global rule in `globals.css` collapses transitions and only the named entrance animations.

## Watch out
- Opening a modal from Matches to check visuals runs a paid AI analysis that counts against the daily limit; verify modal CSS from the compiled stylesheet instead.
- Primary teal #0D9488 under white text is 3.74:1, below AA for body-size text; #0F766E (also in the palette) passes.
