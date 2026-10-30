"""
Saving an edited CV filed it under the user's default language when the
client did not say which language it was in: a Hebrew edit overwrote the
English version (one CV per language per job since #134). The client now
sends cv_locale; without it, the server reads the language from the CV.
"""
from types import SimpleNamespace

import pytest

import backend.api.routes.resumes as resumes

HE_CV = {"summary": "מומחה הטמעה טכנולוגית עם ניסיון עשיר בניהול לקוחות.",
         "experience": [{"bullets": ["הובלתי צוות של 12 עובדים."]}]}


@pytest.fixture()
def saved(monkeypatch):
    calls = []
    monkeypatch.setattr(resumes.job_store, "get_all", lambda uid: [SimpleNamespace(job_id="j1")])
    monkeypatch.setattr(resumes, "save_tailored_cv",
                        lambda job_id, uid, cv, ms, cv_locale: calls.append(cv_locale))
    monkeypatch.setattr(resumes, "_stored_cv_locale", lambda uid: "en")
    return calls


async def test_an_explicit_language_is_used(saved):
    await resumes.save_cv(resumes.SaveCvRequest(job_id="j1", cv_data=HE_CV, cv_locale="he"),
                          user=SimpleNamespace(user_id="u1"))
    assert saved == ["he"]


async def test_without_a_language_the_cvs_own_text_decides_not_the_default(saved):
    await resumes.save_cv(resumes.SaveCvRequest(job_id="j1", cv_data=HE_CV),
                          user=SimpleNamespace(user_id="u1"))
    assert saved == ["he"], "a Hebrew edit must not be filed under the English default"
