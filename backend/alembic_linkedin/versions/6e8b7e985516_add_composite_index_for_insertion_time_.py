"""add composite index for insertion_time,id pagination sort

Revision ID: 6e8b7e985516
Revises: f5bd530a002f
Create Date: 2026-07-23 14:56:14.188545

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6e8b7e985516'
down_revision: Union[str, None] = 'f5bd530a002f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Supports GET /api/linkedin/jobs's deterministic sort
    # (ORDER BY insertion_time DESC, id DESC) — none of the existing
    # single-column indexes on this table serve a two-column ORDER BY
    # efficiently. DESC/DESC matches the query's own ordering exactly, so
    # Postgres can walk the index directly with no extra sort step.
    op.execute(
        "CREATE INDEX ix_linkedin_jobs_insertion_time_id_desc "
        "ON linkedin.jobs (insertion_time DESC, id DESC)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX linkedin.ix_linkedin_jobs_insertion_time_id_desc")
