"""fold match_triggers and job_feedback into user_job_matches

Revision ID: 3542b0021d6b
Revises: fa884910ef1d
Create Date: 2026-08-02 19:50:00.000000

Step 4 of docs/db-architecture-spec.md — principle 3: a fact that is 1:1 with
an existing row is a column, not a table.

SCOPE CORRECTION vs the spec as written
---------------------------------------
The spec listed three tables to fold in. Checking which of them the schema
actually constrains to 1:1 — rather than trusting the label — showed only two:

  match_triggers          UNIQUE (user_id, job_id) via uq_match_triggers_user_job.
                          The repository even documents its insert as returning
                          False "if the (user, job) pair already fired". FOLDED.
  job_feedback            UNIQUE (user_id, job_id) via uq_job_feedback_user_job,
                          and the writer is an upsert ("latest opinion wins").
                          FOLDED.
  recruiter_reply_drafts  NO uniqueness. insert() mints a fresh draft_id per
                          call with no conflict handling, and each row carries
                          the email_excerpt of the specific message it answers —
                          a recruiter who writes twice about one job produces
                          two drafts. Genuine 1:N. NOT FOLDED; it stays a table
                          under the same principle 3 that justifies folding the
                          other two.

Denormalised blobs
------------------
payload_json is DROPPED. Its own comment explains why it existed: "compact
payload for the notification channels — enough to render an alert without a
join back to the jobs table". After the fold the row is that join; title,
company, fit_brief and score are all present on it.

snapshot_json is KEPT as feedback_snapshot. It looks like the same kind of
denormalisation but is not: build_job_snapshot() records culture_axis,
operational_pace and work_model, which come from the company_intel culture
cache and appear nowhere on user_job_matches. The preference-learning path
reads snap["culture_axis"] directly, and freezing it at rating time is also
more correct than re-reading a cache that may since have been re-researched.

All three tables are empty on Dev, but the backfill is written for real anyway
so this migration is safe against an environment that has data.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = '3542b0021d6b'
down_revision: Union[str, None] = 'fa884910ef1d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── from match_triggers ───────────────────────────────────────────────────
    # trigger_score is kept separate from match_score: it records the score at
    # the moment the threshold was crossed, which re-scoring can move away from.
    op.add_column('user_job_matches', sa.Column('trigger_state', sa.Text(), nullable=True), schema='public')
    op.add_column('user_job_matches', sa.Column('trigger_score', sa.Float(), nullable=True), schema='public')
    op.add_column('user_job_matches', sa.Column('trigger_threshold', sa.Float(), nullable=True), schema='public')
    op.add_column('user_job_matches', sa.Column('triggered_at', sa.DateTime(timezone=True), nullable=True), schema='public')
    op.add_column('user_job_matches', sa.Column('trigger_consumed_at', sa.DateTime(timezone=True), nullable=True), schema='public')

    # ── from job_feedback ─────────────────────────────────────────────────────
    op.add_column('user_job_matches', sa.Column('feedback_type', sa.Text(), nullable=True), schema='public')
    op.add_column('user_job_matches', sa.Column('feedback_reason', sa.Text(), nullable=True), schema='public')
    op.add_column('user_job_matches', sa.Column('feedback_snapshot', postgresql.JSONB(astext_type=sa.Text()), nullable=True), schema='public')
    op.add_column('user_job_matches', sa.Column('feedback_at', sa.DateTime(timezone=True), nullable=True), schema='public')

    op.create_check_constraint(
        'ck_user_job_matches_trigger_state', 'user_job_matches',
        "trigger_state IS NULL OR trigger_state IN ('pending', 'consumed')",
        schema='public',
    )

    # Partial indexes: these keep "what is pending" and "what was rated" as
    # cheap as the dedicated tables were — a scan over the handful of matching
    # rows, not over every match the user has.
    op.create_index('ix_ujm_pending_triggers', 'user_job_matches', ['user_id', 'triggered_at'],
                    schema='public', postgresql_where=sa.text("trigger_state = 'pending'"))
    op.create_index('ix_ujm_feedback', 'user_job_matches', ['user_id', 'feedback_at'],
                    schema='public', postgresql_where=sa.text("feedback_type IS NOT NULL"))

    # ── backfill ──────────────────────────────────────────────────────────────
    op.execute("""
        UPDATE public.user_job_matches ujm
        SET trigger_state       = mt.status,
            trigger_score       = mt.score,
            trigger_threshold   = mt.threshold,
            triggered_at        = CAST(NULLIF(mt.created_at, '') AS timestamptz),
            trigger_consumed_at = CAST(NULLIF(mt.consumed_at, '') AS timestamptz)
        FROM public.match_triggers mt
        WHERE mt.job_id = ujm.job_id AND mt.user_id = ujm.user_id
    """)
    op.execute("""
        UPDATE public.user_job_matches ujm
        SET feedback_type     = jf.feedback_type,
            feedback_reason   = jf.reason,
            feedback_snapshot = CAST(NULLIF(jf.snapshot_json, '') AS jsonb),
            feedback_at       = CAST(NULLIF(COALESCE(jf.updated_at, jf.created_at), '') AS timestamptz)
        FROM public.job_feedback jf
        WHERE jf.job_id = ujm.job_id AND jf.user_id = ujm.user_id
    """)

    # A row whose (user, job) has no user_job_matches counterpart would vanish
    # silently. Fail instead — on Dev both counts are 0.
    op.execute("""
        DO $$
        DECLARE lost int;
        BEGIN
            SELECT (SELECT count(*) FROM public.match_triggers mt
                    WHERE NOT EXISTS (SELECT 1 FROM public.user_job_matches u
                                      WHERE u.job_id = mt.job_id AND u.user_id = mt.user_id))
                 + (SELECT count(*) FROM public.job_feedback jf
                    WHERE NOT EXISTS (SELECT 1 FROM public.user_job_matches u
                                      WHERE u.job_id = jf.job_id AND u.user_id = jf.user_id))
              INTO lost;
            IF lost > 0 THEN
                RAISE EXCEPTION
                  'aborting: % trigger/feedback row(s) have no user_job_matches row and would be lost', lost;
            END IF;
        END $$;
    """)

    op.drop_table('match_triggers', schema='public')
    op.drop_table('job_feedback', schema='public')


def downgrade() -> None:
    op.create_table(
        'match_triggers',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column('job_id', sa.String(), nullable=False),
        sa.Column('score', sa.Float(), nullable=False),
        sa.Column('threshold', sa.Float(), nullable=False),
        sa.Column('payload_json', sa.Text(), nullable=False, server_default='{}'),
        sa.Column('status', sa.String(), nullable=False, server_default='pending'),
        sa.Column('created_at', sa.String(), nullable=False),
        sa.Column('consumed_at', sa.String(), nullable=True),
        schema='public',
    )
    op.create_index('ix_match_triggers_user_id', 'match_triggers', ['user_id'], schema='public')
    op.create_index('ix_match_triggers_status', 'match_triggers', ['status'], schema='public')
    op.create_index('uq_match_triggers_user_job', 'match_triggers', ['user_id', 'job_id'],
                    unique=True, schema='public')
    op.create_foreign_key('fk_match_triggers_user_id_profiles', 'match_triggers', 'profiles',
                          ['user_id'], ['id'], source_schema='public', referent_schema='public',
                          ondelete='CASCADE')

    op.create_table(
        'job_feedback',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column('job_id', sa.String(), nullable=False),
        sa.Column('feedback_type', sa.String(), nullable=False),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('snapshot_json', sa.Text(), nullable=True),
        sa.Column('created_at', sa.String(), nullable=False),
        sa.Column('updated_at', sa.String(), nullable=True),
        schema='public',
    )
    op.create_index('ix_job_feedback_user_id', 'job_feedback', ['user_id'], schema='public')
    op.create_index('uq_job_feedback_user_job', 'job_feedback', ['user_id', 'job_id'],
                    unique=True, schema='public')
    op.create_foreign_key('fk_job_feedback_user_id_profiles', 'job_feedback', 'profiles',
                          ['user_id'], ['id'], source_schema='public', referent_schema='public',
                          ondelete='CASCADE')

    # payload_json cannot be reconstructed field-for-field; rebuild it from the
    # joined row, which is where its contents came from in the first place.
    op.execute("""
        INSERT INTO public.match_triggers
            (user_id, job_id, score, threshold, payload_json, status, created_at, consumed_at)
        SELECT ujm.user_id, ujm.job_id,
               COALESCE(ujm.trigger_score, 0), COALESCE(ujm.trigger_threshold, 0),
               jsonb_build_object('job_id', ujm.job_id, 'title', jp.title,
                                  'company', jp.company, 'score', ujm.trigger_score,
                                  'fit_brief', left(COALESCE(ujm.fit_brief, ''), 250))::text,
               ujm.trigger_state,
               COALESCE(ujm.triggered_at::text, ''), ujm.trigger_consumed_at::text
        FROM public.user_job_matches ujm
        JOIN public.job_postings jp ON jp.id = ujm.job_posting_id
        WHERE ujm.trigger_state IS NOT NULL
    """)
    op.execute("""
        INSERT INTO public.job_feedback
            (user_id, job_id, feedback_type, reason, snapshot_json, created_at, updated_at)
        SELECT user_id, job_id, feedback_type, feedback_reason,
               feedback_snapshot::text,
               COALESCE(feedback_at::text, ''), feedback_at::text
        FROM public.user_job_matches WHERE feedback_type IS NOT NULL
    """)

    op.drop_index('ix_ujm_feedback', table_name='user_job_matches', schema='public')
    op.drop_index('ix_ujm_pending_triggers', table_name='user_job_matches', schema='public')
    op.drop_constraint('ck_user_job_matches_trigger_state', 'user_job_matches',
                       schema='public', type_='check')
    for col in ('feedback_at', 'feedback_snapshot', 'feedback_reason', 'feedback_type',
                'trigger_consumed_at', 'triggered_at', 'trigger_threshold',
                'trigger_score', 'trigger_state'):
        op.drop_column('user_job_matches', col, schema='public')
