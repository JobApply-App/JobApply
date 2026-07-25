"""Repository for the company_intel table.

Consolidates the raw CompanyIntelRow CRUD previously inlined in
backend/services/company_intelligence_service.py's _load_cached/_save_cached.
Global/shared cache — no user_id scoping (see docs/multi-tenant-erd.md).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from backend.core.database import ENGINE
from backend.models.matching import CompanyIntelRow


@dataclass(frozen=True)
class CompanyIntel:
    company_key: str
    display_name: str
    profile_json: str
    researched_at: str


def get(company_key: str, engine: Optional[Engine] = None) -> Optional[CompanyIntel]:
    eng = engine or ENGINE
    with Session(eng) as session:
        row = session.get(CompanyIntelRow, company_key)
        if row is None:
            return None
        return CompanyIntel(
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
        row = session.get(CompanyIntelRow, company_key)
        if row is None:
            row = CompanyIntelRow(company_key=company_key)
            session.add(row)
        row.display_name  = display_name
        row.profile_json  = profile_json
        row.researched_at = researched_at
        session.commit()
