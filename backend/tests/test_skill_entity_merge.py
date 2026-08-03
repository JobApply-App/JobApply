"""
Guards for the cv_claims-skills → profile_entities merge (migration fa884910ef1d).

The merge put the profile document's skill list and the Confidence Matrix's
scored entities in the same rows. That is the point — one capability, one row —
but it also means profile_repository.save(), which runs on EVERY profile
mutation, now writes to a table whose confidence_score is derived from
append-only evidence. Three properties keep that safe, and none of them are
observable from any feature test:

  1. save() must not move confidence_score, evidence_records or
     confidence_audit_log. A wholesale rewrite would flatten scores that took
     real evidence to earn.
  2. Removing a skill from the profile must clear source_document_id, NOT
     delete the entity — evidence and audit rows reference entity_id and are
     append-only.
  3. get_profile() must return only CV-claimed skills, not the whole matrix.
     profile_entities holds ~3x more entities (inferred, conversational,
     derived) than the CV lists; leaking those into the profile document would
     silently inflate every generated CV.

Postgres-only (the merge columns and jsonb live there); skips via db_available.
"""
from __future__ import annotations

import copy

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

_QA_USER = "2631c93b-93bb-4313-a2c2-79dbb786d199"


def _matrix_state(user_id: str) -> dict:
    from backend.core.database import ENGINE

    with ENGINE.connect() as c:
        return {
            "score_sum": c.execute(
                text("SELECT COALESCE(sum(confidence_score), 0) FROM public.profile_entities "
                     "WHERE user_id = CAST(:u AS uuid)"), {"u": user_id}).scalar(),
            "entities": c.execute(
                text("SELECT count(*) FROM public.profile_entities WHERE user_id = CAST(:u AS uuid)"),
                {"u": user_id}).scalar(),
            "evidence": c.execute(
                text("SELECT count(*) FROM public.evidence_records WHERE user_id = CAST(:u AS uuid)"),
                {"u": user_id}).scalar(),
            "audit": c.execute(
                text("SELECT count(*) FROM public.confidence_audit_log WHERE user_id = CAST(:u AS uuid)"),
                {"u": user_id}).scalar(),
        }


@pytest.fixture
def seeded_skill(db_available):
    """A scored entity claimed on the user's CV, cleaned up afterwards."""
    import uuid
    from datetime import datetime, timezone

    from backend.core.database import ENGINE
    from backend.repositories import profile_repository as pr

    name = f"MergeGuard {uuid.uuid4().hex[:8]}"
    eid = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    with Session(ENGINE) as s:
        handle, _ = pr.get_or_create(s, _QA_USER, now=now)
        mp = copy.deepcopy(handle.master_profile)
        mp.setdefault("skills", []).append(name)
        handle.master_profile = mp
        pr.save(s, handle)
        s.commit()

    # Give it a non-zero score, as ProfileUpdateService would.
    with ENGINE.begin() as c:
        c.execute(
            text("""UPDATE public.profile_entities SET entity_id = :eid, confidence_score = 42.5
                    WHERE user_id = CAST(:u AS uuid) AND entity_type = 'skill' AND name = :n"""),
            {"eid": eid, "u": _QA_USER, "n": name},
        )
    yield name, eid

    with ENGINE.begin() as c:
        c.execute(text("DELETE FROM public.profile_entities WHERE entity_id = :e"), {"e": eid})
    with Session(ENGINE) as s:
        handle, _ = pr.get_or_create(s, _QA_USER, now=now)
        mp = copy.deepcopy(handle.master_profile)
        mp["skills"] = [x for x in (mp.get("skills") or []) if x != name]
        handle.master_profile = mp
        pr.save(s, handle)
        s.commit()


class TestSaveDoesNotDisturbTheMatrix:
    def test_resaving_the_same_profile_is_inert(self, db_available, seeded_skill):
        """The common case: any profile edit re-saves the whole document."""
        from backend.core.database import ENGINE
        from backend.repositories import profile_repository as pr

        before = _matrix_state(_QA_USER)
        with Session(ENGINE) as s:
            handle, _ = pr.get_or_create(s, _QA_USER, now="2026-01-01T00:00:00")
            pr.save(s, handle)
            s.commit()

        assert _matrix_state(_QA_USER) == before, (
            "profile_repository.save() moved Confidence Matrix state; it must only "
            "mark which capabilities are claimed on the CV"
        )


class TestRemovalPreservesEvidence:
    def test_removing_a_skill_clears_the_link_but_keeps_the_entity(self, db_available, seeded_skill):
        from backend.core.database import ENGINE
        from backend.repositories import profile_repository as pr

        name, eid = seeded_skill
        before = _matrix_state(_QA_USER)

        with Session(ENGINE) as s:
            handle, _ = pr.get_or_create(s, _QA_USER, now="2026-01-01T00:00:00")
            mp = copy.deepcopy(handle.master_profile)
            mp["skills"] = [x for x in mp["skills"] if x != name]
            handle.master_profile = mp
            pr.save(s, handle)
            s.commit()

        with ENGINE.connect() as c:
            row = c.execute(
                text("SELECT confidence_score, source_document_id FROM public.profile_entities "
                     "WHERE entity_id = :e"), {"e": eid}).fetchone()

        assert row is not None, "removing a skill deleted its entity — evidence rows are now orphaned"
        assert row.source_document_id is None, "source_document_id should be cleared on removal"
        assert row.confidence_score == pytest.approx(42.5), "removal must not touch the score"

        after = _matrix_state(_QA_USER)
        assert after["entities"] == before["entities"]
        assert after["evidence"] == before["evidence"]
        assert after["audit"] == before["audit"]

    def test_removed_skill_disappears_from_the_profile_document(self, db_available, seeded_skill):
        from backend.core.database import ENGINE
        from backend.repositories import profile_repository as pr

        name, _eid = seeded_skill
        assert name in pr.get(_QA_USER).master_profile.get("skills", [])

        with Session(ENGINE) as s:
            handle, _ = pr.get_or_create(s, _QA_USER, now="2026-01-01T00:00:00")
            mp = copy.deepcopy(handle.master_profile)
            mp["skills"] = [x for x in mp["skills"] if x != name]
            handle.master_profile = mp
            pr.save(s, handle)
            s.commit()

        assert name not in pr.get(_QA_USER).master_profile.get("skills", [])


class TestProfileDocumentIsNotTheWholeMatrix:
    def test_unclaimed_entities_stay_out_of_the_profile(self, db_available, seeded_skill):
        """
        profile_entities holds far more than the CV claims. get_profile() must
        return only the claimed subset, or every generated CV silently inflates.
        """
        from backend.core.database import ENGINE
        from backend.repositories import profile_repository as pr

        with ENGINE.connect() as c:
            total = c.execute(
                text("SELECT count(*) FROM public.profile_entities "
                     "WHERE user_id = CAST(:u AS uuid) AND entity_type = 'skill'"),
                {"u": _QA_USER}).scalar()
            claimed = c.execute(
                text("SELECT count(*) FROM public.profile_entities "
                     "WHERE user_id = CAST(:u AS uuid) AND entity_type = 'skill' "
                     "AND source_document_id IS NOT NULL"),
                {"u": _QA_USER}).scalar()

        doc_skills = pr.get(_QA_USER).master_profile.get("skills", [])
        assert len(doc_skills) == claimed, (
            f"profile document returned {len(doc_skills)} skills but {claimed} are CV-claimed "
            f"(of {total} total entities)"
        )


class TestCvClaimsNoLongerHoldsSkills:
    def test_skill_claim_type_is_rejected(self, db_available):
        """
        The CHECK constraint is what stops the split silently regressing: a
        future writer that still thinks skills belong here fails loudly.
        """
        import uuid

        from backend.core.database import ENGINE
        from sqlalchemy.exc import IntegrityError

        with ENGINE.connect() as c:
            doc_id = c.execute(
                text("SELECT id FROM public.cv_documents WHERE user_id = CAST(:u AS uuid) LIMIT 1"),
                {"u": _QA_USER}).scalar()
        if doc_id is None:
            pytest.skip("QA account has no cv_document to test against")

        with pytest.raises(IntegrityError):
            with ENGINE.begin() as c:
                c.execute(
                    text("INSERT INTO public.cv_claims (id, document_id, claim_type, content) "
                         "VALUES (:i, :d, 'skill', '{\"name\": \"nope\"}'::jsonb)"),
                    {"i": str(uuid.uuid4()), "d": doc_id},
                )
