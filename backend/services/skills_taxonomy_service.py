"""
Global skills taxonomy — canonicalization service.

profile_entities used to store skills as flat, uncanonicalized strings:
"Management", "ניהול", "Managing", and "לנהל" were four unrelated entities,
each independently scored, even though they name the same real-world
capability. This module is the single choke point that resolves a raw
extracted skill string to one canonical, globally-shared skills_taxonomy
row — every write path that creates a skill entity (CV parse, chat
self-assertion, certification ingest, conversation-event ingest, and
profile_repository's CV-claim sync) must go through resolve_skill()
instead of writing name/normalized_name independently, or the same skill
will fragment across the two currently-independent choke points again
(see backend/services/profile_update_service.py's _upsert_entity and
backend/repositories/profile_repository.py's _write_skill_entities — this
module is imported by both).

Deliberately NOT an LLM call per resolution: canonicalization needs to be
consistent across thousands of independent extraction calls (a CV-parse LLM
call for user A and a chat tool-call for user B must agree that "ReactJS"
and "React" are the same skill), which a stateless LLM call re-deciding from
scratch every time cannot guarantee. A lookup-and-grow table can. The static
_SYNONYM_SEED below covers the common cases the taxonomy starts with; any
skill not covered gets a deterministic fallback (title-cased) and is
inserted as its own new taxonomy row — the taxonomy grows from real usage,
it isn't meant to be exhaustively pre-populated.

_SYNONYM_SEED is intentionally identical to the one hardcoded into migration
90b20294d1d3's backfill — duplicated on purpose (see that migration's
docstring: migrations must not import application code, since app code can
move/change shape/be deleted while old migration history must keep working
unchanged).
"""
from __future__ import annotations

import logging
import re
import uuid
from typing import Optional

from sqlalchemy import text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)


# canonical form -> (canonical_name, category). Keys are the output of
# _clean_key() — lowercase, whitespace-collapsed — so lookups are case- and
# whitespace-insensitive without needing per-entry variants for that.
_SYNONYM_SEED: dict[str, tuple[str, str]] = {
    "management":  ("Management", "Management"),
    "managing":    ("Management", "Management"),
    "manage":      ("Management", "Management"),
    "ניהול":        ("Management", "Management"),
    "לנהל":         ("Management", "Management"),
    "react":       ("React", "Engineering"),
    "reactjs":     ("React", "Engineering"),
    "react.js":    ("React", "Engineering"),
    "ריאקט":        ("React", "Engineering"),
    "python":      ("Python", "Engineering"),
    "sql":         ("SQL", "Data"),
    "javascript":  ("JavaScript", "Engineering"),
    "js":          ("JavaScript", "Engineering"),
    "machine learning": ("Machine Learning", "Data"),
    "ml":          ("Machine Learning", "Data"),
    "kubernetes":  ("Kubernetes", "Engineering"),
    "k8s":         ("Kubernetes", "Engineering"),
    "excel":       ("Excel", "Data"),
    "figma":       ("Figma", "Product"),
    "jira":        ("Jira", "Product"),
    "scrum":       ("Scrum", "Product"),
    "agile":       ("Agile", "Product"),
    "customer success": ("Customer Success", "Customer Success"),
    "stakeholder management": ("Stakeholder Management", "Management"),
}

# Standard categories this service will assign — informational only (no DB
# CHECK constraint), documents the intended vocabulary so new fallback/seed
# entries stay consistent rather than inventing ad hoc category strings.
STANDARD_CATEGORIES = frozenset({
    "Engineering", "Product", "Management", "Soft Skills",
    "Marketing", "Data", "Customer Success", "Uncategorized",
})


def _clean_key(raw: str) -> str:
    """Case/whitespace-insensitive lookup key — mirrors the migration's helper."""
    return re.sub(r"\s+", " ", (raw or "").strip().lower())


def _fallback_canonical(raw: str) -> str:
    """Deterministic canonical form for a skill with no seed/taxonomy match yet."""
    return re.sub(r"\s+", " ", (raw or "").strip()).title()


def resolve_skill(engine: Engine, raw_text: str) -> Optional[dict]:
    """
    Resolve a raw extracted skill string to a canonical skills_taxonomy row,
    inserting a new one if this exact canonical form doesn't exist yet.

    Returns {"id": str, "canonical_name": str, "category": str}, or None if
    raw_text is blank (nothing to resolve).

    Lookup order:
      1. _SYNONYM_SEED, by cleaned key — the curated common-case fast path.
      2. skills_taxonomy.canonical_name, case-insensitive exact match — a
         skill already resolved once (by this or a prior call, from any
         user) is reused rather than duplicated.
      3. skills_taxonomy.synonyms, case-insensitive containment — a raw form
         already recorded as a synonym of an existing canonical skill.
      4. Fallback: title-cased raw_text becomes a brand-new canonical_name,
         category "Uncategorized", inserted now.

    Every non-seed resolution that used a raw form other than the canonical
    name itself appends that raw form to the matched row's synonyms array
    (deduplicated), so the taxonomy actually learns synonyms over time
    instead of just accumulating unlinked near-duplicate rows.
    """
    cleaned = _clean_key(raw_text)
    if not cleaned:
        return None

    seed = _SYNONYM_SEED.get(cleaned)
    if seed:
        canonical_name, category = seed
    else:
        canonical_name, category = None, None

    with engine.begin() as conn:
        if canonical_name:
            row = conn.execute(
                text("SELECT id, canonical_name, category FROM public.skills_taxonomy "
                     "WHERE lower(canonical_name) = lower(:name)"),
                {"name": canonical_name},
            ).fetchone()
            if row is None:
                row = _insert_taxonomy_row(conn, canonical_name, category)
            _maybe_add_synonym(conn, row.id, raw_text, canonical_name)
            return {"id": str(row.id), "canonical_name": row.canonical_name, "category": row.category}

        # No seed hit — try an exact canonical_name match on the raw text itself
        # (handles the common case where the raw text already IS a clean,
        # previously-seen canonical form, e.g. a second user who also wrote
        # "Excel").
        row = conn.execute(
            text("SELECT id, canonical_name, category FROM public.skills_taxonomy "
                 "WHERE lower(canonical_name) = lower(:name)"),
            {"name": raw_text.strip()},
        ).fetchone()
        if row is not None:
            return {"id": str(row.id), "canonical_name": row.canonical_name, "category": row.category}

        # Try matching against existing synonyms arrays.
        row = conn.execute(
            text("SELECT id, canonical_name, category FROM public.skills_taxonomy "
                 "WHERE :raw = ANY(synonyms) OR lower(:raw) = ANY(SELECT lower(s) FROM unnest(synonyms) AS s)"),
            {"raw": raw_text.strip()},
        ).fetchone()
        if row is not None:
            return {"id": str(row.id), "canonical_name": row.canonical_name, "category": row.category}

        # Nothing matched anywhere — this is a genuinely new skill concept.
        canonical_name = _fallback_canonical(raw_text)
        row = conn.execute(
            text("SELECT id, canonical_name, category FROM public.skills_taxonomy "
                 "WHERE lower(canonical_name) = lower(:name)"),
            {"name": canonical_name},
        ).fetchone()
        if row is None:
            row = _insert_taxonomy_row(conn, canonical_name, "Uncategorized")
        return {"id": str(row.id), "canonical_name": row.canonical_name, "category": row.category}


def _insert_taxonomy_row(conn, canonical_name: str, category: str):
    new_id = str(uuid.uuid4())
    conn.execute(
        text("INSERT INTO public.skills_taxonomy (id, canonical_name, category, synonyms, created_at) "
             "VALUES (CAST(:id AS uuid), :name, :cat, '{}', now())"),
        {"id": new_id, "name": canonical_name, "cat": category},
    )
    logger.info("[skills_taxonomy] new canonical skill created: %r (category=%s, id=%s)",
                canonical_name, category, new_id)
    row = conn.execute(
        text("SELECT id, canonical_name, category FROM public.skills_taxonomy WHERE id = CAST(:id AS uuid)"),
        {"id": new_id},
    ).fetchone()
    return row


def _maybe_add_synonym(conn, taxonomy_id, raw_text: str, canonical_name: str) -> None:
    """Record a seed-resolved raw form as a synonym, if it isn't the canonical
    name itself and isn't already recorded."""
    raw = raw_text.strip()
    if not raw or raw.lower() == canonical_name.lower():
        return
    conn.execute(
        text("""
            UPDATE public.skills_taxonomy
            SET synonyms = CASE
                WHEN :raw = ANY(synonyms) THEN synonyms
                ELSE array_append(synonyms, :raw)
            END
            WHERE id = :id
        """),
        {"raw": raw, "id": taxonomy_id},
    )
