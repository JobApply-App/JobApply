"""all_jobs.location: jsonb -> json, to preserve city/district/country key order

Revision ID: 301ebb505efa
Revises: 0db60a4a839e
Create Date: 2026-07-26 20:10:00.000000

`jsonb` always normalizes object key order internally (by key length, then
alphabetically for ties) regardless of insertion order — "city"(4),
"country"(7), "district"(8) sorted to city/country/district no matter what
order jsonb_build_object() was called with. There is no way to override
this while staying `jsonb`. Switching to the older `json` type stores the
exact validated text as given, so construction order is what's preserved.

No functionality is lost: nothing in this codebase uses jsonb-only features
on this column (no `@>`/`?` containment operators, no GIN index) — plain
`->`/`->>` key access, which backend/repositories/all_jobs_repository.py
and backend/api/routes/all_jobs.py's AllJobItem/LocationInfo already do,
works identically on `json`.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = '301ebb505efa'
down_revision: Union[str, None] = '0db60a4a839e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_UPGRADE_USING = """
json_build_object('city', location -> 'city', 'district', location -> 'district', 'country', location -> 'country')
"""

_DOWNGRADE_USING = """
jsonb_build_object('city', location -> 'city', 'district', location -> 'district', 'country', location -> 'country')
"""


def upgrade() -> None:
    op.execute(f"ALTER TABLE public.all_jobs ALTER COLUMN location TYPE json USING ({_UPGRADE_USING})")


def downgrade() -> None:
    op.execute(f"ALTER TABLE public.all_jobs ALTER COLUMN location TYPE jsonb USING ({_DOWNGRADE_USING})")
