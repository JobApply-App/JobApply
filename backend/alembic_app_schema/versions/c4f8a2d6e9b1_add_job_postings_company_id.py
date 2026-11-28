"""add job_postings.company_id — every job points at its company

Revision ID: c4f8a2d6e9b1
Revises: b9d2e6f0a1c7
Create Date: 2026-11-28 00:00:00.000000

Phase 2 of docs/research/09-companies-and-costs.md. Set on save by
job_repository._upsert_posting; existing rows are filled by
backend/scripts/backfill_companies.py. Null for an empty or placeholder
company name ("Confidential"). ON DELETE SET NULL: removing a company never
removes jobs.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c4f8a2d6e9b1'
down_revision: Union[str, None] = 'b9d2e6f0a1c7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('job_postings', sa.Column('company_id', sa.String(), nullable=True), schema='public')
    op.create_foreign_key('fk_job_postings_company_id', 'job_postings', 'companies',
                          ['company_id'], ['id'], source_schema='public', referent_schema='public',
                          ondelete='SET NULL')
    op.create_index('ix_job_postings_company_id', 'job_postings', ['company_id'], schema='public')


def downgrade() -> None:
    op.drop_index('ix_job_postings_company_id', table_name='job_postings', schema='public')
    op.drop_constraint('fk_job_postings_company_id', 'job_postings', schema='public', type_='foreignkey')
    op.drop_column('job_postings', 'company_id', schema='public')
