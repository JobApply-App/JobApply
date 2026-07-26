"""split all_jobs.location into structured {country, city[]} JSONB

Revision ID: c39d615527ca
Revises: f1c4f486a0a8
Create Date: 2026-07-26 19:55:00.000000

`location` was a freeform "City, District, Country" (or bare "Country")
TEXT column, carried through verbatim from LinkedIn's scraped HTML with no
parsing anywhere. Converts it to `jsonb` shaped `{"country": str | None,
"city": [str, ...]}` — comma-split, last segment is the country, every
segment before it (including district/region names like "Tel Aviv
District" — there's no separate district field, so those go in the same
array as real city names) becomes a `city` array entry. Mirrors
backend/services/linkedin_job_normalize.py's parse_location(), which the
write path (backend/repositories/all_jobs_repository.py's
build_all_jobs_record()) now calls for every future upsert — this
migration only backfills the rows that already existed before that.

`ix_all_jobs_location` (a plain btree index on the old TEXT column) is
dropped first — Postgres won't let an ALTER COLUMN TYPE proceed while a
type-specific index still references the column.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'c39d615527ca'
down_revision: Union[str, None] = 'f1c4f486a0a8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Splits `location` on comma (trimming surrounding whitespace per part),
# takes the last element as `country`, everything before it as `city`.
# No CTE/subquery here — Postgres's ALTER COLUMN ... USING does not accept
# one ("cannot use subquery in transform expression"); the split is
# recomputed inline instead (fine for a one-time backfill, not a hot path).
_USING_EXPR = """
CASE
    WHEN location IS NULL OR btrim(location) = '' THEN NULL
    ELSE jsonb_build_object(
        'country', (regexp_split_to_array(btrim(location), '\\s*,\\s*'))[cardinality(regexp_split_to_array(btrim(location), '\\s*,\\s*'))],
        'city', to_jsonb(
            CASE WHEN cardinality(regexp_split_to_array(btrim(location), '\\s*,\\s*')) > 1
                 THEN (regexp_split_to_array(btrim(location), '\\s*,\\s*'))[1:cardinality(regexp_split_to_array(btrim(location), '\\s*,\\s*'))-1]
                 ELSE ARRAY[]::text[]
            END
        )
    )
END
"""

# Reverses the split for downgrade: "city1, city2, country" (rejoins the
# array + country with ", ") or just "country" if city is empty. Strips
# the jsonb array's own bracket/quote text representation with
# regexp_replace rather than jsonb_array_elements_text() + array_agg,
# since the latter is a subquery and hits the same USING restriction as
# the upgrade expression above.
_DOWNGRADE_EXPR = r"""
CASE
    WHEN location IS NULL THEN NULL
    WHEN jsonb_array_length(location -> 'city') = 0 THEN location ->> 'country'
    ELSE regexp_replace(regexp_replace((location -> 'city')::text, '^\[|\]$', '', 'g'), '"', '', 'g')
         || ', ' || (location ->> 'country')
END
"""


def upgrade() -> None:
    op.drop_index('ix_all_jobs_location', table_name='all_jobs', schema='public')
    op.execute(f"ALTER TABLE public.all_jobs ALTER COLUMN location TYPE jsonb USING ({_USING_EXPR})")


def downgrade() -> None:
    op.execute(f"ALTER TABLE public.all_jobs ALTER COLUMN location TYPE text USING ({_DOWNGRADE_EXPR})")
    op.create_index('ix_all_jobs_location', 'all_jobs', ['location'], unique=False, schema='public')
