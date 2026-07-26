"""reshape all_jobs.location from {country, city[]} to {city, district, country}

Revision ID: 0db60a4a839e
Revises: c39d615527ca
Create Date: 2026-07-26 20:05:00.000000

The previous migration (c39d615527ca) treated every segment before the
country as an undifferentiated "city" array. Checking the actual segment
counts across all 80 production rows showed exactly 3 distinct cases, never
more — LinkedIn's "City, District, Country" convention:
  1 segment  ("Israel")                               -> country only
  2 segments ("Tel Aviv District, Israel")             -> district + country
  3 segments ("Ramat Gan, Tel Aviv District, Israel")  -> city + district + country
So what was previously stored as e.g. `{"city": ["Ramat Gan", "Tel Aviv
District"], "country": "Israel"}` is reshaped here into `{"city": "Ramat
Gan", "district": "Tel Aviv District", "country": "Israel"}` — a 2-element
city array becomes city=first element/district=second; a 1-element city
array becomes city=null/district=that element; a 0-element city array
(country-only) stays city=null/district=null.

This is a plain UPDATE (location is already jsonb from the prior
migration, no ALTER COLUMN TYPE needed here), so — unlike c39d615527ca —
subqueries are fine to use in the expression.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0db60a4a839e'
down_revision: Union[str, None] = 'c39d615527ca'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_UPGRADE_SQL = """
UPDATE public.all_jobs
SET location = jsonb_build_object(
    'city', CASE WHEN jsonb_array_length(location -> 'city') = 2
                 THEN location -> 'city' -> 0
                 ELSE NULL END,
    'district', CASE WHEN jsonb_array_length(location -> 'city') = 2
                      THEN location -> 'city' -> 1
                      WHEN jsonb_array_length(location -> 'city') = 1
                      THEN location -> 'city' -> 0
                      ELSE NULL END,
    'country', location -> 'country'
)
WHERE location IS NOT NULL
"""

_DOWNGRADE_SQL = """
UPDATE public.all_jobs
SET location = jsonb_build_object(
    'city', (
        SELECT jsonb_agg(elem) FROM (
            SELECT elem FROM jsonb_array_elements_text(
                jsonb_build_array(location -> 'city', location -> 'district')
            ) AS elem
            WHERE elem IS NOT NULL AND elem != 'null'
        ) sub
    ),
    'country', location -> 'country'
)
WHERE location IS NOT NULL
"""


def upgrade() -> None:
    op.execute(_UPGRADE_SQL)


def downgrade() -> None:
    op.execute(_DOWNGRADE_SQL)
