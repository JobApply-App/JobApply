---
title: Canva template research (docs/research/06-cv-generation.md section 49) works only through the signed-in Chrome
author: RonMorim
date: 2026-11-12
branch: claude/bugs-ui-improvements-31vblx
cost: { minutes: 1, tokens: 1572 }
id: l-48c70250
scope: repo
status: active
src: agent
touches:
  - docs/research/06-cv-generation.md
---

## Decided
- Research on Canva templates for `docs/research/06-cv-generation.md` (section 49) runs through Claude in Chrome on the founder's signed-in browser, at `https://www.canva.com/search/templates?q=<query>`. The public gallery `canva.com/templates/?query=` finds nothing for Hebrew, and `/he_il/templates/` returns 404.
- Screenshots stay out of git (`docs/research/canva-shots/`, excluded through `.git/info/exclude`). The repo is public and the images are other people's designs. Cite templates by ID: `canva.com/templates/<id>/`.

## Tried and ruled out
- Reading the template ID with `[^-/]+` cut IDs that contain `-` or `_`. IDs are `EA` plus 9 more characters.
- Reading `img.src` after scrolling: the grid is virtualised, and off-screen cards lose their src. Record each src while the card is in view.
- Getting the creator or the fonts from the template page HTML: it is client-rendered, and fonts are never listed. Fonts can only be identified by eye.
- An automatic detector for columns and sidebars on the preview images missed about a quarter of multi-column pages. Count columns by eye.

## Watch out
- Pixel access needs `crossOrigin='anonymous'` and the `/1131w/` image size.
- Every search reports about 20,000 matches and mixes in cover letters and job ads, so filter by title.
- Never open a template in the editor: that creates a design in the founder's account.
