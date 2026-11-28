---
title: "Comeet's careers_page_active_url can be the company's shared careers page; key Comeet jobs on careers_page_url"
author: RonMorim
date: 2026-11-28
branch: fix/comeet-per-position-url
cost: { minutes: 13, tokens: 33469 }
id: l-78c93978
scope: repo
status: active
src: agent
touches:
  - backend/main.py
  - backend/scrapers/comeet_adapter.py
  - backend/tests/test_comeet_adapter.py
---

## Decided
`_apply_url()` in `backend/scrapers/comeet_adapter.py` uses `careers_page_url` first, then `careers_page_active_url`, then `position_url`. The job_id (`make_job_id`) is a hash of that URL, so the URL must be unique per position.

## Tried and ruled out
`careers_page_active_url` first, which was the old order. It follows the company's settings and can point to its own generic careers page. On 2026-11-28, 113 of Comm-IT's (76.008) 124 positions shared `comm-it.com/commit-jobs#career-sec`, so 124 positions became 11 job IDs.

## Watch out
- Comm-IT (https://www.comeet.com/jobs/comm-it/76.008) is a live Comeet board: 124 positions, 47 in Israel. Use it as the positive control before saying "Comeet is broken".
- The same title can appear twice with different position_uids, one per city (17.574 Tel Aviv, 17.574-43.606 Hod Hasharon). They are separate jobs.
