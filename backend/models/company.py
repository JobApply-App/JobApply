"""ORM models for companies and their aliases.

A company is one row that everything else can point to, built from data we
already hold (LinkedIn listings, culture profiles), without new AI calls.
See docs/research/09-companies-and-costs.md §4.

Each group of fields (logo, industries, culture) carries its own source and
updated_at, so a stronger source is never overwritten by a weaker one: when
recruiters can edit their company, a later scrape must not undo it. The ranks
live in backend/repositories/company_repository.py (SOURCE_RANK).
"""
from __future__ import annotations

from sqlalchemy import JSON, Column, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB

from backend.core.database import Base

# none_as_null: a missing value is SQL NULL, not the JSON value null, so
# "culture IS NOT NULL" means "has a culture profile".
_JSON = JSON(none_as_null=True).with_variant(JSONB(none_as_null=True), "postgresql")


class CompanyRow(Base):
    __tablename__ = "companies"

    id                    = Column(String, primary_key=True)
    display_name          = Column(String, nullable=False)
    # LinkedIn's /company/<slug>: the strongest identity we have.
    linkedin_slug         = Column(String, nullable=True, unique=True)
    linkedin_url          = Column(String, nullable=True)

    logo_url              = Column(String, nullable=True)
    logo_source           = Column(String, nullable=True)
    logo_updated_at       = Column(String, nullable=True)

    industries            = Column(_JSON, nullable=True)       # list[str]
    industries_source     = Column(String, nullable=True)
    industries_updated_at = Column(String, nullable=True)

    culture               = Column(_JSON, nullable=True)       # CompanyCultureProfile fields
    culture_confidence    = Column(String, nullable=True)      # high | medium | low
    culture_source        = Column(String, nullable=True)
    culture_updated_at    = Column(String, nullable=True)

    created_at            = Column(String, nullable=False)     # ISO-8601 UTC
    updated_at            = Column(String, nullable=False)


class CompanyAliasRow(Base):
    """Every spelling we have seen, as company_key(), pointing at one company."""
    __tablename__ = "company_aliases"

    alias_key  = Column(String, primary_key=True)
    company_id = Column(String, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    alias      = Column(String, nullable=False)                # one raw spelling, for reading
    created_at = Column(String, nullable=False)

    __table_args__ = (Index("ix_company_aliases_company", "company_id"),)
