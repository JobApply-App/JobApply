"""create public app-schema tables (Postgres port of backend/jobs.db)

Revision ID: 413f4ed8fbc6
Revises: 
Create Date: 2026-07-26 15:35:53.812312

Mirrors backend/jobs.db's SQLite schema (audited 2026-07-26) into Postgres's
default `public` schema, on the same shared engine as `linkedin.jobs`
(backend/core/postgres.py). SCHEMA-ONLY — does not touch backend/jobs.db and
does not change what the running app reads from (still SQLite, see
CLAUDE.md). Data copy is backend/scripts/migrate_jobs_db_to_supabase.py.

Type mapping: SQLite TEXT/VARCHAR -> Postgres TEXT/VARCHAR unchanged (keeps
the existing ISO-8601-string timestamp convention byte-for-byte, no TZ
reinterpretation risk); SQLite JSON -> JSONB; SQLite BOOLEAN -> BOOLEAN;
chat_sessions.created_at/updated_at -> TIMESTAMPTZ (the one genuinely
tz-aware sqlalchemy.DateTime column in the source schema, confirmed via
backend/api/routes/history.py). One FK (confidence_audit_log.evidence_id ->
evidence_records.evidence_id) is intentionally NOT enforced — the audit
found 2 existing rows that would violate it; SQLite never enforced this FK
either, so kept as a plain index to guarantee zero data loss on copy.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = '413f4ed8fbc6'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'profile_entities',
        sa.Column('entity_id', sa.Text(), primary_key=True, nullable=False),
        sa.Column('user_id', sa.Text(), nullable=False),
        sa.Column('entity_type', sa.Text(), nullable=False),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('normalized_name', sa.Text(), nullable=False),
        sa.Column('confidence_score', sa.Float(), server_default=sa.text('0.0'), nullable=False),
        sa.Column('verification_status', sa.Text(), server_default=sa.text("'unverified'"), nullable=False),
        sa.Column('last_evidence_at', sa.Text(), nullable=True),
        sa.Column('created_at', sa.Text(), nullable=False),
        sa.Column('updated_at', sa.Text(), nullable=False),
        sa.Column('manual_review_required', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('skill_tier', sa.Text(), nullable=True),
        sa.Column('architecture_confidence', sa.Float(), server_default=sa.text('0.0'), nullable=False),
        sa.Column('syntax_confidence', sa.Float(), server_default=sa.text('0.0'), nullable=False),
        sa.Column('verification_level', sa.Text(), server_default=sa.text("'UNVERIFIED'"), nullable=False),
        sa.Column('proficiency_level', sa.Text(), nullable=True),
        sa.Column('tenant_id', sa.Text(), nullable=True),
        schema='public',
    )
    op.create_index('ix_profile_entities_tenant_id', 'profile_entities', ['tenant_id'], unique=False, schema='public')
    op.create_index('idx_pe_user_score', 'profile_entities', ['user_id', 'confidence_score'], unique=False, schema='public')
    op.create_index('idx_pe_user_type', 'profile_entities', ['user_id', 'entity_type'], unique=False, schema='public')
    op.create_index('idx_pe_user', 'profile_entities', ['user_id'], unique=False, schema='public')
    op.create_index('uq_profile_entities_user_normalized_entity_type', 'profile_entities', ['user_id', 'normalized_name', 'entity_type'], unique=True, schema='public')

    op.create_table(
        'ariel_sessions',
        sa.Column('session_id', sa.Text(), primary_key=True, nullable=False),
        sa.Column('user_id', sa.Text(), nullable=False),
        sa.Column('session_type', sa.Text(), nullable=False),
        sa.Column('target_job_id', sa.Text(), nullable=True),
        sa.Column('target_entities', sa.Text(), nullable=True),
        sa.Column('ariel_goal', sa.Text(), nullable=True),
        sa.Column('status', sa.Text(), server_default=sa.text("'active'"), nullable=False),
        sa.Column('transcript_json', sa.Text(), nullable=True),
        sa.Column('confidence_delta_total', sa.Float(), server_default=sa.text('0.0'), nullable=False),
        sa.Column('started_at', sa.Text(), nullable=False),
        sa.Column('ended_at', sa.Text(), nullable=True),
        sa.Column('tenant_id', sa.Text(), nullable=True),
        schema='public',
    )
    op.create_index('ix_ariel_sessions_tenant_id', 'ariel_sessions', ['tenant_id'], unique=False, schema='public')
    op.create_index('idx_as_job', 'ariel_sessions', ['target_job_id'], unique=False, schema='public')
    op.create_index('idx_as_user', 'ariel_sessions', ['user_id', 'started_at'], unique=False, schema='public')

    op.create_table(
        'conversation_events',
        sa.Column('event_id', sa.Text(), primary_key=True, nullable=False),
        sa.Column('session_id', sa.Text(), nullable=False),
        sa.Column('user_id', sa.Text(), nullable=False),
        sa.Column('star_situation', sa.Text(), nullable=True),
        sa.Column('star_task', sa.Text(), nullable=True),
        sa.Column('star_action', sa.Text(), nullable=True),
        sa.Column('star_result', sa.Text(), nullable=True),
        sa.Column('extracted_entity_ids', sa.Text(), nullable=False),
        sa.Column('extraction_confidence', sa.Float(), nullable=False),
        sa.Column('raw_quote', sa.Text(), nullable=True),
        sa.Column('analyzed_at', sa.Text(), nullable=False),
        sa.Column('tenant_id', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['session_id'], ['ariel_sessions.session_id'], name='fk_conversation_events_session_id_ariel_sessions'),
        schema='public',
    )
    op.create_index('ix_conversation_events_tenant_id', 'conversation_events', ['tenant_id'], unique=False, schema='public')
    op.create_index('idx_ce_user', 'conversation_events', ['user_id', 'analyzed_at'], unique=False, schema='public')
    op.create_index('idx_ce_session', 'conversation_events', ['session_id'], unique=False, schema='public')

    op.create_table(
        'evidence_records',
        sa.Column('evidence_id', sa.Text(), primary_key=True, nullable=False),
        sa.Column('entity_id', sa.Text(), nullable=False),
        sa.Column('user_id', sa.Text(), nullable=False),
        sa.Column('source_type', sa.Text(), nullable=False),
        sa.Column('base_weight', sa.Float(), nullable=False),
        sa.Column('raw_content', sa.Text(), nullable=True),
        sa.Column('verified_at', sa.Text(), nullable=False),
        sa.Column('hard_expires_at', sa.Text(), nullable=True),
        sa.Column('session_id', sa.Text(), nullable=True),
        sa.Column('event_id', sa.Text(), nullable=True),
        sa.Column('extra_metadata', sa.Text(), nullable=True),
        sa.Column('is_ai_assisted', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('tenant_id', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['event_id'], ['conversation_events.event_id'], name='fk_evidence_records_event_id_conversation_events'),
        sa.ForeignKeyConstraint(['session_id'], ['ariel_sessions.session_id'], name='fk_evidence_records_session_id_ariel_sessions'),
        sa.ForeignKeyConstraint(['entity_id'], ['profile_entities.entity_id'], name='fk_evidence_records_entity_id_profile_entities'),
        schema='public',
    )
    op.create_index('ix_evidence_records_tenant_id', 'evidence_records', ['tenant_id'], unique=False, schema='public')

    op.create_table(
        'evidence_records_old',
        sa.Column('evidence_id', sa.Text(), primary_key=True, nullable=False),
        sa.Column('entity_id', sa.Text(), nullable=False),
        sa.Column('user_id', sa.Text(), nullable=False),
        sa.Column('source_type', sa.Text(), nullable=False),
        sa.Column('base_weight', sa.Float(), nullable=False),
        sa.Column('raw_content', sa.Text(), nullable=True),
        sa.Column('verified_at', sa.Text(), nullable=False),
        sa.Column('hard_expires_at', sa.Text(), nullable=True),
        sa.Column('session_id', sa.Text(), nullable=True),
        sa.Column('event_id', sa.Text(), nullable=True),
        sa.Column('extra_metadata', sa.Text(), nullable=True),
        sa.Column('is_ai_assisted', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.ForeignKeyConstraint(['event_id'], ['conversation_events.event_id'], name='fk_evidence_records_old_event_id_conversation_events'),
        sa.ForeignKeyConstraint(['session_id'], ['ariel_sessions.session_id'], name='fk_evidence_records_old_session_id_ariel_sessions'),
        sa.ForeignKeyConstraint(['entity_id'], ['profile_entities.entity_id'], name='fk_evidence_records_old_entity_id_profile_entities'),
        schema='public',
    )
    op.create_index('idx_er_user', 'evidence_records_old', ['user_id', 'source_type'], unique=False, schema='public')
    op.create_index('idx_er_entity', 'evidence_records_old', ['entity_id', 'verified_at'], unique=False, schema='public')

    op.create_table(
        'ariel_gap_queue',
        sa.Column('gap_id', sa.Text(), primary_key=True, nullable=False),
        sa.Column('user_id', sa.Text(), nullable=False),
        sa.Column('entity_id', sa.Text(), nullable=False),
        sa.Column('job_id', sa.Text(), nullable=True),
        sa.Column('current_confidence', sa.Float(), nullable=False),
        sa.Column('required_confidence', sa.Float(), nullable=False),
        sa.Column('gap_severity', sa.Text(), nullable=False),
        sa.Column('status', sa.Text(), server_default=sa.text("'pending'"), nullable=False),
        sa.Column('session_id', sa.Text(), nullable=True),
        sa.Column('detected_at', sa.Text(), nullable=False),
        sa.Column('resolved_at', sa.Text(), nullable=True),
        sa.Column('tenant_id', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['session_id'], ['ariel_sessions.session_id'], name='fk_ariel_gap_queue_session_id_ariel_sessions'),
        sa.ForeignKeyConstraint(['entity_id'], ['profile_entities.entity_id'], name='fk_ariel_gap_queue_entity_id_profile_entities'),
        schema='public',
    )
    op.create_index('ix_ariel_gap_queue_tenant_id', 'ariel_gap_queue', ['tenant_id'], unique=False, schema='public')
    op.create_index('idx_agq_job', 'ariel_gap_queue', ['job_id', 'status'], unique=False, schema='public')
    op.create_index('idx_agq_user', 'ariel_gap_queue', ['user_id', 'gap_severity', 'status'], unique=False, schema='public')

    op.create_table(
        'ariel_probe_log',
        sa.Column('probe_id', sa.Text(), primary_key=True, nullable=False),
        sa.Column('user_id', sa.Text(), nullable=False),
        sa.Column('entity_id', sa.Text(), nullable=False),
        sa.Column('session_id', sa.Text(), nullable=False),
        sa.Column('outcome', sa.Text(), nullable=True),
        sa.Column('probed_at', sa.Text(), nullable=False),
        sa.Column('tenant_id', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['session_id'], ['ariel_sessions.session_id'], name='fk_ariel_probe_log_session_id_ariel_sessions'),
        sa.ForeignKeyConstraint(['entity_id'], ['profile_entities.entity_id'], name='fk_ariel_probe_log_entity_id_profile_entities'),
        schema='public',
    )
    op.create_index('ix_ariel_probe_log_tenant_id', 'ariel_probe_log', ['tenant_id'], unique=False, schema='public')
    op.create_index('idx_apl_user_entity', 'ariel_probe_log', ['user_id', 'entity_id', 'probed_at'], unique=False, schema='public')

    op.create_table(
        'confidence_audit_log',
        sa.Column('log_id', sa.Integer(), primary_key=True, nullable=False, autoincrement=True),
        sa.Column('entity_id', sa.Text(), nullable=False),
        sa.Column('user_id', sa.Text(), nullable=False),
        sa.Column('old_score', sa.Float(), nullable=False),
        sa.Column('new_score', sa.Float(), nullable=False),
        sa.Column('delta', sa.Float(), nullable=False),
        sa.Column('trigger_source', sa.Text(), nullable=False),
        sa.Column('evidence_id', sa.Text(), nullable=True),
        sa.Column('session_id', sa.Text(), nullable=True),
        sa.Column('changed_at', sa.Text(), nullable=False),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('tenant_id', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['session_id'], ['ariel_sessions.session_id'], name='fk_confidence_audit_log_session_id_ariel_sessions'),
        sa.ForeignKeyConstraint(['entity_id'], ['profile_entities.entity_id'], name='fk_confidence_audit_log_entity_id_profile_entities'),
        schema='public',
    )
    op.create_index('ix_confidence_audit_log_tenant_id', 'confidence_audit_log', ['tenant_id'], unique=False, schema='public')
    op.create_index('idx_cal_user', 'confidence_audit_log', ['user_id', 'changed_at'], unique=False, schema='public')
    op.create_index('idx_cal_entity', 'confidence_audit_log', ['entity_id', 'changed_at'], unique=False, schema='public')

    op.create_table(
        'applications',
        sa.Column('application_id', sa.String(), primary_key=True, nullable=False),
        sa.Column('job_id', sa.String(), nullable=False),
        sa.Column('title', sa.String(), nullable=False),
        sa.Column('company', sa.String(), nullable=False),
        sa.Column('ats', sa.String(), nullable=False),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('submitted_at', sa.String(), nullable=False),
        sa.Column('last_update', sa.String(), nullable=False),
        sa.Column('score', sa.Float(), nullable=False),
        sa.Column('cover_letter', sa.Text(), nullable=True),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('user_id', sa.Text(), server_default=sa.text("'default'"), nullable=False),
        sa.Column('tenant_id', sa.Text(), nullable=True),
        schema='public',
    )
    op.create_index('ix_applications_tenant_user', 'applications', ['tenant_id', 'user_id'], unique=False, schema='public')
    op.create_index('ix_applications_tenant_id', 'applications', ['tenant_id'], unique=False, schema='public')
    op.create_index('ix_applications_user_status', 'applications', ['user_id', 'status'], unique=False, schema='public')
    op.create_index('ix_applications_submitted_at', 'applications', ['submitted_at'], unique=False, schema='public')
    op.create_index('ix_applications_status', 'applications', ['status'], unique=False, schema='public')
    op.create_index('ix_applications_user_id', 'applications', ['user_id'], unique=False, schema='public')
    op.create_index('ix_applications_job_id', 'applications', ['job_id'], unique=False, schema='public')

    op.create_table(
        'chat_sessions',
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False, autoincrement=True),
        sa.Column('session_id', sa.String(length=64), nullable=False),
        sa.Column('user_id', sa.String(length=64), nullable=False),
        sa.Column('messages_json', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        schema='public',
    )
    op.create_index('ix_chat_sessions_user_id', 'chat_sessions', ['user_id'], unique=False, schema='public')
    op.create_index('ix_chat_sessions_session_id', 'chat_sessions', ['session_id'], unique=True, schema='public')

    op.create_table(
        'company_culture',
        sa.Column('company_key', sa.String(), primary_key=True, nullable=False),
        sa.Column('display_name', sa.String(), nullable=False),
        sa.Column('profile_json', sa.Text(), nullable=False),
        sa.Column('researched_at', sa.String(), nullable=False),
        schema='public',
    )

    op.create_table(
        'company_intel',
        sa.Column('company_key', sa.String(), primary_key=True, nullable=False),
        sa.Column('display_name', sa.String(), nullable=False),
        sa.Column('profile_json', sa.Text(), nullable=False),
        sa.Column('researched_at', sa.String(), nullable=False),
        schema='public',
    )

    op.create_table(
        'job_feedback',
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False, autoincrement=True),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('job_id', sa.String(), nullable=False),
        sa.Column('feedback_type', sa.String(), nullable=False),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('snapshot_json', sa.Text(), nullable=False),
        sa.Column('created_at', sa.String(), nullable=False),
        sa.Column('updated_at', sa.String(), nullable=False),
        sa.Column('tenant_id', sa.Text(), nullable=True),
        schema='public',
    )
    op.create_index('ix_job_feedback_tenant_id', 'job_feedback', ['tenant_id'], unique=False, schema='public')
    op.create_index('ix_job_feedback_user_id', 'job_feedback', ['user_id'], unique=False, schema='public')
    op.create_index('uq_job_feedback_user_job', 'job_feedback', ['user_id', 'job_id'], unique=True, schema='public')

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
        sa.Column('tenant_id', sa.Text(), nullable=True),
        schema='public',
    )
    op.create_index('ix_jobs_tenant_user', 'jobs', ['tenant_id', 'user_id'], unique=False, schema='public')
    op.create_index('ix_jobs_tenant_id', 'jobs', ['tenant_id'], unique=False, schema='public')
    op.create_index('ix_jobs_created_at', 'jobs', ['created_at'], unique=False, schema='public')
    op.create_index('ix_jobs_is_open', 'jobs', ['is_open'], unique=False, schema='public')
    op.create_index('ix_jobs_source', 'jobs', ['source'], unique=False, schema='public')
    op.create_index('ix_jobs_status', 'jobs', ['status'], unique=False, schema='public')
    op.create_index('ix_jobs_user_applied', 'jobs', ['user_id', 'applied'], unique=False, schema='public')
    op.create_index('ix_jobs_user_status', 'jobs', ['user_id', 'status'], unique=False, schema='public')
    op.create_index('ix_jobs_dedup_key', 'jobs', ['dedup_key'], unique=False, schema='public')

    op.create_table(
        'kv_store',
        sa.Column('key', sa.String(), primary_key=True, nullable=False),
        sa.Column('value', sa.Text(), nullable=False),
        sa.Column('updated_at', sa.String(), nullable=False),
        schema='public',
    )

    op.create_table(
        'master_profiles',
        sa.Column('user_id', sa.String(), primary_key=True, nullable=False),
        sa.Column('onboarding_status', sa.String(), nullable=False),
        sa.Column('master_profile', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('created_at', sa.String(), nullable=True),
        sa.Column('updated_at', sa.String(), nullable=True),
        sa.Column('is_admin', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('email', sa.Text(), nullable=True),
        sa.Column('tenant_id', sa.Text(), nullable=True),
        schema='public',
    )
    op.create_index('ix_master_profiles_tenant_id', 'master_profiles', ['tenant_id'], unique=False, schema='public')
    op.create_index('ix_master_profiles_email', 'master_profiles', ['email'], unique=False, schema='public')

    op.create_table(
        'match_triggers',
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False, autoincrement=True),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('job_id', sa.String(), nullable=False),
        sa.Column('score', sa.Float(), nullable=False),
        sa.Column('threshold', sa.Float(), nullable=False),
        sa.Column('payload_json', sa.Text(), nullable=False),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('created_at', sa.String(), nullable=False),
        sa.Column('consumed_at', sa.String(), nullable=True),
        sa.Column('tenant_id', sa.Text(), nullable=True),
        schema='public',
    )
    op.create_index('ix_match_triggers_tenant_id', 'match_triggers', ['tenant_id'], unique=False, schema='public')
    op.create_index('ix_match_triggers_status', 'match_triggers', ['status'], unique=False, schema='public')
    op.create_index('ix_match_triggers_user_id', 'match_triggers', ['user_id'], unique=False, schema='public')
    op.create_index('uq_match_triggers_user_job', 'match_triggers', ['user_id', 'job_id'], unique=True, schema='public')

    op.create_table(
        'profile_interviews',
        sa.Column('session_id', sa.String(), primary_key=True, nullable=False),
        sa.Column('messages', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('draft_profile', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('confidence_map', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('pending_probes', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('document_refs', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('created_at', sa.String(), nullable=True),
        sa.Column('updated_at', sa.String(), nullable=True),
        sa.Column('user_id', sa.Text(), server_default=sa.text("'default'"), nullable=False),
        sa.Column('intent', sa.Text(), nullable=True),
        sa.Column('tenant_id', sa.Text(), nullable=True),
        schema='public',
    )
    op.create_index('ix_profile_interviews_tenant_id', 'profile_interviews', ['tenant_id'], unique=False, schema='public')
    op.create_index('ix_profile_interviews_user_id', 'profile_interviews', ['user_id'], unique=False, schema='public')

    op.create_table(
        'recruiter_reply_drafts',
        sa.Column('draft_id', sa.String(), primary_key=True, nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('job_id', sa.String(), nullable=False),
        sa.Column('email_excerpt', sa.Text(), nullable=False),
        sa.Column('draft_text', sa.Text(), nullable=False),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('created_at', sa.String(), nullable=False),
        sa.Column('tenant_id', sa.Text(), nullable=True),
        schema='public',
    )
    op.create_index('ix_recruiter_reply_drafts_tenant_id', 'recruiter_reply_drafts', ['tenant_id'], unique=False, schema='public')
    op.create_index('ix_recruiter_reply_drafts_user_id', 'recruiter_reply_drafts', ['user_id'], unique=False, schema='public')
    op.create_index('ix_recruiter_reply_drafts_job_id', 'recruiter_reply_drafts', ['job_id'], unique=False, schema='public')

    op.create_table(
        'shadow_match_scores',
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False, autoincrement=True),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('job_title', sa.String(), nullable=True),
        sa.Column('company', sa.String(), nullable=True),
        sa.Column('existing_score', sa.Float(), nullable=False),
        sa.Column('ats_score', sa.Float(), nullable=False),
        sa.Column('breakdown_json', sa.Text(), nullable=False),
        sa.Column('created_at', sa.String(), nullable=False),
        sa.Column('tenant_id', sa.Text(), nullable=True),
        schema='public',
    )
    op.create_index('ix_shadow_match_scores_tenant_id', 'shadow_match_scores', ['tenant_id'], unique=False, schema='public')
    op.create_index('ix_shadow_match_scores_user_id', 'shadow_match_scores', ['user_id'], unique=False, schema='public')


def downgrade() -> None:
    op.drop_table('shadow_match_scores', schema='public')
    op.drop_table('recruiter_reply_drafts', schema='public')
    op.drop_table('profile_interviews', schema='public')
    op.drop_table('match_triggers', schema='public')
    op.drop_table('master_profiles', schema='public')
    op.drop_table('kv_store', schema='public')
    op.drop_table('jobs', schema='public')
    op.drop_table('job_feedback', schema='public')
    op.drop_table('company_intel', schema='public')
    op.drop_table('company_culture', schema='public')
    op.drop_table('chat_sessions', schema='public')
    op.drop_table('applications', schema='public')
    op.drop_table('confidence_audit_log', schema='public')
    op.drop_table('ariel_probe_log', schema='public')
    op.drop_table('ariel_gap_queue', schema='public')
    op.drop_table('evidence_records_old', schema='public')
    op.drop_table('evidence_records', schema='public')
    op.drop_table('conversation_events', schema='public')
    op.drop_table('ariel_sessions', schema='public')
    op.drop_table('profile_entities', schema='public')

