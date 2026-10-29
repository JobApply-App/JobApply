"""
profile_repository.save() writes only what changed since the profile was
read. It used to delete and re-insert every profile_answers row and every CV
claim on each save: a role change rewrote the whole CV (database egress), and
a row another writer added between the read and the save was deleted.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session


@pytest.fixture()
def user(db_available):
    from backend.core.database import ENGINE
    from backend.repositories import profile_repository as repo
    uid = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    with Session(ENGINE) as s:
        h, _ = repo.get_or_create(s, uid, now=now)
        h.master_profile = {
            "personal": {"name": "Dana", "phone": "050"},
            "role_preferences": {"target_titles": ["Analyst"]},
            "experience": [{"company": "Acme", "role": "Analyst", "period": "2020-2024"}],
            "skills": ["SQL"],
        }
        repo.save(s, h)
        s.commit()
    yield uid
    with ENGINE.begin() as c:
        c.execute(text("DELETE FROM public.profiles WHERE id = CAST(:u AS uuid)"), {"u": uid})


def _claim_ids(uid):
    from backend.core.database import ENGINE
    with ENGINE.connect() as c:
        return sorted(str(r[0]) for r in c.execute(text("""
            SELECT cc.id FROM public.cv_claims cc JOIN public.cv_documents d ON d.id = cc.document_id
            WHERE d.user_id = CAST(:u AS uuid)"""), {"u": uid}))


def test_changing_roles_leaves_the_cv_and_other_rows_alone(user):
    from backend.core.database import ENGINE
    from backend.repositories import profile_repository as repo
    claims_before = _claim_ids(user)
    assert claims_before, "the fixture must have written CV claims"

    with Session(ENGINE) as s:
        h = repo.get_in_session(s, user)
        # Another writer adds a row after this read (e.g. cached search terms).
        with ENGINE.begin() as c:
            c.execute(text("""INSERT INTO public.profile_answers (user_id, question_id, answer)
                              VALUES (CAST(:u AS uuid), 'title_search_terms', '{"terms": ["x"]}')"""), {"u": user})
        mp = dict(h.master_profile)
        mp["role_preferences"] = {"target_titles": ["Data Analyst"]}
        h.master_profile = mp
        repo.save(s, h)
        s.commit()

    assert _claim_ids(user) == claims_before, "a role change must not rewrite the CV"
    doc = repo.get_profile_json(user)
    assert doc["role_preferences"]["target_titles"] == ["Data Analyst"]
    assert doc.get("title_search_terms") == {"terms": ["x"]}, "a row written meanwhile must survive"


def test_a_removed_key_is_deleted_and_a_cv_change_is_written(user):
    from backend.core.database import ENGINE
    from backend.repositories import profile_repository as repo
    with Session(ENGINE) as s:
        h = repo.get_in_session(s, user)
        mp = dict(h.master_profile)
        mp.pop("role_preferences")
        mp["experience"] = mp["experience"] + [{"company": "Beta", "role": "Lead", "period": "2024-"}]
        h.master_profile = mp
        repo.save(s, h)
        s.commit()
    with ENGINE.connect() as c:
        left = c.execute(text("""SELECT count(*) FROM public.profile_answers
                                 WHERE user_id = CAST(:u AS uuid) AND question_id = 'role_preferences'"""),
                         {"u": user}).scalar()
    assert left == 0, "a key removed from the document must be deleted"
    companies = {e["company"] for e in repo.get_profile_json(user)["experience"]}
    assert companies == {"Acme", "Beta"}, "a CV change must be written"
