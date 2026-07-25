"""
LinkedIn Scraper Reset Utility
================================
Clears the BLOCKED state and stale browser profile so the scraper can boot
cleanly — but keeps the enrichment loop suppressed until you explicitly resume
it with a fresh cookie.

WORKFLOW
--------
Step 1 (run this):
    venv/bin/python -m backend.scripts.reset_linkedin_scraper --pause

    Clears BLOCKED + error counters, deletes stale browser profile, and sets
    linkedin_scraper_paused=1 so the enrichment loop stays halted even though
    the BLOCKED flag is gone.  The UI banner will now say "Paused" instead of
    "Connection Blocked".

Step 2 (manual):
    Update LINKEDIN_LI_AT in backend/.env with a fresh li_at cookie from
    linkedin.com (DevTools → Application → Cookies → li_at).

Step 3 (run this):
    venv/bin/python -m backend.scripts.reset_linkedin_scraper --resume

    Clears linkedin_scraper_paused and lets the enrichment loop attempt
    LinkedIn scraping with the new cookie.

Usage:
    --pause     Clear BLOCKED state + set pause gate (use before cookie update)
    --resume    Clear pause gate (use after cookie update — loop restarts)
    --status    Print current KV state without changing anything
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.repositories import kv_repository

_ALL_SCRAPER_KEYS = [
    "linkedin_scraper_status",
    "linkedin_redirect_error_count",
    "linkedin_scraper_blocked_at",
    "linkedin_cookie_status",
    "linkedin_scraper_paused",
]

BROWSER_PROFILE = ROOT / "backend" / "data" / "linkedin_browser_profile"
ENV_FILE        = ROOT / "backend" / ".env"


def _print_kv_state() -> None:
    print("\n── Current KV state ───────────────────────────────────────────────────")
    for key in _ALL_SCRAPER_KEYS:
        entry = kv_repository.get(key)
        value = entry.value if entry else "(not set)"
        print(f"  {key:<45s} = {value!r}")


def do_pause() -> None:
    """Clear BLOCKED + error counters; set pause gate; delete browser profile."""
    print("\n── Step 1: Clear BLOCKED state + set pause gate ───────────────────────")
    keys_to_delete = [
        "linkedin_scraper_status",
        "linkedin_redirect_error_count",
        "linkedin_scraper_blocked_at",
        "linkedin_cookie_status",
    ]
    # One shared session/transaction for the whole delete-sequence + pause-gate
    # upsert, so an interruption mid-sequence rolls back to the pre-pause state
    # instead of leaving the KV store partially reset.
    with kv_repository.kv_session() as s:
        for key in keys_to_delete:
            entry = kv_repository.get(key, session=s)
            if entry:
                print(f"  Deleted   {key:<45s} (was: {entry.value!r})")
                kv_repository.delete(key, session=s)
            else:
                print(f"  (absent)  {key}")

        # Set pause gate — kept for future use; cleared by --resume.
        kv_repository.upsert("linkedin_scraper_paused", "1", session=s)
    print(f"  Set       linkedin_scraper_paused             = '1'  (loop halted)")

    print("\n── Step 2: Delete browser profile ────────────────────────────────────")
    if BROWSER_PROFILE.exists():
        shutil.rmtree(BROWSER_PROFILE)
        print(f"  Deleted   {BROWSER_PROFILE}")
    else:
        print(f"  (absent)  {BROWSER_PROFILE}")

    _check_env()

    print("""
── Next step ──────────────────────────────────────────────────────────
  The enrichment loop is now PAUSED (not BLOCKED).
  1. Grab a fresh li_at cookie from linkedin.com
     → DevTools → Application → Cookies → https://www.linkedin.com → li_at
  2. Paste it into  backend/.env  as:
       LINKEDIN_LI_AT=<paste here>
  3. Run:
       venv/bin/python -m backend.scripts.reset_linkedin_scraper --resume
  The loop will then restart with the new cookie.
""")


def do_resume() -> None:
    """Clear the pause gate AND all block-related keys so the loop can restart clean."""
    print("\n── Clearing pause gate + all block-related keys ───────────────────────")
    _check_env(warn_if_unchanged=True)

    keys_to_clear = [
        "linkedin_scraper_paused",
        "linkedin_scraper_status",
        "linkedin_redirect_error_count",
        "linkedin_scraper_blocked_at",
        "linkedin_cookie_status",
    ]
    # One shared session/transaction for the whole delete-sequence, so an
    # interruption mid-sequence rolls back to the pre-resume state instead of
    # leaving the KV store partially cleared.
    with kv_repository.kv_session() as s:
        for key in keys_to_clear:
            entry = kv_repository.get(key, session=s)
            if entry:
                print(f"  Deleted   {key:<45s} (was: {entry.value!r})")
                kv_repository.delete(key, session=s)
            else:
                print(f"  (absent)  {key}")

    _print_kv_state()
    print("\n  The enrichment loop will attempt LinkedIn scraping on its next cycle.")
    print("  Monitor backend logs for redirect errors to confirm the new cookie works.")


def _check_env(warn_if_unchanged: bool = False) -> None:
    print("\n── Check LINKEDIN_LI_AT in backend/.env ──────────────────────────────")
    if not ENV_FILE.exists():
        print(f"  WARNING: {ENV_FILE} not found.")
        return

    li_at = None
    for line in ENV_FILE.read_text().splitlines():
        stripped = line.strip()
        if stripped.startswith("LINKEDIN_LI_AT"):
            parts = stripped.split("=", 1)
            li_at = parts[1].strip().strip('"').strip("'") if len(parts) == 2 else ""
            break

    if not li_at:
        print("  ⚠ LINKEDIN_LI_AT is NOT set in backend/.env — scraper cannot run.")
    else:
        preview = li_at[:8] + "…" + li_at[-4:] if len(li_at) > 16 else li_at[:4] + "…"
        print(f"  LINKEDIN_LI_AT is set  ({preview})")
        if warn_if_unchanged:
            print("  ⚠ Ensure this is a FRESH cookie — not the one that caused the block.")


def do_status() -> None:
    _print_kv_state()
    _check_env()


def main() -> None:
    parser = argparse.ArgumentParser(description="LinkedIn scraper KV reset tool.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--pause",  action="store_true",
                       help="Clear BLOCKED state, set pause gate, delete browser profile")
    group.add_argument("--resume", action="store_true",
                       help="Clear pause gate to let the loop restart (run after cookie update)")
    group.add_argument("--status", action="store_true",
                       help="Print KV state without changing anything")
    args = parser.parse_args()

    if args.pause:
        do_pause()
    elif args.resume:
        do_resume()
    elif args.status:
        do_status()


if __name__ == "__main__":
    main()
