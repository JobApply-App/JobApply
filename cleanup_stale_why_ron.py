"""
One-time cleanup: clear why_ron for jobs where the analysis is not substantive.

A "stale" why_ron is defined as:
  - shorter than 50 characters, OR
  - matches the pattern "<optional prefix><words>:" with nothing after
    (e.g. "🟢 Core Strengths:" or "Key strengths:")

Running this script forces the enrichment service to re-process those jobs
from scratch on the next s2 cycle.

Usage:
    python cleanup_stale_why_ron.py [--dry-run]
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

# Ensure project root is on the path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from backend.core.database import ENGINE
from backend.models.job import JobRow
from sqlalchemy.orm import Session

_MIN_LEN     = 50
_HEADER_ONLY = re.compile(r'^[^\w]*[\w\s]+:\s*$')
_CORE_STR    = re.compile(r'(?i)^[^\w]*core strengths\s*:')

DRY_RUN = "--dry-run" in sys.argv


def is_stale(why_ron: str | None) -> bool:
    if not why_ron:
        return False
    text = why_ron.strip()
    if len(text) < _MIN_LEN:
        return True
    first_line = text.split('\n')[0]
    if _HEADER_ONLY.match(text) or _CORE_STR.match(first_line):
        return True
    return False


def main() -> None:
    cleared = 0
    with Session(ENGINE) as session:
        rows = session.query(JobRow).filter(JobRow.why_ron.isnot(None)).all()
        print(f"Scanning {len(rows)} jobs with why_ron set…")

        for row in rows:
            if is_stale(row.why_ron):
                print(f"  {'[DRY RUN] ' if DRY_RUN else ''}Clearing why_ron for {row.job_id} ({row.title} @ {row.company}) — was: {repr(row.why_ron[:60])}")
                if not DRY_RUN:
                    row.why_ron = None
                    row.score_is_proxy = True
                cleared += 1

        if not DRY_RUN and cleared:
            session.commit()

    print(f"\n{'Would clear' if DRY_RUN else 'Cleared'} {cleared} stale why_ron entries.")
    if DRY_RUN:
        print("Run without --dry-run to apply.")


if __name__ == "__main__":
    main()
