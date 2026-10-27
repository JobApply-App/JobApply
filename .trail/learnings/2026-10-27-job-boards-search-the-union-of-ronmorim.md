---
title: "Job boards search the union of users' cached title terms; caps and a kv-persisted rotation bound the cost"
author: RonMorim
date: 2026-10-27
branch: feat/per-user-board-search
cost: { minutes: 13, tokens: 91947 }
id: l-e82f73aa
scope: repo
status: active
src: agent
touches:
  - backend/services/board_search_terms.py
  - backend/config.py
  - backend/services/board_discovery.py
  - backend/tests/test_board_search_terms.py
---

## Decided
- Israeli boards (Drushim, AllJobs, Gotfriends, Dialog, Nisha) run from backend/services/board_discovery.py: one cycle for all pipeline users, searching the union of their cached title terms (board_search_terms.union_terms), capped at BOARD_TERMS_PER_CYCLE=10 with 70% of slots for Hebrew, every 4h. Each job is saved only for users whose build_title_matcher accepts it.
- Google Dork stays per user (discovery._dork_terms_for) with that user's OWN terms, capped at 8 (20 queries vs 90). Using the union there would repeat the same queries once per user.
- Terms are read with user_title_terms.cached_terms_for_users: one narrow query on profile_answers. Not get_profile_json, which pulls the whole profile (Supabase egress). No LLM call in these loops; refresh_user_terms in the all-jobs loop fills the cache.
- Board scrapers and Dork are no longer registered in SCRAPER_MANAGER (main._seed_scraper_registry). It holds only Comeet now. The "sync" button and /api/jobs/scrape call run_board_discovery_cycle([uid], respect_interval=False).

## Tried and ruled out
- In-memory rotation cursor / interval: the Render free instance restarts on every wake, so it would reset to 0 and re-run the same first window on each wake. Both live in kv_store (search_terms_cycle:*, board_discovery:last_run).
- Letting a single word cover longer terms in the union ("Manager" covering "Product Manager"): searching one generic word returns 5 pages of unrelated jobs and loses the specific role. Only multi-word terms may cover others.

## Watch out
- Before this change the boards never ran in the background, only on "sync". A board-volume number from before 2026-10-27 is button traffic only.
- Local jobapply_test can lag CI's preparation. Run CI's steps on it (ci-bootstrap-auth.sql, drop fk_profiles_id_auth_users, ci-seed-qa-users.sql, alembic upgrade head). Otherwise profile/locale tests fail for reasons unrelated to the change.
