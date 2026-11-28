---
title: "Greenhouse/Lever company boards keep only jobs in Israel or open to remote, and IL in a location means Illinois"
author: RonMorim
date: 2026-11-28
branch: feat/ats-board-adapters
id: l-2a07aca8
scope: repo
status: active
src: agent
touches:
  - backend/api/routes/jobs.py
  - backend/scrapers/scraper_manager.py
---

## Decided
2026-11-28, founder's call: `backend/scrapers/ats_board_adapters.py` keeps a posting only when one of its locations is in Israel or it can be done remotely (`israel_or_remote`). A remote posting with an office abroad is kept on purpose: the founder said remote work must never be ruled out, because a job like that can be done from Israel. A posting with several locations (Greenhouse `offices`, Lever `allLocations`) is kept when any one of them is in Israel. Expanding beyond Israel later means changing this one gate.

## Tried and ruled out
Treating a trailing ", IL" as Israel. Live data had "Chicago, IL" (Illinois) passing as Israeli. Israel is matched by the word Israel/ישראל, by `services/israel_cities.resolve_city`, or by Lever's `country == "IL"` field, never by a bare "IL" in free text.

## Watch out
"Remote - USA" postings are kept, but many of them require residence in that country. If users complain about those, the fix is to read the region after "Remote" rather than to drop remote jobs.
