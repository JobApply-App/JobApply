"""enforce tenancy: user_id -> UUID + FK to profiles on all 14 user-owned tables

Revision ID: 00eab53e0f00
Revises: 3a6b5cab3433
Create Date: 2026-08-02 16:45:00.000000

Step 1 of docs/db-architecture-spec.md — "profiles.id is the single tenancy
anchor" (principle 1).

Before this migration only 5 tables were FK'd to profiles. The other 14 held
user_id as free-form TEXT/VARCHAR with no referential integrity, and the
consequences were already in the data: 41 rows referenced user_ids with no
matching profile. Those were triaged by hand before this migration ran
(see docs/db-architecture-spec.md §2.1 and the backup CSV under
backend/backups/):

  - 13 evidence_records carried a typo'd UUID (…bcfede vs the real …bcfe0e)
    and were REAL evidence rows for the real account's entities -> repointed.
  - 23 rows (10 chat_sessions, 13 shadow_match_scores) carried the retired
    'default' single-user id and were genuine pre-auth data -> repointed to
    the owning account.
  - 5 'test_neg_cr_user' fixture rows -> deleted.

After this migration, deleting a user is a single
`DELETE FROM profiles WHERE id = $1` and Postgres cascades the whole graph,
instead of 14 manual deletes that were easy to get wrong.

Note on chat_sessions/ariel_sessions/profile_interviews: these three merge
into a unified `conversations` table in Step 5 of the spec. They are still
converted here, deliberately — Step 5's migration should start from data it
can trust rather than re-doing this cleanup mid-merge.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '00eab53e0f00'
down_revision: Union[str, None] = '3a6b5cab3433'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Every table that stores rows owned by a single user. Ordered alphabetically;
# order does not matter because each FK targets profiles, never each other.
_USER_TABLES: tuple[str, ...] = (
    "applications",
    "ariel_gap_queue",
    "ariel_probe_log",
    "ariel_sessions",
    "chat_sessions",
    "confidence_audit_log",
    "conversation_events",
    "evidence_records",
    "job_feedback",
    "match_triggers",
    "profile_entities",
    "profile_interviews",
    "recruiter_reply_drafts",
    "shadow_match_scores",
)


# Leftovers from the retired single-user mode: these two columns still carried
# `DEFAULT 'default'::text`, which blocks the type change outright ("default for
# column user_id cannot be cast automatically to type uuid"). Nothing should ever
# have relied on it — an unauthenticated insert is exactly what tenancy forbids.
_TABLES_WITH_LEGACY_DEFAULT: tuple[str, ...] = ("applications", "profile_interviews")


def _fk_name(table: str) -> str:
    return f"fk_{table}_user_id_profiles"


def upgrade() -> None:
    for table in _TABLES_WITH_LEGACY_DEFAULT:
        op.alter_column(table, "user_id", server_default=None, schema="public")

    for table in _USER_TABLES:
        # USING is required: Postgres will not implicitly cast text -> uuid.
        op.alter_column(
            table, "user_id",
            existing_type=sa.Text(),
            type_=sa.dialects.postgresql.UUID(as_uuid=False),
            postgresql_using="user_id::uuid",
            existing_nullable=False,
            schema="public",
        )
        op.create_foreign_key(
            _fk_name(table), table, "profiles",
            ["user_id"], ["id"],
            source_schema="public", referent_schema="public",
            ondelete="CASCADE",
        )


def downgrade() -> None:
    for table in _USER_TABLES:
        op.drop_constraint(_fk_name(table), table, schema="public", type_="foreignkey")
        op.alter_column(
            table, "user_id",
            existing_type=sa.dialects.postgresql.UUID(as_uuid=False),
            type_=sa.Text(),
            postgresql_using="user_id::text",
            existing_nullable=False,
            schema="public",
        )
