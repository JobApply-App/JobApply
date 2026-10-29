"""
Military service is always shown as its own CV section, never under Work
Experience — even when the role was real professional work. The tailoring
model sometimes lists it as a job; _inject_static_sections moves it.
"""
from __future__ import annotations

import backend.agents.tailor as tailor_module
from backend.agents.tailor import _inject_static_sections

PROFILE = {
    "experience": [
        {"company": "Wix", "role": "Backend Developer", "period": "2023 - Present"},
        {"company": "Israeli Air Force", "role": "Software Developer", "period": "2019 - 2022",
         "kind": "military"},
    ],
    "education": [], "skills": [],
}


def _run(monkeypatch, data):
    monkeypatch.setattr(tailor_module, "_resolve_profile", lambda _uid: PROFILE)
    return _inject_static_sections(data, user_id="u1")


def test_service_listed_as_a_job_moves_to_the_military_section(monkeypatch):
    out = _run(monkeypatch, {"experience": [
        {"company": "Wix", "role": "Backend Developer", "bullets": []},
        {"company": "Israeli Air Force", "role": "Software Developer", "bullets": ["Built tools"]},
    ]})
    assert [e["company"] for e in out["experience"]] == ["Wix"]
    assert out["military_service"]["role_title"] == "Software Developer"
    assert out["military_service"]["unit_type"] == "Israeli Air Force"


def test_military_section_written_by_the_model_is_kept(monkeypatch):
    mil = {"role_title": "Software Developer", "unit_type": "IAF", "dates": "2019-2022",
           "key_responsibilities": ["Led a team of 4"]}
    out = _run(monkeypatch, {"experience": [], "military_service": dict(mil)})
    assert out["military_service"]["key_responsibilities"] == ["Led a team of 4"]


def test_a_civilian_job_mentioning_the_air_force_stays_a_job(monkeypatch):
    job = {"company": "Elbit Systems", "role": "Engineer, Air Force programs", "bullets": []}
    out = _run(monkeypatch, {"experience": [job]})
    assert out["experience"] == [job]


def test_military_is_not_a_required_employer(monkeypatch):
    monkeypatch.setattr(tailor_module, "_resolve_profile", lambda _uid: PROFILE)
    assert [e["company"] for e in tailor_module._required_profile_employers("u1")] == ["Wix"]
