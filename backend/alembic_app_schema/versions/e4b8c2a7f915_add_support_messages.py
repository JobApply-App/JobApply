"""add support_messages table — Eliya's saved support conversations

Revision ID: e4b8c2a7f915
Revises: 7d3e1a9b4c62
Create Date: 2026-10-31 00:00:00.000000

One row per message in a conversation with Eliya, the support assistant.
Keyed by the browser's anonymous session_id; user_id is filled in once the
visitor signs in, so a signed-in user's conversation continues on any device.
Kept 90 days (support_message_repository.purge_expired).
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'e4b8c2a7f915'
down_revision: Union[str, None] = '7d3e1a9b4c62'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'support_messages',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('session_id', sa.String(), nullable=False),
        # postgresql.UUID to match profiles.id (see 30cb3de92412).
        sa.Column('user_id', postgresql.UUID(), nullable=True),
        sa.Column('role', sa.String(), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('created_at', sa.String(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['user_id'], ['profiles.id'],
                                 name='fk_support_messages_user_id_profiles', ondelete='CASCADE'),
        schema='public',
    )
    op.create_index('ix_support_messages_session_created', 'support_messages',
                     ['session_id', 'created_at'], schema='public')
    op.create_index('ix_support_messages_user_created', 'support_messages',
                     ['user_id', 'created_at'], schema='public')

    # Only the backend reads and writes this table; anonymous rows have no
    # auth.uid() to match, so the owner policy covers signed-in rows only.
    op.execute("ALTER TABLE public.support_messages ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE public.support_messages FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY support_messages_owner_select ON public.support_messages
            FOR SELECT USING (user_id = auth.uid())
    """)


def downgrade() -> None:
    op.drop_index('ix_support_messages_user_created', table_name='support_messages', schema='public')
    op.drop_index('ix_support_messages_session_created', table_name='support_messages', schema='public')
    op.drop_table('support_messages', schema='public')
