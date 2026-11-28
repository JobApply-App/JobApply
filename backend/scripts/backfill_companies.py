#!/usr/bin/env python3
"""
One-shot backfill of companies / company_aliases from data already held.
No AI calls.

  1. all_jobs: every LinkedIn listing's company name, company page, logo and
     industries. Most frequent spelling first, so it becomes the display name
     and keeps a name shared by two LinkedIn pages; most recent row first
     within a company, so the logo and industries are the latest.
  2. job_postings: company names of the feed's jobs, so every job's company
     exists before phase 2 links job_postings.company_id to it.
  3. company_intel (culture): the culture profiles already paid for. Rows
     whose key ends in an 8-hex suffix ("megacorp_1efe3bc4") are test data
     written by an earlier test run and are skipped.

Idempotent: a second run adds nothing new. Writes only with --apply; without
it the run counts what it would do and rolls back.

    PYTHONPATH=. python backend/scripts/backfill_companies.py           # count only
    PYTHONPATH=. python backend/scripts/backfill_companies.py --apply
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from backend.core.database import ENGINE
from backend.models.company import CompanyAliasRow, CompanyRow
from backend.repositories.company_repository import _set_group, upsert_listing
from backend.services.company_identity import linkedin_slug

_TEST_KEY = re.compile(r"_[0-9a-f]{8}$")


def main(apply: bool) -> None:
    with Session(ENGINE) as session:
        if session.get_bind().dialect.name == "postgresql":
            session.execute(text("SET statement_timeout = '120s'"))

        listings = session.execute(text(
            "SELECT company_name, company_url, company_logo_url, industries "
            "FROM all_jobs WHERE company_name IS NOT NULL ORDER BY last_seen_at DESC"
        )).all()
        frequency = Counter(r.company_name for r in listings)
        # One row per (spelling, page), the most recent: the rest add nothing
        # and would cost a round trip each.
        latest: dict[tuple, object] = {}
        for r in listings:
            latest.setdefault((r.company_name, linkedin_slug(r.company_url)), r)
        distinct = sorted(latest.values(), key=lambda r: -frequency[r.company_name])
        for r in distinct:
            upsert_listing(session, name=r.company_name, company_url=r.company_url,
                           logo_url=r.company_logo_url, industries=r.industries)
        print(f"all_jobs: {len(listings)} rows, {len(frequency)} spellings")

        postings = session.execute(text(
            "SELECT company, count(*) n FROM job_postings WHERE company IS NOT NULL "
            "GROUP BY company ORDER BY n DESC"
        )).all()
        for r in postings:
            upsert_listing(session, name=r.company)
        print(f"job_postings: {len(postings)} spellings")

        culture = session.execute(text(
            "SELECT company_key, display_name, profile_json FROM company_intel WHERE profile_type = 'culture'"
        )).all()
        attached = skipped = 0
        for r in culture:
            if _TEST_KEY.search(r.company_key):
                skipped += 1
                continue
            row = upsert_listing(session, name=r.display_name, source="jd_inferred")
            if row is None:
                continue
            profile = json.loads(r.profile_json)
            _set_group(row, "culture", profile, "jd_inferred", culture_confidence=profile.get("confidence"))
            attached += 1
        print(f"culture: {attached} attached, {skipped} test rows skipped")

        companies = session.scalar(select(func.count()).select_from(CompanyRow))
        aliases = session.scalar(select(func.count()).select_from(CompanyAliasRow))
        with_logo = session.scalar(select(func.count()).select_from(CompanyRow).where(CompanyRow.logo_url.is_not(None)))
        with_culture = session.scalar(select(func.count()).select_from(CompanyRow).where(CompanyRow.culture.is_not(None)))
        print(f"companies={companies} aliases={aliases} with_logo={with_logo} with_culture={with_culture}")

        if apply:
            session.commit()
            print("committed")
        else:
            session.rollback()
            print("dry run: rolled back (pass --apply to write)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    main(parser.parse_args().apply)
