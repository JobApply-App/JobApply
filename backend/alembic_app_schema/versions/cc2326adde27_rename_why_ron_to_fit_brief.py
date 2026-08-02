"""rename user_job_matches.why_ron -> fit_brief (neutral, multi-user naming)

Revision ID: cc2326adde27
Revises: 00eab53e0f00
Create Date: 2026-08-02 17:20:00.000000

Step 2 of docs/db-architecture-spec.md — principle 5, "no column, script or
constant names a specific person; the system serves whoever signs up".

The column holds an LLM-written brief explaining why a given posting fits a
given candidate. It is per-(user, posting) by construction — living on
user_job_matches — so a name bound to one person was always a
single-tenant artifact.

`fit_brief` was chosen over `why_candidate` because agents/tailor.py already
labels this exact value `WHY_CANDIDATE:` inside its prompt; reusing that
string as the column name would make grep results ambiguous between the
schema and the prompt template.

Scope note: this rename is NOT backend-internal. `why_ron` is a field on the
JobMatch Pydantic schema, which is the response_model of five routes
(/feed, /{job_id}, /analyze, /analyze-job, and the jobs list), so the JSON
key visible to clients changes too, and the frontend reads it in 8 files.
Backend and frontend therefore have to ship together — a split deploy would
blank the AI-analysis box on every job card.
"""
from typing import Sequence, Union

from alembic import op


revision: str = 'cc2326adde27'
down_revision: Union[str, None] = '00eab53e0f00'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "user_job_matches", "why_ron",
        new_column_name="fit_brief",
        schema="public",
    )


def downgrade() -> None:
    op.alter_column(
        "user_job_matches", "fit_brief",
        new_column_name="why_ron",
        schema="public",
    )
