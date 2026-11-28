"""Repository for companies and company_aliases.

See backend/models/company.py for what a row is. Identity: LinkedIn's company
slug first, then any alias (company_key() of a spelling we have seen).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from backend.core.database import ENGINE
from backend.models.company import CompanyAliasRow, CompanyRow
from backend.services.company_identity import company_key, is_placeholder, linkedin_slug

# A field group is written only by a source at least as strong as the one
# that wrote it last (docs/research/09-companies-and-costs.md §4.3), so a
# recruiter's edit survives the next scrape.
SOURCE_RANK = {"jd_inferred": 1, "linkedin": 2, "web_research": 3, "company_portal": 4}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def _outranks(new_source: str, old_source: Optional[str]) -> bool:
    return SOURCE_RANK[new_source] >= SOURCE_RANK.get(old_source or "", 0)


def _set_group(row: CompanyRow, group: str, value: Any, source: str, **extra: Any) -> None:
    if not _outranks(source, getattr(row, f"{group}_source")):
        return
    setattr(row, {"logo": "logo_url"}.get(group, group), value)
    for col, v in extra.items():
        setattr(row, col, v)
    setattr(row, f"{group}_source", source)
    setattr(row, f"{group}_updated_at", _now())
    row.updated_at = _now()


def _resolve(session: Session, slug: Optional[str], key: Optional[str]) -> Optional[CompanyRow]:
    if slug:
        row = session.execute(select(CompanyRow).where(CompanyRow.linkedin_slug == slug)).scalar_one_or_none()
        if row is not None:
            return row
    if key:
        alias = session.get(CompanyAliasRow, key)
        if alias is not None:
            row = session.get(CompanyRow, alias.company_id)
            # Same name, a different LinkedIn page: two companies (country
            # pages, namesakes). The alias stays with the first one.
            if slug and row.linkedin_slug not in (None, slug):
                return None
            return row
    return None


def upsert_listing(
    session: Session,
    *,
    name: Optional[str],
    company_url: Optional[str] = None,
    logo_url: Optional[str] = None,
    industries: Optional[list[str]] = None,
    source: str = "linkedin",
) -> Optional[CompanyRow]:
    """Find or create the company a listing belongs to, record its spelling,
    and fill logo/industries where `source` is allowed to. No commit."""
    from backend.repositories.all_jobs_repository import usable_logo

    key, slug = company_key(name), linkedin_slug(company_url)
    if is_placeholder(key):
        key = None          # never an alias; only a LinkedIn page can identify it
    if not key and not slug:
        return None
    now = _now()
    row = _resolve(session, slug, key)
    if row is None:
        row = CompanyRow(
            id=uuid.uuid4().hex, display_name=(name or slug).strip(),
            linkedin_slug=slug, linkedin_url=company_url if slug else None,
            created_at=now, updated_at=now,
        )
        session.add(row)
        session.flush()
    elif slug and row.linkedin_slug is None:
        # First time this company is seen with its LinkedIn page. Another
        # company already holding the slug is resolved by slug above, so
        # reaching here means the slug is free.
        row.linkedin_slug, row.linkedin_url, row.updated_at = slug, company_url, now

    logo = usable_logo(logo_url)
    if logo:
        _set_group(row, "logo", logo, source)
    if industries:
        _set_group(row, "industries", list(industries), source)

    if key and session.get(CompanyAliasRow, key) is None:
        session.add(CompanyAliasRow(alias_key=key, company_id=row.id, alias=(name or "").strip(), created_at=now))
        session.flush()
    return row


def company_id_for(session: Session, name: Optional[str]) -> Optional[str]:
    """The company a job's company name belongs to, created if new; None for
    an empty or placeholder name. No commit."""
    row = upsert_listing(session, name=name)
    return row.id if row is not None else None


def upsert_listings(rows: list[dict], *, engine: Optional[Engine] = None) -> int:
    """rows: dicts with company_name, company_url, company_logo_url, industries
    (the all_jobs record shape). Returns how many rows named a company."""
    seen = 0
    with Session(engine or ENGINE) as session:
        for r in rows:
            if upsert_listing(
                session, name=r.get("company_name"), company_url=r.get("company_url"),
                logo_url=r.get("company_logo_url"), industries=r.get("industries"),
            ) is not None:
                seen += 1
        session.commit()
    return seen


def attach_culture(
    name: str,
    culture: dict,
    *,
    confidence: Optional[str],
    source: str = "jd_inferred",
    engine: Optional[Engine] = None,
) -> bool:
    """Store a culture profile on the company named `name` (created if new).
    False when the name normalizes to nothing."""
    with Session(engine or ENGINE) as session:
        row = upsert_listing(session, name=name, source=source)
        if row is None:
            return False
        _set_group(row, "culture", culture, source, culture_confidence=confidence)
        session.commit()
    return True


def industries_for(name: Optional[str], *, engine: Optional[Engine] = None) -> list[str]:
    """The LinkedIn industries of the company with this name; [] when unknown."""
    k = company_key(name)
    if not k or is_placeholder(k):
        return []
    stmt = (
        select(CompanyRow.industries)
        .join(CompanyAliasRow, CompanyRow.id == CompanyAliasRow.company_id)
        .where(CompanyAliasRow.alias_key == k)
    )
    with Session(engine or ENGINE) as session:
        found = session.execute(stmt).scalar()
    return [str(i) for i in found] if isinstance(found, list) else []


def get_logos(names: list[str], *, engine: Optional[Engine] = None) -> dict[str, str]:
    """{name as given: logo url} for names whose company has a logo."""
    by_key: dict[str, list[str]] = {}
    for n in names:
        k = company_key(n)
        if k and not is_placeholder(k):
            by_key.setdefault(k, []).append(n)
    if not by_key:
        return {}
    stmt = (
        select(CompanyAliasRow.alias_key, CompanyRow.logo_url)
        .join(CompanyRow, CompanyRow.id == CompanyAliasRow.company_id)
        .where(CompanyAliasRow.alias_key.in_(list(by_key)), CompanyRow.logo_url.is_not(None))
    )
    out: dict[str, str] = {}
    with Session(engine or ENGINE) as session:
        for k, url in session.execute(stmt).all():
            for n in by_key[k]:
                out[n] = url
    return out
