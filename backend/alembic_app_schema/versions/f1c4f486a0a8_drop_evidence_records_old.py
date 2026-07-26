"""drop evidence_records_old — accidental permanent duplicate of evidence_records

Revision ID: f1c4f486a0a8
Revises: 8726d4a42112
Create Date: 2026-07-26 19:47:00.000000

`evidence_records_old` should never have existed as a standalone Postgres
table. It's an artifact of SQLite's ALTER-TABLE-by-recreate pattern (rename
the live table to `_old`, create the new shape, copy rows across, drop the
`_old` table — see backend/core/migrations.py's migrations 003/004/008,
where this rename/copy/drop happens and finishes within the same SQLite
transaction every time). backend/alembic_app_schema/versions/
413f4ed8fbc6_create_app_tables.py mistakenly translated that transient
intermediate step into a second, permanent CREATE TABLE in Postgres
(lines 128-147) instead of only creating the final `evidence_records`
shape.

Verified before dropping:
  - Zero references to `evidence_records_old` anywhere in
    backend/repositories/*.py, backend/api/routes/*.py, or
    backend/models/*.py (grep, this repo) — nothing reads or writes it.
  - Its 45 rows are test/seed content (e.g. user_id='test_neg_cr_user',
    sample CV-parse entries also present in spirit in the real
    `evidence_records` table), not unique production data.
  - `public.evidence_records` (the correctly-named table) is unaffected —
    only the `_old` duplicate is dropped here.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'f1c4f486a0a8'
down_revision: Union[str, None] = '8726d4a42112'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index('idx_er_entity', table_name='evidence_records_old', schema='public')
    op.drop_index('idx_er_user', table_name='evidence_records_old', schema='public')
    op.drop_table('evidence_records_old', schema='public')


def downgrade() -> None:
    op.create_table(
        'evidence_records_old',
        sa.Column('evidence_id', sa.Text(), nullable=False),
        sa.Column('entity_id', sa.Text(), nullable=False),
        sa.Column('user_id', sa.Text(), nullable=False),
        sa.Column('source_type', sa.Text(), nullable=False),
        sa.Column('base_weight', sa.Float(), nullable=False),
        sa.Column('raw_content', sa.Text(), nullable=True),
        sa.Column('verified_at', sa.Text(), nullable=False),
        sa.Column('hard_expires_at', sa.Text(), nullable=True),
        sa.Column('session_id', sa.Text(), nullable=True),
        sa.Column('event_id', sa.Text(), nullable=True),
        sa.Column('extra_metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('is_ai_assisted', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.PrimaryKeyConstraint('evidence_id'),
        sa.ForeignKeyConstraint(['event_id'], ['conversation_events.event_id'], name='fk_evidence_records_old_event_id_conversation_events'),
        sa.ForeignKeyConstraint(['session_id'], ['ariel_sessions.session_id'], name='fk_evidence_records_old_session_id_ariel_sessions'),
        sa.ForeignKeyConstraint(['entity_id'], ['profile_entities.entity_id'], name='fk_evidence_records_old_entity_id_profile_entities'),
        schema='public',
    )
    op.create_index('idx_er_user', 'evidence_records_old', ['user_id', 'source_type'], unique=False, schema='public')
    op.create_index('idx_er_entity', 'evidence_records_old', ['entity_id', 'verified_at'], unique=False, schema='public')
