"""add all_jobs.posted_at (absolute datetime, derived from posted_text)

Revision ID: 42295e0a0319
Revises: 99674c76c778
Create Date: 2026-07-26 20:20:00.000000

posted_text/exact_posted_text are LinkedIn's relative "N units ago" text —
kept as-is (see 9f25d77ed964's own "Deliberately omitted" rationale for
why an absolute posted_at wasn't attempted originally: no exact source
timestamp exists, only relative text). This adds a best-effort absolute
`posted_at`, computed by subtracting the parsed duration from
`last_scraped_at` — the scrape run's own timestamp, which is the closest
available anchor to "when was this relative text accurate." Mirrors
backend/services/linkedin_job_normalize.py's parse_posted_at(), which the
write path now calls for every future upsert; this migration only
backfills rows that already existed.

Uses Postgres's native `interval` literal cast (e.g. '2 hour'::interval)
rather than replicating parse_posted_at()'s day-based month/year
approximation — more accurate for a one-time backfill, and moot for the
data that exists today (only "hour"/"minute" units are present).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '42295e0a0319'
down_revision: Union[str, None] = '99674c76c778'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_BACKFILL_SQL = r"""
UPDATE public.all_jobs
SET posted_at = sub.last_scraped_at - ((sub.m[1] || ' ' || sub.m[2])::interval)
FROM (
    SELECT id, last_scraped_at,
           regexp_match(posted_text, '^(\d+)\s+(second|minute|hour|day|week|month|year)s?\s+ago$', 'i') AS m
    FROM public.all_jobs
) sub
WHERE public.all_jobs.id = sub.id AND sub.m IS NOT NULL
"""


def upgrade() -> None:
    op.add_column('all_jobs', sa.Column('posted_at', sa.DateTime(timezone=True), nullable=True), schema='public')
    op.execute(_BACKFILL_SQL)


def downgrade() -> None:
    op.drop_column('all_jobs', 'posted_at', schema='public')
