"""re-parse all_jobs.industries with the atomic-phrase fix

Revision ID: 514248e8d2cb
Revises: 96cc8a4cc78c
Create Date: 2026-07-27 11:00:00.000000

backend/services/linkedin_job_normalize.py's normalize_list_field() now
recognizes known LinkedIn industry taxonomy names that contain their own
internal comma (e.g. "Technology, Information and Internet") before doing
its generic comma-split — see that function's docstring for the full
rationale and the specific evidence (each phrase confirmed to appear as a
job's ENTIRE raw industries string on at least one real row, proving the
comma belongs to the name itself). Previously a string like "Entertainment,
Technology, Information and Media, and Technology, Information and
Internet" (3 real industries) fragmented into 5 nonsense pieces including
"and Technology" and "Information and Internet".

This migration re-derives `industries` for every row from `raw_payload`
(which still holds the untouched original scraped value) using the fixed
function — done in Python via a data migration rather than SQL, since the
sentinel-substitution logic isn't reasonably expressible as a single SQL
expression.
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text
from sqlalchemy.orm import Session

revision: str = '514248e8d2cb'
down_revision: Union[str, None] = '96cc8a4cc78c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    from backend.services.linkedin_job_normalize import normalize_list_field

    bind = op.get_bind()
    session = Session(bind=bind)
    rows = session.execute(text(
        "SELECT id, raw_payload ->> 'industries' AS raw FROM public.all_jobs "
        "WHERE raw_payload ->> 'industries' IS NOT NULL"
    )).all()

    for row in rows:
        new_industries = normalize_list_field(row.raw)
        session.execute(
            text("UPDATE public.all_jobs SET industries = :industries WHERE id = :id"),
            {"industries": new_industries, "id": row.id},
        )
    session.commit()


def downgrade() -> None:
    # Not reversible: the pre-fix split is lossy (it discarded the
    # information needed to tell which pieces were wrongly fragmented),
    # so there's no way to reconstruct the old (broken) array shape.
    pass
