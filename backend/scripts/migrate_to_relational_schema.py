"""
Phase 2 Migrate: one-time (re-runnable) data migration from the old
blob/mixed-table shape (master_profiles, jobs) into the new normalized
relational schema created by backend/alembic_app_schema/versions/
b19a4c6d2e71_create_relational_profile_job_schema.py
(profiles, user_preferences, profile_answers, cv_documents, cv_claims,
job_postings, user_job_matches).

This is the MIGRATE half of Expand -> Migrate -> Contract: master_profiles
and jobs are read-only here, never modified or dropped. The application
layer cutover (reading/writing the new tables) and the eventual Contract
migration that drops the old tables are separate steps.

── master_profiles -> profiles/user_preferences/profile_answers/cv_documents/cv_claims ──

profiles.id has a hard FK to auth.users(id) (see the Expand migration) — a
master_profiles row can only be migrated if its user_id is BOTH a
syntactically valid UUID AND an existing auth.users row. Verified against
real Dev data before writing this script: of 6 master_profiles rows, 3
qualify (the real account + two QA-test Supabase accounts); the other 3
('default', 'interview-test-user', 'test-user') are pre-auth scaffolding/
fixture rows with no corresponding Supabase user and are skipped — they
stay behind in master_profiles, unmigrated, which is correct: there is no
legitimate `profiles` row to create for a user_id that was never a real
login.

Field mapping (see docs/db-redesign-proposal.md §3.1, refined here against
the REAL evolved document shape — richer than the "fresh scaffold" in
backend/services/user_profile_store.py's _default_profile()):
  profiles.email/full_name/phone/linkedin_url/location
      <- master_profile["metrics_doc"]["personal"] (the richer, actively-
         synced copy — see master_profile_service.py's metrics_doc sync),
         falling back to the top-level master_profile["personal"]["name"]
         for full_name only, and the master_profiles.email column for email.
  user_preferences.target_titles
      <- master_profile["role_preferences"]["target_titles"], falling back
         to ["career_goals"]["target_roles"], then
         ["metrics_doc"]["role_preferences"]["target_titles"].
  user_preferences.preferred_locations
      <- master_profile["career_goals"]["preferred_locations"], falling
         back to ["metrics_doc"]["role_preferences"]["preferred_locations"].
  user_preferences.work_type
      <- master_profile["career_goals"]["work_environment"], falling back
         to ["metrics_doc"]["role_preferences"]["work_type"].
  user_preferences.salary_min_usd
      <- master_profile["metrics_doc"]["role_preferences"]["salary_min_usd"]
         (not present at the top level in real data).
  cv_documents (at most one per user, synthesized)
      created only if the top-level "skills"/"experience"/"education" lists
      are non-empty or "cv_imported_at" is present.
      summary      <- master_profile["professional_summary"]
      uploaded_at  <- master_profile["cv_imported_at"], else now()
  cv_claims (one row per entry, linked to the synthesized cv_documents row)
      claim_type='skill'      content={"name": <str>}   <- top-level "skills"
      claim_type='experience' content=<dict>             <- top-level "experience"
      claim_type='education'  content=<dict>             <- top-level "education"
  profile_answers (catch-all bucket for supplemental data with no other
  first-class home yet — never fabricated, only carried forward if present)
      "career_goals_notes" <- master_profile["career_goals"]["notes"], if non-empty
      "baseline_snapshot"  <- master_profile["baseline_snapshot"], if present
      one row per key      <- master_profile["metrics_doc"]["metrics"] items, if any

  Explicitly NOT migrated: master_profile["metrics_doc"]["enriched_entities"]
  — per docs/db-redesign-proposal.md §3.1, this is already duplicated by the
  existing, separately-designed profile_entities table.

── jobs -> job_postings/user_job_matches ──

Only 4 rows across 2 users in real Dev data, both users among the 3
migratable profiles above — trivial to migrate directly, no fuzzy dedup
needed. canonical_job_key = COALESCE(dedup_key, job_id) (unique per row in
practice for this dataset). jobs.posted_at is frequently a non-parseable
relative string ("just now", "") rather than a real timestamp — parsed
best-effort, NULL on failure (job_postings.posted_at is nullable).

Idempotency: every insert uses INSERT ... ON CONFLICT DO NOTHING (or, for
job_postings, ON CONFLICT ... DO UPDATE ... RETURNING id — a harmless
self-referential update purely so RETURNING always yields the row's id,
whether freshly inserted or already present) keyed on each table's natural
uniqueness, so re-running this script is safe and adds nothing on a second
pass.

Network/write safety gate (same convention as migrate_jobs_db_to_supabase.py
and cleanup_test_master_profiles.py): no row is ever written unless BOTH
  1. --allow-write is passed on the command line, AND
  2. ALLOW_RELATIONAL_SCHEMA_MIGRATION=true is set in the environment
are true. Omitting --allow-write always runs the safe, read-only preview.

Usage
-----
    # Safe default — read-only preview:
    python -m backend.scripts.migrate_to_relational_schema

    # Real migration:
    ALLOW_RELATIONAL_SCHEMA_MIGRATION=true python -m backend.scripts.migrate_to_relational_schema --allow-write
"""
from __future__ import annotations

import argparse
import os
import sys
import uuid as uuidlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from sqlalchemy import text  # noqa: E402

from backend.core.postgres import get_pg_session  # noqa: E402


def _guard_write(args: argparse.Namespace) -> None:
    env_allowed = os.environ.get("ALLOW_RELATIONAL_SCHEMA_MIGRATION", "").strip().lower() in ("1", "true", "yes")
    cli_allowed = bool(getattr(args, "allow_write", False))
    if not (cli_allowed and env_allowed):
        print(
            "[GUARD] Refusing to write: requires BOTH --allow-write AND "
            "ALLOW_RELATIONAL_SCHEMA_MIGRATION=true in the environment. Omit "
            "--allow-write to run the safe read-only preview instead.",
            file=sys.stderr,
        )
        sys.exit(1)


def _is_valid_uuid(value: str) -> bool:
    try:
        uuidlib.UUID(value)
        return True
    except (ValueError, AttributeError):
        return False


def _parse_dt(value: Any) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        s = str(value)
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _first_nonempty(*values: Any) -> Any:
    for v in values:
        if v:
            return v
    return None


def preview() -> None:
    with get_pg_session() as session:
        rows = session.execute(text("SELECT user_id, email FROM public.master_profiles")).fetchall()

    eligible, skipped = [], []
    with get_pg_session() as session:
        for uid, email in rows:
            if not _is_valid_uuid(uid):
                skipped.append((uid, "not a UUID"))
                continue
            exists = session.execute(
                text("SELECT count(*) FROM auth.users WHERE id = CAST(:uid AS uuid)"), {"uid": uid}
            ).scalar_one()
            (eligible if exists else skipped).append((uid, email if exists else "no matching auth.users row"))

    print(f"[preview] master_profiles: {len(eligible)} row(s) migratable to profiles, {len(skipped)} skipped:")
    for uid, reason in eligible:
        print(f"  MIGRATE  {uid}  ({reason})")
    for uid, reason in skipped:
        print(f"  SKIP     {uid}  ({reason})")

    with get_pg_session() as session:
        job_count = session.execute(text("SELECT count(*) FROM public.jobs")).scalar_one()
    print(f"\n[preview] jobs: {job_count} row(s) would be split into job_postings + user_job_matches.")
    print("[preview] Run with --allow-write (+ ALLOW_RELATIONAL_SCHEMA_MIGRATION=true) to actually migrate.")


def _migrate_profile(session, user_id: str, email: str, is_admin: bool, onboarding_status: str,
                      created_at: Optional[str], updated_at: Optional[str], mp: dict) -> None:
    metrics_doc = mp.get("metrics_doc") or {}
    md_personal = metrics_doc.get("personal") or {}
    top_personal = mp.get("personal") or {}
    md_role_prefs = metrics_doc.get("role_preferences") or {}
    role_prefs = mp.get("role_preferences") or {}
    career_goals = mp.get("career_goals") or {}

    session.execute(
        text("""
            INSERT INTO public.profiles
                (id, email, full_name, phone, linkedin_url, location,
                 is_admin, onboarding_status, created_at, updated_at)
            VALUES
                (CAST(:uid AS uuid), :email, :full_name, :phone, :linkedin_url, :location,
                 :is_admin, :onboarding_status,
                 COALESCE(CAST(:created_at AS timestamptz), now()),
                 COALESCE(CAST(:updated_at AS timestamptz), now()))
            ON CONFLICT (id) DO NOTHING
        """),
        {
            "uid": user_id,
            "email": email or md_personal.get("email"),
            "full_name": _first_nonempty(md_personal.get("full_name"), top_personal.get("name")),
            "phone": md_personal.get("phone"),
            "linkedin_url": md_personal.get("linkedin_url"),
            "location": md_personal.get("location"),
            "is_admin": is_admin,
            "onboarding_status": onboarding_status,
            "created_at": created_at,
            "updated_at": updated_at,
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

    import json as _json
    session.execute(
        text("""
            INSERT INTO public.user_preferences
                (user_id, target_titles, preferred_locations, work_type, salary_min_usd)
            VALUES
                (CAST(:uid AS uuid), CAST(:target_titles AS jsonb), CAST(:preferred_locations AS jsonb),
                 :work_type, :salary_min_usd)
            ON CONFLICT (user_id) DO NOTHING
        """),
        {
            "uid": user_id,
            "target_titles": _json.dumps(target_titles),
            "preferred_locations": _json.dumps(preferred_locations),
            "work_type": work_type,
            "salary_min_usd": salary_min_usd,
        },
    )

    # profile_answers — catch-all for supplemental data, never fabricated.
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
                INSERT INTO public.profile_answers (user_id, question_id, answer)
                VALUES (CAST(:uid AS uuid), :qid, CAST(:answer AS jsonb))
                ON CONFLICT (user_id, question_id) DO NOTHING
            """),
            {"uid": user_id, "qid": question_id, "answer": _json.dumps(answer)},
        )

    # cv_documents/cv_claims — synthesize at most one legacy document per user.
    skills = mp.get("skills") or []
    experience = mp.get("experience") or []
    education = mp.get("education") or []
    cv_imported_at = mp.get("cv_imported_at")
    if not (skills or experience or education or cv_imported_at):
        return

    already = session.execute(
        text("SELECT id FROM public.cv_documents WHERE user_id = CAST(:uid AS uuid) LIMIT 1"),
        {"uid": user_id},
    ).fetchone()
    if already:
        return  # already migrated in a prior run — idempotent skip

    doc_id = session.execute(
        text("""
            INSERT INTO public.cv_documents (user_id, summary, uploaded_at)
            VALUES (CAST(:uid AS uuid), :summary, COALESCE(CAST(:uploaded_at AS timestamptz), now()))
            RETURNING id
        """),
        {"uid": user_id, "summary": mp.get("professional_summary") or None, "uploaded_at": cv_imported_at},
    ).scalar_one()

    for skill in skills:
        session.execute(
            text("INSERT INTO public.cv_claims (document_id, claim_type, content) VALUES (:doc, 'skill', CAST(:content AS jsonb))"),
            {"doc": doc_id, "content": _json.dumps({"name": skill})},
        )
    for exp in experience:
        session.execute(
            text("INSERT INTO public.cv_claims (document_id, claim_type, content) VALUES (:doc, 'experience', CAST(:content AS jsonb))"),
            {"doc": doc_id, "content": _json.dumps(exp)},
        )
    for edu in education:
        session.execute(
            text("INSERT INTO public.cv_claims (document_id, claim_type, content) VALUES (:doc, 'education', CAST(:content AS jsonb))"),
            {"doc": doc_id, "content": _json.dumps(edu)},
        )


def _migrate_jobs(session) -> None:
    rows = session.execute(text("""
        SELECT job_id, title, company, company_website_url, location, jd_text, jd_structured,
               apply_url, source, source_type, locale, posted_at, is_open, dedup_key, user_id,
               score, match_score, confidence_score, culture_fit_score, trajectory_alignment,
               company_dna_inference, investigation_points, detailed_analysis, reasons, why_ron,
               scoring_rationale, tailored_cv, status, is_new, applied, applied_at, category,
               score_is_proxy, enrichment_failures, outreach_text, culture_delta, culture_alignment,
               culture_category, culture_note
        FROM public.jobs
    """)).fetchall()

    for r in rows:
        m = r._mapping
        if not _is_valid_uuid(m["user_id"]):
            print(f"  SKIP job {m['job_id']!r}: user_id {m['user_id']!r} is not a migratable UUID account")
            continue

        canonical_key = m["dedup_key"] or m["job_id"]
        posted_at = _parse_dt(m["posted_at"])

        import json as _json

        job_posting_id = session.execute(
            text("""
                INSERT INTO public.job_postings
                    (canonical_job_key, title, company, company_website_url, location, jd_text,
                     jd_structured, apply_url, source, source_type, locale, posted_at, is_open)
                VALUES
                    (:key, :title, :company, :company_url, :location, :jd_text,
                     CAST(:jd_structured AS jsonb), :apply_url, :source, :source_type, :locale, :posted_at, :is_open)
                ON CONFLICT (canonical_job_key)
                    DO UPDATE SET canonical_job_key = EXCLUDED.canonical_job_key
                RETURNING id
            """),
            {
                "key": canonical_key, "title": m["title"], "company": m["company"],
                "company_url": m["company_website_url"], "location": m["location"], "jd_text": m["jd_text"],
                # jobs.jd_structured is plain TEXT holding a JSON string (or NULL);
                "jd_structured": m["jd_structured"], "apply_url": m["apply_url"], "source": m["source"],
                "source_type": m["source_type"], "locale": m["locale"], "posted_at": posted_at,
                "is_open": m["is_open"],
            },
        ).scalar_one()

        session.execute(
            text("""
                INSERT INTO public.user_job_matches
                    (user_id, job_posting_id, score, match_score, confidence_score, culture_fit_score,
                     trajectory_alignment, company_dna_inference, investigation_points, detailed_analysis,
                     reasons, why_ron, scoring_rationale, tailored_cv, status, is_new, applied, applied_at,
                     category, score_is_proxy, enrichment_failures, outreach_text, culture_delta,
                     culture_alignment, culture_category, culture_note)
                VALUES
                    (CAST(:uid AS uuid), :jpid, :score, :match_score, :confidence_score, :culture_fit_score,
                     :trajectory_alignment, :company_dna_inference, CAST(:investigation_points AS jsonb),
                     CAST(:detailed_analysis AS jsonb), CAST(:reasons AS jsonb), :why_ron, :scoring_rationale,
                     CAST(:tailored_cv AS jsonb), :status, :is_new, :applied,
                     CAST(:applied_at AS timestamptz), :category, :score_is_proxy, :enrichment_failures,
                     :outreach_text, :culture_delta, :culture_alignment, :culture_category, :culture_note)
                ON CONFLICT (user_id, job_posting_id) DO NOTHING
            """),
            {
                "uid": m["user_id"], "jpid": job_posting_id, "score": m["score"], "match_score": m["match_score"],
                "confidence_score": m["confidence_score"], "culture_fit_score": m["culture_fit_score"],
                "trajectory_alignment": m["trajectory_alignment"], "company_dna_inference": m["company_dna_inference"],
                # investigation_points/detailed_analysis/reasons/tailored_cv come back from the
                # SELECT already deserialized into Python dict/list (jobs.* are native jsonb
                # columns) — must be re-serialized before binding, psycopg2 can't adapt a raw dict.
                "investigation_points": _json.dumps(m["investigation_points"]),
                "detailed_analysis": _json.dumps(m["detailed_analysis"]),
                "reasons": _json.dumps(m["reasons"]),
                "why_ron": m["why_ron"], "scoring_rationale": m["scoring_rationale"],
                "tailored_cv": _json.dumps(m["tailored_cv"]) if m["tailored_cv"] is not None else None,
                "status": m["status"], "is_new": m["is_new"],
                "applied": m["applied"], "applied_at": m["applied_at"], "category": m["category"],
                "score_is_proxy": m["score_is_proxy"], "enrichment_failures": m["enrichment_failures"],
                "outreach_text": m["outreach_text"], "culture_delta": m["culture_delta"],
                "culture_alignment": m["culture_alignment"], "culture_category": m["culture_category"],
                "culture_note": m["culture_note"],
            },
        )
        print(f"  migrated job {m['job_id']!r} -> job_posting {job_posting_id}")


def run_migration() -> None:
    with get_pg_session() as session:
        rows = session.execute(text("""
            SELECT user_id, email, is_admin, onboarding_status, created_at, updated_at, master_profile
            FROM public.master_profiles
        """)).fetchall()

        for r in rows:
            m = r._mapping
            uid = m["user_id"]
            if not _is_valid_uuid(uid):
                print(f"  SKIP profile {uid!r}: not a UUID")
                continue
            exists = session.execute(
                text("SELECT count(*) FROM auth.users WHERE id = CAST(:uid AS uuid)"), {"uid": uid}
            ).scalar_one()
            if not exists:
                print(f"  SKIP profile {uid!r}: no matching auth.users row")
                continue
            _migrate_profile(
                session, uid, m["email"], m["is_admin"], m["onboarding_status"],
                m["created_at"], m["updated_at"], m["master_profile"] or {},
            )
            print(f"  migrated profile {uid!r}")
        session.commit()

        print("\n=== jobs -> job_postings/user_job_matches ===")
        _migrate_jobs(session)
        session.commit()


def main():
    parser = argparse.ArgumentParser(description="Migrate master_profiles/jobs into the new relational schema.")
    parser.add_argument("--allow-write", action="store_true")
    args = parser.parse_args()

    if not args.allow_write:
        preview()
        return

    _guard_write(args)
    run_migration()


if __name__ == "__main__":
    main()
