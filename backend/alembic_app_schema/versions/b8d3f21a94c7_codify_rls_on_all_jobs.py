"""codify RLS on public.all_jobs (was out-of-band dashboard state)

Revision ID: b8d3f21a94c7
Revises: a7c91e40b3f2
Create Date: 2026-08-13 00:00:00.000000

Closes the single schema difference found when standing up JobApply-Production
and diffing it against Dev.

The drift
----------
Dev's `public.all_jobs` carries relrowsecurity=true, but no migration in this
repo ever set it — e34f0ea56e30's docstring already recorded this and
deliberately left the table alone ("likely a Supabase-dashboard default").
Production, built purely by replaying this chain, therefore came up WITHOUT
RLS on that table: a real difference, and one that only existed because the
Dev setting lived in a dashboard rather than in code.

Enabling it here, rather than clicking the same toggle on Production, is the
point: a setting that isn't in the chain isn't reproducible, and the next
environment would have diverged exactly the same way.

What this does and does not change
-----------------------------------
RLS enabled with ZERO policies denies all access to any role that is not
RLS-exempt — the same "backend/service-role only" posture e34f0ea56e30 applied
to the tenant tables, and the reason no policy is added here.

The backend connects as `postgres` (BYPASSRLS), so this changes nothing about
current query behaviour on either environment. It takes effect the day any
direct-Supabase-client path exists (PostgREST, supabase-js with an anon or
user JWT) — at which point the safe default for a global scraped-jobs
catalogue is "not world-readable".

On Dev this is a no-op: the flag is already set, and ENABLE ROW LEVEL SECURITY
is idempotent. Its only effect is to make the existing state reproducible.
"""
from typing import Sequence, Union

from alembic import op


revision: str = 'b8d3f21a94c7'
down_revision: Union[str, None] = 'a7c91e40b3f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # IF EXISTS guard for the same reason c7a3e1f6b0d4 needed one: this chain
    # must stay replayable against a database where an earlier step legitimately
    # produced a different set of objects.
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name = 'all_jobs'
            ) THEN
                ALTER TABLE public.all_jobs ENABLE ROW LEVEL SECURITY;
            END IF;
        END $$;
    """)


def downgrade() -> None:
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name = 'all_jobs'
            ) THEN
                ALTER TABLE public.all_jobs DISABLE ROW LEVEL SECURITY;
            END IF;
        END $$;
    """)
