"""
Hebrew localization pass (services/cv_localize.py). A Hebrew CV kept English
role titles, skills and education because the main prompt mirrors an English
job description; this pass turns the whole CV into Israeli-market Hebrew and
is rejected if it changes a fact.
"""
import copy
import json
from types import SimpleNamespace

import pytest

from backend.services import cv_localize
from backend.services.cv_localize import localize_cv_to_hebrew, validate_localization

CV = {
    "header": {"target_title": "Junior Technical Implementation Specialist"},
    "summary": "Implementation specialist managing Onboarding for 1,000 B2B SaaS accounts.",
    "experience": [{"role": "Customer Success & Partnerships Team Lead", "company": "GO-OUT", "dates": "2023 - 2026",
                    "bullets": ["Led UAT cycles and QA sign-off for 12 releases.", "Managed 30 partners."]}],
    "education": [{"degree": "B.A. Business Administration", "institution": "Reichman University", "dates": "2020 - 2023"}],
    "skills": {"categories": [{"label": "Tools & Systems", "items": ["Jira", "Postman"]}]},
    "languages": [{"language": "Hebrew", "level": "Native"}],
}


def _hebrew(cv):
    he = copy.deepcopy(cv)
    he["header"]["target_title"] = "מומחה/ית הטמעה טכנולוגית"
    he["summary"] = "מומחה/ית הטמעה המנהל/ת תהליכי Onboarding עבור 1,000 לקוחות B2B SaaS."
    he["experience"][0]["role"] = "ראש צוות Customer Success ושותפויות"
    he["experience"][0]["bullets"] = ["הובלתי מחזורי UAT ואישור QA עבור 12 גרסאות.", "ניהלתי 30 שותפים."]
    he["education"][0].update(degree="תואר ראשון (B.A.) במנהל עסקים", institution="אוניברסיטת רייכמן")
    he["skills"]["categories"][0]["label"] = "כלים ומערכות"
    return he


def _model_returns(monkeypatch, payload):
    seen = {}

    async def fake(**kw):
        seen.update(kw)
        return SimpleNamespace(text=json.dumps(payload, ensure_ascii=False) if not isinstance(payload, str) else payload)
    monkeypatch.setattr("backend.services.llm_client.call_llm", fake)
    return seen


async def test_a_faithful_hebrew_version_is_used(monkeypatch):
    seen = _model_returns(monkeypatch, _hebrew(CV))
    out = await localize_cv_to_hebrew(CV, "jd", ["onboarding", "uat"], gender=None)
    assert out["experience"][0]["role"].startswith("ראש צוות")
    assert out["education"][0]["institution"] == "אוניברסיטת רייכמן"
    assert out["languages"] == CV["languages"]
    assert "KEY_TERMS (keep in English): onboarding, uat" in seen["messages"][0]["content"]
    assert "do not guess" in seen["system"]


async def test_a_version_that_changes_a_number_is_rejected(monkeypatch):
    bad = _hebrew(CV)
    bad["experience"][0]["bullets"][0] = "הובלתי מחזורי UAT עבור 15 גרסאות."
    _model_returns(monkeypatch, bad)
    assert await localize_cv_to_hebrew(CV, "jd", []) == CV


async def test_a_version_that_drops_a_bullet_or_renames_a_company_is_rejected(monkeypatch):
    dropped = _hebrew(CV)
    dropped["experience"][0]["bullets"].pop()
    assert validate_localization(CV, dropped).startswith("structure")
    renamed = _hebrew(CV)
    renamed["experience"][0]["company"] = "גו-אאוט"
    assert validate_localization(CV, renamed) == "companies changed"


async def test_a_model_failure_keeps_the_cv(monkeypatch):
    _model_returns(monkeypatch, "not json at all")
    assert await localize_cv_to_hebrew(CV, "jd", []) == CV


def test_gender_choice_reaches_the_prompt():
    assert "feminine" in cv_localize._GENDER_RULES["f"] and "masculine" in cv_localize._GENDER_RULES["m"]


async def test_tailor_passes_the_jd_keywords_the_cv_already_has(monkeypatch):
    from backend.agents import tailor
    captured = {}

    async def fake_localize(cv, jd, terms, **kw):
        captured["terms"] = terms
        return cv
    monkeypatch.setattr("backend.services.cv_localize.localize_cv_to_hebrew", fake_localize)
    monkeypatch.setattr("backend.services.match_score_service._extract_jd_keywords",
                        lambda jd: {"uat", "onboarding", "kubernetes"})
    await tailor._localize_hebrew(CV, "jd", "u1", None)
    assert captured["terms"] == ["onboarding", "uat"], "only terms the CV already contains"
