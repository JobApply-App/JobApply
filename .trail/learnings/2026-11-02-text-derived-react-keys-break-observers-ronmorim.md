---
title: Text-derived React keys break observers attached once on mount when the language switches
author: RonMorim
date: 2026-11-02
branch: fix/landing-feed-scene
cost: { minutes: 57, tokens: 535011 }
id: l-9ac58ea4
scope: repo
status: active
src: agent
touches:
  - frontend/src/components/landing/LandingPage.tsx
  - frontend/src/components/LanguageSwitcher.tsx
  - frontend/src/locales/en.ts
  - frontend/src/locales/he.ts
  - frontend/src/locales/types.ts
  - frontend/src/components/ApplierPreview.tsx
  - frontend/src/components/ArielChat.tsx
  - frontend/src/components/ChatOverlay.tsx
  - frontend/src/components/JobCard.tsx
  - frontend/src/components/LiveEditor.tsx
---

## Decided
In the landing `Story` (frontend/src/components/landing/LandingPage.tsx) the steps use `key={i}`, not `key={s.title}`. The IntersectionObserver is attached once in a `[]` effect, so a key built from translated text replaces the DOM nodes on a language switch and leaves the observer watching detached elements: the feed stays scrambled and the scene never advances, with no error anywhere.

## Watch out
Any `key` built from dictionary text remounts on a locale change. Check this when an element is held by a ref that a mount-only effect uses.

Testing scroll animations in the browser pane: when `document.visibilityState` is `hidden` it runs at about 1 frame per second, so observers fire late and a working animation reads as stuck. Show the pane and check visibility before trusting the reading; a control run without a language switch caught this.
