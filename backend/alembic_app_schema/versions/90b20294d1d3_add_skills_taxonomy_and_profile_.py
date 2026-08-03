"""add skills taxonomy and profile_entities skill metadata

Revision ID: 90b20294d1d3
Revises: e34f0ea56e30
Create Date: 2026-08-03 18:55:57.640768

Adds a global, cross-tenant `skills_taxonomy` table (canonical_name, category,
synonyms) and links `profile_entities` to it via a new nullable `skill_id` FK,
plus three new per-user metadata columns: `raw_text` (the original extracted
phrase, for auditability — `name` stays as the canonical display form),
`years_of_experience`, `last_used_year`. `proficiency_level` already exists on
`profile_entities` (added earlier for apply_chat_proficiency_update) and is
reused as-is.

Backfill (163 existing profile_entities rows, 121 with entity_type='skill'):
every existing skill row is matched against a small static synonym seed
(_SYNONYM_SEED below) covering common surface-form variants across English
and Hebrew phrasing (e.g. "Management"/"ניהול"/"לנהל"/"Managing" all resolve
to one canonical_name). Anything not in the seed gets a deterministic
fallback: canonical_name = title-cased, whitespace-collapsed `name`,
category = 'Uncategorized'. This is NOT full semantic/LLM-based
canonicalization — that happens at write-time going forward, in
backend/services/skills_taxonomy_service.py, which every new skill write now
goes through. A migration has to be deterministic and reproducible without a
live API key (CI has none — see llm_available in conftest.py), so a static
seed + safe fallback is the right shape here; the taxonomy grows organically
after this from real writes.

No data loss: `name`/`normalized_name`/`entity_type` are untouched. `skill_id`
is nullable (non-skill entity_types — trait/domain/experience — get NULL,
since the taxonomy is skills-specific per the ticket's own framing) and its
FK is ON DELETE SET NULL, matching the existing source_document_id pattern
(fa884910ef1d) rather than cascading a taxonomy edit into entity deletion.

RLS: skills_taxonomy carries no user_id (global reference data, same
category as company_intel/job_postings) — enabled with a read-all policy,
same shape as job_postings_read_all / company_intel_read_all (e34f0ea56e30).
"""
from typing import Sequence, Union
import re

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql import table, column


# revision identifiers, used by Alembic.
revision: str = '90b20294d1d3'
down_revision: Union[str, None] = 'e34f0ea56e30'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ── Static synonym seed ───────────────────────────────────────────────────────
# Maps a lowercase, whitespace-collapsed surface form -> (canonical_name,
# category). Deliberately small and hand-curated rather than exhaustive — this
# is the bootstrap seed; backend/services/skills_taxonomy_service.py is the
# single source of truth going forward and grows this via real writes, not
# migration edits. Mirrors backend/services/skills_taxonomy_service.py's
# _SYNONYM_SEED exactly (duplicated intentionally: a migration must not import
# application code, since app code can change shape/move/be deleted later and
# migrations must keep working against history — see this repo's existing
# convention of self-contained migration files).
_SYNONYM_SEED: dict[str, tuple[str, str]] = {
    "management":  ("Management", "Management"),
    "managing":    ("Management", "Management"),
    "manage":      ("Management", "Management"),
    "ניהול":        ("Management", "Management"),
    "לנהל":         ("Management", "Management"),
    "react":       ("React", "Engineering"),
    "reactjs":     ("React", "Engineering"),
    "react.js":    ("React", "Engineering"),
    "ריאקט":        ("React", "Engineering"),
    "python":      ("Python", "Engineering"),
    "sql":         ("SQL", "Data"),
    "javascript":  ("JavaScript", "Engineering"),
    "js":          ("JavaScript", "Engineering"),
    "machine learning": ("Machine Learning", "Data"),
    "ml":          ("Machine Learning", "Data"),
    "kubernetes":  ("Kubernetes", "Engineering"),
    "k8s":         ("Kubernetes", "Engineering"),
    "excel":       ("Excel", "Data"),
    "figma":       ("Figma", "Product"),
    "jira":        ("Jira", "Product"),
    "scrum":       ("Scrum", "Product"),
    "agile":       ("Agile", "Product"),
    "customer success": ("Customer Success", "Customer Success"),
    "stakeholder management": ("Stakeholder Management", "Management"),
}


def _clean_key(raw: str) -> str:
    """Match backend/services/skills_taxonomy_service.py's _clean_key exactly."""
    return re.sub(r"\s+", " ", (raw or "").strip().lower())


def _fallback_canonical(raw: str) -> str:
    """Title-cased, whitespace-collapsed fallback for anything not in the seed."""
    return re.sub(r"\s+", " ", (raw or "").strip()).title()


def upgrade() -> None:
    # ── skills_taxonomy ───────────────────────────────────────────────────────
    op.create_table(
        'skills_taxonomy',
        sa.Column('id', postgresql.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('canonical_name', sa.Text(), nullable=False),
        sa.Column('category', sa.Text(), server_default=sa.text("'Uncategorized'"), nullable=False),
        sa.Column('synonyms', postgresql.ARRAY(sa.Text()), server_default=sa.text("'{}'"), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('canonical_name', name='uq_skills_taxonomy_canonical_name'),
        schema='public',
    )

    # ── profile_entities: new columns ────────────────────────────────────────
    op.add_column('profile_entities', sa.Column('skill_id', postgresql.UUID(), nullable=True), schema='public')
    op.add_column('profile_entities', sa.Column('raw_text', sa.Text(), nullable=True), schema='public')
    op.add_column('profile_entities', sa.Column('years_of_experience', sa.Numeric(4, 1), nullable=True), schema='public')
    op.add_column('profile_entities', sa.Column('last_used_year', sa.Integer(), nullable=True), schema='public')
    op.create_foreign_key(
        'fk_profile_entities_skill_id', 'profile_entities', 'skills_taxonomy',
        ['skill_id'], ['id'], source_schema='public', referent_schema='public',
        ondelete='SET NULL',
    )
    op.create_index('ix_profile_entities_skill_id', 'profile_entities', ['skill_id'], schema='public')

    # ── RLS: global reference table, read-all (matches company_intel/job_postings) ──
    op.execute("ALTER TABLE public.skills_taxonomy ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE public.skills_taxonomy FORCE ROW LEVEL SECURITY")
    op.execute("CREATE POLICY skills_taxonomy_read_all ON public.skills_taxonomy FOR SELECT USING (true)")

    # ── Backfill: raw_text + skill_id for existing skill entities ────────────
    conn = op.get_bind()

    profile_entities_t = table(
        'profile_entities',
        column('entity_id', sa.String()),
        column('entity_type', sa.String()),
        column('name', sa.String()),
        column('skill_id', postgresql.UUID()),
        column('raw_text', sa.Text()),
    )
    skills_taxonomy_t = table(
        'skills_taxonomy',
        column('id', postgresql.UUID()),
        column('canonical_name', sa.Text()),
        column('category', sa.Text()),
    )

    # raw_text = name for every row, regardless of entity_type — preserves the
    # exact original extracted phrasing for auditability, matching the design
    # doc's requirement, even for entity_types the taxonomy itself doesn't
    # cover (trait/domain/experience keep skill_id = NULL).
    conn.execute(
        profile_entities_t.update().values(raw_text=profile_entities_t.c.name)
    )

    skill_rows = conn.execute(
        sa.select(profile_entities_t.c.entity_id, profile_entities_t.c.name)
        .where(profile_entities_t.c.entity_type == 'skill')
    ).fetchall()

    # canonical_name -> taxonomy id, built up as we go so two different raw
    # names that resolve to the same canonical_name (e.g. "Management" and
    # "ניהול") share one taxonomy row instead of violating the unique
    # constraint on a second insert.
    canonical_to_id: dict[str, str] = {
        row.canonical_name: str(row.id)
        for row in conn.execute(sa.select(skills_taxonomy_t.c.canonical_name, skills_taxonomy_t.c.id)).fetchall()
    }

    linked = 0
    seeded_new = 0
    for row in skill_rows:
        key = _clean_key(row.name)
        canonical_name, category = _SYNONYM_SEED.get(key, (None, None))
        if canonical_name is None:
            canonical_name = _fallback_canonical(row.name)
            category = "Uncategorized"

        taxonomy_id = canonical_to_id.get(canonical_name)
        if taxonomy_id is None:
            result = conn.execute(
                sa.text(
                    "INSERT INTO public.skills_taxonomy (canonical_name, category) "
                    "VALUES (:name, :cat) RETURNING id"
                ),
                {"name": canonical_name, "cat": category},
            )
            taxonomy_id = str(result.scalar())
            canonical_to_id[canonical_name] = taxonomy_id
            seeded_new += 1

        conn.execute(
            profile_entities_t.update()
            .where(profile_entities_t.c.entity_id == row.entity_id)
            .values(skill_id=taxonomy_id)
        )
        linked += 1

    print(f"[90b20294d1d3] backfill: linked {linked} skill entities across "
          f"{len(canonical_to_id)} taxonomy rows ({seeded_new} newly inserted "
          f"by this migration).")


def downgrade() -> None:
    op.drop_index('ix_profile_entities_skill_id', table_name='profile_entities', schema='public')
    op.drop_constraint('fk_profile_entities_skill_id', 'profile_entities', schema='public', type_='foreignkey')
    op.drop_column('profile_entities', 'last_used_year', schema='public')
    op.drop_column('profile_entities', 'years_of_experience', schema='public')
    op.drop_column('profile_entities', 'raw_text', schema='public')
    op.drop_column('profile_entities', 'skill_id', schema='public')

    op.execute("DROP POLICY IF EXISTS skills_taxonomy_read_all ON public.skills_taxonomy")
    op.execute("ALTER TABLE public.skills_taxonomy NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE public.skills_taxonomy DISABLE ROW LEVEL SECURITY")
    op.drop_table('skills_taxonomy', schema='public')
