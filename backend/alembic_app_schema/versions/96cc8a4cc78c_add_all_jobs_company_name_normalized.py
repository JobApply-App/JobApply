"""add all_jobs.company_name_normalized (lowercased, whitespace-collapsed matching key)

Revision ID: 96cc8a4cc78c
Revises: 20e002b02046
Create Date: 2026-07-26 20:35:00.000000

Lets "Google Inc", " google inc ", and "GOOGLE INC" all match/group
together. Mirrors backend/services/linkedin_job_normalize.py's
normalize_company_key(), which the write path now calls for every future
upsert; this migration backfills the column for rows that already existed
using the equivalent SQL expression (lower + btrim + collapse internal
whitespace).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '96cc8a4cc78c'
down_revision: Union[str, None] = '20e002b02046'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('all_jobs', sa.Column('company_name_normalized', sa.Text(), nullable=True), schema='public')
    op.execute(r"""
        UPDATE public.all_jobs
        SET company_name_normalized = lower(btrim(regexp_replace(company_name, '\s+', ' ', 'g')))
        WHERE company_name IS NOT NULL
    """)
    op.create_index(
        'ix_all_jobs_company_name_normalized', 'all_jobs', ['company_name_normalized'],
        unique=False, schema='public',
    )


def downgrade() -> None:
    op.drop_index('ix_all_jobs_company_name_normalized', table_name='all_jobs', schema='public')
    op.drop_column('all_jobs', 'company_name_normalized', schema='public')
