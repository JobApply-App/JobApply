"""add job_id text column to user_job_matches (preserve external string identifier)

Revision ID: f1a9c3d5b2e7
Revises: e8f4c2a71b93
Create Date: 2026-07-30 11:00:00.000000

Phase 2 (jobs pipeline cutover, docs/db-redesign-proposal.md): job_postings/
user_job_matches were created with only a UUID `id` on each table. But ~25
routes/services and the frontend all pass around the OLD `jobs.job_id` —
a deterministic, per-(user, posting) salted string hash (make_tenant_job_id)
— as the stable job identifier. Switching that to a UUID would be a breaking
API/frontend change, explicitly out of scope for this backend-only cutover
(confirmed with the user before writing this migration).

This adds `user_job_matches.job_id TEXT UNIQUE NOT NULL` so job_repository.py
can keep exposing exactly the same JobMatch.job_id string contract while its
internal storage moves to the new tables. Backfilled from the still-live
`jobs` table (matched via job_postings.canonical_job_key = COALESCE(jobs.
dedup_key, jobs.job_id), same derivation migrate_to_relational_schema.py used
originally) — this migration only makes sense to run before jobs is ever
dropped (Contract phase), which is exactly the order this whole cutover runs in.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f1a9c3d5b2e7'
down_revision: Union[str, None] = 'e8f4c2a71b93'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('user_job_matches', sa.Column('job_id', sa.Text(), nullable=True), schema='public')

    op.execute("""
        UPDATE public.user_job_matches ujm
        SET job_id = j.job_id
        FROM public.jobs j
        JOIN public.job_postings jp ON jp.canonical_job_key = COALESCE(j.dedup_key, j.job_id)
        WHERE jp.id = ujm.job_posting_id
          AND j.user_id = ujm.user_id::text
    """)

    op.alter_column('user_job_matches', 'job_id', nullable=False, schema='public')
    op.create_unique_constraint('uq_user_job_matches_job_id', 'user_job_matches', ['job_id'], schema='public')
    op.create_index('ix_user_job_matches_job_id', 'user_job_matches', ['job_id'], schema='public')


def downgrade() -> None:
    op.drop_index('ix_user_job_matches_job_id', table_name='user_job_matches', schema='public')
    op.drop_constraint('uq_user_job_matches_job_id', 'user_job_matches', schema='public', type_='unique')
    op.drop_column('user_job_matches', 'job_id', schema='public')
