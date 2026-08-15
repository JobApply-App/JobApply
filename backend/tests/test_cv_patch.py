"""
RFC 6902 CV patching (backend/services/cv_patch_service.py).

Ariel used to answer every instruction by regenerating the whole CV, with
nothing but a prompt line asking it not to disturb the rest. These tests pin the
property that replaces that request with a guarantee: an edit can only touch the
paths it names, and every failure mode leaves the user's document exactly as it
was. A half-applied patch is the outcome worth engineering against — it corrupts
a document the user may have spent an hour on, in ways they cannot see.

Pure: no DB, no LLM, no network.
"""
from __future__ import annotations

import copy

import pytest

from backend.services.cv_patch_service import (
    MAX_OPS,
    apply_cv_patch,
    diff_cv,
    summarize_ops,
    validate_patch,
)


def _cv() -> dict:
    """A schema-valid canonical CV."""
    return {
        "header": {"full_name": "Ron", "target_title": "Product Manager",
                   "email": "r@example.com", "phone": "050", "location": "TLV",
                   "linkedin": "linkedin.com/in/ron"},
        "summary": "Managed a 40-account portfolio.",
        "experience": [
            {"company": "Acme", "role": "CSM", "dates": "2020 - 2023",
             "bullets": ["Cut churn by 12%.", "Onboarded 20 partners.", "Ran QBRs."]},
            {"company": "Globex", "role": "APM", "dates": "2018 - 2020", "bullets": ["Shipped X."]},
        ],
        "education": [{"degree": "BA Economics", "institution": "TAU", "dates": "2016 - 2019",
                       "honors": "", "coursework": ""}],
        "military_service": {"role_title": "Ops NCO", "unit_type": "IDF Logistics",
                             "dates": "2014 - 2016", "key_responsibilities": []},
        "skills": {"categories": [{"label": "Tools", "items": ["Salesforce", "Jira"]}]},
        "languages": [{"language": "Hebrew", "level": "Native"}],
        "volunteering": "",
    }


# ── Targeted edits ───────────────────────────────────────────────────────────

def test_single_bullet_edit_leaves_everything_else_byte_identical():
    """The core guarantee: untouched paths are untouched by construction."""
    before = _cv()
    frozen = copy.deepcopy(before)

    res = apply_cv_patch(before, [
        {"op": "replace", "path": "/experience/0/bullets/1", "value": "Onboarded 25 partners."}
    ])

    assert res.ok
    assert res.cv_data["experience"][0]["bullets"][1] == "Onboarded 25 partners."
    # every other location identical
    assert res.cv_data["experience"][0]["bullets"][0] == frozen["experience"][0]["bullets"][0]
    assert res.cv_data["experience"][0]["bullets"][2] == frozen["experience"][0]["bullets"][2]
    assert res.cv_data["experience"][1] == frozen["experience"][1]
    assert res.cv_data["summary"] == frozen["summary"]
    assert res.cv_data["skills"] == frozen["skills"]
    assert res.cv_data["education"] == frozen["education"]


def test_input_document_is_never_mutated_in_place():
    """Callers hold the pre-edit document; a mutation here corrupts their state."""
    before = _cv()
    frozen = copy.deepcopy(before)
    apply_cv_patch(before, [{"op": "replace", "path": "/summary", "value": "Changed."}])
    assert before == frozen


def test_append_bullet_with_dash_index():
    res = apply_cv_patch(_cv(), [
        {"op": "add", "path": "/experience/0/bullets/-", "value": "Led migration to a new CRM."}
    ])
    assert res.ok
    assert len(res.cv_data["experience"][0]["bullets"]) == 4
    assert res.cv_data["experience"][0]["bullets"][-1].startswith("Led migration")


def test_remove_a_bullet_shifts_the_rest():
    res = apply_cv_patch(_cv(), [{"op": "remove", "path": "/experience/0/bullets/0"}])
    assert res.ok
    assert res.cv_data["experience"][0]["bullets"] == ["Onboarded 20 partners.", "Ran QBRs."]


def test_multi_op_patch_applies_atomically():
    res = apply_cv_patch(_cv(), [
        {"op": "replace", "path": "/summary", "value": "New summary."},
        {"op": "replace", "path": "/experience/1/role", "value": "Product Manager"},
    ])
    assert res.ok
    assert res.cv_data["summary"] == "New summary."
    assert res.cv_data["experience"][1]["role"] == "Product Manager"


# ── Section add / delete ─────────────────────────────────────────────────────

def test_delete_whole_optional_section_via_null():
    res = apply_cv_patch(_cv(), [{"op": "replace", "path": "/military_service", "value": None}])
    assert res.ok
    assert res.cv_data["military_service"] is None


def test_add_a_whole_experience_entry():
    res = apply_cv_patch(_cv(), [{
        "op": "add", "path": "/experience/-",
        "value": {"company": "Initech", "role": "PM", "dates": "2016 - 2018", "bullets": ["Did work."]},
    }])
    assert res.ok
    assert len(res.cv_data["experience"]) == 3
    assert res.cv_data["experience"][-1]["company"] == "Initech"


def test_clear_an_array_section():
    res = apply_cv_patch(_cv(), [{"op": "replace", "path": "/education", "value": []}])
    assert res.ok
    assert res.cv_data["education"] == []


def test_add_a_skill_to_an_existing_category():
    res = apply_cv_patch(_cv(), [
        {"op": "add", "path": "/skills/categories/0/items/-", "value": "Looker"}
    ])
    assert res.ok
    assert "Looker" in res.cv_data["skills"]["categories"][0]["items"]


# ── Error recovery: the document must survive every failure ──────────────────

def test_broken_path_returns_the_original_untouched():
    """The most likely model error: an index that does not exist."""
    before = _cv()
    res = apply_cv_patch(before, [
        {"op": "replace", "path": "/experience/7/bullets/2", "value": "nope"}
    ])
    assert not res.ok
    assert res.error_kind == "apply_failed"
    assert res.cv_data == before


def test_partially_valid_patch_applies_nothing():
    """
    Op 1 is fine, op 2 is broken. Applying only the first would leave a document
    that is neither the original nor what the user asked for — and they would
    have no way to tell.
    """
    before = _cv()
    res = apply_cv_patch(before, [
        {"op": "replace", "path": "/summary", "value": "Valid change."},
        {"op": "replace", "path": "/experience/99/role", "value": "broken"},
    ])
    assert not res.ok
    assert res.cv_data == before
    assert res.cv_data["summary"] == "Managed a 40-account portfolio."


def test_patch_producing_an_invalid_cv_is_rejected():
    """Syntactically valid, semantically ruinous — caught by re-validating."""
    before = _cv()
    res = apply_cv_patch(before, [{"op": "replace", "path": "/summary", "value": "x" * 5000}])
    assert not res.ok
    assert res.error_kind == "invalid_result"
    assert res.cv_data == before


@pytest.mark.parametrize("bad,reason", [
    ("not a list",                              "not an array"),
    ([],                                        "empty"),
    ([{"path": "/summary", "value": "x"}],      "missing op"),
    ([{"op": "explode", "path": "/summary"}],   "unknown op"),
    ([{"op": "replace", "path": "summary", "value": "x"}], "path lacks leading slash"),
    ([{"op": "replace", "path": "/summary"}],   "missing value"),
    ([{"op": "move", "path": "/summary"}],      "missing from"),
])
def test_malformed_patches_are_rejected_before_touching_the_document(bad, reason):
    before = _cv()
    res = apply_cv_patch(before, bad)
    assert not res.ok, reason
    assert res.cv_data == before


def test_op_ceiling_blocks_a_disguised_full_rewrite():
    huge = [{"op": "replace", "path": "/summary", "value": f"v{i}"} for i in range(MAX_OPS + 1)]
    ok, err = validate_patch(huge)
    assert not ok and "over the" in err


# ── Zero-hallucination boundary ──────────────────────────────────────────────

def test_contact_fields_cannot_be_patched():
    """
    Contact details come from the verified profile. A patch reaching them would
    reintroduce exactly the hallucination risk the unified schema closed.
    """
    for path in ("/header/email", "/header/phone", "/header/full_name", "/header"):
        before = _cv()
        res = apply_cv_patch(before, [{"op": "replace", "path": path, "value": "attacker@evil.com"}])
        assert not res.ok, path
        assert res.error_kind == "forbidden"
        assert res.cv_data == before


def test_target_title_is_the_one_writable_header_field():
    """Positioning is model-authored; identity is not."""
    res = apply_cv_patch(_cv(), [
        {"op": "replace", "path": "/header/target_title", "value": "Senior Product Manager"}
    ])
    assert res.ok
    assert res.cv_data["header"]["target_title"] == "Senior Product Manager"
    assert res.cv_data["header"]["email"] == "r@example.com"   # untouched


def test_move_out_of_a_protected_path_is_blocked():
    before = _cv()
    res = apply_cv_patch(before, [
        {"op": "move", "from": "/header/email", "path": "/summary"}
    ])
    assert not res.ok
    assert res.cv_data == before


# ── test-op / stale state ────────────────────────────────────────────────────

def test_test_op_passes_when_the_document_matches():
    res = apply_cv_patch(_cv(), [
        {"op": "test", "path": "/experience/0/bullets/0", "value": "Cut churn by 12%."},
        {"op": "replace", "path": "/experience/0/bullets/0", "value": "Cut churn by 15%."},
    ])
    assert res.ok
    assert res.cv_data["experience"][0]["bullets"][0] == "Cut churn by 15%."


def test_test_op_fails_cleanly_on_stale_state():
    """
    The user edited that bullet while Ariel was thinking. Failing is correct —
    silently overwriting their edit with a rewrite of text that no longer exists
    is the outcome this op exists to prevent.
    """
    before = _cv()
    res = apply_cv_patch(before, [
        {"op": "test", "path": "/experience/0/bullets/0", "value": "text that is no longer there"},
        {"op": "replace", "path": "/experience/0/bullets/0", "value": "overwrite"},
    ])
    assert not res.ok
    assert res.cv_data == before


# ── diff (full-regeneration fallback) ────────────────────────────────────────

def test_diff_recovers_ops_from_a_full_document():
    """When the model ignores the patch format, the client still gets ops."""
    before = _cv()
    after = copy.deepcopy(before)
    after["summary"] = "Rewritten summary."
    ops = diff_cv(before, after)
    assert any(o["op"] == "replace" and o["path"] == "/summary" for o in ops)


def test_diff_round_trips_through_apply():
    before = _cv()
    after = copy.deepcopy(before)
    after["experience"][0]["bullets"][2] = "Ran quarterly business reviews."
    res = apply_cv_patch(before, diff_cv(before, after))
    assert res.ok
    assert res.cv_data == after


def test_diff_of_identical_documents_is_empty():
    assert diff_cv(_cv(), _cv()) == []


# ── summaries ────────────────────────────────────────────────────────────────

def test_summarize_ops_is_human_readable_and_hides_assertions():
    lines = summarize_ops([
        {"op": "test", "path": "/summary", "value": "x"},
        {"op": "replace", "path": "/summary", "value": "y"},
        {"op": "remove", "path": "/education/0"},
    ])
    assert lines == ["updated /summary", "removed /education/0"]
