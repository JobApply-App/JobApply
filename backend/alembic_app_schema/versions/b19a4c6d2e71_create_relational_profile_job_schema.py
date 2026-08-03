"""Phase 2 Expand: create the normalized profile/job schema
(profiles, user_preferences, profile_answers, cv_documents, cv_claims,
job_postings, user_job_matches), with FKs to auth.users(id), TIMESTAMPTZ
timestamps, and RLS.

Revision ID: b19a4c6d2e71
Revises: c7a3e1f6b0d4
Create Date: 2026-07-27 19:30:00.000000

See docs/db-redesign-proposal.md §3 for the design rationale. This is the
EXPAND half of Expand -> Migrate -> Contract: every table here is additive —
master_profiles and jobs are untouched and keep serving the app exactly as
today until the data-migration and application-layer steps land. Nothing in
this migration is destructive.

Scope note: `companies` (merging company_intel/company_culture) was proposed
in docs/db-redesign-proposal.md §2.3/§3.2 but is explicitly NOT part of this
migration — the approved Phase 2 task list names only the seven tables
below. job_postings.company stays a plain TEXT column, matching jobs.company
today, not a foreign key.

RLS caveat (read before assuming this changes current backend behavior):
the backend connects to Postgres as the `postgres` role, which has
BYPASSRLS — confirmed via `SELECT rolbypassrls FROM pg_roles WHERE rolname
= current_user`. Every policy below is real Postgres RLS and will fully
apply to any future direct-Supabase-client access (PostgREST, supabase-js
with a user JWT), but it does NOT restrict the backend's own queries today,
since bypass-capable roles skip RLS entirely regardless of FORCE ROW LEVEL
SECURITY. Application-level `user_id` filtering (already in place across
every repository) remains the actual isolation mechanism for the current
architecture. RLS here is enabled and configured correctly now so it's
already in force the day any direct-client path is added, not retrofitted
under pressure later.

Column mapping from the old blob/mixed-table shape, for the data-migration
script that follows this Expand migration:
  master_profiles.master_profile ->
      "personal"         -> profiles.{full_name, phone, linkedin_url, location}
      "role_preferences" -> user_preferences.*
      "metrics"          -> profile_answers rows (one per key)
      "cv_claims"        -> cv_documents (one row) + cv_claims (one row per
                            skill/experience/education entry)
      "enriched_entities"-> intentionally dropped (already duplicated by the
                            existing, separately-designed profile_entities
                            table per docs/db-redesign-proposal.md §3.1)
  jobs (per (user_id, job) row, mixing job-facts with match-state) ->
      job-fact columns      -> job_postings (deduped)
      match-state columns   -> user_job_matches
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'b19a4c6d2e71'
down_revision: Union[str, None] = 'c7a3e1f6b0d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ── RLS helpers ───────────────────────────────────────────────────────────────
# Written as raw SQL (not op.execute per-statement duplicated in upgrade/
# downgrade) since Alembic has no first-class RLS op — this is the standard
# way every Supabase-authored migration expresses it too.

def _enable_rls(table: str) -> None:
    op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE public.{table} FORCE ROW LEVEL SECURITY")


def _owner_policy(table: str, user_col: str = "user_id") -> None:
    """Row-owner policy: authenticated users may only see/touch their own rows."""
    op.execute(f"""
        CREATE POLICY {table}_owner_select ON public.{table}
            FOR SELECT USING ({user_col} = auth.uid())
    """)
    op.execute(f"""
        CREATE POLICY {table}_owner_write ON public.{table}
            FOR ALL USING ({user_col} = auth.uid()) WITH CHECK ({user_col} = auth.uid())
    """)


def upgrade() -> None:
    # ── profiles ──────────────────────────────────────────────────────────
    op.create_table(
        'profiles',
        sa.Column('id', postgresql.UUID(), nullable=False),
        sa.Column('email', sa.Text(), nullable=True),
        sa.Column('full_name', sa.Text(), nullable=True),
        sa.Column('phone', sa.Text(), nullable=True),
        sa.Column('linkedin_url', sa.Text(), nullable=True),
        sa.Column('location', sa.Text(), nullable=True),
        sa.Column('is_admin', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('onboarding_status', sa.Text(), server_default=sa.text("'incomplete'"), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['id'], ['auth.users.id'], name='fk_profiles_id_auth_users', ondelete='CASCADE'),
        schema='public',
    )

    # ── user_preferences (1:1) ───────────────────────────────────────────────
    op.create_table(
        'user_preferences',
        sa.Column('user_id', postgresql.UUID(), nullable=False),
        sa.Column('target_titles', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column('preferred_locations', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column('work_type', sa.Text(), server_default=sa.text("'any'"), nullable=False),
        sa.Column('salary_min_usd', sa.Integer(), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('user_id'),
        sa.ForeignKeyConstraint(['user_id'], ['profiles.id'], name='fk_user_preferences_user_id_profiles', ondelete='CASCADE'),
        schema='public',
    )

    # ── profile_answers (1:N — metrics / supplemental Q&A) ──────────────────
    op.create_table(
        'profile_answers',
        sa.Column('id', postgresql.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('user_id', postgresql.UUID(), nullable=False),
        sa.Column('question_id', sa.Text(), nullable=False),
        sa.Column('answer', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['user_id'], ['profiles.id'], name='fk_profile_answers_user_id_profiles', ondelete='CASCADE'),
        sa.UniqueConstraint('user_id', 'question_id', name='uq_profile_answers_user_question'),
        schema='public',
    )
    op.create_index('ix_profile_answers_user_id', 'profile_answers', ['user_id'], schema='public')

    # ── cv_documents ─────────────────────────────────────────────────────────
    op.create_table(
        'cv_documents',
        sa.Column('id', postgresql.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('user_id', postgresql.UUID(), nullable=False),
        sa.Column('summary', sa.Text(), nullable=True),
        sa.Column('uploaded_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['user_id'], ['profiles.id'], name='fk_cv_documents_user_id_profiles', ondelete='CASCADE'),
        schema='public',
    )
    op.create_index('ix_cv_documents_user_id', 'cv_documents', ['user_id'], schema='public')

    # ── cv_claims ────────────────────────────────────────────────────────────
    op.create_table(
        'cv_claims',
        sa.Column('id', postgresql.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('document_id', postgresql.UUID(), nullable=False),
        sa.Column('claim_type', sa.Text(), nullable=False),
        sa.Column('content', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint("claim_type IN ('skill', 'experience', 'education')", name='ck_cv_claims_claim_type'),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['document_id'], ['cv_documents.id'], name='fk_cv_claims_document_id_cv_documents', ondelete='CASCADE'),
        schema='public',
    )
    op.create_index('ix_cv_claims_document_id', 'cv_claims', ['document_id'], schema='public')

    # ── job_postings (deduped job catalog, split from jobs) ──────────────────
    op.create_table(
        'job_postings',
        sa.Column('id', postgresql.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('canonical_job_key', sa.Text(), nullable=False),
        sa.Column('title', sa.Text(), nullable=False),
        sa.Column('company', sa.Text(), nullable=False),
        sa.Column('company_website_url', sa.Text(), nullable=True),
        sa.Column('location', sa.Text(), nullable=False),
        sa.Column('jd_text', sa.Text(), nullable=True),
        sa.Column('jd_structured', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('apply_url', sa.Text(), nullable=True),
        sa.Column('source', sa.Text(), server_default=sa.text("'automatic'"), nullable=False),
        sa.Column('source_type', sa.Text(), server_default=sa.text("'other'"), nullable=False),
        sa.Column('locale', sa.Text(), nullable=True),
        sa.Column('posted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('is_open', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('canonical_job_key', name='uq_job_postings_canonical_job_key'),
        schema='public',
    )

    # ── user_job_matches (per-user match state, split from jobs) ─────────────
    op.create_table(
        'user_job_matches',
        sa.Column('id', postgresql.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('user_id', postgresql.UUID(), nullable=False),
        sa.Column('job_posting_id', postgresql.UUID(), nullable=False),
        sa.Column('score', sa.Float(), server_default=sa.text('0'), nullable=False),
        sa.Column('match_score', sa.Float(), server_default=sa.text('0'), nullable=False),
        sa.Column('confidence_score', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('culture_fit_score', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('trajectory_alignment', sa.Text(), nullable=True),
        sa.Column('company_dna_inference', sa.Text(), nullable=True),
        sa.Column('investigation_points', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column('detailed_analysis', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column('reasons', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column('why_ron', sa.Text(), nullable=True),
        sa.Column('scoring_rationale', sa.Text(), nullable=True),
        sa.Column('tailored_cv', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('status', sa.Text(), server_default=sa.text("'new'"), nullable=False),
        sa.Column('is_new', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('applied', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('applied_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('category', sa.Text(), nullable=True),
        sa.Column('score_is_proxy', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('enrichment_failures', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('outreach_text', sa.Text(), nullable=True),
        sa.Column('culture_delta', sa.Float(), nullable=True),
        sa.Column('culture_alignment', sa.Float(), nullable=True),
        sa.Column('culture_category', sa.Text(), nullable=True),
        sa.Column('culture_note', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['user_id'], ['profiles.id'], name='fk_user_job_matches_user_id_profiles', ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['job_posting_id'], ['job_postings.id'], name='fk_user_job_matches_job_posting_id_job_postings', ondelete='CASCADE'),
        sa.UniqueConstraint('user_id', 'job_posting_id', name='uq_user_job_matches_user_job'),
        schema='public',
    )
    op.create_index('ix_user_job_matches_user_id', 'user_job_matches', ['user_id'], schema='public')
    op.create_index('ix_user_job_matches_status', 'user_job_matches', ['user_id', 'status'], schema='public')

    # ── RLS ───────────────────────────────────────────────────────────────────
    _enable_rls('profiles')
    op.execute("CREATE POLICY profiles_owner_select ON public.profiles FOR SELECT USING (id = auth.uid())")
    op.execute("CREATE POLICY profiles_owner_write ON public.profiles FOR ALL USING (id = auth.uid()) WITH CHECK (id = auth.uid())")

    _enable_rls('user_preferences')
    _owner_policy('user_preferences')

    _enable_rls('profile_answers')
    _owner_policy('profile_answers')

    _enable_rls('cv_documents')
    _owner_policy('cv_documents')

    _enable_rls('cv_claims')
    op.execute("""
        CREATE POLICY cv_claims_owner_select ON public.cv_claims
            FOR SELECT USING (document_id IN (SELECT id FROM public.cv_documents WHERE user_id = auth.uid()))
    """)
    op.execute("""
        CREATE POLICY cv_claims_owner_write ON public.cv_claims
            FOR ALL
            USING (document_id IN (SELECT id FROM public.cv_documents WHERE user_id = auth.uid()))
            WITH CHECK (document_id IN (SELECT id FROM public.cv_documents WHERE user_id = auth.uid()))
    """)

    _enable_rls('user_job_matches')
    _owner_policy('user_job_matches')

    # job_postings is a global catalog, not user-owned: any authenticated
    # client may read; only the backend's service role writes.
    _enable_rls('job_postings')
    op.execute("CREATE POLICY job_postings_read_all ON public.job_postings FOR SELECT USING (true)")


def downgrade() -> None:
    op.drop_table('user_job_matches', schema='public')
    op.drop_table('job_postings', schema='public')
    op.drop_table('cv_claims', schema='public')
    op.drop_table('cv_documents', schema='public')
    op.drop_table('profile_answers', schema='public')
    op.drop_table('user_preferences', schema='public')
    op.drop_table('profiles', schema='public')
