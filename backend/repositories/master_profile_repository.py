"""Repository for the master_profiles table.

Consolidates the "get row, or create one with defaults if absent" pattern
that was independently re-implemented across master_profile_service.py,
ariel_tools.py, feedback_service.py, profile_baseline_service.py, and
several inline route blocks in profile.py/chat.py — each a slightly
divergent copy of the same logic.

get_or_create() takes an already-open Session (mirroring the shared-session
pattern from application_repository.upsert_submitted) so callers can combine
the row creation with further mutations in one atomic commit, and an
explicit `now` string so each caller keeps using its own timestamp
formatting exactly as before (some callers use a truncated-seconds ISO
format, others full isoformat() with microseconds — unifying that was out
of scope for a behavior-preserving move).

Phase 2 relational cutover
---------------------------
docs/db-redesign-proposal.md's new relational schema (profiles/
user_preferences/profile_answers/cv_documents/cv_claims) can only represent
REAL, auth-linked accounts — profiles.id has a hard FK to auth.users(id).
"default" and other synthetic/legacy user_ids (used across ~20 files,
including auth.py's claim-legacy-data-on-first-login flow) structurally
cannot go there. Rather than rewrite the ~10 scattered call sites that
mutate a MasterProfileRow's .master_profile and commit (ariel_tools.py's
handlers, master_profile_service.py, profile_baseline_service.py,
feedback_service.py, inline route blocks), a single before_flush event
listener below mirrors every MasterProfileRow write into the new relational
tables within the SAME transaction, but ONLY when the target Postgres
database has an auth.users row for that user_id. Legacy/synthetic user_ids,
and every SQLite session (the new tables don't exist there), are untouched
no-ops — master_profiles remains the sole store for those, exactly as
before. This achieves full read+write cutover to the new schema for real
accounts without touching each call site's mutation logic individually.
"""
from __future__ import annotations

import json
import uuid as _uuid
from typing import Optional

from sqlalchemy import event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from backend.core.database import ENGINE
from backend.models.profile import MasterProfileRow


def get_or_create(
    session: Session,
    user_id: str,
    *,
    now: str,
) -> tuple[MasterProfileRow, bool]:
    """
    Return the MasterProfileRow for user_id, creating it (with an empty
    master_profile dict) if absent.

    The caller is responsible for committing the session. Returns
    (row, created) — created=True only when a brand new row was added.
    """
    row = session.get(MasterProfileRow, user_id)
    if row is not None:
        return row, False

    row = MasterProfileRow(
        user_id           = user_id,
        onboarding_status = "incomplete",
        master_profile    = {},
        created_at        = now,
        updated_at        = now,
    )
    session.add(row)
    return row, True


def get(user_id: str, engine: Optional[Engine] = None) -> Optional[MasterProfileRow]:
    """Standalone read-only fetch, own session. Row is detached on return."""
    eng = engine or ENGINE
    with Session(eng) as session:
        return session.get(MasterProfileRow, user_id)


def get_profile_json(user_id: str, engine: Optional[Engine] = None) -> dict:
    """Return the master_profile JSON dict for user_id, or {} if absent."""
    row = get(user_id, engine=engine)
    return dict(row.master_profile or {}) if row else {}


# ── Phase 2: mirror writes into the new relational schema (real accounts) ──────

def _is_valid_uuid(value: str) -> bool:
    try:
        _uuid.UUID(value)
        return True
    except (ValueError, AttributeError, TypeError):
        return False


def _first_nonempty(*values):
    for v in values:
        if v:
            return v
    return None


def _sync_row_to_relational(session: Session, row: MasterProfileRow) -> None:
    """
    Decompose row.master_profile into profiles/user_preferences/
    profile_answers/cv_documents/cv_claims and upsert, for a real,
    auth-linked account only. See docs/db-redesign-proposal.md §3.1 for the
    field mapping (personal -> profiles, role_preferences/career_goals ->
    user_preferences, metrics/baseline_snapshot -> profile_answers,
    skills/experience/education -> cv_documents/cv_claims).

    Runs on the same session/connection as the MasterProfileRow flush that
    triggered it, so it's part of the same transaction — never call this
    outside a before_flush handler.
    """
    user_id = row.user_id
    if session.get_bind().dialect.name != "postgresql" or not _is_valid_uuid(user_id):
        return
    exists = session.execute(
        text("SELECT count(*) FROM auth.users WHERE id = CAST(:uid AS uuid)"), {"uid": user_id}
    ).scalar_one()
    if not exists:
        return

    mp = row.master_profile or {}
    metrics_doc = mp.get("metrics_doc") or {}
    md_personal = metrics_doc.get("personal") or {}
    top_personal = mp.get("personal") or {}
    md_role_prefs = metrics_doc.get("role_preferences") or {}
    role_prefs = mp.get("role_preferences") or {}
    career_goals = mp.get("career_goals") or {}

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
            "email": row.email or md_personal.get("email"),
            "full_name": _first_nonempty(md_personal.get("full_name"), top_personal.get("name")),
            "phone": md_personal.get("phone"),
            "linkedin_url": md_personal.get("linkedin_url"),
            "location": md_personal.get("location"),
            "is_admin": row.is_admin,
            "onboarding_status": row.onboarding_status,
        },
    )

    target_titles = _first_nonempty(
        role_prefs.get("target_titles"), career_goals.get("target_roles"), md_role_prefs.get("target_titles"),
    ) or []
    preferred_locations = _first_nonempty(
        career_goals.get("preferred_locations"), md_role_prefs.get("preferred_locations"),
    ) or []
    work_type = _first_nonempty(career_goals.get("work_environment"), md_role_prefs.get("work_type")) or "any"
    salary_min_usd = md_role_prefs.get("salary_min_usd") or role_prefs.get("salary_min_usd")

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

    # profile_answers — replace wholesale each sync, simplest correct approach
    # given these are all derived/small (metrics + a couple of named snapshots).
    answer_rows: list[tuple[str, dict]] = []
    if career_goals.get("notes"):
        answer_rows.append(("career_goals_notes", {"value": career_goals["notes"]}))
    if mp.get("baseline_snapshot"):
        answer_rows.append(("baseline_snapshot", mp["baseline_snapshot"]))
    for k, v in (metrics_doc.get("metrics") or {}).items():
        answer_rows.append((k, {"value": v}))

    for question_id, answer in answer_rows:
        session.execute(
            text("""
                INSERT INTO public.profile_answers (user_id, question_id, answer, updated_at)
                VALUES (CAST(:uid AS uuid), :qid, CAST(:answer AS jsonb), now())
                ON CONFLICT (user_id, question_id) DO UPDATE SET
                    answer = EXCLUDED.answer, updated_at = now()
            """),
            {"uid": user_id, "qid": question_id, "answer": json.dumps(answer)},
        )

    # cv_documents/cv_claims — one synthesized "legacy" document per user,
    # replaced wholesale each sync (delete + reinsert) rather than diffed,
    # since claim lists are short and this only runs on an actual profile edit.
    skills = mp.get("skills") or []
    experience = mp.get("experience") or []
    education = mp.get("education") or []
    if not (skills or experience or education):
        return

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
            {"uid": user_id, "summary": mp.get("professional_summary") or None, "uploaded_at": mp.get("cv_imported_at")},
        ).scalar_one()
    else:
        session.execute(
            text("UPDATE public.cv_documents SET summary = :summary WHERE id = :doc"),
            {"doc": doc_id, "summary": mp.get("professional_summary") or None},
        )
        session.execute(text("DELETE FROM public.cv_claims WHERE document_id = :doc"), {"doc": doc_id})

    for skill in skills:
        session.execute(
            text("INSERT INTO public.cv_claims (document_id, claim_type, content) VALUES (:doc, 'skill', CAST(:content AS jsonb))"),
            {"doc": doc_id, "content": json.dumps({"name": skill})},
        )
    for exp in experience:
        session.execute(
            text("INSERT INTO public.cv_claims (document_id, claim_type, content) VALUES (:doc, 'experience', CAST(:content AS jsonb))"),
            {"doc": doc_id, "content": json.dumps(exp)},
        )
    for edu in education:
        session.execute(
            text("INSERT INTO public.cv_claims (document_id, claim_type, content) VALUES (:doc, 'education', CAST(:content AS jsonb))"),
            {"doc": doc_id, "content": json.dumps(edu)},
        )


@event.listens_for(Session, "before_flush")
def _mirror_master_profile_writes(session: Session, flush_context, instances) -> None:
    """
    Fires on every Session.flush() app-wide (cheap no-op unless a
    MasterProfileRow is actually pending) — see module docstring.

    Best-effort, same contract as ariel_tools.py's _sync_self_assertion/
    _refresh_baseline: master_profiles remains the authoritative store, so a
    mirror-sync failure is logged and swallowed rather than aborting the
    MasterProfileRow write it piggybacks on — a bug in this new relational
    mirror should never break the existing, battle-tested profile save path.
    """
    rows = [obj for obj in (session.new | session.dirty) if isinstance(obj, MasterProfileRow)]
    for row in rows:
        try:
            # SAVEPOINT so a failure partway through (e.g. profiles updated but
            # cv_claims not yet replaced) rolls back only this mirror attempt,
            # never the outer MasterProfileRow flush/transaction it piggybacks on.
            with session.begin_nested():
                _sync_row_to_relational(session, row)
        except Exception as exc:
            import logging
            logging.getLogger(__name__).error(
                "[master_profile_repository] relational sync failed for user=%s: %s", row.user_id, exc,
            )
