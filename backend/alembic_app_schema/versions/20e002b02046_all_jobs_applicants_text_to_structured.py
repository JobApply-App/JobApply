"""all_jobs.applicants_text (text) -> applicants {value, exact} (json)

Revision ID: 20e002b02046
Revises: 42295e0a0319
Create Date: 2026-07-26 20:25:00.000000

applicants_text was always a plain string even though the underlying data
is a number in every case — either LinkedIn's exact applicant count
("116") or its own privacy censoring for low counts, always formatted
"< N" ("< 25"). Structuring it as `{"value": int | None, "exact": bool}`
lets callers actually sort/filter/compare applicant counts instead of
treating everything as opaque text, while still distinguishing a real
count from a censored upper bound via `exact`.

Verified against every distinct value in production before writing this:
32/80 rows are plain integers (exact=true), 48/80 are "< 25" (exact=false,
value=25 as the upper bound), 0 rows are anything else.

Mirrors backend/services/linkedin_job_normalize.py's parse_applicants(),
which the write path now calls for every future upsert — this migration
only backfills rows that already existed. Fully replaces applicants_text
(no data is lost: the structured form captures everything the text did).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = '20e002b02046'
down_revision: Union[str, None] = '42295e0a0319'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_BACKFILL_EXPR = r"""
CASE
    WHEN applicants_text IS NULL THEN NULL
    WHEN applicants_text ~ '^[0-9]+$' THEN json_build_object('value', applicants_text::int, 'exact', true)
    WHEN applicants_text ~ '^<\s*[0-9]+$' THEN json_build_object(
        'value', (regexp_match(applicants_text, '([0-9]+)'))[1]::int, 'exact', false
    )
    ELSE json_build_object('value', NULL, 'exact', false)
END
"""


def upgrade() -> None:
    op.add_column('all_jobs', sa.Column('applicants', sa.JSON(), nullable=True), schema='public')
    op.execute(f"UPDATE public.all_jobs SET applicants = ({_BACKFILL_EXPR})")
    op.drop_column('all_jobs', 'applicants_text', schema='public')


def downgrade() -> None:
    op.add_column('all_jobs', sa.Column('applicants_text', sa.Text(), nullable=True), schema='public')
    op.execute("""
        UPDATE public.all_jobs
        SET applicants_text = CASE
            WHEN applicants IS NULL THEN NULL
            WHEN (applicants ->> 'exact')::boolean THEN (applicants ->> 'value')
            ELSE '< ' || (applicants ->> 'value')
        END
    """)
    op.drop_column('all_jobs', 'applicants', schema='public')
