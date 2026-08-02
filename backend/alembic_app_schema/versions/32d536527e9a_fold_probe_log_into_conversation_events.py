"""fold ariel_probe_log into conversation_events

Revision ID: 32d536527e9a
Revises: 3542b0021d6b
Create Date: 2026-08-03 00:25:00.000000

Step 5 of docs/db-architecture-spec.md, in the reduced scope the evidence
supports.

SCOPE CORRECTION vs the spec as written
---------------------------------------
The spec called for unifying chat_sessions + ariel_sessions +
profile_interviews into one `conversations` table with a `kind`
discriminator, plus folding ariel_probe_log into conversation_events. Only
the second half survives scrutiny.

The three session tables are three different PROCESSES that happen to store
messages, not three copies of one thing:

  chat_sessions       open-ended. No status, no ended_at — a conversation that
                      never terminates. 0 dedicated columns.
  ariel_sessions      goal-directed: session_type, ariel_goal, target_job_id,
                      target_entities, confidence_delta_total, ended_at.
                      5 dedicated columns and a real terminal state.
  profile_interviews  an extraction state machine: draft_profile,
                      confidence_map, pending_probes, document_refs, intent.
                      5 dedicated columns that converge over the session.

They also share no consumer — chat_sessions is read by history.py and the
persona extractor, ariel_sessions by ariel.py and profile_update_service,
profile_interviews by its own repository — and nothing anywhere asks for a
combined view. Merging them yields a ~16-column table where every row leaves
at least 5 columns NULL, which contradicts the spec's own guard that a kind
needing more than 4 dedicated columns earns a satellite table rather than
bloating the shared one. Two of the three already need 5.

ariel_probe_log is a different case and does merge. It and
conversation_events are both event-level records inside one ariel_session:
both FK to ariel_sessions(session_id) and profiles(user_id), both feed the
Confidence Matrix, and both are empty. The probe kind needs exactly two
dedicated columns (probe_outcome, entity_id), well inside the guard.

Preserving the cooldown path
----------------------------
ariel_probe_log's index (user_id, entity_id, probed_at DESC) backs the
"don't re-probe an entity within PROBE_COOLDOWN_H" LEFT JOIN in
ariel_probe_service._select_probe_targets. The partial index created below
keeps that lookup on the same shape — user_id, entity_id, analyzed_at over
probe rows only — so the cooldown query costs what it did before.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '32d536527e9a'
down_revision: Union[str, None] = '3542b0021d6b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('conversation_events',
                  sa.Column('event_kind', sa.Text(), nullable=False, server_default='star_extraction'),
                  schema='public')
    op.add_column('conversation_events', sa.Column('probe_outcome', sa.Text(), nullable=True), schema='public')
    # Single entity for a probe. star_extraction rows keep using
    # extracted_entity_ids, which is a list and cannot carry a FK.
    op.add_column('conversation_events', sa.Column('entity_id', sa.Text(), nullable=True), schema='public')

    # extracted_entity_ids and extraction_confidence were NOT NULL because
    # every row used to be a STAR extraction. A probe row has neither, so they
    # become kind-specific and nullable — with the CHECK below taking over the
    # integrity they used to provide.
    op.alter_column('conversation_events', 'extracted_entity_ids',
                    existing_type=sa.Text(), nullable=True, schema='public')
    op.alter_column('conversation_events', 'extraction_confidence',
                    existing_type=sa.Float(), nullable=True, schema='public')

    op.create_foreign_key(
        'fk_conversation_events_entity_id_profile_entities',
        'conversation_events', 'profile_entities', ['entity_id'], ['entity_id'],
        source_schema='public', referent_schema='public',
    )
    # The discriminator carries its own integrity: relaxing two NOT NULLs to
    # add a second kind would otherwise let a malformed STAR row through.
    op.create_check_constraint(
        'ck_conversation_events_event_kind', 'conversation_events',
        """
        (event_kind = 'star_extraction'
             AND extracted_entity_ids IS NOT NULL
             AND extraction_confidence IS NOT NULL)
        OR
        (event_kind = 'probe'
             AND entity_id IS NOT NULL)
        """,
        schema='public',
    )
    # Mirrors idx_apl_user_entity — the cooldown lookup's access path.
    op.create_index('ix_ce_probe_cooldown', 'conversation_events',
                    ['user_id', 'entity_id', 'analyzed_at'],
                    schema='public', postgresql_where=sa.text("event_kind = 'probe'"))

    op.execute("""
        INSERT INTO public.conversation_events
            (event_id, session_id, user_id, event_kind, entity_id, probe_outcome, analyzed_at)
        SELECT probe_id, session_id, user_id, 'probe', entity_id, outcome, probed_at
        FROM public.ariel_probe_log
    """)

    op.drop_table('ariel_probe_log', schema='public')


def downgrade() -> None:
    op.create_table(
        'ariel_probe_log',
        sa.Column('probe_id', sa.Text(), primary_key=True),
        sa.Column('user_id', sa.dialects.postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column('entity_id', sa.Text(), nullable=False),
        sa.Column('session_id', sa.Text(), nullable=True),
        sa.Column('outcome', sa.Text(), nullable=False),
        sa.Column('probed_at', sa.Text(), nullable=False),
        schema='public',
    )
    op.create_index('idx_apl_user_entity', 'ariel_probe_log',
                    ['user_id', 'entity_id', 'probed_at'], schema='public')
    op.create_foreign_key('fk_ariel_probe_log_session_id_ariel_sessions', 'ariel_probe_log',
                          'ariel_sessions', ['session_id'], ['session_id'],
                          source_schema='public', referent_schema='public')
    op.create_foreign_key('fk_ariel_probe_log_entity_id_profile_entities', 'ariel_probe_log',
                          'profile_entities', ['entity_id'], ['entity_id'],
                          source_schema='public', referent_schema='public')
    op.create_foreign_key('fk_ariel_probe_log_user_id_profiles', 'ariel_probe_log', 'profiles',
                          ['user_id'], ['id'], source_schema='public', referent_schema='public',
                          ondelete='CASCADE')

    op.execute("""
        INSERT INTO public.ariel_probe_log (probe_id, user_id, entity_id, session_id, outcome, probed_at)
        SELECT event_id, user_id, entity_id, session_id, probe_outcome, analyzed_at
        FROM public.conversation_events WHERE event_kind = 'probe'
    """)
    op.execute("DELETE FROM public.conversation_events WHERE event_kind = 'probe'")

    op.drop_index('ix_ce_probe_cooldown', table_name='conversation_events', schema='public')
    op.drop_constraint('ck_conversation_events_event_kind', 'conversation_events',
                       schema='public', type_='check')
    op.alter_column('conversation_events', 'extraction_confidence',
                    existing_type=sa.Float(), nullable=False, schema='public')
    op.alter_column('conversation_events', 'extracted_entity_ids',
                    existing_type=sa.Text(), nullable=False, schema='public')
    op.drop_constraint('fk_conversation_events_entity_id_profile_entities', 'conversation_events',
                       schema='public', type_='foreignkey')
    op.drop_column('conversation_events', 'entity_id', schema='public')
    op.drop_column('conversation_events', 'probe_outcome', schema='public')
    op.drop_column('conversation_events', 'event_kind', schema='public')
