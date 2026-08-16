# Dev Soak Plan — before Production DB deployment

## Why this exists

`main` now runs the full DB redesign (PRs #16/#17/#18): Postgres as the primary
datastore, the relational profile/job schema, uniform RLS, dead-code cleanup.
All of it has been verified against **Dev** Supabase only — no soak period,
no Production credentials configured on any machine that did this work (see
`docs/db-architecture-spec.md`). This doc is the checklist to work through on
Dev before touching Production, not a schedule — sign off on the criteria
below, not a calendar date.

## What "soak" means here

Run the app against Dev exactly as it will run against Production — real
traffic pattern (your own usage, not a one-off migration script), for long
enough that background/periodic paths get exercised at least once, not just
the request/response paths a manual click-through covers.

## Checklist

### 1. Background/periodic paths get exercised at least once
These don't run on every request, so a short click-through misses them
entirely:
- [ ] `backend/main.py`'s enrichment loop (`_enrichment_loop`, 30s interval) —
      confirm it scores at least one newly-added job end to end.
- [ ] Discovery loop (interval=86400s / daily) — either wait for a real cycle
      or trigger it manually once; confirm it writes to `job_postings`/
      `user_job_matches` without FK errors.
- [ ] The Ofelia-scheduled LinkedIn scrape (`docker-compose.yml`, twice
      daily) — confirm one full run against `linkedin.jobs` + `all_jobs`.
- [ ] At least one full CV tailor → mark-applied → feedback cycle by hand,
      since that's the path that writes to the most tables in one flow
      (`user_job_matches`, `applications`, `cv_claims`/`profile_entities`).

### 2. Error logs — check, don't just glance
No centralized error tracking is wired up yet (no Sentry/equivalent — just
Python `logging` to stdout). Until that changes, "check the logs" means
actually reading them, not trusting a quiet terminal:
- [ ] Grep the full soak-period log for `ERROR`/`Traceback` — zero unexplained
      entries. Every `WARNING` should map to something already documented
      (e.g. `[ProxyManager] No proxies configured` is expected, not a signal).
- [ ] Specifically confirm zero `ForeignKeyViolation` / `IntegrityError` —
      the RLS + tenancy-FK work (PR #18) is exactly the kind of change that
      fails loudly here if a call site still writes an unscoped or stale
      `user_id`.
- [ ] Confirm zero `no such table` / `relation does not exist` — the
      signature of a stale reference to a dropped table slipping past review
      (see the `jobs`/`master_profiles` zombie-table bugs already caught and
      fixed this way).

### 3. Test frequency during the soak window
- [ ] Full `pytest backend/tests/` at the start of the window (baseline) and
      again at the end — both green, same pass count (315 as of this doc;
      update if the suite changes during soak).
- [ ] Re-run `pytest backend/tests/test_feedback_loop.py` specifically after
      any soak-period activity that rates jobs — it's the one file that
      creates and tears down real disposable Supabase accounts
      (`disposable_qa_account`), so it's the fastest signal that
      account-lifecycle (create/delete via the Admin Auth API) still works
      cleanly against whichever project Dev points at.
- [ ] One full manual smoke pass through the four core B2C features (Master
      Profile, Match Score, Template Engine, Live Editor) — pytest doesn't
      cover the frontend at all.

### 4. Schema/RLS spot-check (mirrors the eventual Production pre-check)
Run this against Dev now so the exact same query is a known-good baseline
when it's run against Production later:
```sql
-- table count
SELECT count(*) FROM information_schema.tables WHERE table_schema='public';
-- RLS coverage
SELECT count(*) FROM pg_class
  WHERE relnamespace='public'::regnamespace AND relkind='r' AND relrowsecurity;
-- policy count
SELECT count(*) FROM pg_policies WHERE schemaname='public';
-- zombie tables that must NOT exist
SELECT table_name FROM information_schema.tables
  WHERE table_schema='public' AND table_name IN ('jobs','master_profiles');
```
Expected on Dev right now: 21 tables, 21 with RLS, 36 policies, 0 zombie
tables. Record the actual numbers here when you run it — if they drift from
21/21/36/0 without an explanation (a deliberate new migration), stop and
find out why before Production is anywhere in the conversation.

### 5. Sign-off
- [ ] Every box above checked, with the date and who checked it.
- [ ] No open question from this list carried forward silently — if
      something couldn't be verified (e.g. the daily discovery loop didn't
      fire during the window), that's a reason to extend the soak window,
      not to check the box anyway.

## Explicitly out of scope here

- Actually deploying to Production — this doc only covers what has to be true
  on Dev *before* that conversation starts.
- Provisioning a second Supabase project — separate decision, not a technical
  step. As of 2026-08-16 there is exactly one project
  (`ynirccgaxwcwmbhkfxnh`), reached via the bare `DATABASE_URL`, and it
  serves both local development and the deployed Render service. The former
  `DATABASE_URL_DEV`/`_PROD` pair is gone: `_PROD` pointed at an empty second
  project, which is how production ended up authenticating against one
  database and reading from another.
