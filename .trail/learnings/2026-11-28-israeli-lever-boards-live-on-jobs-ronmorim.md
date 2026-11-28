---
title: "Israeli Lever boards live on jobs.eu.lever.co, which the US Lever API cannot see; detect the ATS from the careers page"
author: RonMorim
date: 2026-11-28
branch: feat/workday-boards
id: l-b3693608
scope: repo
status: active
replaces: l-774a3b57
src: agent
touches:
  - backend/api/routes/jobs.py
  - backend/main.py
  - backend/scrapers/ats_board_adapters.py
  - backend/tests/test_ats_board_adapters.py
---

## Decided
Default boards in `_seed_scraper_registry()` (`backend/main.py`): 22 Greenhouse boards, Comm-IT on Comeet, Mobileye on Lever EU (`https://jobs.eu.lever.co/mobileye`, 150 jobs, all in Israel, on 2026-11-28), then 8 Workday sites last. Each Greenhouse slug was checked against the board's own name, so `via` really is Via.
`LeverBoardAdapter` calls `api.eu.lever.co` when the company URL is on `jobs.eu.lever.co`. Greenhouse EU boards (`job-boards.eu.greenhouse.io`) are served by the shared `boards-api.greenhouse.io`, so they only needed the host accepted.
`backend/scrapers/ats_detect.py` finds the ATS behind a careers page by URL patterns in its links (no AI): Mobileye → Lever EU, NICE → Greenhouse EU, Fiverr → Comeet, CyberArk → Palo Alto's Workday. `adapter: "auto"` in `/jobs/scrape` uses it. The board linked most often wins, because Mobileye's page also links a subsidiary's Comeet board.

## Tried and ruled out
The earlier finding "Lever has no Israeli companies" came from probing only `api.lever.co`. The EU boards are invisible there, so that result was a check that never reached them, not evidence. Pages that load their board from a script (Playtika's greenHouseMain.js) or use Ashby, HiBob, or Eightfold give None; there is no adapter for those.

## Watch out
`ScraperManager.run_all` saves in registration order and stops at `MAX_RELEVANT_JOBS` (50), so order decides who fills a sync. Mobileye goes after the Greenhouse boards because its 150 postings alone could fill the cap. Re-probe before adding to the list, because slugs and boards change.
