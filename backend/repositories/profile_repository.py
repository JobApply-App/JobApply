"""
Repository for the relational profile schema (profiles / user_preferences /
profile_answers / cv_documents / cv_claims) — the Phase 3 replacement for
master_profile_repository.py / the master_profiles table.

Design
------
Every caller in this codebase (ariel_tools.py's handlers, master_profile_service,
feedback_service, profile_baseline_service, the profile/chat/auth routes) was
built around one shape: a mutable "master_profile" JSON document plus a few
scalar columns (email, is_admin, onboarding_status, updated_at) on one row per
user. That document is open-ended — callers add whatever top-level keys they
need (experience, skills, career_goals, role_preferences, metrics_doc,
baseline_snapshot, enriched_entities, user_persona, cv_data, ...) with no
fixed schema.

Rather than force every caller to learn five new tables' worth of typed
columns, ProfileHandle below reproduces that same "row with a JSON document"
shape, backed by the new schema instead of master_profiles:

  - profiles: typed projection of personal/contact fields + the three
    always-scalar columns (email, is_admin, onboarding_status) that the app
    genuinely queries by column (deps.py's admin check, tenant_registry's
    onboarding-complete scan, auth.py's email-match lookup).
  - cv_documents/cv_claims: skills/experience/education/professional_summary/
    cv_imported_at — the one sub-structure with real typed shape (claim_type
    CHECK constraint), so these get a real decomposition rather than a blob.
  - profile_answers: everything else, generically. One row per top-level
    document key (question_id = key, answer = JSON-encoded value), replaced
    wholesale on every save — the same "whole column overwritten" semantics
    master_profiles.master_profile had, just spread across rows instead of
    packed into one JSON column. This is what keeps the cutover lossless
    without having to enumerate and hand-migrate every ad-hoc key any handler
    has ever written (baseline_snapshot, enriched_entities, user_persona,
    cv_data, metrics_doc, role_preferences, career_goals, personal, ...).

get_or_create()/get()/save() intentionally mirror master_profile_repository's
old signatures (session-scoped get_or_create + caller commits, standalone
get() with its own session) so call sites only need s/MasterProfileRow
handling/ProfileHandle handling/ — the mutation logic inside each handler
(deepcopy the dict, mutate a key, reassign) is unchanged.
"""
from __future__ import annotations

import json
import logging
import uuid as _uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from backend.core.database import ENGINE

logger = logging.getLogger(__name__)

# Top-level document keys backed by cv_documents/cv_claims rather than a
# generic profile_answers row.
_CV_KEYS = ("skills", "experience", "education", "professional_summary", "cv_imported_at")


@dataclass
class ProfileHandle:
    """Drop-in replacement for a MasterProfileRow, backed by the new schema."""
    user_id: str
    email: Optional[str] = None
    is_admin: bool = False
    onboarding_status: str = "incomplete"
    master_profile: dict = field(default_factory=dict)
    updated_at: str = ""


def _is_valid_uuid(value) -> bool:
    try:
        _uuid.UUID(str(value))
        return True
    except (ValueError, AttributeError, TypeError):
        return False


# ── Read ──────────────────────────────────────────────────────────────────────

def _read_cv(session: Session, user_id: str) -> dict:
    doc = session.execute(
        text("SELECT id, summary, uploaded_at FROM public.cv_documents WHERE user_id = CAST(:uid AS uuid) LIMIT 1"),
        {"uid": user_id},
    ).fetchone()
    result = {
        "skills": [], "experience": [], "education": [],
        "professional_summary": "", "cv_imported_at": None,
    }
    if doc is None:
        return result

    result["professional_summary"] = doc.summary or ""
    result["cv_imported_at"] = doc.uploaded_at.isoformat() if doc.uploaded_at else None

    # Employment and education records stay in cv_claims — they are dated CV
    # entries, not capabilities (see migration fa884910ef1d).
    claims = session.execute(
        text("SELECT claim_type, content FROM public.cv_claims WHERE document_id = :doc ORDER BY created_at"),
        {"doc": doc.id},
    ).fetchall()
    for claim_type, content in claims:
        if claim_type == "experience":
            result["experience"].append(content)
        elif claim_type == "education":
            result["education"].append(content)

    # Skills live in profile_entities, where they also carry a confidence
    # score. source_document_id is what marks a capability as currently
    # claimed on the CV, so this returns exactly the list that used to come
    # back from cv_claims — the other ~80 scored entities (inferred, derived,
    # conversation-sourced) are Confidence Matrix state, not CV content, and
    # must not leak into the profile document.
    skills = session.execute(
        text("""
            SELECT name FROM public.profile_entities
            WHERE user_id = CAST(:uid AS uuid)
              AND entity_type = 'skill'
              AND source_document_id = :doc
            ORDER BY created_at
        """),
        {"uid": user_id, "doc": doc.id},
    ).fetchall()
    result["skills"] = [r[0] for r in skills]
    return result


def _read_generic(session: Session, user_id: str) -> dict:
    rows = session.execute(
        text("SELECT question_id, answer FROM public.profile_answers WHERE user_id = CAST(:uid AS uuid)"),
        {"uid": user_id},
    ).fetchall()
    return {qid: answer for qid, answer in rows}


def _read_full_dict(session: Session, user_id: str) -> dict:
    result = _read_generic(session, user_id)
    cv = _read_cv(session, user_id)
    non_empty_cv = {k: v for k, v in cv.items() if v}
    result.update(non_empty_cv)
    return result


def _row_to_handle(row, user_id: str, mp: dict) -> ProfileHandle:
    return ProfileHandle(
        user_id=user_id,
        email=row.email,
        is_admin=bool(row.is_admin),
        onboarding_status=row.onboarding_status,
        master_profile=mp,
        updated_at=str(row.updated_at) if row.updated_at is not None else "",
    )


def get_in_session(session: Session, user_id: str) -> Optional[ProfileHandle]:
    """Read-only fetch reusing an already-open session/transaction."""
    if not _is_valid_uuid(user_id):
        return None
    row = session.execute(
        text("SELECT email, is_admin, onboarding_status, updated_at FROM public.profiles WHERE id = CAST(:uid AS uuid)"),
        {"uid": user_id},
    ).fetchone()
    if row is None:
        return None
    return _row_to_handle(row, user_id, _read_full_dict(session, user_id))


def get(user_id: str, engine: Optional[Engine] = None) -> Optional[ProfileHandle]:
    """Standalone read-only fetch, own session. Mirrors master_profile_repository.get()."""
    eng = engine or ENGINE
    with Session(eng) as session:
        return get_in_session(session, user_id)


def get_profile_json(user_id: str, engine: Optional[Engine] = None) -> dict:
    """Return the profile document dict for user_id, or {} if absent."""
    handle = get(user_id, engine=engine)
    return dict(handle.master_profile) if handle else {}


def get_by_email(session: Session, email: str, exclude_user_id: str) -> Optional[ProfileHandle]:
    """
    Most-recently-updated profile with this email, excluding exclude_user_id.
    Used by auth.py's account-linking flow (same verified email, different
    auth user_id — e.g. Google OAuth minting a new identity for an existing
    password account).
    """
    if not email:
        return None
    row = session.execute(
        text("""
            SELECT id, email, is_admin, onboarding_status, updated_at
            FROM public.profiles
            WHERE email = :email AND id != CAST(:exclude AS uuid)
            ORDER BY updated_at DESC
            LIMIT 1
        """),
        {"email": email, "exclude": exclude_user_id},
    ).fetchone()
    if row is None:
        return None
    uid = str(row.id)
    return _row_to_handle(row, uid, _read_full_dict(session, uid))


# ── Write ─────────────────────────────────────────────────────────────────────

def get_or_create(session: Session, user_id: str, *, now: str) -> tuple[ProfileHandle, bool]:
    """
    Return the ProfileHandle for user_id, creating an empty profiles row if
    absent. Caller is responsible for committing the session — mirrors
    master_profile_repository.get_or_create()'s contract exactly.
    """
    row = session.execute(
        text("SELECT email, is_admin, onboarding_status, updated_at FROM public.profiles WHERE id = CAST(:uid AS uuid)"),
        {"uid": user_id},
    ).fetchone()
    if row is not None:
        return _row_to_handle(row, user_id, _read_full_dict(session, user_id)), False

    session.execute(
        text("INSERT INTO public.profiles (id, onboarding_status, updated_at) VALUES (CAST(:uid AS uuid), 'incomplete', now())"),
        {"uid": user_id},
    )
    handle = ProfileHandle(user_id=user_id, onboarding_status="incomplete", master_profile={}, updated_at=now)
    return handle, True


def _normalize_entity_name(name: str) -> str:
    """Mirror ProfileUpdateService's normalized_name derivation."""
    return name.strip().lower().replace(" ", "_").replace("-", "_")


def _write_skill_entities(session: Session, user_id: str, doc_id, skills) -> None:
    """
    Reconcile the profile document's skill list against profile_entities.

    Three rules, all of them load-bearing:

    1. NEVER writes confidence_score. ProfileUpdateService owns that column
       (it derives it from evidence_records); this function only marks which
       capabilities are currently claimed on the CV. save() runs on every
       profile mutation, so a wholesale rewrite here would flatten scores that
       took real evidence to earn.

    2. Removing a skill CLEARS source_document_id rather than deleting the
       entity. evidence_records and confidence_audit_log reference entity_id
       and are append-only — deleting the row would orphan a permanent audit
       trail because someone edited a CV.

    3. A skill with no entity yet gets a minimal placeholder at score 0.
       In practice every real write path (ariel_tools' handlers, the CV-upload
       routes) calls ProfileUpdateService first, so this is a safety net for
       an unexpected path rather than the main road — losing the skill
       silently would be worse. It is logged so such a path is findable.
    """
    wanted: dict[str, str] = {}          # normalized -> display name
    for skill in (skills or []):
        raw = skill.get("name") if isinstance(skill, dict) else skill
        display = str(raw or "").strip()
        if display:
            wanted[_normalize_entity_name(display)] = display

    existing = {
        r.normalized_name: r
        for r in session.execute(
            text("""
                SELECT entity_id, normalized_name, name, source_document_id
                FROM public.profile_entities
                WHERE user_id = CAST(:uid AS uuid) AND entity_type = 'skill'
            """),
            {"uid": user_id},
        ).fetchall()
    }

    for norm, display in wanted.items():
        row = existing.get(norm)
        if row is not None:
            session.execute(
                text("""
                    UPDATE public.profile_entities
                    SET source_document_id = :doc, content = CAST(:content AS jsonb)
                    WHERE entity_id = :eid
                """),
                {"doc": doc_id, "eid": row.entity_id, "content": json.dumps({"name": display})},
            )
        else:
            logger.info(
                "[profile_repository] skill %r had no profile_entities row for user=%s — "
                "creating an unscored placeholder; the ProfileUpdateService ingest path "
                "should normally have created it first.",
                display, user_id,
            )
            session.execute(
                text("""
                    INSERT INTO public.profile_entities
                        (entity_id, user_id, entity_type, name, normalized_name,
                         confidence_score, verification_status, source_document_id,
                         content, origin, created_at, updated_at)
                    VALUES
                        (:eid, CAST(:uid AS uuid), 'skill', :name, :norm,
                         0.0, 'unverified', :doc,
                         CAST(:content AS jsonb), 'cv_parse', :now, :now)
                """),
                {
                    "eid": str(_uuid.uuid4()), "uid": user_id, "name": display, "norm": norm,
                    "doc": doc_id, "content": json.dumps({"name": display}),
                    "now": datetime.now(timezone.utc).isoformat(),
                },
            )

    stale = [r.entity_id for norm, r in existing.items()
             if norm not in wanted and r.source_document_id is not None]
    if stale:
        session.execute(
            text("""
                UPDATE public.profile_entities
                SET source_document_id = NULL
                WHERE entity_id = ANY(:ids)
            """),
            {"ids": stale},
        )


def _write_cv(session: Session, user_id: str, *, skills, experience, education, professional_summary, cv_imported_at) -> None:
    doc_id = session.execute(
        text("SELECT id FROM public.cv_documents WHERE user_id = CAST(:uid AS uuid) LIMIT 1"),
        {"uid": user_id},
    ).scalar()
    if doc_id is None:
        doc_id = session.execute(
            text("""
                INSERT INTO public.cv_documents (user_id, summary, uploaded_at)
                VALUES (CAST(:uid AS uuid), :summary, COALESCE(CAST(:uploaded_at AS timestamptz), now()))
                RETURNING id
            """),
            {"uid": user_id, "summary": professional_summary or None, "uploaded_at": cv_imported_at},
        ).scalar_one()
    else:
        session.execute(
            text("UPDATE public.cv_documents SET summary = :summary WHERE id = :doc"),
            {"doc": doc_id, "summary": professional_summary or None},
        )
        session.execute(text("DELETE FROM public.cv_claims WHERE document_id = :doc"), {"doc": doc_id})

    _write_skill_entities(session, user_id, doc_id, skills)

    for exp in (experience or []):
        session.execute(
            text("INSERT INTO public.cv_claims (document_id, claim_type, content) VALUES (:doc, 'experience', CAST(:content AS jsonb))"),
            {"doc": doc_id, "content": json.dumps(exp)},
        )
    for edu in (education or []):
        session.execute(
            text("INSERT INTO public.cv_claims (document_id, claim_type, content) VALUES (:doc, 'education', CAST(:content AS jsonb))"),
            {"doc": doc_id, "content": json.dumps(edu)},
        )


def _write_generic(session: Session, user_id: str, data: dict) -> None:
    """Wholesale replace every profile_answers row for user_id with `data`."""
    session.execute(text("DELETE FROM public.profile_answers WHERE user_id = CAST(:uid AS uuid)"), {"uid": user_id})
    for question_id, value in data.items():
        if value is None:
            continue
        session.execute(
            text("""
                INSERT INTO public.profile_answers (user_id, question_id, answer, updated_at)
                VALUES (CAST(:uid AS uuid), :qid, CAST(:answer AS jsonb), now())
            """),
            {"uid": user_id, "qid": question_id, "answer": json.dumps(value)},
        )


def save(session: Session, handle: ProfileHandle) -> None:
    """
    Persist handle back to the relational schema. Does NOT commit — same
    contract as mutating a MasterProfileRow and letting the caller commit.
    """
    user_id = handle.user_id
    mp = dict(handle.master_profile or {})
    personal = mp.get("personal") or {}
    if not isinstance(personal, dict):
        personal = {}

    session.execute(
        text("""
            INSERT INTO public.profiles
                (id, email, full_name, phone, linkedin_url, location, is_admin, onboarding_status, updated_at)
            VALUES
                (CAST(:uid AS uuid), :email, :full_name, :phone, :linkedin_url, :location, :is_admin, :onboarding_status, now())
            ON CONFLICT (id) DO UPDATE SET
                email = EXCLUDED.email, full_name = EXCLUDED.full_name, phone = EXCLUDED.phone,
                linkedin_url = EXCLUDED.linkedin_url, location = EXCLUDED.location,
                is_admin = EXCLUDED.is_admin, onboarding_status = EXCLUDED.onboarding_status,
                updated_at = now()
        """),
        {
            "uid": user_id,
            "email": handle.email,
            "full_name": personal.get("name") or personal.get("full_name"),
            "phone": personal.get("phone"),
            "linkedin_url": personal.get("linkedin") or personal.get("linkedin_url"),
            "location": personal.get("location"),
            "is_admin": handle.is_admin,
            "onboarding_status": handle.onboarding_status,
        },
    )

    role_prefs = mp.get("role_preferences") or {}
    career_goals = mp.get("career_goals") or {}
    if not isinstance(role_prefs, dict):
        role_prefs = {}
    if not isinstance(career_goals, dict):
        career_goals = {}
    target_titles = role_prefs.get("target_titles") or career_goals.get("target_roles") or []
    preferred_locations = career_goals.get("preferred_locations") or role_prefs.get("preferred_locations") or []
    work_type = career_goals.get("work_environment") or role_prefs.get("work_type") or "any"
    salary_min_usd = role_prefs.get("salary_min_usd")

    session.execute(
        text("""
            INSERT INTO public.user_preferences
                (user_id, target_titles, preferred_locations, work_type, salary_min_usd, updated_at)
            VALUES
                (CAST(:uid AS uuid), CAST(:target_titles AS jsonb), CAST(:preferred_locations AS jsonb),
                 :work_type, :salary_min_usd, now())
            ON CONFLICT (user_id) DO UPDATE SET
                target_titles = EXCLUDED.target_titles, preferred_locations = EXCLUDED.preferred_locations,
                work_type = EXCLUDED.work_type, salary_min_usd = EXCLUDED.salary_min_usd, updated_at = now()
        """),
        {
            "uid": user_id,
            "target_titles": json.dumps(target_titles),
            "preferred_locations": json.dumps(preferred_locations),
            "work_type": work_type,
            "salary_min_usd": salary_min_usd,
        },
    )

    if any(k in mp for k in _CV_KEYS):
        _write_cv(
            session, user_id,
            skills=mp.get("skills"), experience=mp.get("experience"), education=mp.get("education"),
            professional_summary=mp.get("professional_summary"), cv_imported_at=mp.get("cv_imported_at"),
        )

    generic = {k: v for k, v in mp.items() if k not in _CV_KEYS}
    _write_generic(session, user_id, generic)


def reassign_user(session: Session, old_uid: str, new_uid: str) -> None:
    """
    Merge old_uid's relational profile data into new_uid, then delete the old
    profiles row. Used by auth.py's account-linking flow — profiles.id is a
    real, immutable FK to auth.users(id), so unlike other per-user tables this
    can't be a plain UPDATE user_id; it's a field-by-field merge + row delete.

    Assumes new_uid's own profiles row is either absent or blank (caller's
    responsibility to check, exactly like the old MasterProfileRow flow) —
    any pre-existing child rows for new_uid are cleared before re-pointing
    old_uid's rows, to avoid unique-constraint collisions.
    """
    old = session.execute(
        text("""
            SELECT email, full_name, phone, linkedin_url, location, is_admin, onboarding_status
            FROM public.profiles WHERE id = CAST(:uid AS uuid)
        """),
        {"uid": old_uid},
    ).fetchone()
    if old is None:
        return

    session.execute(text("DELETE FROM public.user_preferences WHERE user_id = CAST(:uid AS uuid)"), {"uid": new_uid})
    session.execute(text("DELETE FROM public.profile_answers WHERE user_id = CAST(:uid AS uuid)"), {"uid": new_uid})
    session.execute(text("DELETE FROM public.cv_documents WHERE user_id = CAST(:uid AS uuid)"), {"uid": new_uid})

    session.execute(
        text("UPDATE public.user_preferences SET user_id = CAST(:new AS uuid) WHERE user_id = CAST(:old AS uuid)"),
        {"new": new_uid, "old": old_uid},
    )
    session.execute(
        text("UPDATE public.profile_answers SET user_id = CAST(:new AS uuid) WHERE user_id = CAST(:old AS uuid)"),
        {"new": new_uid, "old": old_uid},
    )
    session.execute(
        text("UPDATE public.cv_documents SET user_id = CAST(:new AS uuid) WHERE user_id = CAST(:old AS uuid)"),
        {"new": new_uid, "old": old_uid},
    )
    session.execute(
        text("""
            UPDATE public.profiles SET
                email = :email, full_name = :full_name, phone = :phone, linkedin_url = :linkedin_url,
                location = :location, is_admin = :is_admin, onboarding_status = :onboarding_status, updated_at = now()
            WHERE id = CAST(:uid AS uuid)
        """),
        {
            "uid": new_uid, "email": old.email, "full_name": old.full_name, "phone": old.phone,
            "linkedin_url": old.linkedin_url, "location": old.location,
            "is_admin": old.is_admin, "onboarding_status": old.onboarding_status,
        },
    )
    session.execute(text("DELETE FROM public.profiles WHERE id = CAST(:uid AS uuid)"), {"uid": old_uid})


# ── Standalone lookups (no explicit session) ────────────────────────────────────

def is_admin_lookup(user_id: str) -> bool:
    """Cheap standalone is_admin check. Absent row (or any DB error) → False."""
    if not _is_valid_uuid(user_id):
        return False
    try:
        with ENGINE.connect() as conn:
            row = conn.execute(
                text("SELECT is_admin FROM public.profiles WHERE id = CAST(:uid AS uuid)"), {"uid": user_id},
            ).fetchone()
        return bool(row[0]) if row else False
    except Exception:
        return False


def get_updated_at(user_id: str) -> str:
    """profiles.updated_at for user_id, "" when absent/unreadable."""
    try:
        handle = get(user_id)
        return handle.updated_at if handle else ""
    except Exception:
        return ""


def list_onboarding_complete_user_ids() -> list[str]:
    """user_ids with onboarding_status='complete' — tenant_registry's pipeline fan-out."""
    with ENGINE.connect() as conn:
        rows = conn.execute(text("SELECT id FROM public.profiles WHERE onboarding_status = 'complete'")).fetchall()
    return [str(r[0]) for r in rows]
