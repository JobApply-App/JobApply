"""enforce RLS on remaining tenant tables

Revision ID: e34f0ea56e30
Revises: 32d536527e9a
Create Date: 2026-08-03 14:20:20.204696

11 tables got a real FK to profiles(id) in 00eab53e0f00 (tenancy
enforcement) but never got the matching RLS treatment that
b19a4c6d2e71 already gave profiles/user_preferences/profile_answers/
cv_documents/cv_claims/user_job_matches/job_postings — so isolation on
these 11 rested on FK integrity + application-level user_id filtering
only, with no DB-level backstop. This migration closes that gap using the
exact same _enable_rls/_owner_policy helpers and naming convention as
b19a4c6d2e71, so behavior is consistent across every tenant table:

    applications, ariel_gap_queue, ariel_sessions, chat_sessions,
    confidence_audit_log, conversation_events, evidence_records,
    profile_entities, profile_interviews, recruiter_reply_drafts,
    shadow_match_scores

Also brings company_intel and kv_store — the two GLOBAL_TABLES (see
backend/core/migrations.py) that live in Postgres — under RLS:
  - company_intel: read-all policy, same shape as job_postings
    (job_postings_read_all) — a shared research cache, identical
    regardless of viewer, never written by a direct client.
  - kv_store: RLS enabled, deliberately NO policies. Per
    backend/core/migrations.py's GLOBAL_TABLES comment this is
    "process-level operational flags, not user data" — nobody should
    read or write it via a direct-client (PostgREST/supabase-js) path.
    RLS-enabled-with-zero-policies denies all access to any role that
    isn't RLS-exempt, which is exactly "backend/service-role only"
    without needing an explicit bypass policy.

Same caveat as b19a4c6d2e71: the backend connects as the `postgres` role
(BYPASSRLS), so none of this changes current backend query behavior —
application-level user_id filtering remains the actual isolation
mechanism today. This is real Postgres RLS, in force the day any direct-
Supabase-client path (PostgREST, supabase-js with a user JWT) is added.

`all_jobs` is intentionally left untouched here: it already carries
rls=true from outside this Alembic chain (no matching migration in this
repo sets it — likely a Supabase-dashboard default), and it isn't part of
either requested table list.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e34f0ea56e30'
down_revision: Union[str, None] = '32d536527e9a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Mirrors b19a4c6d2e71's _enable_rls/_owner_policy — duplicated rather than
# imported, matching this repo's existing convention of self-contained
# migration files (see e.g. every other versions/*.py here).
def _enable_rls(table: str) -> None:
    op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE public.{table} FORCE ROW LEVEL SECURITY")


def _disable_rls(table: str) -> None:
    op.execute(f"ALTER TABLE public.{table} NO FORCE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE public.{table} DISABLE ROW LEVEL SECURITY")


def _owner_policy(table: str, user_col: str = "user_id") -> None:
    op.execute(f"""
        CREATE POLICY {table}_owner_select ON public.{table}
            FOR SELECT USING ({user_col} = auth.uid())
    """)
    op.execute(f"""
        CREATE POLICY {table}_owner_write ON public.{table}
            FOR ALL USING ({user_col} = auth.uid()) WITH CHECK ({user_col} = auth.uid())
    """)


def _drop_owner_policy(table: str) -> None:
    op.execute(f"DROP POLICY IF EXISTS {table}_owner_select ON public.{table}")
    op.execute(f"DROP POLICY IF EXISTS {table}_owner_write ON public.{table}")


_TENANT_TABLES = (
    "applications", "ariel_gap_queue", "ariel_sessions", "chat_sessions",
    "confidence_audit_log", "conversation_events", "evidence_records",
    "profile_entities", "profile_interviews", "recruiter_reply_drafts",
    "shadow_match_scores",
)


def upgrade() -> None:
    for table in _TENANT_TABLES:
        _enable_rls(table)
        _owner_policy(table)

    _enable_rls('company_intel')
    op.execute("CREATE POLICY company_intel_read_all ON public.company_intel FOR SELECT USING (true)")

    # kv_store: RLS on, no policies — service-role/backend-only by omission.
    _enable_rls('kv_store')


def downgrade() -> None:
    _disable_rls('kv_store')

    op.execute("DROP POLICY IF EXISTS company_intel_read_all ON public.company_intel")
    _disable_rls('company_intel')

    for table in reversed(_TENANT_TABLES):
        _drop_owner_policy(table)
        _disable_rls(table)
