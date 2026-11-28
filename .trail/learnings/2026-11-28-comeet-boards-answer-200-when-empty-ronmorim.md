---
title: "Comeet boards answer 200 [] when empty and 302 to the homepage when gone; neither is an adapter bug"
author: RonMorim
date: 2026-11-28
branch: fix/drop-dead-comeet-defaults
cost: { minutes: 8, tokens: 111832 }
id: l-7e5c9a08
scope: repo
status: active
src: agent
touches:
  - backend/api/routes/agents.py
  - backend/api/routes/jobs.py
  - backend/main.py
  - backend/scrapers/ats_board_adapters.py
  - backend/scrapers/scraper_manager.py
  - backend/tests/test_ats_board_adapters.py
  - backend/scrapers/comeet_adapter.py
  - backend/tests/test_comeet_adapter.py
---

## Decided
Dropped both Comeet defaults (Wix, Spark Hire) from `_seed_scraper_registry()` in `backend/main.py` on 2026-11-28. `ComeetAdapter._scrape_credentials` now raises "no Comeet board" when the page has no COMPANY_DATA.

## Tried and ruled out
Token scraping and the positions API both work. The token for 30.005 resolves; a fake token gets `400 "Account uid or token are not valid"`, so `200 []` with the real one means the board really is empty. The page's server-rendered `POSITIONS_DATA = []` agrees with it.

## Watch out
- A company that left Comeet 302s to comeet.com/, which returns 200. That page is Comeet's marketing page, not an error. Wix (ED.30A) does this and now hosts careers.wix.com itself.
- monday (41.00B) has a Comeet page that is also empty. Before adding any Comeet board, check its POSITIONS_DATA is non-empty first. No live Comeet board was found as a positive control on 2026-11-28.
- Comeet was renamed Spark Hire Recruit. The "Spark Hire" board is the vendor's own US board, not an Israeli employer.
