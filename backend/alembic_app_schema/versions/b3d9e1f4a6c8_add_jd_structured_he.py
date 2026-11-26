"""add job_postings.jd_structured_he — the job summary in Hebrew, for display

Revision ID: b3d9e1f4a6c8
Revises: a7c31e5d9b20
Create Date: 2026-11-26 00:00:00.000000

jd_structured is written in English on purpose (jd_structure_service rule 5)
and the scorer reads its requirement lines, so it stays English. A Hebrew
interface showed that English summary on every card, even for jobs posted in
Hebrew. This column holds a Hebrew translation of the same structure, used
only for display to Hebrew-UI users. NULL = not translated yet (the card
falls back to English). job_postings is shared, so each posting is
translated once for every Hebrew user.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'b3d9e1f4a6c8'
down_revision: Union[str, None] = 'a7c31e5d9b20'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('job_postings', sa.Column('jd_structured_he', postgresql.JSONB(), nullable=True),
                  schema='public')


def downgrade() -> None:
    op.drop_column('job_postings', 'jd_structured_he', schema='public')
