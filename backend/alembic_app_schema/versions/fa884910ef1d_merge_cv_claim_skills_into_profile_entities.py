"""merge cv_claims skills into profile_entities (one row per real capability)

Revision ID: fa884910ef1d
Revises: cc2326adde27
Create Date: 2026-08-02 17:55:00.000000

Step 3 of docs/db-architecture-spec.md — principle 2, "one real-world entity,
one row". A skill named "Figma" lived twice: as a raw claim in cv_claims and
as a scored entity in profile_entities, with no link between them, so an
update on either side left the other stale.

SCOPE CORRECTION vs the spec as written
---------------------------------------
The spec called for merging cv_claims wholesale. Checking the actual data
before executing showed that only the skills are duplicated:

  claim_type='skill'      36 rows — 36/36 match a profile_entities row by
                          (user_id, lower(name)). Genuine duplication. MERGED.
  claim_type='experience' 14 rows — 0/14 match. They are not the same kind of
                          thing: cv_claims.experience is an employment record
                          ({company, role, start, end, bullets}) that
                          match_score_service and tailor read as the dated
                          career timeline (CLAUDE.md scoring principle 1),
                          while profile_entities.experience is a scored
                          capability ("Product Ownership (de facto PM)").
                          Merging them would corrupt both. NOT MERGED.

So cv_claims shrinks to what it is actually good at — the CV's structured
employment and education records — rather than disappearing. Its claim_type
CHECK drops 'skill' so the split cannot silently regress.

Column semantics added to profile_entities
------------------------------------------
  content            the rich claim payload that used to live in
                     cv_claims.content
  source_document_id the cv_document this capability is currently claimed on,
                     NULL when it is not on the CV. profile_repository sets it
                     when a skill is present in the profile document and
                     clears it when the skill is removed — which is what keeps
                     get_profile() returning exactly the same skill list as
                     before, now with each skill carrying its confidence score.
                     Removal deliberately clears this rather than deleting the
                     entity: evidence_records and confidence_audit_log are
                     append-only, and dropping the entity would orphan them.
  origin             where the capability first came from
                     (cv_parse | self_assertion | conversation | inferred).

confidence_score is untouched by this migration and by the repository layer —
ProfileUpdateService remains its only writer.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'fa884910ef1d'
down_revision: Union[str, None] = 'cc2326adde27'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('profile_entities',
                  sa.Column('content', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
                  schema='public')
    op.add_column('profile_entities',
                  sa.Column('source_document_id', postgresql.UUID(as_uuid=False), nullable=True),
                  schema='public')
    op.add_column('profile_entities',
                  sa.Column('origin', sa.Text(), nullable=False, server_default='self_assertion'),
                  schema='public')
    op.create_foreign_key(
        'fk_profile_entities_source_document', 'profile_entities', 'cv_documents',
        ['source_document_id'], ['id'],
        source_schema='public', referent_schema='public', ondelete='SET NULL',
    )
    op.create_index('ix_profile_entities_source_document', 'profile_entities',
                    ['source_document_id'], schema='public')

    # Backfill: every cv_claims skill onto its already-existing entity.
    # Matching on (user_id, lower(trim(name))) mirrors how normalized_name is
    # derived elsewhere and was verified to hit 36/36 before this was written.
    op.execute("""
        UPDATE public.profile_entities pe
        SET content            = cl.content,
            source_document_id = cl.document_id,
            origin             = 'cv_parse',
            updated_at         = pe.updated_at
        FROM public.cv_claims cl
        JOIN public.cv_documents d ON d.id = cl.document_id
        WHERE cl.claim_type = 'skill'
          AND pe.user_id     = d.user_id
          AND pe.entity_type = 'skill'
          AND lower(trim(pe.name)) = lower(trim(cl.content->>'name'))
    """)

    # A skill claim with no matching entity would be silently dropped by the
    # delete below, so fail loudly instead — on this dataset the count is 0.
    op.execute("""
        DO $$
        DECLARE orphans int;
        BEGIN
            SELECT count(*) INTO orphans
            FROM public.cv_claims cl
            JOIN public.cv_documents d ON d.id = cl.document_id
            WHERE cl.claim_type = 'skill'
              AND NOT EXISTS (
                  SELECT 1 FROM public.profile_entities pe
                  WHERE pe.user_id = d.user_id AND pe.entity_type = 'skill'
                    AND lower(trim(pe.name)) = lower(trim(cl.content->>'name'))
              );
            IF orphans > 0 THEN
                RAISE EXCEPTION
                  'aborting: % cv_claims skill(s) have no profile_entities row and would be lost', orphans;
            END IF;
        END $$;
    """)

    op.execute("DELETE FROM public.cv_claims WHERE claim_type = 'skill'")

    op.drop_constraint('ck_cv_claims_claim_type', 'cv_claims', schema='public', type_='check')
    op.create_check_constraint(
        'ck_cv_claims_claim_type', 'cv_claims',
        "claim_type IN ('experience', 'education')",
        schema='public',
    )


def downgrade() -> None:
    op.drop_constraint('ck_cv_claims_claim_type', 'cv_claims', schema='public', type_='check')
    op.create_check_constraint(
        'ck_cv_claims_claim_type', 'cv_claims',
        "claim_type IN ('skill', 'experience', 'education')",
        schema='public',
    )

    # Rebuild the skill claims from the entities that carry a source document.
    op.execute("""
        INSERT INTO public.cv_claims (document_id, claim_type, content)
        SELECT pe.source_document_id, 'skill',
               COALESCE(pe.content, jsonb_build_object('name', pe.name))
        FROM public.profile_entities pe
        WHERE pe.entity_type = 'skill' AND pe.source_document_id IS NOT NULL
    """)

    op.drop_index('ix_profile_entities_source_document', table_name='profile_entities', schema='public')
    op.drop_constraint('fk_profile_entities_source_document', 'profile_entities',
                       schema='public', type_='foreignkey')
    op.drop_column('profile_entities', 'origin', schema='public')
    op.drop_column('profile_entities', 'source_document_id', schema='public')
    op.drop_column('profile_entities', 'content', schema='public')
