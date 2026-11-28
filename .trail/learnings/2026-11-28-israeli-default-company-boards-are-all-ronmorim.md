---
title: "Israeli default company boards are all Greenhouse; Lever had none, and the list order decides who fills the 50-job cap"
author: RonMorim
date: 2026-11-28
branch: feat/ats-board-adapters
id: l-774a3b57
scope: repo
status: active
src: agent
touches:
  - backend/main.py
---

## Decided
The 22 default boards in `_seed_scraper_registry()` (`backend/main.py`) were picked on 2026-11-28 by probing about 90 Israeli company slugs against both list APIs and keeping only the boards that had Israel-or-remote jobs. Each slug was checked against the board's own name (`GET boards-api.greenhouse.io/v1/boards/{slug}` → `name`) so that, for example, `via` really is Via.

## Tried and ruled out
Lever for Israeli companies: yotpo, bringg, dataloop, fireblocks, guesty, coralogix, elementor and others either have no Lever board or have no Israel-or-remote jobs there. Several Israeli companies we expected (monday, Check Point, CyberArk, Cyera, Wix) are not on Greenhouse; they use Comeet or their own sites.

## Watch out
`ScraperManager.run_all` saves companies in registration order and stops at `MAX_RELEVANT_JOBS` (50), so the companies at the top of the list fill a user's sync first. The list is ordered by Israel-or-remote job count as of 2026-11-28. Re-probe before adding to it, because slugs and boards change.
