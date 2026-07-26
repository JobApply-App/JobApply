#!/bin/sh
# Twice-daily scheduled LinkedIn scrape, triggered by Ofelia's job-exec
# against the running `backend` container (see docker-compose.yml's
# `ofelia` service and the `backend` service's ofelia.* labels) — not a
# separate always-running process. Runs at 00:00 and 12:00; --hours 12
# matches that cadence exactly (no gap, no overlap between runs).
#
# Chains the two already-existing, independently-guarded scripts so one
# scheduled trigger populates both linkedin.jobs (dual-persisted by the
# scraper itself) and public.all_jobs (this wrapper's second step):
#   1. backend/scripts/linkedin_israel_jobs.py        -> linkedin.jobs + CSV
#   2. backend/scripts/upsert_linkedin_csv_to_all_jobs.py -> public.all_jobs
#
# Both scripts keep their own two-step safety gates (--allow-linkedin-request
# + ALLOW_LINKEDIN_SCRAPE=true; --allow-write + ALLOW_SUPABASE_APP_MIGRATION=true)
# — this script sets them explicitly rather than loosening either guard.
set -u
cd /app

echo "[scheduled-scrape] Starting at $(date -u +%Y-%m-%dT%H:%M:%SZ)"

OUTPUT=$(ALLOW_LINKEDIN_SCRAPE=true python -m backend.scripts.linkedin_israel_jobs \
  --allow-linkedin-request --hours 12 2>&1)
SCRAPE_EXIT=$?
echo "$OUTPUT"

if [ "$SCRAPE_EXIT" -ne 0 ]; then
  echo "[scheduled-scrape] Scraper exited $SCRAPE_EXIT — aborting before any all_jobs upsert."
  exit "$SCRAPE_EXIT"
fi

# The scraper only prints this line when jobs.length > 0 (see
# linkedin_israel_jobs.py's main()) — no line at all means 0 jobs found in
# the window, which is a legitimate, non-error outcome, not a failure.
CSV_PATH=$(echo "$OUTPUT" | grep "CSV export:" | sed 's/^ *CSV export: //')

if [ -z "$CSV_PATH" ]; then
  echo "[scheduled-scrape] No jobs found this run — nothing to upsert into all_jobs."
  exit 0
fi

echo "[scheduled-scrape] Upserting $CSV_PATH into public.all_jobs"
ALLOW_SUPABASE_APP_MIGRATION=true python -m backend.scripts.upsert_linkedin_csv_to_all_jobs \
  --csv "$CSV_PATH" --allow-write
UPSERT_EXIT=$?

if [ "$UPSERT_EXIT" -ne 0 ]; then
  echo "[scheduled-scrape] all_jobs upsert exited $UPSERT_EXIT — linkedin.jobs and the CSV are still intact."
  exit "$UPSERT_EXIT"
fi

echo "[scheduled-scrape] Done at $(date -u +%Y-%m-%dT%H:%M:%SZ)"
