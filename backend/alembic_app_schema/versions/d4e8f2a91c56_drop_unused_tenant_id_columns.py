"""Phase 2: drop unused tenant_id column from all 15 tables that carry it

Revision ID: d4e8f2a91c56
Revises: b19a4c6d2e71
Create Date: 2026-07-27 19:31:00.000000

tenant_id was added as forward-compatible multi-tenant prep (docs/
multi-tenant-erd.md), backfilled to equal user_id, but never consumed by
any query filter anywhere in the codebase — confirmed via grep across
backend/repositories, backend/services, backend/api before writing this
migration (only backend/core/migrations.py's own backfill/rollback logic
and backend/tests/test_tenant_isolation.py's dedicated tenant_id-backfill
assertions reference it; no application query filters on it).

Dropping the column also drops its dependent indexes automatically
(confirmed: ix_<table>_tenant_id on all 15 tables, plus the two composite
indexes ix_jobs_tenant_user and ix_applications_tenant_user) — Postgres
drops any index defined on a dropped column as part of the same DDL
statement, so no separate DROP INDEX is needed here.

Downgrade recreates the column (nullable, unbackfilled) and its single-
column index on each table, but does NOT restore data or the two composite
indexes — if tenant_id is ever needed again, that's a fresh design
decision, not a blind revert.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd4e8f2a91c56'
down_revision: Union[str, None] = 'b19a4c6d2e71'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLES = [
    "applications", "ariel_gap_queue", "ariel_probe_log", "ariel_sessions",
    "confidence_audit_log", "conversation_events", "evidence_records",
    "job_feedback", "jobs", "master_profiles", "match_triggers",
    "profile_entities", "profile_interviews", "recruiter_reply_drafts",
    "shadow_match_scores",
]


def upgrade() -> None:
    for table in TABLES:
        op.drop_column(table, 'tenant_id', schema='public')


def downgrade() -> None:
    for table in TABLES:
        op.add_column(table, sa.Column('tenant_id', sa.Text(), nullable=True), schema='public')
        op.create_index(f'ix_{table}_tenant_id', table, ['tenant_id'], schema='public')
