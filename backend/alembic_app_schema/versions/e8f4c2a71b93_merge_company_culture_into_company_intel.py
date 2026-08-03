"""merge company_culture into company_intel (profile_type discriminator), drop company_culture

Revision ID: e8f4c2a71b93
Revises: d4e8f2a91c56
Create Date: 2026-07-28 12:00:00.000000

company_intel and company_culture were structurally identical tables
(company_key PK, display_name, profile_json, researched_at) holding two
different kinds of company research: 'intel' (financial vibe/tech stack,
for CV tailoring) and 'culture' (persona/culture-fit, JOB-19, consumed by
the Dynamic Matching Score, JOB-20). See docs/db-redesign-proposal.md's
cleanup plan.

Adds a profile_type column to company_intel (default 'intel', so every
existing/future row from the pre-merge callers is unaffected) and widens
its primary key to (company_key, profile_type) — a bare company_key PK
would let a company's intel row and culture row silently overwrite each
other, since both kinds of research can legitimately exist for the same
company at once.

Verified before writing this migration:
  - Zero references to company_culture_repository/CompanyCultureRow left
    anywhere in backend/ (grep) — backend/agents/company_culture.py already
    repointed to company_intel_repository.get/upsert(..., profile_type="culture").
  - company_intel held 0 rows at the time of this migration (no possible
    (company_key, profile_type) collision from the data copy below).
  - company_culture held 13 rows, all copied with profile_type='culture'.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e8f4c2a71b93'
down_revision: Union[str, None] = 'd4e8f2a91c56'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('company_intel', sa.Column('profile_type', sa.String(), nullable=False, server_default='intel'), schema='public')
    op.drop_constraint('company_intel_pkey', 'company_intel', schema='public', type_='primary')
    op.create_primary_key('company_intel_pkey', 'company_intel', ['company_key', 'profile_type'], schema='public')

    # Copy every company_culture row into company_intel as profile_type='culture'.
    op.execute("""
        INSERT INTO public.company_intel (company_key, profile_type, display_name, profile_json, researched_at)
        SELECT company_key, 'culture', display_name, profile_json, researched_at
        FROM public.company_culture
        ON CONFLICT (company_key, profile_type) DO NOTHING
    """)

    op.drop_table('company_culture', schema='public')


def downgrade() -> None:
    op.create_table(
        'company_culture',
        sa.Column('company_key', sa.String(), nullable=False),
        sa.Column('display_name', sa.String(), nullable=False),
        sa.Column('profile_json', sa.Text(), nullable=False),
        sa.Column('researched_at', sa.String(), nullable=False),
        sa.PrimaryKeyConstraint('company_key', name='company_culture_pkey'),
        schema='public',
    )
    op.execute("""
        INSERT INTO public.company_culture (company_key, display_name, profile_json, researched_at)
        SELECT company_key, display_name, profile_json, researched_at
        FROM public.company_intel WHERE profile_type = 'culture'
    """)
    op.execute("DELETE FROM public.company_intel WHERE profile_type = 'culture'")

    op.drop_constraint('company_intel_pkey', 'company_intel', schema='public', type_='primary')
    op.create_primary_key('company_intel_pkey', 'company_intel', ['company_key'], schema='public')
    op.drop_column('company_intel', 'profile_type', schema='public')
