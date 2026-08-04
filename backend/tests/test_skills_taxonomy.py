"""
Global skills taxonomy (JOB-138): canonicalization, synonym resolution, and
duplicate prevention across profile_entities <-> skills_taxonomy.

Covers:
  * Synonym resolution — "ReactJS"/"React.js"/"ריאקט" all resolve to the
    same canonical "React" taxonomy row (backend/services/
    skills_taxonomy_service.py's resolve_skill()).
  * Duplicate prevention — a user stating "ניהול" and later "לנהל" (two
    different Hebrew surface forms of "Management") ends up with exactly
    ONE profile_entities row and ONE skills_taxonomy row, not two unrelated
    entities (ProfileUpdateService._upsert_entity's skill_id-based dedup,
    which runs BEFORE the older normalized_name check).
  * Proficiency/experience metadata extraction — ingest_cv_parse() writes
    proficiency_level/years_of_experience/last_used_year onto the entity
    when the caller (in production: _cv_claims_to_parsed_entities, fed by
    the CV-extraction LLM) supplies them, and never fabricates a value that
    wasn't provided.
  * _cv_claims_to_parsed_entities' skill_details mapping (pure function,
    no DB) — the CV-aggregation-output shape this feature actually
    consumes.

Postgres-only throughout (skills_taxonomy uses real array/uuid SQL with no
SQLite equivalent) — every DB-touching test takes db_available and skips
cleanly without it.

Cleanup discipline (important — this migration also backfilled 121 REAL
skill entities across real accounts, several under the exact seed-dict
canonical names this file exercises, e.g. "React"/"Python"/"Management"):
never delete a skills_taxonomy row here — the seed-dict canonical names are
global and almost certainly already shared by real data (confirmed: e.g.
"React" is already referenced by a real account's evidence-backed entity).
Only ever delete a profile_entities row by its own specific entity_id, one
this test itself just created — never by skill_id/canonical_name, which
could reach into unrelated real rows sharing that same global taxonomy
concept. Tests that need a taxonomy row created and safely removable use a
randomly-suffixed throwaway skill name instead of a real seeded one.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from backend.services.skills_taxonomy_service import (
    STANDARD_CATEGORIES,
    _clean_key,
    _fallback_canonical,
    resolve_skill,
)

# Real account, reused elsewhere in this suite (test_skill_entity_merge.py,
# test_profile_baseline.py) — profile_entities.user_id has a hard FK to
# auth.users, so an arbitrary UUID can't be used.
_QA_USER = "2631c93b-93bb-4313-a2c2-79dbb786d199"


def _unique_skill_name(label: str) -> str:
    return f"Zztest {label} {uuid.uuid4().hex[:8]}"


@pytest.fixture()
def cleanup_entities(db_available):
    """
    Tracks specific entity_ids created during a test and deletes exactly
    those rows (plus their evidence_records/confidence_audit_log, to satisfy
    the FK) on teardown — never a blanket delete by skill_id or
    canonical_name, which could reach real data sharing the same global
    taxonomy concept (see this module's docstring).
    """
    from backend.core.database import ENGINE

    created_entity_ids: list[str] = []
    yield created_entity_ids

    if not created_entity_ids:
        return
    with ENGINE.begin() as conn:
        conn.execute(text("DELETE FROM evidence_records WHERE entity_id = ANY(:ids)"),
                      {"ids": created_entity_ids})
        conn.execute(text("DELETE FROM confidence_audit_log WHERE entity_id = ANY(:ids)"),
                      {"ids": created_entity_ids})
        conn.execute(text("DELETE FROM profile_entities WHERE entity_id = ANY(:ids)"),
                      {"ids": created_entity_ids})


@pytest.fixture()
def cleanup_taxonomy_rows(db_available):
    """
    Tracks canonical_names created during a test — used ONLY for randomly-
    suffixed throwaway skill names (never a real seed-dict canonical like
    "React"), so it's always safe to delete the whole taxonomy row: nothing
    else could reference a name with a random hex suffix.
    """
    from backend.core.database import ENGINE

    created_canonical_names: list[str] = []
    yield created_canonical_names

    if not created_canonical_names:
        return
    with ENGINE.begin() as conn:
        conn.execute(text("DELETE FROM skills_taxonomy WHERE canonical_name = ANY(:names)"),
                      {"names": created_canonical_names})


# ── Pure helpers (no DB) ──────────────────────────────────────────────────────

def test_clean_key_is_case_and_whitespace_insensitive():
    assert _clean_key("  ReactJS  ") == "reactjs"
    assert _clean_key("Machine   Learning") == "machine learning"
    assert _clean_key("") == ""
    assert _clean_key(None) == ""


def test_fallback_canonical_title_cases_unknown_skills():
    assert _fallback_canonical("some totally new skill") == "Some Totally New Skill"
    assert _fallback_canonical("  extra   spaces  ") == "Extra Spaces"


def test_standard_categories_includes_uncategorized_fallback():
    assert "Uncategorized" in STANDARD_CATEGORIES


# ── Synonym resolution ────────────────────────────────────────────────────────
# These resolve against the REAL, shared seed-dict canonical rows (already
# present in Dev from the migration backfill) — read-only assertions, no
# cleanup, nothing created or touched.

def test_synonym_resolution_reactjs_and_hebrew_map_to_same_canonical(db_available):
    from backend.core.database import ENGINE

    r1 = resolve_skill(ENGINE, "ReactJS")
    r2 = resolve_skill(ENGINE, "React.js")
    r3 = resolve_skill(ENGINE, "ריאקט")

    assert r1["id"] == r2["id"] == r3["id"]
    assert r1["canonical_name"] == "React"
    assert r1["category"] == "Engineering"


def test_synonym_resolution_case_insensitive(db_available):
    from backend.core.database import ENGINE

    r1 = resolve_skill(ENGINE, "PYTHON")
    r2 = resolve_skill(ENGINE, "python")

    assert r1["id"] == r2["id"]
    assert r1["canonical_name"] == "Python"


def test_unknown_skill_gets_a_new_taxonomy_row_and_is_reused_on_repeat(db_available, cleanup_taxonomy_rows):
    from backend.core.database import ENGINE

    name = _unique_skill_name("Unknown Skill")
    r1 = resolve_skill(ENGINE, name)
    cleanup_taxonomy_rows.append(r1["canonical_name"])
    r2 = resolve_skill(ENGINE, name)

    assert r1["id"] == r2["id"], "resolving the same new skill twice must not create two rows"
    assert r1["category"] == "Uncategorized"


def test_blank_input_resolves_to_nothing(db_available):
    from backend.core.database import ENGINE

    assert resolve_skill(ENGINE, "") is None
    assert resolve_skill(ENGINE, "   ") is None


# ── Duplicate prevention at the entity level (the ticket's own scenario) ─────
# "ניהול"/"לנהל" resolve to the real, shared "Management" taxonomy row (also
# already real data in Dev) — this section never deletes that row, only the
# one NEW profile_entities row this test itself creates for _QA_USER (if
# _QA_USER doesn't already have a Management entity; if it does, the dedup
# check against the EXISTING real row is itself the test).

def test_hebrew_management_synonyms_produce_one_entity_for_this_user(db_available, cleanup_entities):
    """
    The exact JOB-138 acceptance scenario: a user's profile states "ניהול"
    and, separately, "לנהל" — both Hebrew surface forms of "Management".
    This must NOT create two unrelated profile_entities rows; it's one
    capability, stated twice in different words. Whether _QA_USER already
    has a Management entity or not, both calls must return the SAME
    entity_id — that's the property under test, not whether the row is new.
    """
    from backend.core.database import ENGINE
    from backend.services.profile_update_service import ProfileUpdateService

    svc = ProfileUpdateService(ENGINE)
    with ENGINE.connect() as conn:
        pre_existing = conn.execute(text("""
            SELECT entity_id FROM profile_entities
            WHERE user_id = CAST(:u AS uuid) AND skill_id = (
                SELECT id FROM skills_taxonomy WHERE canonical_name = 'Management'
            )
        """), {"u": _QA_USER}).fetchone()

    with ENGINE.begin() as conn:
        entity_id_1 = svc._upsert_entity(conn, _QA_USER, "skill", "ניהול")
        entity_id_2 = svc._upsert_entity(conn, _QA_USER, "skill", "לנהל")

    assert entity_id_1 == entity_id_2, "ניהול and לנהל must resolve to the SAME entity for this user"

    with ENGINE.connect() as conn:
        entity_count = conn.execute(
            text("SELECT count(*) FROM profile_entities WHERE entity_id = :e"),
            {"e": entity_id_1},
        ).scalar()
        row = conn.execute(
            text("SELECT skill_id FROM profile_entities WHERE entity_id = :e"),
            {"e": entity_id_1},
        ).fetchone()

    assert entity_count == 1, "exactly one user link (profile_entities row)"
    assert row.skill_id is not None

    if pre_existing is None:
        # This test created a genuinely new row — safe to remove afterward.
        cleanup_entities.append(entity_id_1)
    else:
        # _QA_USER already had a Management entity before this test ran;
        # both calls correctly returned it unchanged — nothing to clean up.
        assert entity_id_1 == pre_existing.entity_id


def test_two_different_skills_never_collapse_into_one_entity(db_available, cleanup_entities, cleanup_taxonomy_rows):
    """Sanity check on the other direction: genuinely different skills must
    stay genuinely different entities — dedup only applies to real
    synonyms. Uses throwaway names so this is fully isolated from real data."""
    from backend.core.database import ENGINE
    from backend.services.profile_update_service import ProfileUpdateService

    name_a = _unique_skill_name("Skill Alpha")
    name_b = _unique_skill_name("Skill Beta")
    svc = ProfileUpdateService(ENGINE)

    with ENGINE.begin() as conn:
        eid_a = svc._upsert_entity(conn, _QA_USER, "skill", name_a)
        eid_b = svc._upsert_entity(conn, _QA_USER, "skill", name_b)

    assert eid_a != eid_b
    cleanup_entities.extend([eid_a, eid_b])
    cleanup_taxonomy_rows.extend([_fallback_canonical(name_a), _fallback_canonical(name_b)])


# ── Proficiency / experience metadata extraction ─────────────────────────────

def test_ingest_cv_parse_writes_supplied_skill_metadata(db_available, cleanup_entities, cleanup_taxonomy_rows):
    from backend.core.database import ENGINE
    from backend.services.profile_update_service import ProfileUpdateService

    name = _unique_skill_name("Metadata Skill")
    svc = ProfileUpdateService(ENGINE)

    entity_ids = svc.ingest_cv_parse(_QA_USER, [{
        "entity_type": "skill", "name": name, "raw_content": "",
        "proficiency_level": "advanced", "years_of_experience": 4.5, "last_used_year": 2025,
    }])
    entity_id = entity_ids[0]
    cleanup_entities.append(entity_id)
    cleanup_taxonomy_rows.append(_fallback_canonical(name))

    with ENGINE.connect() as conn:
        row = conn.execute(
            text("SELECT proficiency_level, years_of_experience, last_used_year, skill_id, raw_text "
                 "FROM profile_entities WHERE entity_id = :e"),
            {"e": entity_id},
        ).fetchone()

    assert row.proficiency_level == "advanced"
    assert float(row.years_of_experience) == 4.5
    assert row.last_used_year == 2025
    assert row.skill_id is not None
    assert row.raw_text == name


def test_ingest_cv_parse_never_fabricates_omitted_metadata(db_available, cleanup_entities, cleanup_taxonomy_rows):
    """A skill entity with no proficiency/years/last-used info supplied must
    stay NULL, not default to some fabricated value."""
    from backend.core.database import ENGINE
    from backend.services.profile_update_service import ProfileUpdateService

    name = _unique_skill_name("No Metadata Skill")
    svc = ProfileUpdateService(ENGINE)

    entity_ids = svc.ingest_cv_parse(_QA_USER, [
        {"entity_type": "skill", "name": name, "raw_content": ""},
    ])
    entity_id = entity_ids[0]
    cleanup_entities.append(entity_id)
    cleanup_taxonomy_rows.append(_fallback_canonical(name))

    with ENGINE.connect() as conn:
        row = conn.execute(
            text("SELECT proficiency_level, years_of_experience, last_used_year "
                 "FROM profile_entities WHERE entity_id = :e"),
            {"e": entity_id},
        ).fetchone()

    assert row.proficiency_level is None
    assert row.years_of_experience is None
    assert row.last_used_year is None


# ── _cv_claims_to_parsed_entities (pure, no DB) ──────────────────────────────

def test_cv_claims_skill_details_produce_entities_with_metadata():
    from backend.api.routes.profile import _cv_claims_to_parsed_entities

    entities = _cv_claims_to_parsed_entities({
        "skills": ["React", "Excel"],
        "skill_details": [
            {"name": "React", "proficiency_level": "expert",
             "years_of_experience": 5, "last_used_year": 2026},
        ],
    })

    skill_entities = [e for e in entities if e["entity_type"] == "skill"]
    by_name = {e["name"]: e for e in skill_entities}

    assert len(skill_entities) == 2, "React (with details) + Excel (plain) — no duplicate React entry"
    assert by_name["React"]["proficiency_level"] == "expert"
    assert by_name["React"]["years_of_experience"] == 5
    assert by_name["React"]["last_used_year"] == 2026
    assert "proficiency_level" not in by_name["Excel"]


def test_cv_claims_skill_details_case_insensitive_dedup_against_flat_skills():
    from backend.api.routes.profile import _cv_claims_to_parsed_entities

    entities = _cv_claims_to_parsed_entities({
        "skills": ["react"],   # lowercase, as sometimes emitted
        "skill_details": [{"name": "React", "proficiency_level": "", "years_of_experience": None, "last_used_year": None}],
    })
    skill_entities = [e for e in entities if e["entity_type"] == "skill"]
    assert len(skill_entities) == 1, "'react' and 'React' must be recognized as the same skill, not duplicated"


def test_cv_claims_missing_skill_details_key_falls_back_cleanly():
    """Older/degraded LLM output without skill_details must still work —
    this key is additive, not required."""
    from backend.api.routes.profile import _cv_claims_to_parsed_entities

    entities = _cv_claims_to_parsed_entities({"skills": ["Kubernetes"]})
    skill_entities = [e for e in entities if e["entity_type"] == "skill"]
    assert len(skill_entities) == 1
    assert skill_entities[0]["name"] == "Kubernetes"
    assert "proficiency_level" not in skill_entities[0]


# ── tailor.py synonym-aware ranking (integration with the taxonomy) ─────────

def test_tailor_ranks_skill_ahead_using_taxonomy_synonym(db_available):
    """A JD that says 'ReactJS' must credit a profile skill stored as
    'React' — proves the taxonomy synonym map actually changes ranking
    outcomes, not just that the lookup function returns something. Reads
    the real, shared React taxonomy row — nothing created, nothing to
    clean up."""
    from backend.agents.tailor import _build_skill_synonym_map, _rank_skills_by_jd_relevance

    skills = ["Excel", "React"]
    jd = "We need someone with strong ReactJS skills."

    without_synonyms = _rank_skills_by_jd_relevance(skills, jd)
    assert without_synonyms == ["Excel", "React"], "baseline: exact-match only puts React last"

    synonym_map = _build_skill_synonym_map(skills)
    with_synonyms = _rank_skills_by_jd_relevance(skills, jd, synonym_map)
    assert with_synonyms[0] == "React", "React must rank first once its ReactJS synonym is known"
