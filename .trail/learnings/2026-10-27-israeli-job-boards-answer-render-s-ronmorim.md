---
title: "Israeli job boards answer Render's IP with 403; board discovery is paused behind BOARD_DISCOVERY_ENABLED"
author: RonMorim
date: 2026-10-27
branch: fix/pause-board-discovery
cost: { minutes: 18, tokens: 99764 }
id: l-d61235a6
scope: repo
status: active
src: agent
touches:
  - backend/config.py
  - backend/main.py
  - backend/services/board_discovery.py
  - backend/tests/test_board_search_terms.py
  - backend/api/routes/agents.py
  - backend/api/routes/jobs.py
  - backend/scrapers/alljobs_scraper.py
  - backend/scrapers/dialog_scraper.py
  - backend/scrapers/drushim_scraper.py
  - backend/scrapers/google_dork_scraper.py
---

## Decided
- Board discovery (backend/services/board_discovery.py) is off unless BOARD_DISCOVERY_ENABLED=true. The check lives inside run_board_discovery_cycle, so the "sync" button stops too, not only the loop. Turn it on only once there is a route the boards don't block (proxy / other network).

## Tried and ruled out
- Running the boards straight from Render: on 2026-10-27 Drushim, AllJobs, Gotfriends and Dialog returned 403 Forbidden on every request, and Nisha failed with an empty error. No proxy is configured (ProxyManager falls back to direct requests). The search terms and caps were correct; the sites refuse the IP.
- Setting BOARD_TERMS_PER_CYCLE=0 to stop it: the scrapers turn an empty keyword list into one empty search ([""]), which is the whole board listing. The cycle now skips an empty list instead.

## Watch out
- `fetched=0` from a board cycle reads like "no matching jobs". Check the httpx lines for 403 before concluding anything about terms or matchers.
- Auto-merge is disabled on this GitHub repo; merge manually after CI.
