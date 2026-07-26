"""create canonical public.all_jobs table

Revision ID: 9f25d77ed964
Revises: 413f4ed8fbc6
Create Date: 2026-07-26 17:10:00.000000

Canonical, provider-agnostic jobs table. First populated from the LinkedIn
guest-scraper (backend/scripts/linkedin_israel_jobs.py), designed to hold
other providers later via the `source` column — this is deliberately NOT
the same table as `linkedin.jobs` (backend/models/linkedin_job.py), which
stores LinkedIn's raw scraped shape verbatim; `all_jobs` is the normalized,
cross-provider layer above it.

No CSV file exists on disk in this environment yet (the scraper has never
been run to completion here) — the column set below is derived from the
scraper's own `JobListing` dataclass and `save_to_csv()` in
backend/scripts/linkedin_israel_jobs.py, which is the exact, deterministic
source of the CSV's headers (`csv.DictWriter(fieldnames=list(asdict(job).keys()))`),
not a guess.

CSV header -> column mapping
-----------------------------
  title              -> job_title
  company            -> company_name
  location           -> location              (freeform string, e.g. "Haifa,
                                                 Haifa District, Israel" — no
                                                 city/region/country split;
                                                 see "Deliberately omitted")
  posted_text        -> posted_text            (raw relative text, e.g.
                                                 "2 hours ago" — LinkedIn's
                                                 guest API never exposes an
                                                 absolute timestamp)
  job_url            -> job_url
  company_url        -> company_url
  description        -> description
  exact_posted_text  -> exact_posted_text
  applicants_text    -> applicants_text        (kept as TEXT, not INTEGER —
                                                 LinkedIn censors this to a
                                                 string like "< 25"; see
                                                 "Deliberately omitted")
  seniority_level    -> seniority_level
  employment_type    -> employment_type
  job_function       -> job_function
  industries         -> industries (TEXT[])    (comma-split list — see
                                                 "Deliberately omitted" for
                                                 why this is plural, not the
                                                 suggested singular `industry`)
  company_logo_url   -> company_logo_url

  (derived, not a CSV column) -> normalized_job_url, via the already-tested
  normalize_url() in backend/services/linkedin_job_normalize.py — reused at
  ingestion time, not reimplemented here.

Deliberately omitted from the "suggested job fields" list (not present in,
or not reliably derivable from, the current LinkedIn scraper's output —
adding them now would be inventing data, not preserving it):
  - city / region / country: no geocoding/parsing of the freeform
    `location` string is done anywhere in this codebase today.
  - posted_at / listed_at / expires_at: the source only ever provides
    relative text ("2 hours ago"), never an absolute timestamp; parsing
    relative English/Hebrew time phrases into a timestamp is nontrivial and
    not implemented anywhere in this repo — kept as raw text instead
    (posted_text / exact_posted_text).
  - applicant_count (integer): applicants_text can be the literal string
    "< 25" (LinkedIn's own privacy censoring, see clean_applicants() in the
    scraper) — not a value that can be cast to an integer without lying
    about precision.
  - industry (singular): the source is a comma-split LIST of industries;
    forcing it into one column would silently drop data, so this table
    uses `industries text[]` instead.
  - workplace_type, easy_apply, salary_min/max/currency/period,
    description_html: no field in JobListing maps to any of these for the
    LinkedIn guest scraper. Left off entirely rather than pre-created as
    permanently-NULL speculative columns; a future provider that actually
    supplies this data can add the column additively then.

Job identity / dedup
----------------------
`canonical_job_key` is computed at ingestion time (not by this migration,
matching the existing repo convention of Python-side normalization in
backend/services/linkedin_job_normalize.py — no DB trigger/generated
column): the extracted LinkedIn numeric job ID (-> source_job_id) when
extract_linkedin_job_id() succeeds, else the normalized_job_url — the same
two-tier fallback backend/models/linkedin_job.py already uses, just
expressed as one column + one UNIQUE(source, canonical_job_key) constraint
here instead of two partial unique indexes, per this table's own spec.

Indexes
---------
`source`, `is_active`, `last_seen_at DESC`, `company_name` (+ a
case-insensitive `lower(company_name)` expression index), `job_title` (+
`lower(job_title)`), `location`, and `job_url` (lookups by raw URL). No
`posted_at DESC` index — that column doesn't exist here (see above).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = '9f25d77ed964'
down_revision: Union[str, None] = '413f4ed8fbc6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'all_jobs',
        # ── Required system columns (exact spec) ────────────────────────
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                   server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('source', sa.Text(), server_default=sa.text("'linkedin'"), nullable=False),
        sa.Column('source_job_id', sa.Text(), nullable=True),
        sa.Column('canonical_job_key', sa.Text(), nullable=False),
        sa.Column('first_seen_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('last_seen_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('insertion_time', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('last_scraped_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=True),
        sa.Column('closed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('raw_payload', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        # ── CSV-derived job fields (see module docstring for the mapping) ──
        sa.Column('job_title', sa.Text(), nullable=True),
        sa.Column('company_name', sa.Text(), nullable=True),
        sa.Column('company_url', sa.Text(), nullable=True),
        sa.Column('company_logo_url', sa.Text(), nullable=True),
        sa.Column('job_url', sa.Text(), nullable=False),
        sa.Column('normalized_job_url', sa.Text(), nullable=False),
        sa.Column('location', sa.Text(), nullable=True),
        sa.Column('seniority_level', sa.Text(), nullable=True),
        sa.Column('employment_type', sa.Text(), nullable=True),
        sa.Column('job_function', sa.Text(), nullable=True),
        sa.Column('industries', postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('posted_text', sa.Text(), nullable=True),
        sa.Column('exact_posted_text', sa.Text(), nullable=True),
        sa.Column('applicants_text', sa.Text(), nullable=True),
        sa.UniqueConstraint('source', 'canonical_job_key', name='uq_all_jobs_source_canonical_job_key'),
        schema='public',
    )

    op.create_index('ix_all_jobs_source', 'all_jobs', ['source'], unique=False, schema='public')
    op.create_index('ix_all_jobs_is_active', 'all_jobs', ['is_active'], unique=False, schema='public')
    op.create_index('ix_all_jobs_last_seen_at_desc', 'all_jobs', [sa.text('last_seen_at DESC')],
                     unique=False, schema='public')
    op.create_index('ix_all_jobs_company_name', 'all_jobs', ['company_name'], unique=False, schema='public')
    op.create_index('ix_all_jobs_job_title', 'all_jobs', ['job_title'], unique=False, schema='public')
    op.create_index('ix_all_jobs_location', 'all_jobs', ['location'], unique=False, schema='public')
    op.create_index('ix_all_jobs_job_url', 'all_jobs', ['job_url'], unique=False, schema='public')

    # Case-insensitive lookups — plain lower() expression indexes rather than
    # the citext extension, to avoid taking on an extension dependency for
    # two columns.
    op.execute(
        "CREATE INDEX ix_all_jobs_company_name_lower ON public.all_jobs (lower(company_name))"
    )
    op.execute(
        "CREATE INDEX ix_all_jobs_job_title_lower ON public.all_jobs (lower(job_title))"
    )


def downgrade() -> None:
    op.drop_index('ix_all_jobs_job_title_lower', table_name='all_jobs', schema='public')
    op.drop_index('ix_all_jobs_company_name_lower', table_name='all_jobs', schema='public')
    op.drop_index('ix_all_jobs_job_url', table_name='all_jobs', schema='public')
    op.drop_index('ix_all_jobs_location', table_name='all_jobs', schema='public')
    op.drop_index('ix_all_jobs_job_title', table_name='all_jobs', schema='public')
    op.drop_index('ix_all_jobs_company_name', table_name='all_jobs', schema='public')
    op.drop_index('ix_all_jobs_last_seen_at_desc', table_name='all_jobs', schema='public')
    op.drop_index('ix_all_jobs_is_active', table_name='all_jobs', schema='public')
    op.drop_index('ix_all_jobs_source', table_name='all_jobs', schema='public')
    op.drop_table('all_jobs', schema='public')
