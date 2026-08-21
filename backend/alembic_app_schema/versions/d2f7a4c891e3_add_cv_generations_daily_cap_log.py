"""add cv_generations table — backs the daily per-user CV-generation cap

Revision ID: d2f7a4c891e3
Revises: b8d3f21a94c7
Create Date: 2026-08-21 00:00:00.000000

One row per successful POST /tailor call (initial generation and
force=true regenerate both count — each is a real LLM generation).
backend/api/deps.py's daily_generation_limit() counts today's rows for the
calling user and rejects once the configured cap is reached.

Not reusing the existing in-memory llm_rate_limit: that's a per-minute
burst guard that resets on process restart, which is fine for its purpose
but wrong for a DAILY cap on a service that restarts through the day
(Render free-tier sleep/wake — see config.py's DISCOVERY_INTERVAL_SECONDS
comment for the same constraint on a different feature). A DB row survives
restarts and gives an honest, queryable count instead of a counter that
quietly grants extra generations for free every time the instance naps.

String id/created_at (not UUID/TIMESTAMPTZ) to match this table's own
model (backend/models/cv_generation.py) exactly, and because this is a
lightweight audit-log table in the same family as kv_store/applications,
not the core relational schema — no need for the heavier Phase 2 convention.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'd2f7a4c891e3'
down_revision: Union[str, None] = 'b8d3f21a94c7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'cv_generations',
        sa.Column('id', sa.String(), nullable=False),
        # postgresql.UUID, not sa.String — profiles.id is a real Postgres uuid
        # column (see the 'profiles' create_table earlier in this chain), and
        # an FK's two sides must be the same physical type or Postgres refuses
        # to create the constraint at all (caught by actually running this
        # migration, not just reading it: DatatypeMismatch, "character
        # varying and uuid"). Matches backend/models/cv_generation.py's
        # UUID_FK type, which resolves to exactly this on the Postgres side.
        sa.Column('user_id', postgresql.UUID(), nullable=False),
        sa.Column('job_id', sa.String(), nullable=False),
        sa.Column('created_at', sa.String(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['user_id'], ['profiles.id'],
                                 name='fk_cv_generations_user_id_profiles', ondelete='CASCADE'),
        schema='public',
    )
    # Matches the model's own composite index — see cv_generation.py's
    # docstring: the daily-cap query is "count rows for user_id where
    # created_at falls in today," not a plain user_id lookup.
    op.create_index('ix_cv_generations_user_created', 'cv_generations',
                     ['user_id', 'created_at'], schema='public')

    op.execute("ALTER TABLE public.cv_generations ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE public.cv_generations FORCE ROW LEVEL SECURITY")
    # user_id is a real uuid column (see above) — compare directly against
    # auth.uid()'s own uuid return type, no cast. The first attempt at this
    # migration had it as text with a ::text cast on auth.uid(), left over
    # from before the FK-type fix above; caught the same way, by actually
    # running it: "operator does not exist: uuid = text".
    op.execute("""
        CREATE POLICY cv_generations_owner_select ON public.cv_generations
            FOR SELECT USING (user_id = auth.uid())
    """)
    op.execute("""
        CREATE POLICY cv_generations_owner_write ON public.cv_generations
            FOR ALL USING (user_id = auth.uid()) WITH CHECK (user_id = auth.uid())
    """)


def downgrade() -> None:
    op.drop_index('ix_cv_generations_user_created', table_name='cv_generations', schema='public')
    op.drop_table('cv_generations', schema='public')
