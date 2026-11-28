"""add user_job_matches.fit_brief_i18n — Ariel's analysis in both languages

Revision ID: c7a4e2d9f1b3
Revises: b3d9e1f4a6c8
Create Date: 2026-11-28 00:00:00.000000

fit_brief is written once, in the interface language of the moment, and the
Hebrew backfill used to translate it in place. A user who then switched to
English saw Hebrew on every card (Ron, 2026-11-28: 213 of 214). This column
keeps translations beside the original: {"src": <fit_brief translated>,
"he": ..., "en": ...}. A translation counts only while src still equals
fit_brief, so a re-score retires it without any writer having to clear it.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'c7a4e2d9f1b3'
down_revision: Union[str, None] = 'b3d9e1f4a6c8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('user_job_matches', sa.Column('fit_brief_i18n', postgresql.JSONB(), nullable=True),
                  schema='public')


def downgrade() -> None:
    op.drop_column('user_job_matches', 'fit_brief_i18n', schema='public')
