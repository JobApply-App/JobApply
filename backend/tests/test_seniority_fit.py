"""
Seniority chosen in onboarding was stored and never used: a senior engineer's
feed held internships and VP roles alike. Jobs are now kept within one level
of what the user picked; a job whose level can't be told is always kept.
"""
from __future__ import annotations

import pytest

from backend.services.seniority_fit import fits, job_level_range, user_levels

SENIOR = user_levels([{"role": "Software Engineer", "seniority": "senior"}])
JUNIOR = user_levels([{"role": "Data Analyst", "seniority": "junior"}])


@pytest.mark.parametrize("title", [
    "Senior Backend Engineer", "Backend Engineer", "Tech Lead - Payments",
    "מפתח/ת Backend בכיר/ה", "Software Engineer",
])
def test_senior_keeps_its_level_and_neighbours_and_unknowns(title):
    assert fits(SENIOR, title)


@pytest.mark.parametrize("title", [
    "Software Engineering Intern", "Junior Backend Developer", "סטודנט/ית לפיתוח",
    "VP Engineering", "Director of Engineering", 'סמנכ"ל טכנולוגיות',
])
def test_senior_drops_far_levels(title):
    assert not fits(SENIOR, title)


def test_junior_drops_senior_and_up_keeps_intern():
    assert not fits(JUNIOR, "Senior Data Analyst")
    assert not fits(JUNIOR, "Head of Data")
    assert fits(JUNIOR, "Data Analyst Intern")
    assert fits(JUNIOR, "Data Analyst")


def test_linkedin_field_used_when_title_is_silent():
    assert not fits(SENIOR, "Backend Developer", "Internship")
    assert fits(SENIOR, "Backend Developer", "Mid-Senior level")
    assert fits(SENIOR, "Backend Developer", None)


def test_title_beats_linkedin_field():
    assert job_level_range("Senior Engineer", "Entry level") == (3, 3)


def test_no_preference_keeps_everything():
    assert fits(set(), "VP Engineering")
    assert user_levels([{"role": "X", "seniority": ""}, "bad", None]) == set()


def test_multiple_roles_union_levels():
    levels = user_levels([{"role": "A", "seniority": "junior"}, {"role": "B", "seniority": "director"}])
    assert fits(levels, "Junior Analyst") and fits(levels, "Head of Product")


def test_lead_generation_is_a_function_not_a_level():
    from backend.services.seniority_fit import title_level
    for t in ["Lead Generation Specialist", "Lead Gen Manager", "Lead-Generation Rep",
              "SDR - Lead Qualification", "Lead Nurturing Specialist"]:
        assert title_level(t) != 4, t
    assert title_level("Lead Generation Specialist") is None
    assert title_level("Senior Lead Generation Manager") == 3
    assert title_level("Team Lead") == 4 and title_level("Lead Engineer") == 4
    assert title_level("Sales Lead") == 4


def test_lead_generation_title_keeps_its_profession_in_search_terms():
    from backend.services.user_title_terms import deterministic_terms
    assert deterministic_terms(["Lead Generation Specialist"]) == ["Lead Generation Specialist"]
    assert "Engineer" in deterministic_terms(["Lead Engineer"])
