"""
One saved CV per language per job. The job's tailored_cv held a single CV:
creating the Hebrew version replaced the English one, and switching back
meant generating it again (another daily generation).
"""
from __future__ import annotations

import json
import uuid

import pytest
from sqlalchemy import text


@pytest.fixture()
def job(db_available, monkeypatch):
    from backend.core.database import ENGINE
    from backend.repositories import job_repository
    # A fixed fingerprint: these tests are about versions, not staleness.
    monkeypatch.setattr(job_repository, "profile_fingerprint", lambda uid: "fp")
    uid, pid = str(uuid.uuid4()), str(uuid.uuid4())
    jid = f"cvver-{uid[:8]}"
    with ENGINE.begin() as c:
        c.execute(text("INSERT INTO public.profiles (id, email) VALUES (CAST(:u AS uuid), :e)"),
                  {"u": uid, "e": f"cvver-{uid[:8]}@example.invalid"})
        c.execute(text("""INSERT INTO public.job_postings (id, canonical_job_key, title, company, location)
                          VALUES (CAST(:p AS uuid), :k, 'CSM', 'Acme', 'Tel Aviv')"""), {"p": pid, "k": jid})
        c.execute(text("""INSERT INTO public.user_job_matches (user_id, job_posting_id, job_id, status)
                          VALUES (CAST(:u AS uuid), CAST(:p AS uuid), :j, 'new')"""),
                  {"u": uid, "p": pid, "j": jid})
    yield jid, uid
    with ENGINE.begin() as c:
        c.execute(text("DELETE FROM public.profiles WHERE id = CAST(:u AS uuid)"), {"u": uid})
        c.execute(text("DELETE FROM public.job_postings WHERE id = CAST(:p AS uuid)"), {"p": pid})


EN = {"summary": "English CV"}
HE = {"summary": "קורות חיים בעברית"}


def test_creating_the_hebrew_version_keeps_the_english_one(job):
    from backend.repositories.job_repository import get_tailored_cv, save_tailored_cv, tailored_cv_locales
    jid, uid = job
    save_tailored_cv(jid, uid, EN, None, cv_locale="en")
    save_tailored_cv(jid, uid, HE, None, cv_locale="he")
    assert tailored_cv_locales(jid, uid) == ["en", "he"]
    assert get_tailored_cv(jid, uid, cv_locale="en")["cv_data"] == EN
    assert get_tailored_cv(jid, uid, cv_locale="he")["cv_data"] == HE
    assert get_tailored_cv(jid, uid)["cv_data"] == HE, "without a language: the latest version"


def test_regenerating_one_language_clears_only_that_one(job):
    from backend.repositories.job_repository import (
        clear_tailored_cv, get_tailored_cv, save_tailored_cv, tailored_cv_locales,
    )
    jid, uid = job
    save_tailored_cv(jid, uid, EN, None, cv_locale="en")
    save_tailored_cv(jid, uid, HE, None, cv_locale="he")
    assert clear_tailored_cv(jid, uid, cv_locale="he")
    assert tailored_cv_locales(jid, uid) == ["en"]
    assert get_tailored_cv(jid, uid)["cv_data"] == EN
    assert clear_tailored_cv(jid, uid) and get_tailored_cv(jid, uid) is None


def test_a_cv_saved_before_versions_reads_as_its_own_language(job):
    from backend.core.database import ENGINE
    from backend.repositories.job_repository import get_tailored_cv, save_tailored_cv, tailored_cv_locales
    jid, uid = job
    legacy = {"cv_data": EN, "match_score": None, "profile_fingerprint": "fp"}   # no cv_locale, no by_locale
    with ENGINE.begin() as c:
        c.execute(text("""UPDATE public.user_job_matches SET tailored_cv = CAST(:b AS jsonb)
                          WHERE job_id = :j"""), {"b": json.dumps(legacy), "j": jid})
    assert get_tailored_cv(jid, uid, cv_locale="en")["cv_data"] == EN
    save_tailored_cv(jid, uid, HE, None, cv_locale="he")
    assert tailored_cv_locales(jid, uid) == ["en", "he"], "the legacy CV is kept as the English version"
