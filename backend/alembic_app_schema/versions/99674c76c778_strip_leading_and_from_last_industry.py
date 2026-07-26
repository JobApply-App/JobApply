"""strip leading "and " from the last element of all_jobs.industries

Revision ID: 99674c76c778
Revises: 301ebb505efa
Create Date: 2026-07-26 20:15:00.000000

industries is a naive comma-split of LinkedIn's English list phrase (e.g.
"Technology, Information and Media, and Software Development") — see
backend/services/linkedin_job_normalize.py's normalize_list_field(). The
split leaves the Oxford-comma "and " on whichever element followed it,
always the last one (English only ever places that conjunction right
before the final list item), e.g. the raw phrase above splits into
["Technology", "Information and Media", "and Software Development"] —
that last entry's real name is "Software Development", not "and Software
Development". normalize_list_field() now strips this at scrape time; this
migration backfills the 7 already-affected rows in production (found via
`WHERE industries[array_upper(industries,1)] ILIKE 'and %'`).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '99674c76c778'
down_revision: Union[str, None] = '301ebb505efa'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_UPGRADE_SQL = r"""
UPDATE public.all_jobs
SET industries = industries[1:array_upper(industries, 1) - 1]
                  || ARRAY[regexp_replace(industries[array_upper(industries, 1)], '^[Aa]nd\s+', '')]
WHERE industries IS NOT NULL
  AND array_upper(industries, 1) IS NOT NULL
  AND industries[array_upper(industries, 1)] ~* '^and\s+'
"""


def upgrade() -> None:
    op.execute(_UPGRADE_SQL)


def downgrade() -> None:
    # Not reversible: the original "and " prefix text is not recoverable
    # from the corrected data alone (no separate column records which rows
    # were touched or what the exact original prefix casing/spacing was).
    pass
