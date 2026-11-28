"""add llm_usage — one row per successful AI call

Revision ID: a3e7c1f9d2b4
Revises: c7a4e2d9f1b3
Create Date: 2026-11-28 00:00:00.000000

Until now the only cost record was a stdout line per call, so there was no
daily total anywhere (docs/research/09-companies-and-costs.md, decision 1).
Written by backend/services/llm_client.py; summed by the daily per-user spend
ceiling in backend/api/deps.py. Metadata only, never prompt or response text.

RLS on with no policy: only the backend reads or writes this table, so the
public API roles see nothing.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a3e7c1f9d2b4'
down_revision: Union[str, None] = 'c7a4e2d9f1b3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'llm_usage',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('created_at', sa.String(), nullable=False),
        sa.Column('purpose', sa.String(), nullable=False),
        sa.Column('provider', sa.String(), nullable=False),
        sa.Column('model', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=True),
        sa.Column('job_id', sa.String(), nullable=True),
        sa.Column('input_tokens', sa.Integer(), nullable=True),
        sa.Column('output_tokens', sa.Integer(), nullable=True),
        sa.Column('cache_read_tokens', sa.Integer(), nullable=True),
        sa.Column('cache_write_tokens', sa.Integer(), nullable=True),
        sa.Column('latency_ms', sa.Integer(), nullable=True),
        sa.Column('cost_usd', sa.Float(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        schema='public',
    )
    op.create_index('ix_llm_usage_user_created', 'llm_usage', ['user_id', 'created_at'], schema='public')
    op.create_index('ix_llm_usage_created', 'llm_usage', ['created_at'], schema='public')
    op.execute("ALTER TABLE public.llm_usage ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE public.llm_usage FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_index('ix_llm_usage_created', table_name='llm_usage', schema='public')
    op.drop_index('ix_llm_usage_user_created', table_name='llm_usage', schema='public')
    op.drop_table('llm_usage', schema='public')
