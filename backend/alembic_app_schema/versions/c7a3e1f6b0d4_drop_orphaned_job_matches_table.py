"""drop job_matches — orphaned table, zero references anywhere in the codebase

Revision ID: c7a3e1f6b0d4
Revises: ef1e2163ea27
Create Date: 2026-07-27 18:45:00.000000

`job_matches` was never created by backend/alembic_app_schema/versions/
413f4ed8fbc6_create_app_tables.py (it isn't one of the 19 SQLite-ported
tables — see docs/db-redesign-proposal.md's audit) and has no corresponding
ORM model, repository, or route anywhere in backend/. Its origin is unknown
(pre-existing on the Supabase project before this app's tables were ever
migrated there), and it has held 0 rows the entire time this branch has been
under development.

Verified before dropping:
  - Zero references to `job_matches` anywhere in backend/repositories/*.py,
    backend/api/routes/*.py, backend/models/*.py, or backend/services/*.py
    (grep, this repo).
  - Row count: 0.
  - Schema: id (uuid PK), why_ron (text), score_is_proxy (boolean),
    enrichment_failures (integer), created_at (timestamptz) — no foreign
    keys reference it, and it references no other table.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'c7a3e1f6b0d4'
down_revision: Union[str, None] = 'ef1e2163ea27'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_table('job_matches', schema='public')


def downgrade() -> None:
    op.create_table(
        'job_matches',
        sa.Column('id', postgresql.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('why_ron', sa.Text(), nullable=True),
        sa.Column('score_is_proxy', sa.Boolean(), server_default=sa.text('true'), nullable=True),
        sa.Column('enrichment_failures', sa.Integer(), server_default=sa.text('0'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('id', name='job_matches_pkey'),
        schema='public',
    )
