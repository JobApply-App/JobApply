"""
Tests for the Company Culture Agent (JOB-19).

Covers:
  • Source-hint inference across the three scraper source types the issue
    names (ATS, job board, agency) plus the unknown fallback.
  • Payload normalization / schema validation — enum cleaning, culture_axis
    clamping at 1-decimal precision, list caps.
  • Sparse-data honesty — thin input produces an "unknown" low-confidence
    profile without any LLM call (Thin-JD principle mirror).
  • Output-schema stability for the Dynamic Matching Score consumer (JOB-20).
  • Constraint mapping against the JOB-18 baseline's hard constraints.
  • Per-company cache roundtrip, staleness, and the don't-cache-unknowns rule.

No LLM calls anywhere: the agent's sparse-input gate is exercised directly,
and cache tests use an isolated SQLite engine.
"""
import asyncio
import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.agents.company_culture import (
    CompanyCultureAgent,
    CompanyCultureProfile,
    build_profile_from_payload,
    build_sparse_profile,
    constraint_conflicts,
    get_culture_profile,
    infer_source_hint,
    is_stale,
    load_cached_profile,
    save_cached_profile,
)
from backend.core.database import Base
from backend.models.matching import CompanyCultureRow
from backend.models import application, ariel, job, kv, matching, profile  # noqa: F401

NOW = datetime(2026, 7, 10, tzinfo=timezone.utc)

# Consumed by JOB-20 — changing this set is a breaking schema change.
STABLE_SCHEMA_KEYS = {
    "company_key", "display_name", "culture_axis", "culture_category",
    "operational_pace", "formality", "work_model",
    "work_life_balance_signals", "accepted_persona_traits",
    "operational_needs", "evidence", "confidence", "source_hint",
    "researched_at",
}


@pytest.fixture
def engine(tmp_path):
    eng = create_engine(f"sqlite:///{tmp_path / 'culture_test.db'}")
    Base.metadata.create_all(eng)
    return eng


def _payload(**over) -> dict:
    base = {
        "culture_axis":              78.0,
        "culture_category":          "startup",
        "operational_pace":          "fast",
        "formality":                 "casual",
        "work_model":                "hybrid",
        "work_life_balance_signals": ["flexible hours"],
        "accepted_persona_traits":   ["scrappy generalist", "high ownership"],
        "operational_needs":         ["own onboarding end-to-end"],
        "evidence":                  ["'thrive in a fast-paced environment'"],
        "confidence":                "high",
    }
    base.update(over)
    return base


# ── Source-hint inference (3 source types per acceptance criteria) ────────────

def test_ats_sources_classified():
    assert infer_source_hint("comeet") == "ats"
    assert infer_source_hint("", "https://boards.greenhouse.io/acme/jobs/123") == "ats"
    assert infer_source_hint("", "https://jobs.lever.co/acme/456") == "ats"


def test_job_board_sources_classified():
    assert infer_source_hint("linkedin") == "job_board"
    assert infer_source_hint("drushim") == "job_board"
    assert infer_source_hint("", "https://www.alljobs.co.il/job/789") == "job_board"


def test_agency_sources_classified():
    assert infer_source_hint("gotfriends") == "agency"
    assert infer_source_hint("nisha") == "agency"
    assert infer_source_hint("ethosia") == "agency"


def test_unknown_source_falls_back():
    assert infer_source_hint("", "") == "unknown"
    assert infer_source_hint("company_site", "https://acme.example.com/careers") == "unknown"


def test_agency_beats_job_board_when_both_present():
    # An agency posting syndicated to a board is still agency-authored text.
    assert infer_source_hint("gotfriends", "https://linkedin.com/jobs/1") == "agency"


# ── Payload normalization / schema validation ─────────────────────────────────

def test_valid_payload_normalizes():
    p = build_profile_from_payload("Acme", _payload(), source_hint="ats", now=NOW)
    assert p.company_key == "acme"
    assert p.culture_axis == 78.0
    assert p.culture_category == "startup"
    assert p.work_model == "hybrid"
    assert p.source_hint == "ats"
    assert p.confidence == "high"


def test_culture_axis_clamped_and_one_decimal():
    assert build_profile_from_payload("A", _payload(culture_axis=150)).culture_axis == 100.0
    assert build_profile_from_payload("A", _payload(culture_axis=-5)).culture_axis == 0.0
    assert build_profile_from_payload("A", _payload(culture_axis=66.666)).culture_axis == 66.7


def test_invalid_enums_become_unknown():
    p = build_profile_from_payload("A", _payload(
        culture_category="mega-corp", operational_pace="frantic",
        formality="suit-and-tie", work_model="wework",
    ))
    assert p.culture_category == "unknown"
    assert p.operational_pace == "unknown"
    assert p.formality == "unknown"
    assert p.work_model == "unknown"


def test_list_fields_are_capped():
    p = build_profile_from_payload("A", _payload(
        evidence=[f"sig-{i}" for i in range(20)],
        accepted_persona_traits=[f"trait-{i}" for i in range(20)],
    ))
    assert len(p.evidence) == 8
    assert len(p.accepted_persona_traits) == 6


def test_company_key_normalization():
    p = build_profile_from_payload("GO-OUT (Startup)", _payload())
    assert p.company_key == "go_out_startup"


# ── Output-schema stability (JOB-20 contract) ─────────────────────────────────

def test_as_dict_schema_is_stable():
    p = build_profile_from_payload("Acme", _payload(), now=NOW)
    assert set(p.as_dict().keys()) == STABLE_SCHEMA_KEYS


def test_sparse_profile_uses_same_schema():
    assert set(build_sparse_profile("Acme", now=NOW).as_dict().keys()) == STABLE_SCHEMA_KEYS


# ── Sparse-data honesty (Thin-JD principle mirror) ────────────────────────────

@pytest.mark.asyncio
async def test_sparse_input_skips_llm_and_returns_unknown(monkeypatch):
    # If the LLM were called despite thin input, the missing/invalid API
    # response path would be hit — assert it is never reached by poisoning
    # the client factory.
    import anthropic

    def _explode(*a, **k):
        raise AssertionError("LLM must not be called on sparse input")

    monkeypatch.setattr(anthropic, "AsyncAnthropic", _explode)
    profile = await CompanyCultureAgent().analyze("Acme", "Senior PM", source="comeet")
    assert profile.culture_category == "unknown"
    assert profile.confidence == "low"
    assert profile.culture_axis == 50.0           # neutral, not fabricated
    assert profile.source_hint == "ats"           # metadata still recorded


@pytest.mark.asyncio
async def test_missing_api_key_degrades_honestly(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    profile = await CompanyCultureAgent().analyze(
        "Acme", "x" * 500, source="linkedin",
    )
    assert profile.culture_category == "unknown"
    assert profile.confidence == "low"


def test_sparse_profile_never_conflicts_with_constraints():
    sparse = build_sparse_profile("Acme")
    assert constraint_conflicts(sparse, {"work_model": "remote_only"}) == []


# ── Constraint mapping (JOB-18 bridge) ────────────────────────────────────────

def test_onsite_company_conflicts_with_remote_only_user():
    p = build_profile_from_payload("Acme", _payload(work_model="onsite"))
    conflicts = constraint_conflicts(p, {"work_model": "remote_only"})
    assert len(conflicts) == 1
    assert "remote-only" in conflicts[0]


def test_flexible_or_unknown_work_model_never_conflicts():
    for wm in ("flexible", "unknown", "hybrid", "remote"):
        p = build_profile_from_payload("Acme", _payload(work_model=wm))
        assert constraint_conflicts(p, {"work_model": "remote_only"}) == []


def test_flexible_user_never_conflicts():
    p = build_profile_from_payload("Acme", _payload(work_model="onsite"))
    assert constraint_conflicts(p, {"work_model": None}) == []


# ── LLM response parsing robustness ───────────────────────────────────────────

def test_extract_json_handles_fences_and_annotation_escape():
    from backend.agents.company_culture import _extract_json

    # Observed live (GO-OUT smoke test): markdown fences plus an annotation
    # escaping the string quotes — '"Tel-Aviv office" (onsite...)"'.
    raw = '''```json
{
  "culture_axis": 78,
  "culture_category": "startup",
  "operational_pace": "fast",
  "formality": "casual",
  "work_model": "onsite",
  "work_life_balance_signals": [],
  "accepted_persona_traits": [],
  "operational_needs": [],
  "evidence": [
    "growing at a crazy pace",
    "Tel-Aviv office" (onsite location specified)"
  ],
  "confidence": "high"
}
```'''
    data = _extract_json(raw)
    assert data["culture_category"] == "startup"
    assert data["evidence"][1] == "Tel-Aviv office (onsite location specified)"


def test_extract_json_repairs_truncation():
    from backend.agents.company_culture import _extract_json

    truncated = '{"culture_axis": 60, "culture_category": "scaleup", "evidence": ["signal one'
    data = _extract_json(truncated)
    assert data["culture_axis"] == 60


def test_extract_json_raises_on_garbage():
    from backend.agents.company_culture import _extract_json

    with pytest.raises(ValueError):
        _extract_json("no json here at all")


# ── Cache layer ────────────────────────────────────────────────────────────────

def test_cache_roundtrip(engine):
    p = build_profile_from_payload("Acme Corp", _payload(), source_hint="ats", now=NOW)
    assert save_cached_profile(p, engine=engine) is True
    loaded = load_cached_profile("Acme Corp", engine=engine)
    assert loaded is not None
    assert loaded.as_dict() == p.as_dict()


def test_cache_key_is_normalized(engine):
    p = build_profile_from_payload("Acme Corp", _payload(), now=NOW)
    save_cached_profile(p, engine=engine)
    # Different surface spellings of the same company hit the same row.
    assert load_cached_profile("acme-corp", engine=engine) is not None
    assert load_cached_profile("ACME  CORP", engine=engine) is not None


def test_staleness_window():
    fresh = build_profile_from_payload("A", _payload(), now=NOW - timedelta(days=29))
    stale = build_profile_from_payload("A", _payload(), now=NOW - timedelta(days=31))
    assert is_stale(fresh, now=NOW) is False
    assert is_stale(stale, now=NOW) is True
    assert is_stale(CompanyCultureProfile(
        company_key="a", display_name="A", researched_at="not-a-date"), now=NOW) is True


def test_corrupt_cache_row_treated_as_miss(engine):
    with Session(engine) as s:
        s.add(CompanyCultureRow(
            company_key="acme", display_name="Acme",
            profile_json="{not valid json", researched_at=NOW.isoformat(),
        ))
        s.commit()
    assert load_cached_profile("Acme", engine=engine) is None


# ── Cached-first entry point ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_fresh_cache_short_circuits_research(engine, monkeypatch):
    p = build_profile_from_payload("Acme", _payload(), now=NOW)
    save_cached_profile(p, engine=engine)

    async def _explode(self, *a, **k):
        raise AssertionError("analyze() must not run on a fresh cache hit")

    monkeypatch.setattr(CompanyCultureAgent, "analyze", _explode)
    got = await get_culture_profile("Acme", jd_text="irrelevant", engine=engine)
    assert got is not None
    assert got.culture_category == "startup"


@pytest.mark.asyncio
async def test_unknown_profiles_are_not_cached(engine, monkeypatch):
    # Sparse posting → unknown profile → must NOT occupy the cache slot,
    # so a later richer posting can still research the company.
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    got = await get_culture_profile("Acme", jd_text="x" * 500, engine=engine)
    assert got is not None
    assert got.culture_category == "unknown"
    assert load_cached_profile("Acme", engine=engine) is None


@pytest.mark.asyncio
async def test_empty_company_name_returns_none(engine):
    assert await get_culture_profile("", jd_text="y" * 500, engine=engine) is None
    assert await get_culture_profile("   ", jd_text="y" * 500, engine=engine) is None
    assert await get_culture_profile("!!!", jd_text="y" * 500, engine=engine) is None
