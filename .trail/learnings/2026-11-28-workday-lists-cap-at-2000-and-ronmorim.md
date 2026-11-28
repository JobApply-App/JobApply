---
title: Workday lists cap at 2000 and facet groups AND together; its Cloudflare refuses Python HTTP clients that curl gets past
author: RonMorim
date: 2026-11-28
branch: feat/workday-boards
id: l-3b6026f9
scope: repo
status: active
src: agent
touches:
  - backend/main.py
  - backend/scrapers/ats_board_adapters.py
  - backend/scrapers/scraper_manager.py
---

## Decided
`backend/scrapers/workday_adapter.py` reads a company's jobs from Workday's public `/wday/cxs/{tenant}/{site}/jobs` with the location facet for Israel, then one detail GET per posting for the JD (the list has no description). Israel only, no remote abroad: Ron's call on 2026-11-28, the same as Comeet, unlike Greenhouse/Lever. `ats_board_adapters.in_israel` is checked again on the detail's own locations, and a posting kept for its Israeli office shows that office as its location. Up to `MAX_POSTINGS` (50) per company per run, because `run_all` saves at most 50 jobs per sync anyway. The Workday sites are registered last in `_seed_scraper_registry()`.

## Tried and ruled out
Paging the whole list: Workday reports `total` as at most 2000 (NVIDIA), so a large employer can't be read whole without facets. One query for Israel plus Remote: values in two facet groups (`locationHierarchy1` "Israel", `locationHierarchy2` "Remote") combine as AND and return nothing together, so each needs its own query. Changing headers, body formatting or the TLS client to get past the 429s: that is bypassing bot protection. The adapter retries 429/503 three times (Retry-After or 2/4/8 s), then gives up and logs a warning.

## Watch out
Cloudflare in front of `*.myworkdayjobs.com` started answering httpx and requests with 429 after a burst, while curl from the same machine kept getting 200. It's the client, not the IP. A Workday company coming back with 0 jobs and a "refused" warning is this, not an empty board. Whether Render's IP is treated the same is unknown until a deploy.
