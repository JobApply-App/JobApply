"""add companies and company_aliases

Revision ID: b9d2e6f0a1c7
Revises: a3e7c1f9d2b4
Create Date: 2026-11-28 00:00:00.000000

One row per company, built from data already held (LinkedIn listings in
all_jobs, culture profiles in company_intel), plus every spelling seen for it.
Phase 1 of docs/research/09-companies-and-costs.md §4. Filled by
backend/scripts/backfill_companies.py once, then kept current by the all_jobs
ingest and the culture-profile writer.

RLS on with no policy: only the backend reads or writes these tables.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'b9d2e6f0a1c7'
down_revision: Union[str, None] = 'a3e7c1f9d2b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'companies',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('display_name', sa.String(), nullable=False),
        sa.Column('linkedin_slug', sa.String(), nullable=True),
        sa.Column('linkedin_url', sa.String(), nullable=True),
        sa.Column('logo_url', sa.String(), nullable=True),
        sa.Column('logo_source', sa.String(), nullable=True),
        sa.Column('logo_updated_at', sa.String(), nullable=True),
        sa.Column('industries', postgresql.JSONB(), nullable=True),
        sa.Column('industries_source', sa.String(), nullable=True),
        sa.Column('industries_updated_at', sa.String(), nullable=True),
        sa.Column('culture', postgresql.JSONB(), nullable=True),
        sa.Column('culture_confidence', sa.String(), nullable=True),
        sa.Column('culture_source', sa.String(), nullable=True),
        sa.Column('culture_updated_at', sa.String(), nullable=True),
        sa.Column('created_at', sa.String(), nullable=False),
        sa.Column('updated_at', sa.String(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('linkedin_slug', name='uq_companies_linkedin_slug'),
        schema='public',
    )
    op.create_table(
        'company_aliases',
        sa.Column('alias_key', sa.String(), nullable=False),
        sa.Column('company_id', sa.String(), nullable=False),
        sa.Column('alias', sa.String(), nullable=False),
        sa.Column('created_at', sa.String(), nullable=False),
        sa.PrimaryKeyConstraint('alias_key'),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'],
                                name='fk_company_aliases_company_id', ondelete='CASCADE'),
        schema='public',
    )
    op.create_index('ix_company_aliases_company', 'company_aliases', ['company_id'], schema='public')
    for table in ('companies', 'company_aliases'):
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE public.{table} FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_index('ix_company_aliases_company', table_name='company_aliases', schema='public')
    op.drop_table('company_aliases', schema='public')
    op.drop_table('companies', schema='public')
