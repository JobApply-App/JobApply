"""enable RLS on the two Alembic version tables

Revision ID: a7c31e5d9b20
Revises: e4b8c2a7f915
Create Date: 2026-11-23 00:00:00.000000

Supabase's Security Advisor (checked 2026-11-23) reported "RLS Disabled in
Public" on exactly two tables: alembic_version (backend/alembic_linkedin) and
alembic_version_app_schema (this chain). Every other public table already has
RLS. Without it, anyone holding the public anon key could read these tables
through PostgREST, and with Supabase's default grants also change or empty
them, which would break the next deploy's `alembic upgrade head`.

Same treatment as kv_store in e34f0ea56e30: RLS on, deliberately no policies,
so no client role gets in. The backend and Alembic connect as `postgres`
(BYPASSRLS), so migrations and /health's schema check are unaffected. No
FORCE: the owner must keep writing its own version row.

IF EXISTS because alembic_version only exists where the LinkedIn chain has
run.
"""
from typing import Sequence, Union

from alembic import op


revision: str = 'a7c31e5d9b20'
down_revision: Union[str, None] = 'e4b8c2a7f915'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLES = ("alembic_version", "alembic_version_app_schema")


def upgrade() -> None:
    for table in _TABLES:
        op.execute(f"ALTER TABLE IF EXISTS public.{table} ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    for table in _TABLES:
        op.execute(f"ALTER TABLE IF EXISTS public.{table} DISABLE ROW LEVEL SECURITY")
