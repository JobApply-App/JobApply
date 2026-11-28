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

  4. job_postings.company_id for jobs that have none yet (phase 2), and
     removal of placeholder aliases ("confidential") written before such
     names were recognised.

Idempotent: a second run adds nothing new. Writes only with --apply; without
it the run reads, resolves locally and prints what it would write.

    PYTHONPATH=. python backend/scripts/backfill_companies.py           # count only
    PYTHONPATH=. python backend/scripts/backfill_companies.py --apply
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter

from sqlalchemy import create_engine, func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.core.database import ENGINE
from backend.models.company import CompanyAliasRow, CompanyRow
from backend.repositories.company_repository import _set_group, upsert_listing
from backend.services.company_identity import company_key, is_placeholder, linkedin_slug

_TEST_KEY = re.compile(r"_[0-9a-f]{8}$")
_BATCH = 500


def _columns(table) -> list[str]:
    return [c.name for c in table.columns]


def _rows(session: Session, model) -> list[dict]:
    cols = _columns(model.__table__)
    return [{c: getattr(r, c) for c in cols} for r in session.execute(select(model)).scalars()]


def _has_company_id(session: Session) -> bool:
    """job_postings.company_id arrives with migration c4f8a2d6e9b1."""
    if session.get_bind().dialect.name != "postgresql":
        return False
    return bool(session.execute(text(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name = 'job_postings' AND column_name = 'company_id'"
    )).first())


def main(apply: bool) -> None:
    """
    Reads the three sources and the current companies/aliases from the app
    database in a handful of queries, resolves everything in a local
    in-memory SQLite copy with the same repository code (same identity rules,
    same source precedence), then writes the result back in batches. Resolving
    row by row against the remote database cost a round trip per lookup:
    tens of minutes for ~4,000 names.
    """
    with Session(ENGINE) as remote:
        if remote.get_bind().dialect.name == "postgresql":
            remote.execute(text("SET statement_timeout = '120s'"))
        listings = remote.execute(text(
            "SELECT company_name, company_url, company_logo_url, industries "
            "FROM all_jobs WHERE company_name IS NOT NULL ORDER BY last_seen_at DESC"
        )).all()
        postings = remote.execute(text(
            "SELECT company, count(*) n FROM job_postings WHERE company IS NOT NULL "
            "GROUP BY company ORDER BY n DESC"
        )).all()
        culture = remote.execute(text(
            "SELECT company_key, display_name, profile_json FROM company_intel WHERE profile_type = 'culture'"
        )).all()
        unlinked = remote.execute(text(
            "SELECT id::text AS id, company FROM job_postings WHERE company_id IS NULL AND company IS NOT NULL"
        )).all() if _has_company_id(remote) else []
        existing_companies = _rows(remote, CompanyRow)
        existing_aliases = _rows(remote, CompanyAliasRow)
    # Placeholder spellings ("Confidential") written before they were
    # recognised: drop them here, delete them remotely on --apply.
    stale_aliases = [a["alias_key"] for a in existing_aliases if is_placeholder(a["alias_key"])]
    existing_aliases = [a for a in existing_aliases if not is_placeholder(a["alias_key"])]
    print(f"read: {len(listings)} listings, {len(postings)} posting names, {len(culture)} culture rows, "
          f"{len(existing_companies)} companies and {len(existing_aliases)} aliases already present")

    local = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    CompanyRow.__table__.create(local)
    CompanyAliasRow.__table__.create(local)
    with Session(local) as session:
        session.bulk_insert_mappings(CompanyRow, existing_companies)
        session.bulk_insert_mappings(CompanyAliasRow, existing_aliases)
        session.flush()

        frequency = Counter(r.company_name for r in listings)
        # One row per (spelling, page), the most recent; most frequent
        # spelling first, so it names the company and keeps a shared name.
        latest: dict[tuple, object] = {}
        for r in listings:
            latest.setdefault((r.company_name, linkedin_slug(r.company_url)), r)
        for r in sorted(latest.values(), key=lambda r: -frequency[r.company_name]):
            upsert_listing(session, name=r.company_name, company_url=r.company_url,
                           logo_url=r.company_logo_url, industries=r.industries)

        for r in postings:
            upsert_listing(session, name=r.company)

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
        session.commit()

        companies = _rows(session, CompanyRow)
        aliases = _rows(session, CompanyAliasRow)
        alias_to_company = {a["alias_key"]: a["company_id"] for a in aliases}

    links = []
    for r in unlinked:
        key = company_key(r.company)
        if key and not is_placeholder(key) and key in alias_to_company:
            links.append({"id": r.id, "company_id": alias_to_company[key]})

    print(f"culture: {attached} attached, {skipped} test rows skipped")
    print(f"result: companies={len(companies)} aliases={len(aliases)} "
          f"with_logo={sum(1 for c in companies if c['logo_url'])} "
          f"with_culture={sum(1 for c in companies if c['culture'])} "
          f"with_linkedin={sum(1 for c in companies if c['linkedin_slug'])}")
    print(f"placeholder aliases to delete: {len(stale_aliases)}; "
          f"jobs to link: {len(links)} of {len(unlinked)} without a company")

    if not apply:
        print("dry run: nothing written (pass --apply to write)")
        return

    company_cols = [c for c in _columns(CompanyRow.__table__) if c != "id"]
    with Session(ENGINE) as remote:
        for i in range(0, len(companies), _BATCH):
            stmt = pg_insert(CompanyRow.__table__).values(companies[i:i + _BATCH])
            remote.execute(stmt.on_conflict_do_update(
                index_elements=["id"], set_={c: stmt.excluded[c] for c in company_cols},
            ))
        for i in range(0, len(aliases), _BATCH):
            remote.execute(pg_insert(CompanyAliasRow.__table__).values(aliases[i:i + _BATCH])
                           .on_conflict_do_nothing(index_elements=["alias_key"]))
        if stale_aliases:
            remote.execute(text("DELETE FROM company_aliases WHERE alias_key = ANY(:keys)"), {"keys": stale_aliases})
        for i in range(0, len(links), _BATCH):
            remote.execute(text(
                "UPDATE job_postings p SET company_id = v.company_id "
                "FROM jsonb_to_recordset(CAST(:rows AS jsonb)) AS v(id uuid, company_id text) "
                "WHERE p.id = v.id AND p.company_id IS NULL"
            ), {"rows": json.dumps(links[i:i + _BATCH])})
        remote.commit()
        print("written:", remote.scalar(select(func.count()).select_from(CompanyRow)), "companies,",
              remote.scalar(select(func.count()).select_from(CompanyAliasRow)), "aliases")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    main(parser.parse_args().apply)
