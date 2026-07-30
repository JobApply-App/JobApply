"""drop legacy jobs and master_profiles tables (Contract phase)

Revision ID: 3a6b5cab3433
Revises: f1a9c3d5b2e7
Create Date: 2026-07-30 21:40:00.000000

Phase 4 (docs/db-redesign-proposal.md) — the CONTRACT step of Expand ->
Migrate -> Contract. Application code no longer reads or writes either
table:
  - jobs: job_repository.py was rewritten against job_postings/
    user_job_matches (Phase 2 / commit f41a526).
  - master_profiles: every read/write path was repointed at
    backend/repositories/profile_repository.py, and the before_flush
    dual-write listener that used to mirror writes into the new schema was
    removed (Phase 3).

Every migratable row was carried forward by
backend/scripts/migrate_to_relational_schema.py before this migration was
written and verified against Dev:
  - jobs: 4/4 rows migrated to job_postings/user_job_matches.
  - master_profiles: 3/6 rows migrated to profiles/user_preferences/
    profile_answers/cv_documents/cv_claims. The other 3 ('default',
    'interview-test-user', 'test-user') are pre-auth fixture rows with no
    corresponding auth.users account — they were never real accounts and
    cannot have a profiles row (profiles.id has a hard FK to
    auth.users(id)). This is an intentional, disclosed data loss of
    unrecoverable fixture data, not active user data.

downgrade() recreates both tables' current (post tenant_id-drop) shape so
the migration is structurally reversible, but does NOT restore any data —
once this migration's upgrade() runs against a real database, the row data
is gone. Re-running the Migrate script after a downgrade would need the
data to still exist in the new schema (it does — Migrate never deletes
from the new tables) but cannot reverse-populate these legacy tables.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = '3a6b5cab3433'
down_revision: Union[str, None] = 'f1a9c3d5b2e7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_table('master_profiles', schema='public')
    op.drop_table('jobs', schema='public')


def downgrade() -> None:
    op.create_table(
        'jobs',
        sa.Column('job_id', sa.String(), primary_key=True, nullable=False),
        sa.Column('title', sa.String(), nullable=False),
        sa.Column('company', sa.String(), nullable=False),
        sa.Column('location', sa.String(), nullable=False),
        sa.Column('score', sa.Float(), nullable=False),
        sa.Column('confidence_score', sa.Integer(), nullable=False),
        sa.Column('culture_fit_score', sa.Integer(), nullable=False),
        sa.Column('trajectory_alignment', sa.Text(), nullable=False),
        sa.Column('company_dna_inference', sa.Text(), nullable=False),
        sa.Column('investigation_points', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('detailed_analysis', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('reasons', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('apply_url', sa.String(), nullable=True),
        sa.Column('is_new', sa.Boolean(), nullable=False),
        sa.Column('posted_at', sa.String(), nullable=False),
        sa.Column('why_ron', sa.Text(), nullable=True),
        sa.Column('category', sa.String(), nullable=True),
        sa.Column('applied', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('applied_at', sa.Text(), nullable=True),
        sa.Column('source', sa.Text(), server_default=sa.text("'automatic'"), nullable=False),
        sa.Column('is_open', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('scoring_rationale', sa.Text(), nullable=True),
        sa.Column('tailored_cv', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('jd_text', sa.Text(), nullable=True),
        sa.Column('user_id', sa.Text(), server_default=sa.text("'default'"), nullable=False),
        sa.Column('source_type', sa.Text(), server_default=sa.text("'other'"), nullable=False),
        sa.Column('company_website_url', sa.Text(), nullable=True),
        sa.Column('status', sa.Text(), server_default=sa.text("'new'"), nullable=False),
        sa.Column('match_score', sa.Float(), server_default=sa.text('0.0'), nullable=False),
        sa.Column('created_at', sa.Text(), nullable=True),
        sa.Column('locale', sa.Text(), nullable=True),
        sa.Column('dedup_key', sa.Text(), nullable=True),
        sa.Column('jd_structured', sa.Text(), nullable=True),
        sa.Column('score_is_proxy', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('enrichment_failures', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('outreach_text', sa.Text(), nullable=True),
        sa.Column('culture_delta', sa.Float(), nullable=True),
        sa.Column('culture_alignment', sa.Float(), nullable=True),
        sa.Column('culture_category', sa.Text(), nullable=True),
        sa.Column('culture_note', sa.Text(), nullable=True),
        schema='public',
    )
    op.create_index('ix_jobs_created_at', 'jobs', ['created_at'], unique=False, schema='public')
    op.create_index('ix_jobs_is_open', 'jobs', ['is_open'], unique=False, schema='public')
    op.create_index('ix_jobs_source', 'jobs', ['source'], unique=False, schema='public')
    op.create_index('ix_jobs_status', 'jobs', ['status'], unique=False, schema='public')
    op.create_index('ix_jobs_user_applied', 'jobs', ['user_id', 'applied'], unique=False, schema='public')
    op.create_index('ix_jobs_user_status', 'jobs', ['user_id', 'status'], unique=False, schema='public')
    op.create_index('ix_jobs_dedup_key', 'jobs', ['dedup_key'], unique=False, schema='public')

    op.create_table(
        'master_profiles',
        sa.Column('user_id', sa.String(), primary_key=True, nullable=False),
        sa.Column('onboarding_status', sa.String(), nullable=False),
        sa.Column('master_profile', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('created_at', sa.String(), nullable=True),
        sa.Column('updated_at', sa.String(), nullable=True),
        sa.Column('is_admin', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('email', sa.Text(), nullable=True),
        schema='public',
    )
    op.create_index('ix_master_profiles_email', 'master_profiles', ['email'], unique=False, schema='public')
