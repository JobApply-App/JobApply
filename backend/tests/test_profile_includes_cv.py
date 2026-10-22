"""
get_profile() must include what the user's uploaded CV says.

It used to read only the sections Ariel writes in conversation and ignore
cv_data — the CV-upload extraction. Three testers had 5-7 CV roles each and
0-1 roles in the profile, so Ariel asked them for facts their CV already
stated, and job scoring and CV tailoring ran without their history (against
the "full experience timeline" rule). These tests pin the merge.
"""
from backend.services import user_profile as up


def _profile_with(onboarding: dict, monkeypatch) -> dict:
    monkeypatch.setattr(up, "_onboarding_row_profile", lambda user_id: onboarding)
    monkeypatch.setattr(up, "_metrics_doc_personal", lambda user_id: {})
    monkeypatch.setattr(up, "_master_profile_verified_email", lambda user_id: "")
    return up.get_profile("u")


CV = {
    "summary": "FP&A professional.",
    "experiences": [
        {"company": "Intel", "role": "FP&A Analyst", "start": "2019", "end": "present", "summary": "Budgets."},
        {"company": "Solution", "role": "Customer Relations", "start": "2016", "end": "2019", "summary": "Data."},
        {"company": "Expert", "role": "Office Manager", "start": "2014", "end": "2016", "summary": ""},
    ],
    "education": [{"degree": "MBA", "institution": "Tel Aviv University", "years": "2018-2020"}],
    "skills": ["Excel", "Power BI", "Budgeting"],
}


def test_cv_only_user_gets_the_whole_cv(monkeypatch):
    p = _profile_with({"cv_data": CV}, monkeypatch)
    assert [e["company"] for e in p["experience"]] == ["Intel", "Solution", "Expert"]
    assert p["education"][0]["school"] == "Tel Aviv University"
    assert p["skills"] == ["Excel", "Power BI", "Budgeting"]
    assert p["summary"] == "FP&A professional."


def test_ariel_entry_wins_over_the_cv_entry_for_the_same_job(monkeypatch):
    own = {"company": "Intel", "role": "Senior FP&A Analyst", "start": "2017-01", "end": "present",
           "bullets": ["Managed R&D budgets."]}
    p = _profile_with({"experience": [own], "skills": ["Budgeting"], "cv_data": CV}, monkeypatch)
    intel = [e for e in p["experience"] if e["company"] == "Intel"]
    assert len(intel) == 1 and intel[0]["role"] == "Senior FP&A Analyst"
    assert len(p["experience"]) == 3
    assert p["skills"] == ["Budgeting", "Excel", "Power BI"]   # no duplicate, own first


def test_same_company_in_different_years_is_two_jobs(monkeypatch):
    own = {"company": "Intel", "role": "Intern", "start": "2010", "end": "2011", "bullets": []}
    p = _profile_with({"experience": [own], "cv_data": CV}, monkeypatch)
    assert len([e for e in p["experience"] if e["company"] == "Intel"]) == 2


def test_most_recent_first(monkeypatch):
    p = _profile_with({"cv_data": {"experiences": list(reversed(CV["experiences"]))}}, monkeypatch)
    assert [e["company"] for e in p["experience"]] == ["Intel", "Solution", "Expert"]


def test_profile_without_cv_is_unchanged(monkeypatch):
    own = {"company": "Acme", "role": "PM", "start": "2020", "end": "2022", "bullets": ["x"]}
    p = _profile_with({"experience": [own], "education": [{"degree": "BA"}], "skills": ["SQL"]}, monkeypatch)
    assert [e["company"] for e in p["experience"]] == ["Acme"]
    assert p["education"] == [{"degree": "BA"}] and p["skills"] == ["SQL"]
