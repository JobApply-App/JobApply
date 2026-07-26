#!/bin/sh
# Twice-daily scheduled LinkedIn scrape, triggered by Ofelia's job-exec
# against the running `backend` container (see docker-compose.yml's
# `ofelia` service and the `backend` service's ofelia.* labels) — not a
# separate always-running process. Runs at 00:00 and 12:00; --hours 12
# matches that cadence exactly (no gap, no overlap between runs).
#
# linkedin_israel_jobs.py writes straight to Supabase (linkedin.jobs AND
# public.all_jobs) on its own — no CSV, no second script to chain. Both
# writes keep their own two-step safety gate (--allow-linkedin-request +
# ALLOW_LINKEDIN_SCRAPE=true) — this script sets both explicitly rather
# than loosening the guard.
set -u
cd /app

echo "[scheduled-scrape] Starting at $(date -u +%Y-%m-%dT%H:%M:%SZ)"

ALLOW_LINKEDIN_SCRAPE=true python -m backend.scripts.linkedin_israel_jobs \
  --allow-linkedin-request --hours 12
SCRAPE_EXIT=$?

if [ "$SCRAPE_EXIT" -ne 0 ]; then
  echo "[scheduled-scrape] Scraper exited $SCRAPE_EXIT"
  exit "$SCRAPE_EXIT"
fi

echo "[scheduled-scrape] Done at $(date -u +%Y-%m-%dT%H:%M:%SZ)"
