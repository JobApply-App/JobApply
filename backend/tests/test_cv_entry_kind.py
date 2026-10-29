"""
The CV extraction has one "experiences" list and the model filed degrees and
army service there. The founder's profile showed "B.A. Business Administration
& Digital Innovation" as a job. Degrees now move to education (at extraction
and on read); army service stays in the work history, tagged kind="military".
"""
from __future__ import annotations

from backend.services import user_profile as up
from backend.services.cv_entry_kind import separate_degrees

FOUNDER_CV = [
    {"company": "GO-OUT", "role": "Team Lead – Partnerships & Support", "start": "2025", "end": "2026"},
    {"company": "Reichman University", "role": "B.A. Business Administration & Digital Innovation",
     "start": "2020", "end": "2024"},
    {"company": "IDF", "role": "Clerk to Lieutenant Colonel", "start": "2014", "end": "2016"},
]


def test_degree_moves_to_education_military_is_tagged_and_kept():
    jobs, edu = separate_degrees(FOUNDER_CV, [])
    assert [j["role"] for j in jobs] == ["Team Lead – Partnerships & Support", "Clerk to Lieutenant Colonel"]
    assert jobs[1]["kind"] == "military" and "kind" not in jobs[0]
    assert edu == [{"degree": "B.A. Business Administration & Digital Innovation",
                    "institution": "Reichman University", "years": "2020-2024"}]


def test_degree_already_in_education_is_not_duplicated():
    _, edu = separate_degrees(FOUNDER_CV, [{"degree": "B.A. Business Administration & Digital Innovation"}])
    assert len(edu) == 1


def test_stored_cv_is_read_with_the_degree_as_education(monkeypatch):
    monkeypatch.setattr(up, "_onboarding_row_profile",
                        lambda uid: {"cv_data": {"experiences": FOUNDER_CV, "education": []}})
    for name in ("_metrics_doc_personal", "_auth_metadata_personal"):
        monkeypatch.setattr(up, name, lambda uid: {})
    monkeypatch.setattr(up, "_master_profile_verified_email", lambda uid: "")
    profile = up.get_profile("u1")
    roles = [e["role"] for e in profile["experience"]]
    assert "B.A. Business Administration & Digital Innovation" not in roles
    assert "Clerk to Lieutenant Colonel" in roles                      # full history kept
    assert any(e.get("degree", "").startswith("B.A.") for e in profile["education"])


async def test_extraction_moves_a_degree_the_model_filed_as_a_job(monkeypatch):
    import json
    from types import SimpleNamespace
    from backend.services import cv_aggregator_service as agg

    out = {"personal": {}, "skills": [], "domains": [], "summary": "",
           "experiences": FOUNDER_CV, "education": []}

    async def fake_llm(**kw):
        return SimpleNamespace(text=json.dumps(out))

    monkeypatch.setattr(agg, "call_llm", fake_llm)
    claims = await agg.aggregate_cv_claims(["cv text"], "u1")
    assert [e["role"] for e in claims["experiences"]] == [
        "Team Lead – Partnerships & Support", "Clerk to Lieutenant Colonel"]
    assert claims["education"][0]["degree"].startswith("B.A.")
