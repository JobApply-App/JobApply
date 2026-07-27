"""re-parse all_jobs.industries/job_function with the known-and-pairs fallback

Revision ID: ef1e2163ea27
Revises: 1b767d46e559
Create Date: 2026-07-27 12:00:00.000000

backend/services/linkedin_job_normalize.py's normalize_list_field() now
resolves the remaining "bare 'A and B', zero comma" case for both columns
— confirmed directly on linkedin.com that a job's "Job function" line can
render an exactly-2-item list as a plain "Information Technology and
Engineering" with no Oxford comma (the same convention already reverse-
engineered for 3+-item lists elsewhere). _split_known_and_pairs() only
splits when BOTH halves are independently confirmed elsewhere in
production data (_JOB_FUNCTION_KNOWN_TERMS / _INDUSTRY_KNOWN_TERMS) — e.g.
"Management and Manufacturing" -> ["Management", "Manufacturing"], while
genuine atomic names like "Oil and Gas" or "IT Services and IT Consulting"
are left untouched since neither half is independently confirmed.

Same technique as 514248e8d2cb/1b767d46e559: re-derive both columns from
`raw_payload` (untouched original scraped value) via Python, since the
split logic isn't reasonably expressible as a single SQL expression.
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text
from sqlalchemy.orm import Session

revision: str = 'ef1e2163ea27'
down_revision: Union[str, None] = '1b767d46e559'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    from backend.services.linkedin_job_normalize import (
        _INDUSTRY_KNOWN_TERMS,
        _JOB_FUNCTION_KNOWN_TERMS,
        normalize_list_field,
    )

    bind = op.get_bind()
    session = Session(bind=bind)

    for column, known_terms in (
        ("industries", _INDUSTRY_KNOWN_TERMS),
        ("job_function", _JOB_FUNCTION_KNOWN_TERMS),
    ):
        rows = session.execute(text(
            f"SELECT id, raw_payload ->> '{column}' AS raw FROM public.all_jobs "
            f"WHERE raw_payload ->> '{column}' IS NOT NULL"
        )).all()
        for row in rows:
            new_value = normalize_list_field(row.raw, known_terms=known_terms)
            session.execute(
                text(f"UPDATE public.all_jobs SET {column} = :val WHERE id = :id"),
                {"val": new_value, "id": row.id},
            )
    session.commit()


def downgrade() -> None:
    # Not reversible: the "known and pairs" split, once applied, doesn't
    # record which rows were touched or what the exact pre-split value
    # was — same rationale as 514248e8d2cb's downgrade.
    pass
