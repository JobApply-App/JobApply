"""drop dead columns from public.all_jobs (is_active, closed_at)

Revision ID: 8726d4a42112
Revises: 9f25d77ed964
Create Date: 2026-07-26 19:35:00.000000

Both columns were 100% NULL across every row in production (verified via
`SELECT count(*) FROM public.all_jobs WHERE <col> IS NOT NULL` — 0/80) and
neither has a write path anywhere in the codebase:
  - `closed_at`: never referenced outside the model/migration that created
    it — no route, repository, or frontend usage at all.
  - `is_active`: read by GET /api/all-jobs and rendered by the frontend's
    ActiveBadge (backend/api/routes/all_jobs.py, backend/repositories/
    all_jobs_repository.py's _LIST_VIEW_COLUMNS, frontend/src/components/
    AllJobsTab.tsx) but never written by bulk_upsert_all_jobs() — removed
    together with that read-side code in this same change rather than left
    as a permanently-null column.

`ix_all_jobs_is_active` is dropped first since Postgres won't drop a column
that still has an index on it.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '8726d4a42112'
down_revision: Union[str, None] = '9f25d77ed964'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index('ix_all_jobs_is_active', table_name='all_jobs', schema='public')
    op.drop_column('all_jobs', 'is_active', schema='public')
    op.drop_column('all_jobs', 'closed_at', schema='public')


def downgrade() -> None:
    op.add_column('all_jobs', sa.Column('closed_at', sa.DateTime(timezone=True), nullable=True), schema='public')
    op.add_column('all_jobs', sa.Column('is_active', sa.Boolean(), nullable=True), schema='public')
    op.create_index('ix_all_jobs_is_active', 'all_jobs', ['is_active'], unique=False, schema='public')
