"""ui_locale: NULL means "never chosen", not English

Revision ID: 7d3e1a9b4c62
Revises: c5a91b3e7d02
Create Date: 2026-10-17

Why
---
c5a91b3e7d02 added user_preferences.ui_locale as NOT NULL DEFAULT 'en'. The
frontend (I18nContext) was written on the opposite assumption: it adopts the
stored value on login only when there is one, so that a visitor who chose
Hebrew on the landing page keeps Hebrew until they choose otherwise. With a
column that can never be NULL, every account "had chosen" English — the
moment a Hebrew-speaking user signed in, the UI flipped back to English and
stayed there. Testers reported exactly that ("switching to Hebrew doesn't
switch everything").

What
----
- ui_locale becomes nullable with no default; NULL = not chosen.
- Existing 'en' values are cleared to NULL. They cannot be told apart from
  the default, and clearing is harmless: a user who really prefers English
  keeps it through their browser cookie, and the next explicit switch
  stores it again.
- cv_locale is untouched: English is a real default for the generated CV.
"""
from alembic import op
import sqlalchemy as sa

revision = '7d3e1a9b4c62'
down_revision = 'c5a91b3e7d02'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column('user_preferences', 'ui_locale', schema='public',
                    existing_type=sa.Text(), nullable=True, server_default=None)
    op.execute("UPDATE public.user_preferences SET ui_locale = NULL WHERE ui_locale = 'en'")


def downgrade() -> None:
    op.execute("UPDATE public.user_preferences SET ui_locale = 'en' WHERE ui_locale IS NULL")
    op.alter_column('user_preferences', 'ui_locale', schema='public',
                    existing_type=sa.Text(), nullable=False, server_default=sa.text("'en'"))
