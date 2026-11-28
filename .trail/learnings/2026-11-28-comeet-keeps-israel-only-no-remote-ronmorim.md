---
title: "Comeet keeps Israel only (no remote abroad), and a city variant's detail call returns its parent"
author: RonMorim
date: 2026-11-28
branch: fix/comeet-per-position-url
cost: { minutes: 3, tokens: 30754 }
id: l-d2673390
scope: repo
status: active
src: agent
touches:
  - backend/scrapers/comeet_adapter.py
  - backend/tests/test_comeet_adapter.py
  - backend/main.py
---

## Decided
2026-11-28, Ron's call: `ComeetAdapter` keeps only positions in Israel (`israel_only=True` by default) and drops remote jobs abroad. This is stricter than Greenhouse/Lever, which keep Israel or remote. The filter runs before detail fetches. `_in_israel()` trusts `location_object.country` ("IL" is an ISO code here, not Illinois). Without a country it matches the city against `israel_cities.resolve_city`.
Comm-IT (76.008) is registered in `_seed_scraper_registry()` after the Greenhouse boards, so it doesn't push them past MAX_RELEVANT_JOBS. Live result: 124 positions, 48 in Israel, 48 unique job IDs.

## Tried and ruled out
Merging the detail over the list item (`{**pos, **detail}`). The detail call for a city variant (17.574-43.606, Hod Hasharon) returns the parent 17.574 (Tel Aviv), and that overwrote the variant's URL and city, producing a duplicate. The list item now wins (`{**detail, **pos}`).

## Watch out
Comeet's `Remote` field ("Remote"/"Hybrid"/"On-site") says nothing about the country. A "Remote" job with country PL is abroad.
