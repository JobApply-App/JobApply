"""
Phase 3 of docs/research/09-companies-and-costs.md: the user's stated company
preferences (work model, kind of company, industries) reach the match score's
culture fit, bounded at ±5 and never below a prior employer.
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.agents.company_culture import build_profile_from_payload
from backend.models.company import CompanyAliasRow, CompanyRow
from backend.repositories import company_repository as repo
from backend.services import match_score_service as mss
from backend.services.industry_groups import GROUPS, clean, groups_for


def _culture(**over):
    payload = {
        "culture_axis": 60.0, "culture_category": "scaleup", "operational_pace": "fast",
        "formality": "casual", "work_model": "hybrid", "work_life_balance_signals": [],
        "accepted_persona_traits": [], "operational_needs": [], "evidence": ["x"],
        "confidence": "high",
    }
    payload.update(over)
    return build_profile_from_payload("Acme", payload)


NO_PREFS = {"work_model": None, "culture_preference": "any", "industries_prefer": [], "industries_avoid": []}


# ── Industry groups ───────────────────────────────────────────────────────────

def test_linkedin_industries_map_to_groups():
    assert groups_for(["Software Development"]) == {"software"}
    assert groups_for(["Computer and Network Security"]) == {"cyber"}
    assert groups_for(["Financial Services", "Insurance"]) == {"finance"}
    assert groups_for(["Gambling Facilities and Casinos"]) == {"gambling"}
    assert groups_for(["Semiconductor Manufacturing"]) == {"hardware"}
    assert groups_for([]) == set() and groups_for(None) == set()


def test_clean_keeps_known_ids_in_order():
    assert clean(["public", "nope", "software", "software"]) == ["software", "public"]
    assert set(clean(GROUPS)) == set(GROUPS)


# ── Alignment ─────────────────────────────────────────────────────────────────

def test_avoided_industry_scores_zero_even_without_culture_profile():
    prefs = {**NO_PREFS, "industries_avoid": ["gambling"]}
    alignment, note = mss.compute_culture_alignment(None, prefs, ["Gambling Facilities and Casinos"])
    assert alignment == 0.0 and "gambling" in note
    assert mss.culture_delta_from_alignment(alignment) == -5.0


def test_preferred_industry_scores_full():
    prefs = {**NO_PREFS, "industries_prefer": ["cyber"]}
    alignment, _ = mss.compute_culture_alignment(None, prefs, ["Computer and Network Security"])
    assert alignment == 100.0
    assert mss.culture_delta_from_alignment(alignment) == 5.0


def test_avoid_wins_over_prefer():
    prefs = {**NO_PREFS, "industries_prefer": ["software"], "industries_avoid": ["gambling"]}
    alignment, _ = mss.compute_culture_alignment(None, prefs, ["Software Development", "Gambling Facilities and Casinos"])
    assert alignment == 0.0


def test_untagged_or_other_industry_is_no_signal():
    prefs = {**NO_PREFS, "industries_prefer": ["cyber"], "industries_avoid": ["gambling"]}
    assert mss.compute_culture_alignment(None, prefs, []) == (None, "")
    assert mss.compute_culture_alignment(None, prefs, ["Retail"]) == (None, "")


def test_scaleup_preference_reads_category():
    prefs = {**NO_PREFS, "culture_preference": "scaleup"}
    assert mss.compute_culture_alignment(_culture(culture_category="scaleup"), prefs)[0] == 100.0
    assert mss.compute_culture_alignment(_culture(culture_category="corporate"), prefs)[0] == 25.0
    assert mss.compute_culture_alignment(_culture(culture_category="agency"), prefs) == (None, "")


def test_hybrid_user_vs_company_work_model():
    prefs = {**NO_PREFS, "work_model": "hybrid"}
    assert mss.compute_culture_alignment(_culture(work_model="hybrid"), prefs)[0] == 100.0
    assert mss.compute_culture_alignment(_culture(work_model="onsite"), prefs)[0] == 30.0
    assert mss.compute_culture_alignment(_culture(work_model="unknown"), prefs) == (None, "")


def test_signals_average_and_prior_employer_is_never_lowered():
    prefs = {**NO_PREFS, "culture_preference": "scaleup", "industries_avoid": ["finance"]}
    alignment, note = mss.compute_culture_alignment(_culture(culture_category="scaleup"), prefs, ["Banking"])
    assert alignment == 50.0 and ";" in note
    prefs = {**NO_PREFS, "industries_avoid": ["finance"]}
    alignment, _ = mss.compute_culture_alignment(None, prefs, ["Banking"])
    assert mss.culture_delta_from_alignment(alignment, prior_employer=True) == 0.0


def test_no_preferences_no_effect():
    assert mss.compute_culture_alignment(_culture(), NO_PREFS, ["Software Development"]) == (None, "")


# ── Where the preferences are read from ───────────────────────────────────────

def _prefs(monkeypatch, goals: dict, metrics_prefs: dict | None = None) -> dict:
    from backend.repositories import profile_repository
    from backend.services import master_profile_service
    monkeypatch.setattr(profile_repository, "get_profile_json", lambda uid: {"career_goals": goals})
    monkeypatch.setattr(master_profile_service, "load", lambda uid: {"role_preferences": metrics_prefs or {}})
    return mss._load_culture_prefs("u1")


def test_onboarding_work_model_reaches_the_score(monkeypatch):
    # Before this change only the metrics document was read, which no screen writes.
    assert _prefs(monkeypatch, {"work_environment": "remote"})["work_model"] == "remote_only"
    assert _prefs(monkeypatch, {"work_environment": "hybrid"})["work_model"] == "hybrid"
    assert _prefs(monkeypatch, {"work_environment": "any"})["work_model"] is None
    assert _prefs(monkeypatch, {}, {"work_type": "remote"})["work_model"] == "remote_only"


def test_stated_company_type_beats_learned_one(monkeypatch):
    learned = {"culture_preference": "startup", "culture_preference_source": "learned"}
    assert _prefs(monkeypatch, {"company_type": "corporate"}, learned)["culture_preference"] == "corporate"
    assert _prefs(monkeypatch, {"company_type": "any"}, learned)["culture_preference"] == "startup"
    assert _prefs(monkeypatch, {}, learned)["culture_preference"] == "startup"


def test_industries_are_cleaned(monkeypatch):
    p = _prefs(monkeypatch, {"industries_prefer": ["cyber", "bogus"], "industries_avoid": ["gambling"]})
    assert p["industries_prefer"] == ["cyber"] and p["industries_avoid"] == ["gambling"]


def test_load_failure_means_no_preferences(monkeypatch):
    from backend.repositories import profile_repository
    def boom(uid):
        raise RuntimeError("db down")
    monkeypatch.setattr(profile_repository, "get_profile_json", boom)
    assert mss._load_culture_prefs("u1") == NO_PREFS


# ── Company industries from the companies table ──────────────────────────────

def test_industries_for_resolves_any_spelling():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    CompanyRow.__table__.create(eng)
    CompanyAliasRow.__table__.create(eng)
    with Session(eng) as s:
        repo.upsert_listing(s, name="Wix", company_url="https://il.linkedin.com/company/wix-com",
                            logo_url=None, industries=["Software Development"], source="linkedin")
        s.commit()
    assert repo.industries_for("Wix.com", engine=eng) == ["Software Development"]
    assert repo.industries_for("Unknown Co", engine=eng) == []
    assert repo.industries_for("Confidential", engine=eng) == []
