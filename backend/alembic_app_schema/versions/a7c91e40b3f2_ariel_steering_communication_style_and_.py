"""ariel steering: communication_style preference + provenance CHECK constraints

Revision ID: a7c91e40b3f2
Revises: 90b20294d1d3
Create Date: 2026-08-13 00:00:00.000000

Two independent pieces, both prerequisites for the Ariel Steering Agent.

1. user_preferences.communication_style (JSONB)
   -------------------------------------------
   How the user wants Ariel to talk to them, as opposed to what they want to
   hear about (the rest of this table). Shape:

     {"mode": "one_by_one" | "batch",
      "tone": "<free text>",
      "responsiveness": "<free text>"}

   Lives on user_preferences rather than profiles because it is a stated
   preference the user can change at will, not an identity fact — same
   category as work_type/target_titles, and it inherits that table's
   ON DELETE CASCADE + RLS owner policy for free.

   NAMING COLLISION — deliberate, and worth knowing about:
   master_profile_service already produces a `communication_style` STRING
   inside the LLM-derived `user_persona` blob ("direct/narrative,
   data-first/story-first"). That is an *observation about the candidate*
   used to flavour generated CV prose. This column is a *directive from the
   user* about Ariel's turn-taking. They are different things with the same
   name; neither reads the other. Renaming the older one is out of scope
   here (it is embedded in a stored LLM prompt contract), so the two are
   kept apart by location: persona blob vs. this typed column.

   Server default '{}'::jsonb rather than NULL: every reader wants "no
   preference stated" to be an empty mapping it can .get() against, and
   ariel_steering_service normalises unknown/missing keys to documented
   defaults anyway. A NULL would force a null-check at every call site for
   no gain.

2. profile_entities.origin / verification_status CHECK constraints
   ---------------------------------------------------------------
   Both columns have carried documented enums since they were introduced
   (see backend/models/profile.py) but neither was ever constrained at the
   DB level, so a typo'd write ('cv-parse', 'Verified') would persist
   silently and then simply never match any consumer's equality test.

   The allowed sets below are the documented enums UNIONED with every value
   actually present in the live table — checked before writing this
   migration, since a CHECK that excludes existing data fails at ALTER time:

     origin              self_assertion (111), cv_parse (35)
                         + conversation, inferred (documented, never yet written)
     verification_status unverified (142), partial (8), needs_evidence (10),
                         verified (3)

   `verified` is the value Ariel's steering logic gates the tailored CV on
   (an inferred capability must not reach a CV until evidence upgrades it),
   which is exactly why it is worth making unspellable-by-accident.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'a7c91e40b3f2'
down_revision = '90b20294d1d3'
branch_labels = None
depends_on = None


_ORIGINS = ('cv_parse', 'self_assertion', 'conversation', 'inferred')
_VERIFICATION_STATUSES = ('unverified', 'needs_evidence', 'partial', 'verified')


def _in_list(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade() -> None:
    # ── 1. communication_style ────────────────────────────────────────────────
    op.add_column(
        'user_preferences',
        sa.Column(
            'communication_style',
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        schema='public',
    )

    # ── 2. provenance CHECK constraints ───────────────────────────────────────
    # Defensive normalisation first: any row outside the allowed set would
    # abort the ALTER. Nothing matched these at the time of writing (verified
    # against live Dev), so in practice these are no-ops that make the
    # migration safe to run against an environment that has since drifted.
    op.execute(f"""
        UPDATE public.profile_entities
        SET origin = 'self_assertion'
        WHERE origin IS NULL OR origin NOT IN ({_in_list(_ORIGINS)})
    """)
    op.execute(f"""
        UPDATE public.profile_entities
        SET verification_status = 'unverified'
        WHERE verification_status IS NULL
           OR verification_status NOT IN ({_in_list(_VERIFICATION_STATUSES)})
    """)

    op.create_check_constraint(
        'ck_profile_entities_origin',
        'profile_entities',
        f"origin IN ({_in_list(_ORIGINS)})",
        schema='public',
    )
    op.create_check_constraint(
        'ck_profile_entities_verification_status',
        'profile_entities',
        f"verification_status IN ({_in_list(_VERIFICATION_STATUSES)})",
        schema='public',
    )


def downgrade() -> None:
    op.drop_constraint('ck_profile_entities_verification_status', 'profile_entities',
                       schema='public', type_='check')
    op.drop_constraint('ck_profile_entities_origin', 'profile_entities',
                       schema='public', type_='check')
    op.drop_column('user_preferences', 'communication_style', schema='public')
