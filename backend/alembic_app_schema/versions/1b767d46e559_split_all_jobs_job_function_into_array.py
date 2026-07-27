"""all_jobs.job_function: text -> text[] (same comma-split as industries)

Revision ID: 1b767d46e559
Revises: 514248e8d2cb
Create Date: 2026-07-27 11:20:00.000000

job_function had the same underlying problem as industries did before
514248e8d2cb: LinkedIn's own Oxford-comma-joined multi-function strings
(e.g. "Information Technology, Product Management, and Project
Management" — 3 real, distinct job functions) were stored verbatim as a
single opaque TEXT value instead of being split, so the filter dropdown
showed composite glued strings as one option.

Unlike industries, no LinkedIn job-function taxonomy name contains its own
internal comma (verified against every distinct raw value in production —
"Accounting/Auditing", "Business Development", "Information Technology",
etc. are all comma-free) — so normalize_list_field()'s generic Oxford-list
split (no atomic-phrase whitelist needed) is already correct here with no
further work.

Adds a new `text[]` column, backfills it from `raw_payload` (which still
holds the untouched original scraped value) via normalize_list_field(),
then drops the old text column and renames the new one into place — the
same technique 514248e8d2cb used, since the split logic isn't reasonably
expressible as a single SQL expression.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

revision: str = '1b767d46e559'
down_revision: Union[str, None] = '514248e8d2cb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    from backend.services.linkedin_job_normalize import normalize_list_field

    op.add_column('all_jobs', sa.Column('job_function_arr', postgresql.ARRAY(sa.Text()), nullable=True), schema='public')

    bind = op.get_bind()
    session = Session(bind=bind)
    rows = session.execute(text(
        "SELECT id, raw_payload ->> 'job_function' AS raw FROM public.all_jobs "
        "WHERE raw_payload ->> 'job_function' IS NOT NULL"
    )).all()
    for row in rows:
        session.execute(
            text("UPDATE public.all_jobs SET job_function_arr = :val WHERE id = :id"),
            {"val": normalize_list_field(row.raw), "id": row.id},
        )
    session.commit()

    op.drop_column('all_jobs', 'job_function', schema='public')
    op.alter_column('all_jobs', 'job_function_arr', new_column_name='job_function', schema='public')


def downgrade() -> None:
    op.add_column('all_jobs', sa.Column('job_function_text', sa.Text(), nullable=True), schema='public')
    op.execute("""
        UPDATE public.all_jobs
        SET job_function_text = array_to_string(job_function, ', ')
        WHERE job_function IS NOT NULL
    """)
    op.drop_column('all_jobs', 'job_function', schema='public')
    op.alter_column('all_jobs', 'job_function_text', new_column_name='job_function', schema='public')
