"""language preferences: ui_locale + cv_locale on user_preferences

Revision ID: c5a91b3e7d02
Revises: 30cb3de92412
Create Date: 2026-08-25 00:00:00.000000

Two separate locales, deliberately not one
------------------------------------------
`ui_locale` is the language the product speaks to the user in. `cv_locale`
is the language their generated CV comes out in. They are genuinely
independent choices — browsing the site in Hebrew while applying to
English-speaking companies in English is a normal Israeli job-search
pattern, not an edge case — so collapsing them into a single "language"
column would make that pattern impossible to express.

Both live on user_preferences rather than profiles because they are stated
preferences the user changes at will, not identity facts — the same
category as work_type/target_titles, and they inherit that table's
ON DELETE CASCADE + RLS owner policy for free.

Why the stored data itself stays English-only
---------------------------------------------
Neither column changes what language the DATABASE holds. Profile facts
(skills, employers, achievements) are normalised to English on the way in
by the Ariel/profile ingestion layer, whatever language the user typed
them in. That is what keeps a single canonical row per fact: if Hebrew
input were stored verbatim alongside English input, the same employer
would exist twice under two spellings, and every consumer that matches on
a name — the prior-employer boost in match_score_service, skill
deduplication in profile_entities, the confidence matrix — would silently
see them as two unrelated things.

So `cv_locale` is a RENDER-TIME instruction, not a storage format. A
Hebrew CV is produced by translating the canonical English profile at
generation time; the profile underneath is untouched and stays the single
source of truth.

Defaults
--------
'en' for both, matching the frontend's DEFAULT_LOCALE, so existing rows
get today's behaviour rather than a surprise language switch on deploy.
NOT NULL with a server default means every reader can skip a null-check.

The CHECK constraints list exactly the two locales shipping now. Adding a
third language later is an ALTER of these constraints plus a new frontend
dictionary — the column shape does not change, which is the point of
storing a locale code rather than a boolean.
"""
from alembic import op
import sqlalchemy as sa


revision = 'c5a91b3e7d02'
down_revision = '30cb3de92412'
branch_labels = None
depends_on = None

_SUPPORTED_LOCALES = ("en", "he")


def _locale_check(column: str) -> str:
    values = ", ".join(f"'{loc}'" for loc in _SUPPORTED_LOCALES)
    return f"{column} IN ({values})"


def upgrade() -> None:
    op.add_column(
        'user_preferences',
        sa.Column('ui_locale', sa.Text(), server_default=sa.text("'en'"), nullable=False),
        schema='public',
    )
    op.add_column(
        'user_preferences',
        sa.Column('cv_locale', sa.Text(), server_default=sa.text("'en'"), nullable=False),
        schema='public',
    )
    op.create_check_constraint(
        'ck_user_preferences_ui_locale',
        'user_preferences',
        _locale_check('ui_locale'),
        schema='public',
    )
    op.create_check_constraint(
        'ck_user_preferences_cv_locale',
        'user_preferences',
        _locale_check('cv_locale'),
        schema='public',
    )


def downgrade() -> None:
    op.drop_constraint(
        'ck_user_preferences_cv_locale', 'user_preferences',
        type_='check', schema='public',
    )
    op.drop_constraint(
        'ck_user_preferences_ui_locale', 'user_preferences',
        type_='check', schema='public',
    )
    op.drop_column('user_preferences', 'cv_locale', schema='public')
    op.drop_column('user_preferences', 'ui_locale', schema='public')
