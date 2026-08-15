"""
CVDataSchema — the unified CV contract (backend/models/cv.py).

The schema exists to end a specific failure: the CV shape lived in a prompt
template, a TypeScript interface and a Zod schema at once, and adding a field
meant editing three files in two languages with nothing failing if you missed
one. These tests pin the two properties that make the model trustworthy enough
to be that single authority — it must accept every document already in the
database, and it must never invite the LLM to author contact details.

Pure: no DB, no LLM, no network.
"""
from __future__ import annotations

import pytest

from backend.models.cv import (
    LIMITS,
    CVDataSchema,
    MilitaryService,
)


# ── Legacy compatibility ─────────────────────────────────────────────────────
# The shapes below are copied from real rows in user_job_matches.tailored_cv.
# If these break, previously-generated CVs stop rendering for users who did
# nothing wrong.

_LEGACY_CV = {
    "title": "Customer Success Manager | Enterprise Account",
    "summary": "Managed a 40-account portfolio.",
    "experience": [{"role": "CSM", "company": "Acme", "dates": "2020 - 2023",
                    "bullets": ["Cut churn by 12%."]}],
    "education": [{"degree": "BA Economics", "institution": "TAU", "dates": "2016 - 2019",
                   "honors": "", "coursework": ""}],
    "military": {"role": "Clerk to Lieutenant Colonel", "unit": "IDF - Signal Corps",
                 "dates": "2018-03 - 2020-03"},
    "skills": {"categories": [{"label": "Tools", "items": ["Salesforce"]}]},
    "languages": [{"language": "Hebrew", "level": "Native"}],
    "volunteering": "",
}


def test_legacy_document_still_parses():
    cv = CVDataSchema.model_validate(_LEGACY_CV)
    assert cv.summary == "Managed a 40-account portfolio."
    assert cv.experience[0].company == "Acme"


def test_legacy_title_becomes_header_target_title():
    """Top-level `title` predates the header block."""
    cv = CVDataSchema.model_validate(_LEGACY_CV)
    assert cv.header.target_title == "Customer Success Manager | Enterprise Account"


def test_legacy_military_keys_map_to_canonical_names():
    cv = CVDataSchema.model_validate(_LEGACY_CV)
    assert cv.military_service is not None
    assert cv.military_service.role_title == "Clerk to Lieutenant Colonel"
    assert cv.military_service.unit_type == "IDF - Signal Corps"


def test_explicit_header_is_not_overwritten_by_legacy_title():
    """A caller that sets both keeps the explicit one."""
    cv = CVDataSchema.model_validate(
        {**_LEGACY_CV, "header": {"target_title": "Head of Product"}}
    )
    assert cv.header.target_title == "Head of Product"


# ── Absent sections ──────────────────────────────────────────────────────────
# A career-changer has no degree, a non-Israeli candidate no service record.
# Absent must mean absent — not an empty section that renders a bare heading.

@pytest.mark.parametrize("payload", [
    {},                                        # nothing at all
    {"military": {}},                          # legacy "no service"
    {"military": {"role": "", "unit": "x"}},   # legacy blank role
    {"military_service": None},                # canonical null
])
def test_missing_military_is_none_not_an_empty_section(payload):
    cv = CVDataSchema.model_validate(payload)
    assert cv.military_service is None
    assert "military_service" not in cv.present_sections()


def test_present_sections_reports_only_real_content():
    cv = CVDataSchema.model_validate({
        "summary": "  ",                                  # whitespace is not content
        "experience": [{"role": "PM"}],
        "education": [],
        "skills": {"categories": []},
        "volunteering": "",
    })
    assert cv.present_sections() == ["experience"]


def test_military_only_profile_is_valid():
    """A new graduate whose only real experience is service."""
    cv = CVDataSchema.model_validate({
        "military_service": {
            "role_title": "Operations NCO",
            "unit_type": "IDF Logistics",
            "key_responsibilities": ["Ran resupply for a 200-person battalion."],
        }
    })
    assert cv.present_sections() == ["military_service"]
    assert cv.military_service.is_present()
    assert len(cv.military_service.key_responsibilities) == 1


def test_empty_document_produces_no_sections():
    assert CVDataSchema.model_validate({}).present_sections() == []


# ── Zero-hallucination boundary ──────────────────────────────────────────────

def test_header_is_excluded_from_the_llm_schema():
    """
    The guard that stops the model being asked to author contact details.
    pdf_builder injects those from the user's verified profile; an invented
    phone number is undetectable to the reader and fatal to the application.
    """
    full = set(CVDataSchema.model_json_schema()["properties"])
    llm = set(CVDataSchema.llm_json_schema()["properties"])
    assert "header" in full
    assert "header" not in llm
    assert full - llm == {"header"}


def test_llm_schema_hint_is_json_and_carries_the_structure():
    import json
    parsed = json.loads(CVDataSchema.llm_schema_hint())
    assert "military_service" in parsed["properties"]
    assert "header" not in parsed["properties"]


# ── Limits ───────────────────────────────────────────────────────────────────

def test_limits_are_enforced_not_merely_documented():
    with pytest.raises(Exception):
        CVDataSchema.model_validate({"summary": "x" * (LIMITS["summary"] + 1)})


def test_limits_are_visible_in_the_llm_schema():
    """The prompt must state the same numbers the validator enforces —
    the drift this module exists to remove."""
    props = CVDataSchema.llm_json_schema()["properties"]
    assert props["summary"]["maxLength"] == LIMITS["summary"]


# ── Serialisation ────────────────────────────────────────────────────────────

def test_output_uses_canonical_names_never_legacy_aliases():
    """Aliases read old documents; they must never write new ones."""
    out = CVDataSchema.model_validate(_LEGACY_CV).to_render_dict()
    assert "military_service" in out and "military" not in out
    assert "title" not in out
    assert out["header"]["target_title"].startswith("Customer Success Manager")


def test_round_trip_is_stable():
    once = CVDataSchema.model_validate(_LEGACY_CV).to_render_dict()
    twice = CVDataSchema.model_validate(once).to_render_dict()
    assert once == twice


def test_unknown_keys_are_tolerated_not_fatal():
    """A newer producer must not hard-fail an older consumer."""
    cv = CVDataSchema.model_validate({**_LEGACY_CV, "some_future_section": [1, 2]})
    assert cv.experience[0].role == "CSM"


# ── Validation gate in tailor.py ─────────────────────────────────────────────

def test_validation_gate_is_non_fatal_and_normalizes():
    """
    The gate must never raise — a schema violation should not cost the user a
    generation they waited 30 seconds for — but it MUST still hand downstream
    code canonical keys, since _enforce_limits and pdf_builder now read those
    exclusively.
    """
    from backend.agents.tailor import validate_cv_schema
    bad = {"title": "x" * 500, "experience": [{"role": "PM"}]}
    out = validate_cv_schema(bad, context="test")
    assert "title" not in out
    assert out["header"]["target_title"]
    assert out["experience"][0]["role"] == "PM"


def test_military_is_present_requires_a_role():
    assert not MilitaryService(unit_type="IDF").is_present()
    assert MilitaryService(role_title="Ops NCO").is_present()


# ── Normalization choke point ────────────────────────────────────────────────

def test_normalize_maps_legacy_keys_to_canonical():
    from backend.models.cv import normalize_cv
    out = normalize_cv({"title": "PM", "military": {"role": "X", "unit": "Y"}})
    assert "title" not in out and "military" not in out
    assert out["header"]["target_title"] == "PM"
    assert out["military_service"]["role_title"] == "X"
    assert out["military_service"]["unit_type"] == "Y"


def test_over_length_field_does_not_drop_other_sections():
    """
    Regression. Normalization runs BEFORE tailor._enforce_limits clamps
    lengths, so a document whose title exceeds the limit fails strict
    validation. When that made normalization pass the payload through
    unchanged, it stayed shaped `military`, _enforce_limits looked for
    `military_service`, found nothing, and silently deleted the candidate's
    entire military section — data loss caused purely by a long title.
    """
    from backend.models.cv import normalize_cv
    out = normalize_cv({"title": "z" * 300, "military": {"role": "Staff Officer", "unit": "IDF"}})
    assert "military" not in out
    assert out["military_service"]["role_title"] == "Staff Officer"
    assert out["header"]["target_title"]  # preserved for the clamp to trim


def test_enforce_limits_reads_canonical_keys_and_preserves_military():
    from backend.agents.tailor import _enforce_limits
    from backend.models.cv import normalize_cv
    out = _enforce_limits(normalize_cv(
        {"title": "x" * 80, "military": {"role": "Staff Officer", "unit": "IDF"}}
    ))
    assert out["military_service"]["role_title"] == "Staff Officer"
    assert len(out["header"]["target_title"]) <= LIMITS["target_title"]


def test_absent_military_normalizes_to_none_not_empty_dict():
    """An empty object would render a bare 'Military Service' heading."""
    from backend.models.cv import normalize_cv
    assert normalize_cv({"title": "PM", "military": {}})["military_service"] is None
    assert normalize_cv({"title": "PM"})["military_service"] is None


def test_normalize_is_idempotent():
    from backend.models.cv import normalize_cv
    once = normalize_cv({"title": "PM", "military": {"role": "X", "unit": "Y"}})
    assert normalize_cv(once) == once


def test_normalize_tolerates_non_dict_input():
    from backend.models.cv import normalize_cv
    assert normalize_cv(None) == {}
    assert normalize_cv("not a cv") == {}
