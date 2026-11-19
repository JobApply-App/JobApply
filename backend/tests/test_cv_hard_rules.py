"""
The two hard-rule failures of stage 7 part C (docs/research/07-benchmark-results.md):

- p08: the job "Ph.D. Researcher" at the Weizmann Institute was filed as a
  degree, so its six years of work left the experience list (and scoring) and
  a fourth "degree" appeared on the CV.
- p11: a five-year career break became "Bookkeeper, Family Small Business,
  2019-2024", an invented employer, with both CV prompts.

Pure tests: no model, no database.
"""
from __future__ import annotations

from backend.agents import tailor
from backend.services.cv_entry_kind import is_degree, separate_degrees


# ── p08: a degree word followed by a job noun is a job ───────────────────────

def test_a_phd_researcher_is_a_job_and_keeps_its_bullets():
    phd_job = {"role": "Ph.D. Researcher", "company": "Weizmann Institute of Science",
               "start": "2015", "end": "2021", "bullets": ["Built a CRISPR screen"]}
    jobs, edu = separate_degrees([phd_job], [{"degree": "Ph.D. Immunology"}])
    assert jobs == [phd_job]
    assert edu == [{"degree": "Ph.D. Immunology"}]


def test_the_next_role_at_the_same_employer_is_kept():
    from backend.services.user_profile import _merged_experience
    cv = {"experiences": [
        {"company": "Weizmann Institute of Science", "role": "Postdoctoral Researcher", "start": "2021", "end": "present"},
        {"company": "Weizmann Institute of Science", "role": "Ph.D. Researcher", "start": "2015", "end": "2021"},
    ]}
    roles = [e["role"] for e in _merged_experience({"experience": [], "cv_data": cv})]
    assert roles == ["Postdoctoral Researcher", "Ph.D. Researcher"]
    # The same role with a reworded title is still one role.
    own = [{"company": "Acme", "role": "Senior FP&A Analyst", "start": "2020", "end": "2023"}]
    cv = {"experiences": [{"company": "Acme", "role": "FP&A Analyst", "start": "2020", "end": "2023"}]}
    assert len(_merged_experience({"experience": own, "cv_data": cv})) == 1


def test_degrees_are_still_degrees():
    for title in ("Ph.D. Immunology", "B.Sc. Computer Science", "MBA", "תואר ראשון בכלכלה",
                  "B.A. Business Administration & Digital Innovation"):
        assert is_degree({"role": title}), title
    for title in ("PhD Student", "M.Sc. Research Assistant", "MBA Intern", "דוקטורנט, מכון ויצמן"):
        assert not is_degree({"role": title}), title


# ── p11: a career break never gets an employer ───────────────────────────────

PROFILE = {"experience": [
    {"role": "Bookkeeper (part time)", "company": "Dekel Building Materials", "period": "2024 - Present"},
    {"role": "Career break (raising children)", "company": "", "period": "2019 - 2024"},
    {"role": "Senior Bookkeeper (level 3)", "company": "Sela Import and Trading", "period": "2011 - 2019"},
]}


def _cv(*entries):
    return {"experience": [{"role": r, "company": c, "dates": d, "bullets": []} for r, c, d in entries]}


def test_a_break_given_an_employer_is_dropped(monkeypatch):
    monkeypatch.setattr(tailor, "_resolve_profile", lambda uid: PROFILE)
    cv = _cv(("Bookkeeper", "Dekel Building Materials", "2024 - Present"),
             ("Bookkeeper", "Family Small Business", "2019 - 2024"),
             ("Senior Bookkeeper", "Sela Import and Trading", "2011 - 2019"))
    out = tailor._drop_employed_breaks(cv, "u1")
    assert [e["company"] for e in out["experience"]] == ["Dekel Building Materials", "Sela Import and Trading"]


def test_a_hebrew_cv_is_matched_by_years(monkeypatch):
    monkeypatch.setattr(tailor, "_resolve_profile", lambda uid: PROFILE)
    cv = _cv(("מנהלת חשבונות", "עסק משפחתי", "2019 - 2024"),
             ("מנהלת חשבונות בכירה", "סלע יבוא וסחר", "2011 - 2019"))
    out = tailor._drop_employed_breaks(cv, "u1")
    assert [e["dates"] for e in out["experience"]] == ["2011 - 2019"]


def test_a_break_kept_as_a_break_stays(monkeypatch):
    monkeypatch.setattr(tailor, "_resolve_profile", lambda uid: PROFILE)
    cv = _cv(("Career break (raising children)", "", "2019 - 2024"))
    assert tailor._drop_employed_breaks(cv, "u1") == cv


def test_a_freelance_job_with_no_company_is_not_a_break(monkeypatch):
    profile = {"experience": [{"role": "Freelance designer", "company": "", "period": "2019 - 2021"}]}
    monkeypatch.setattr(tailor, "_resolve_profile", lambda uid: profile)
    cv = _cv(("Freelance Designer", "Self-employed", "2019 - 2021"))
    assert tailor._drop_employed_breaks(cv, "u1") == cv


def test_both_prompts_say_a_break_is_not_a_job():
    # The break was first lost when the CV was read in: the extraction filed
    # it as "Bookkeeper (voluntary), Family's small business", so the writer
    # only repeated the profile. Both prompts carry the rule.
    from backend.services.cv_aggregator_service import _AGGREGATION_SYSTEM
    assert "career break, not a job" in tailor._SYSTEM_PROMPT
    assert "Never turn a break" in _AGGREGATION_SYSTEM
