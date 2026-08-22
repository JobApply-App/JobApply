"""add chat_messages_log table — backs the daily per-user Ariel message cap

Revision ID: 30cb3de92412
Revises: d2f7a4c891e3
Create Date: 2026-08-21 00:00:00.000000

One row per accepted user turn on POST /chat/stream or POST /chat/ariel/private
(both are the "Ariel" persona from the user's point of view, both bill
claude-sonnet-4-6). backend/api/deps.py's daily_chat_limit() counts today's
rows for the calling user and rejects once the configured cap is reached.

Same DB-backed-not-in-memory reasoning as d2f7a4c891e3 (cv_generations):
Render free-tier sleep/wake would silently reset an in-memory daily counter
for free multiple times a day.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '30cb3de92412'
down_revision: Union[str, None] = 'd2f7a4c891e3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'chat_messages_log',
        sa.Column('id', sa.String(), nullable=False),
        # postgresql.UUID, not sa.String — see d2f7a4c891e3's comment: an FK's
        # two sides must be the same physical type or Postgres refuses the
        # constraint (profiles.id is a real Postgres uuid column).
        sa.Column('user_id', postgresql.UUID(), nullable=False),
        sa.Column('endpoint', sa.String(), nullable=False),
        sa.Column('created_at', sa.String(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['user_id'], ['profiles.id'],
                                 name='fk_chat_messages_log_user_id_profiles', ondelete='CASCADE'),
        schema='public',
    )
    op.create_index('ix_chat_messages_log_user_created', 'chat_messages_log',
                     ['user_id', 'created_at'], schema='public')

    op.execute("ALTER TABLE public.chat_messages_log ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE public.chat_messages_log FORCE ROW LEVEL SECURITY")
    # user_id is a real uuid column — compare directly against auth.uid()'s
    # own uuid return type, no ::text cast (see d2f7a4c891e3's history of
    # getting this wrong on the first pass).
    op.execute("""
        CREATE POLICY chat_messages_log_owner_select ON public.chat_messages_log
            FOR SELECT USING (user_id = auth.uid())
    """)
    op.execute("""
        CREATE POLICY chat_messages_log_owner_write ON public.chat_messages_log
            FOR ALL USING (user_id = auth.uid()) WITH CHECK (user_id = auth.uid())
    """)


def downgrade() -> None:
    op.drop_index('ix_chat_messages_log_user_created', table_name='chat_messages_log', schema='public')
    op.drop_table('chat_messages_log', schema='public')
