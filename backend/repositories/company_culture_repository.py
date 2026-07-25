"""Repository for the company_culture table.

Consolidates the raw CompanyCultureRow CRUD previously inlined in
backend/agents/company_culture.py's load_cached_profile/save_cached_profile.
Global/shared cache — no user_id scoping (see docs/multi-tenant-erd.md).

Every function accepts an optional `engine` override (falling back to the
shared ENGINE, resolved at call time) since callers already inject an
alternate engine for testability (e.g. feedback_service.py's
_fetch_culture_profile_cached).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from backend.core.database import ENGINE
from backend.models.matching import CompanyCultureRow


@dataclass(frozen=True)
class CompanyCulture:
    company_key: str
    display_name: str
    profile_json: str
    researched_at: str


def get(company_key: str, engine: Optional[Engine] = None) -> Optional[CompanyCulture]:
    eng = engine or ENGINE
    with Session(eng) as session:
        row = session.get(CompanyCultureRow, company_key)
        if row is None:
            return None
        return CompanyCulture(
            company_key   = row.company_key,
            display_name  = row.display_name,
            profile_json  = row.profile_json,
            researched_at = row.researched_at,
        )


def upsert(
    company_key: str,
    display_name: str,
    profile_json: str,
    researched_at: str,
    engine: Optional[Engine] = None,
) -> None:
    eng = engine or ENGINE
    with Session(eng) as session:
        row = session.get(CompanyCultureRow, company_key)
        if row is None:
            row = CompanyCultureRow(company_key=company_key)
            session.add(row)
        row.display_name  = display_name
        row.profile_json  = profile_json
        row.researched_at = researched_at
        session.commit()
