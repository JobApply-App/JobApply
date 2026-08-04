"""
Profile API routes — Master Profile + Researcher Agent + Conversational Onboarding.

Endpoints
---------
GET  /api/profile                      — full master profile
PUT  /api/profile/personal             — update a personal field (phone, location)
PUT  /api/profile/metrics              — upsert supplemental Q&A answers
GET  /api/profile/research             — get cached enriched entities
POST /api/profile/research             — trigger researcher agent and return results

── Conversational Onboarding (Profile Builder) ──────────────────────────────────
POST /api/profile/interview/start      — create a new interview session
POST /api/profile/interview/message    — send a user message, get agent reply + state
GET  /api/profile/interview/{id}       — fetch current session state
POST /api/profile/interview/{id}/upload — upload a document for claim verification
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.api.deps import CurrentUser, get_current_user, llm_rate_limit, standard_rate_limit
from backend.core.database import ENGINE
from backend.models.profile import ProfileEntityRow
from backend.repositories import evidence_repository
from backend.repositories import profile_repository
from backend.repositories import profile_entity_repository
from backend.services.master_profile_service import (
    get_enriched_entities,
    get_enriched_entity,
    load,
    merge_answers,
    merge_parsed_contact,
    save,
    save_enriched_entities,
)
from backend.services.profile_update_service import ProfileUpdateService
from backend.services.confidence_math import compute_decoupled_score, EvidenceRow, verification_status
from backend.services.confidence_matrix_service import (
    get_confidence_matrix,
    get_entity_breakdown,
)

logger = logging.getLogger(__name__)
# Phase 4 invariant: every route carries at least the standard per-user budget.
# LLM-backed routes (cv-upload) additionally attach llm_rate_limit per-route.
router = APIRouter(dependencies=[Depends(standard_rate_limit)])


def _parse_ev_dt(value) -> datetime:
    """
    Parse an evidence_records.verified_at value to a timezone-aware datetime.

    SQLite stores verified_at as a plain ISO string (e.g. "2024-06-01T12:00:00"
    or "2024-06-01T12:00:00+00:00" or "2024-06-01T12:00:00Z").
    Python 3.9's fromisoformat() does NOT handle the Z suffix, so we strip and
    replace it manually before parsing.  Unknown formats fall back to utcnow().
    """
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    s = str(value).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return datetime.now(timezone.utc)


# ── POST /api/profile/init ─────────────────────────────────────────────────────

@router.post("/init")
async def init_profile(user: CurrentUser = Depends(get_current_user)):
    """
    Idempotent: creates the master_profiles row for the authenticated user if
    it does not already exist.  Called immediately after sign-up so every user
    has a DB record from the moment they register.
    """
    db = Session(ENGINE)
    try:
        now = datetime.now(timezone.utc).isoformat()
        row, created = profile_repository.get_or_create(db, user.user_id, now=now)
        if not created:
            return {"status": "ok", "created": False}

        profile_repository.save(db, row)
        db.commit()
        logger.info("[profile/init] Created master_profiles row for %s", user.user_id)
        return {"status": "ok", "created": True}

    except Exception as exc:
        db.rollback()
        logger.exception("[profile/init] Failed to init profile for %s", user.user_id)
        raise HTTPException(
            status_code=500,
            detail="Failed to initialize profile. Please try again shortly.",
        ) from exc
    finally:
        db.close()


# ── GET /api/profile ──────────────────────────────────────────────────────────

@router.get("")
async def get_profile(user: CurrentUser = Depends(get_current_user)):
    """Return the full master profile for the authenticated user."""
    from backend.services.user_profile_store import load as user_load
    return user_load(user.user_id)


# ── PUT /api/profile/personal ─────────────────────────────────────────────────

class PersonalFieldRequest(BaseModel):
    field: str   # "phone" | "location" | "email" | "linkedin_url"
    value: str


@router.put("/personal")
async def update_personal(
    req:  PersonalFieldRequest,
    user: CurrentUser = Depends(get_current_user),
):
    """Update a single personal field in the authenticated user's master profile."""
    from backend.services.user_profile_store import load as user_load, save as user_save
    allowed = {"phone", "location", "email", "linkedin_url", "full_name"}
    if req.field not in allowed:
        raise HTTPException(
            status_code=422,
            detail=f"Field '{req.field}' is not editable via this endpoint. "
                   f"Allowed: {sorted(allowed)}.",
        )
    profile = user_load(user.user_id)
    profile.setdefault("personal", {})[req.field] = req.value.strip()
    user_save(user.user_id, profile)
    return {"status": "ok", "field": req.field}


# ── PUT /api/profile/metrics ──────────────────────────────────────────────────

class MetricsRequest(BaseModel):
    answers: dict[str, str]   # question_id -> answer


@router.put("/metrics")
async def update_metrics(
    req:  MetricsRequest,
    user: CurrentUser = Depends(get_current_user),
):
    """Upsert supplemental Q&A answers into the authenticated user's profile."""
    from backend.services.user_profile_store import merge_answers as user_merge
    if not req.answers:
        raise HTTPException(status_code=422, detail="answers must not be empty.")
    n = user_merge(user.user_id, req.answers)
    return {"status": "ok", "new_entries": n}


# ── GET /api/profile/research ─────────────────────────────────────────────────

@router.get("/research")
async def get_research(user: CurrentUser = Depends(get_current_user)):
    """Return the caller's cached enriched entity data from the last research run."""
    entities = get_enriched_entities(user.user_id)
    return {
        "status":   "ok",
        "count":    len(entities),
        "entities": entities,
    }


# ── POST /api/profile/research ────────────────────────────────────────────────

class ResearchRequest(BaseModel):
    # Optional override: specific entity names to research.
    # If omitted, all entities from the CALLER's profile are researched.
    entity_names: Optional[list[str]] = None
    # Bypass the web-search result cache AND the ground-truth skip guard,
    # forcing a fresh web+LLM pass for every entity in this request. Default
    # False: normal calls are served from cache where possible (0 ScraperAPI
    # credits on a repeat run) and never overwrite a human-verified record.
    force: bool = False


@router.post("/research")
async def trigger_research(req: ResearchRequest, user: CurrentUser = Depends(get_current_user)):
    """
    Run the ResearcherAgent for all profile entities (or a subset).

    This call awaits the full research cycle (~10-30 s depending on entity count).
    Results are persisted to master_profile.json and returned in the response.
    """
    try:
        from backend.agents.researcher import ResearcherAgent, extract_profile_entities

        if req.entity_names:
            entities = [
                {"name": n, "entity_type": "company", "is_high_impact": True}
                for n in req.entity_names
            ]
        else:
            entities = extract_profile_entities(user.user_id)

        if not entities:
            return {"status": "ok", "message": "No entities to research.", "entities": []}

        agent   = ResearcherAgent(user.user_id)
        results = await agent.research(entities, force=req.force)

        # Persist to master profile
        save_enriched_entities([e.as_dict() for e in results], user.user_id)

        logger.info(
            "[profile/research] Completed for user=%s: %d entities researched",
            user.user_id, len(results),
        )
        return {
            "status":   "ok",
            "count":    len(results),
            "entities": [e.as_dict() for e in results],
        }

    except Exception as exc:
        logger.exception("[profile/research] Researcher agent failed")
        raise HTTPException(status_code=502, detail="Research failed. Please try again shortly.")


# ── POST /api/profile/preferences ─────────────────────────────────────────────
# Onboarding: target roles, each with its own seniority level, captured before
# CV upload. Stored in both the per-user profile JSON (role_preferences — read
# by the matching pipeline) and the master_profiles row, so future job scoring
# can use them without a file read.

_SENIORITY_LEVELS: frozenset = frozenset({
    "junior", "entry", "mid", "senior", "lead", "director", "executive",
})


class RoleSeniorityItem(BaseModel):
    role:      str = Field(..., max_length=80)
    seniority: str = Field(..., max_length=40)


class RolePreferencesPayload(BaseModel):
    # Per-role seniority (Phase 8): [{role: "Account Manager", seniority: "mid"}, …]
    roles: List[RoleSeniorityItem] = Field(default_factory=list, max_length=10)


@router.get("/preferences")
async def get_role_preferences(user: CurrentUser = Depends(get_current_user)) -> dict:
    """Return the calling user's saved role/seniority preferences."""
    from backend.services.user_profile_store import load as user_load

    prefs = (user_load(user.user_id).get("role_preferences") or {})
    return {
        "roles":         prefs.get("roles", []),
        "target_titles": prefs.get("target_titles", []),
    }


@router.post("/preferences")
async def save_role_preferences(
    body: RolePreferencesPayload,
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Persist onboarding role/seniority preferences for the calling user only."""
    from backend.services.llm_validation import sanitize_text
    from backend.services.user_profile_store import load as user_load, save as user_save

    roles: list[dict] = []
    for item in body.roles:
        role      = sanitize_text(item.role.strip())[:80]
        seniority = sanitize_text(item.seniority.strip().lower())[:40]
        if not role:
            continue
        if seniority not in _SENIORITY_LEVELS:
            raise HTTPException(
                status_code=422,
                detail=f"seniority for {role!r} must be one of {sorted(_SENIORITY_LEVELS)}",
            )
        roles.append({"role": role, "seniority": seniority})
    roles = roles[:10]

    target_titles = [r["role"] for r in roles]

    # Per-user profile JSON — the store the matching pipeline reads.
    profile = user_load(user.user_id)
    prefs = profile.setdefault("role_preferences", {})
    prefs["target_titles"] = target_titles   # legacy consumers: flat title list
    prefs["roles"]         = roles           # per-role seniority pairs
    user_save(user.user_id, profile)

    # Mirror into the relational profile schema for DB-side consumers.
    _now = datetime.now(timezone.utc).isoformat()
    with Session(ENGINE) as _sess:
        row, _created = profile_repository.get_or_create(_sess, user.user_id, now=_now)
        mp = dict(row.master_profile or {})
        mp["role_preferences"] = {"target_titles": target_titles, "roles": roles}
        row.master_profile = mp
        row.updated_at     = _now
        profile_repository.save(_sess, row)
        _sess.commit()

    logger.info("[profile/preferences] user=%s roles=%d", user.user_id, len(roles))
    return {"status": "ok", "roles": roles}


# ── POST /api/profile/linkedin-import ─────────────────────────────────────────
# Phase 8 stub: accepts a LinkedIn profile URL and returns a mock success after
# a short delay. Real scraping is intentionally NOT implemented (LinkedIn's
# anti-bot protections); this endpoint exists so the onboarding UI flow is
# complete end-to-end and the URL is stored for the future integration.

class LinkedInImportPayload(BaseModel):
    linkedin_url: str = Field(..., max_length=300)


@router.post("/linkedin-import")
async def linkedin_import(
    body: LinkedInImportPayload,
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """
    Mock LinkedIn import (stub). Validates the URL shape, stores it on the
    user's profile for the future real integration, sleeps ~2 s to simulate
    processing, and returns a mock success. No scraping is performed.
    """
    import asyncio
    import re as _re

    from backend.services.llm_validation import sanitize_text
    from backend.services.user_profile_store import load as user_load, save as user_save

    url = sanitize_text(body.linkedin_url.strip())[:300]
    if not _re.match(r"^https?://(www\.)?linkedin\.com/in/[A-Za-z0-9_%\-\.]+/?$", url):
        raise HTTPException(
            status_code=422,
            detail="Please provide a valid LinkedIn profile URL (https://www.linkedin.com/in/your-name).",
        )

    # Persist the URL now so the future real importer can pick it up.
    profile = user_load(user.user_id)
    profile.setdefault("personal", {})["linkedin_url"] = url
    user_save(user.user_id, profile)

    await asyncio.sleep(2)   # simulate processing; real import replaces this

    logger.info("[profile/linkedin-import] user=%s url=%s (stub)", user.user_id, url)
    return {
        "status":   "ok",
        "imported": False,   # stub — no data was actually scraped
        "message":  "LinkedIn profile saved. Full import is coming soon — meanwhile your CV powers the profile.",
    }


# ── POST /api/profile/cv-upload ──────────────────────────────────────────────

_CV_MAX_BYTES = 10 * 1024 * 1024   # 10 MB per file
_CV_MAX_FILES = 10

# ── File-content signature check (shared by cv-upload and interview/upload) ──
# A file extension is trivially spoofable (rename anything.exe to cv.pdf), so
# every upload additionally checks the real file signature (magic bytes)
# before the content is handed to a parser. This is defense in depth, not a
# guarantee of a "safe" file — the parsers themselves (PyMuPDF/python-docx/
# pypdf) already fail closed (return empty text / an "unreadable" result) on
# malformed content, this just avoids handing obviously-mismatched content to
# them at all.
_FILE_SIGNATURES: dict[str, tuple[bytes, ...]] = {
    "pdf":  (b"%PDF-",),
    "docx": (b"PK\x03\x04",),   # OOXML files are ZIP containers
    "png":  (b"\x89PNG\r\n\x1a\n",),
    "jpg":  (b"\xff\xd8\xff",),
    "jpeg": (b"\xff\xd8\xff",),
    "webp": (b"RIFF",),        # full check would also need "WEBP" at offset 8
}


def _content_matches_extension(content: bytes, ext: str) -> bool:
    """
    True if content's magic bytes match what `ext` claims, or if `ext` isn't
    one we have a signature for (fail open for unknown-but-already-rejected
    extensions — the caller's own extension allow-list is the real gate).
    """
    signatures = _FILE_SIGNATURES.get(ext.lower())
    if not signatures:
        return True
    return any(content.startswith(sig) for sig in signatures)


def _cv_claims_to_parsed_entities(cv_claims: dict) -> list[dict]:
    """
    Convert aggregated cv_claims into the ``parsed_entities`` format consumed
    by ProfileUpdateService.ingest_cv_parse().

    Mapping
    -------
    skill_details → entity_type='skill', name=name, plus proficiency_level/
                    years_of_experience/last_used_year when the extraction
                    LLM supplied them (JOB-138: global skills taxonomy).
    skills        → entity_type='skill', name=skill_str, no metadata — the
                    plain-string fallback for any skill skill_details didn't
                    cover (or when the LLM only emitted the flat list).
    domains       → entity_type='domain', name=domain_str
    experiences   → entity_type='experience', name="{role} at {company}"
                    raw_content = experience summary (≤ 500 chars)

    Traits are excluded — they can only be established through behavioral
    probes (STAR interviews), not inferred from a CV.
    """
    entities: list[dict] = []
    covered_skill_names: set[str] = set()

    for detail in cv_claims.get("skill_details", []):
        if not isinstance(detail, dict):
            continue
        name = str(detail.get("name") or "").strip()
        if not name:
            continue
        covered_skill_names.add(name.lower())
        entities.append({
            "entity_type":         "skill",
            "name":                name,
            "raw_content":         "",
            "proficiency_level":   str(detail.get("proficiency_level") or "").strip().lower() or None,
            "years_of_experience": detail.get("years_of_experience"),
            "last_used_year":      detail.get("last_used_year"),
        })

    for skill in cv_claims.get("skills", []):
        if isinstance(skill, str) and skill.strip() and skill.strip().lower() not in covered_skill_names:
            entities.append({
                "entity_type": "skill",
                "name":        skill.strip(),
                "raw_content": "",
            })

    for domain in cv_claims.get("domains", []):
        if isinstance(domain, str) and domain.strip():
            entities.append({
                "entity_type": "domain",
                "name":        domain.strip(),
                "raw_content": "",
            })

    for exp in cv_claims.get("experiences", []):
        if not isinstance(exp, dict):
            continue
        role    = (exp.get("role")    or "").strip()
        company = (exp.get("company") or "").strip()
        summary = (exp.get("summary") or "").strip()
        if not role:
            continue
        name = f"{role} at {company}" if company else role
        entities.append({
            "entity_type": "experience",
            "name":        name[:200],          # cap entity name length
            "raw_content": summary[:500],       # cap evidence excerpt length
        })

    return entities


@router.post("/cv-upload", dependencies=[Depends(llm_rate_limit)])
async def upload_cv_files(
    files:     List[UploadFile]  = File(..., description="One or more CV files (PDF or DOCX)"),
    entity_id: Optional[str]     = Form(None, description=(
        "When set, treat this as a targeted evidence re-upload for a specific "
        "profile entity (used by ManualReviewModal). Skips full-pipeline ingestion."
    )),
    user:      CurrentUser       = Depends(get_current_user),
):
    """
    Two-mode CV upload endpoint:

    **Mode A — full CV ingestion** (entity_id absent):
      1. Extract text from every uploaded PDF / DOCX.
      2. Aggregate and de-duplicate via LLM → cv_claims.
      3. Persist cv_claims to the user's profile JSON + master_profiles table.
      4. Convert cv_claims to parsed_entities and call
         ProfileUpdateService.ingest_cv_parse() to populate profile_entities
         and evidence_records with source_type='cv_parse'.
      5. Return the cv_claims object + ingestion summary.

    **Mode B — targeted evidence re-upload** (entity_id present):
      Used by ManualReviewModal when the user re-submits a certificate or CV
      to add positive evidence for a specific flagged entity.
      1. Extract text from the single uploaded file.
      2. Append one cv_parse evidence record for the given entity_id.
      3. Recompute the entity's confidence score.
      Returns the updated confidence score.
    """
    from backend.services.cv_aggregator_service import extract_text, aggregate_cv_claims
    from backend.services.user_profile_store import load as user_load, save as user_save

    if not files:
        raise HTTPException(status_code=422, detail="At least one file is required.")
    if len(files) > _CV_MAX_FILES:
        raise HTTPException(
            status_code=422,
            detail=f"Too many files. Maximum is {_CV_MAX_FILES} per upload.",
        )

    # ── Phase 1: Extract text from all uploaded files ─────────────────────────
    texts: list[str]     = []
    processed: list[str] = []
    errors: list[str]    = []

    for upload in files:
        fname = upload.filename or "upload"
        ext   = fname.rsplit(".", 1)[-1].lower() if "." in fname else ""
        if ext not in ("pdf", "docx"):
            errors.append(f"{fname}: unsupported format (PDF or DOCX only)")
            continue

        content = await upload.read()
        if len(content) > _CV_MAX_BYTES:
            errors.append(f"{fname}: file too large (max 10 MB)")
            continue
        if not _content_matches_extension(content, ext):
            errors.append(f"{fname}: file content does not match its .{ext} extension")
            continue

        text = extract_text(content, fname)
        if not text.strip():
            errors.append(f"{fname}: could not extract text")
            continue

        texts.append(text)
        processed.append(fname)

    if not texts:
        raise HTTPException(
            status_code=422,
            detail="No readable text could be extracted. " + " | ".join(errors),
        )

    # ── Mode B: Targeted evidence re-upload for a specific entity ─────────────
    if entity_id:
        from sqlalchemy import text as sql_text
        combined_text = "\n\n".join(texts)
        svc = ProfileUpdateService(ENGINE)
        try:
            with ENGINE.begin() as conn:
                # Verify entity belongs to this user
                row = conn.execute(
                    sql_text(
                        "SELECT entity_id, name FROM profile_entities "
                        "WHERE entity_id = :eid AND user_id = :uid"
                    ),
                    {"eid": entity_id, "uid": user.user_id},
                ).fetchone()
                if not row:
                    raise HTTPException(
                        status_code=404,
                        detail=f"Entity {entity_id!r} not found for this user.",
                    )
                entity_name = row[1]

                ev_id = str(__import__("uuid").uuid4())
                # NOTE: never re-import datetime locally here — a function-local
                # `from datetime import datetime` makes `datetime` a local for
                # the WHOLE function, so Mode A (which skips this branch) would
                # crash with UnboundLocalError at its own datetime.now() call.
                # The module-level import (top of file) is the one to use.
                now   = datetime.now(timezone.utc).isoformat()
                from backend.services.confidence_math import BASE_WEIGHTS
                conn.execute(
                    sql_text("""
                        INSERT INTO evidence_records
                            (evidence_id, entity_id, user_id, source_type,
                             base_weight, raw_content, verified_at)
                        VALUES
                            (:evid, :eid, :uid, 'cv_parse', :w, :raw, :now)
                    """),
                    {
                        "evid": ev_id,
                        "eid":  entity_id,
                        "uid":  user.user_id,
                        "w":    BASE_WEIGHTS["cv_parse"],
                        "raw":  combined_text[:500],
                        "now":  now,
                    },
                )
                new_score = svc._recompute_and_persist(
                    conn, entity_id, user.user_id,
                    trigger_source="cv_parse",
                    new_evidence_id=ev_id,
                    note=f"Evidence re-upload for {entity_name}",
                )

            logger.info(
                "[profile/cv-upload] Mode B: user=%s entity=%s new_score=%.1f",
                user.user_id, entity_id, new_score,
            )
            return {
                "status":        "ok",
                "mode":          "evidence_reupload",
                "entity_id":     entity_id,
                "new_confidence": new_score,
                "processed":     processed,
                "errors":        errors,
            }
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("[profile/cv-upload] Mode B failed for entity=%s", entity_id)
            raise HTTPException(
                status_code=500,
                detail="Evidence upload failed. Please try again shortly.",
            ) from exc

    # ── Mode A: Full CV ingestion pipeline ────────────────────────────────────

    # Phase 2: Aggregate via LLM
    cv_claims = await aggregate_cv_claims(texts, user_id=user.user_id)

    # Phase 3: Persist cv_claims to profile JSON + master_profiles table
    profile = user_load(user.user_id)
    profile["cv_claims"] = cv_claims
    user_save(user.user_id, profile)

    _now = datetime.now(timezone.utc).isoformat()
    parsed_personal = cv_claims.get("personal") or {}
    with Session(ENGINE) as _sess:
        row, _created = profile_repository.get_or_create(_sess, user.user_id, now=_now)
        mp = dict(row.master_profile or {})
        mp["cv_data"] = cv_claims
        mp["cv_imported_at"] = _now
        # Top-level onboarding `personal` block — same fill-blanks-only rule
        # as the metrics_doc merge below, and the same key names get_profile()
        # reads (name/phone/linkedin, not full_name/linkedin_url).
        existing_personal = mp.get("personal")
        if not isinstance(existing_personal, dict):
            existing_personal = {}
        for src, dst in (
            ("full_name", "name"), ("phone", "phone"), ("email", "email"),
            ("linkedin_url", "linkedin"), ("location", "location"),
        ):
            value = str(parsed_personal.get(src, "") or "").strip()
            if value and not str(existing_personal.get(dst, "") or "").strip():
                existing_personal[dst] = value
        if existing_personal:
            mp["personal"] = existing_personal
        row.master_profile = mp
        row.updated_at = _now
        profile_repository.save(_sess, row)
        _sess.commit()

    # metrics_doc["personal"] — the other place get_profile() looks for
    # contact details. Non-fatal: a CV whose contact block failed to merge is
    # still a successfully imported CV.
    try:
        merge_parsed_contact(parsed_personal, user.user_id)
    except Exception as exc:
        logger.warning("[cv-upload] contact merge failed (non-fatal): %s", exc)

    # Phase 4: Ingest entities into the Confidence Matrix
    parsed_entities = _cv_claims_to_parsed_entities(cv_claims)
    svc = ProfileUpdateService(ENGINE)
    entity_ids: list[str] = []
    ingestion_error: Optional[str] = None

    if parsed_entities:
        try:
            entity_ids = svc.ingest_cv_parse(user.user_id, parsed_entities)
        except Exception as exc:
            # Entity ingestion failure must NOT roll back the cv_claims persist —
            # the profile data is still valuable.  Log and surface as a warning.
            ingestion_error = str(exc)
            logger.exception(
                "[profile/cv-upload] ingest_cv_parse failed for user=%s",
                user.user_id,
            )

    # Phase 5: Recompute overall trust score + its three-pillar breakdown.
    # Compute both from the SAME familiarity call so any consumer of this
    # endpoint receives the breakdown alongside the overall score — never an
    # overall value with a missing score_breakdown (the Phase 33 bug).
    familiarity = svc.compute_profile_familiarity(user.user_id)
    overall_trust_score = familiarity["overall"]

    logger.info(
        "[profile/cv-upload] Mode A complete: user=%s  files=%s  "
        "skills=%d  domains=%d  experiences=%d  "
        "entities_ingested=%d  overall_score=%.1f",
        user.user_id,
        processed,
        len(cv_claims.get("skills", [])),
        len(cv_claims.get("domains", [])),
        len(cv_claims.get("experiences", [])),
        len(entity_ids),
        overall_trust_score,
    )

    response: dict = {
        "status":              "ok",
        "mode":                "full_ingestion",
        "processed":           processed,
        "errors":              errors,
        "cv_claims":           cv_claims,
        "entities_ingested":   len(entity_ids),
        "overall_trust_score": overall_trust_score,
        "score_breakdown": {
            "breadth": familiarity["breadth"],
            "depth":   familiarity["depth"],
            "context": familiarity["context"],
        },
    }
    if ingestion_error:
        response["ingestion_warning"] = ingestion_error

    return response


# ── GET /api/profile/{user_id}/trust-score ────────────────────────────────────
#
# Human-readable source_type labels used in trust_breakdown entries.
_SOURCE_LABELS: dict[str, str] = {
    "cv_parse":                 "CV Parse",
    "self_assertion":           "Self-Assertion",
    "contextual_reinforcement": "Contextual Mention",
    "certification":            "Certification",
    "portfolio":                "Portfolio",
    "conversation_star":        "STAR Behavioral Probe",
    "negative_flag":            "Negative Flag",
}


@router.get("/{user_id}/trust-score")
async def get_trust_score(
    user_id:  str,
    sort_by:  str = Query("score_desc", description="score_desc | needs_verification | category"),
    top_n:    int = Query(0, ge=0, description="Return only the top N entities (0 = all)"),
    user:     CurrentUser = Depends(get_current_user),
):
    """
    Return the full Confidence Matrix for a user, including per-entity evidence
    breakdowns and the weighted overall trust score.

    Access control
    --------------
    Users may only fetch their own trust score.  Attempting to access another
    user's data returns HTTP 403.

    Empty-profile guard
    -------------------
    A user with zero entities receives HTTP 200 with overall_trust_score=0.0
    and empty lists — never a 500.

    Response shape
    --------------
    Matches the TrustScoreResponse interface in apiTypes.ts:
    {
        user_id:              str,
        overall_trust_score:  float,          # extra field: weighted composite
        entities:             [TrustProfileEntity],
        category_averages:    {skill, trait, domain, experience},
        fetched_at:           ISO-8601 str,
    }

    Each TrustProfileEntity.trust_breakdown entry contains non-hard-expired
    evidence records ordered by verified_at DESC (freshest first).
    """
    # ── Access control ────────────────────────────────────────────────────────
    if user.user_id != user_id:
        raise HTTPException(
            status_code=403,
            detail="You may only access your own trust score.",
        )

    now_iso = datetime.now(timezone.utc).isoformat()

    try:
        # Single session for the whole request so the entity list and every
        # entity's evidence are read from one consistent snapshot, and so the
        # loop below doesn't open a new DB connection per entity.
        with Session(ENGINE) as db:
            # ── 1. Load all profile entities for this user ────────────────────
            entity_rows = profile_entity_repository.get_all_for_user(user_id, session=db)

            # ── 2. For each entity, load its non-expired evidence records ─────
            result_entities = []
            category_scores: dict[str, list[float]] = {
                "skill": [], "trait": [], "domain": [], "experience": [],
            }

            for ent in entity_rows:
                evidence_rows = evidence_repository.get_active_for_entity(ent.entity_id, now_iso, session=db)

                trust_breakdown = [
                    {
                        "evidence_id":   ev.evidence_id,
                        "source_type":   ev.source_type,
                        "source_label":  _SOURCE_LABELS.get(ev.source_type, ev.source_type),
                        "verified_at":   ev.verified_at,
                        "raw_content":   ev.raw_content,
                        "base_weight":   ev.base_weight,
                        "is_ai_assisted": ev.is_ai_assisted,
                    }
                    for ev in evidence_rows
                ]

                # Re-compute decoupled score from live evidence to get the
                # dynamic multiplier and evidence count for UI transparency.
                ev_typed: list[EvidenceRow] = [
                    {
                        "source_type":    ev.source_type,
                        "base_weight":    float(ev.base_weight),
                        "verified_at":    _parse_ev_dt(ev.verified_at),
                        "is_ai_assisted": ev.is_ai_assisted,
                    }
                    for ev in evidence_rows
                ]
                dscore = compute_decoupled_score(ev_typed)

                result_entities.append({
                    "entity_id":               ent.entity_id,
                    "name":                    ent.name,
                    "entity_type":             ent.entity_type,
                    "confidence_score":        ent.confidence_score,
                    "verification_status":     ent.verification_status,
                    "manual_review_required":  ent.manual_review_required,
                    "skill_tier":              ent.skill_tier,
                    "architecture_confidence": ent.architecture_confidence,
                    "syntax_confidence":       ent.syntax_confidence,
                    "verification_level":      ent.verification_level,
                    "evidence_multiplier":     dscore.evidence_multiplier,
                    "evidence_count":          dscore.evidence_count,
                    "trust_breakdown":         trust_breakdown,
                })

                # Accumulate for category averages
                if ent.entity_type in category_scores:
                    category_scores[ent.entity_type].append(ent.confidence_score)

        # ── 2b. Sort and slice entities ───────────────────────────────────────
        if sort_by == "needs_verification":
            result_entities.sort(
                key=lambda e: (
                    0 if e["verification_level"] in ("UNVERIFIED", "ORCHESTRATION_ONLY") else 1,
                    -e["confidence_score"],
                )
            )
        elif sort_by == "category":
            result_entities.sort(key=lambda e: (e["entity_type"], -e["confidence_score"]))
        else:  # score_desc (default)
            result_entities.sort(key=lambda e: -e["confidence_score"])

        if top_n > 0:
            result_entities = result_entities[:top_n]

        # ── 3. Compute category averages (0.0 when no entities in category) ──
        def _avg(scores: list[float]) -> float:
            return round(sum(scores) / len(scores), 1) if scores else 0.0

        category_averages = {
            "skill":      _avg(category_scores["skill"]),
            "trait":      _avg(category_scores["trait"]),
            "domain":     _avg(category_scores["domain"]),
            "experience": _avg(category_scores["experience"]),
        }

        # ── 4. Holistic Familiarity score + three-pillar breakdown ────────────
        svc = ProfileUpdateService(ENGINE)
        familiarity = svc.compute_profile_familiarity(user_id)
        overall_trust_score = familiarity["overall"]

        logger.info(
            "[profile/trust-score] user=%s  entities=%d  overall=%.1f "
            "(breadth=%.1f depth=%.1f context=%.1f)",
            user_id, len(result_entities), overall_trust_score,
            familiarity["breadth"], familiarity["depth"], familiarity["context"],
        )

        return {
            "user_id":             user_id,
            "overall_trust_score": overall_trust_score,
            # Three-pillar breakdown of the Holistic Familiarity score so the UI
            # can show WHY the score is what it is (Phase 32). Maxes: breadth 40,
            # depth 40, context 20.
            "score_breakdown": {
                "breadth": familiarity["breadth"],
                "depth":   familiarity["depth"],
                "context": familiarity["context"],
            },
            "entities":            result_entities,
            "category_averages":   category_averages,
            "fetched_at":          now_iso,
        }

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("[profile/trust-score] Unexpected error for user=%s", user_id)
        raise HTTPException(
            status_code=500,
            detail="Trust score fetch failed. Please try again shortly.",
        ) from exc


# ── POST /api/profile/{user_id}/force-recalculate ─────────────────────────────
#
# Overwrites stale confidence_score, architecture_confidence, syntax_confidence,
# and verification_level for EVERY entity belonging to user_id by re-running
# compute_decoupled_score() against the live evidence ledger.
#
# This is necessary when the scoring formula changes (e.g. dynamic multiplier)
# because _recompute_and_persist() only runs when NEW evidence is ingested —
# existing entities keep their old persisted value until explicitly recalculated.
#
# Access: users may only recalculate their own profile.

@router.post("/{user_id}/force-recalculate")
async def force_recalculate(
    user_id: str,
    user:    CurrentUser = Depends(get_current_user),
):
    """
    Re-run compute_decoupled_score() for every profile entity and persist the
    results, overwriting any stale values left from a previous scoring version.

    Returns a summary: how many entities were recalculated and their new scores.
    """
    if user.user_id != user_id:
        raise HTTPException(status_code=403, detail="You may only recalculate your own profile.")

    now_iso = datetime.now(timezone.utc).isoformat()

    try:
        with Session(ENGINE) as db:
            raw_count = db.query(ProfileEntityRow).filter(ProfileEntityRow.user_id == user_id).count()
            print(f"=== DEBUG FORCE_RECALC: Raw DB entity count for this user = {raw_count} ===")

            entity_rows: list[ProfileEntityRow] = (
                db.query(ProfileEntityRow)
                .filter(ProfileEntityRow.user_id == user_id)
                .all()
            )

            if not entity_rows:
                return {"recalculated": 0, "entities": []}

            results = []
            for ent in entity_rows:
                print(f"=== DEBUG FORCE_RECALC: Processing entity {ent.entity_id} ===")
                evidence_rows = evidence_repository.get_active_for_entity(ent.entity_id, now_iso, session=db)

                ev_typed: list[EvidenceRow] = [
                    {
                        "source_type":    ev.source_type,
                        "base_weight":    float(ev.base_weight),
                        "verified_at":    _parse_ev_dt(ev.verified_at),
                        "is_ai_assisted": ev.is_ai_assisted,
                    }
                    for ev in evidence_rows
                ]

                dscore = compute_decoupled_score(ev_typed)
                new_status = verification_status(dscore.final_score)

                pos_ev = [e for e in ev_typed if e["base_weight"] >= 0]
                new_tier = (
                    "System_Orchestration"
                    if pos_ev and all(e["is_ai_assisted"] for e in pos_ev)
                    else "Core_Mastery" if pos_ev else None
                )

                ent.confidence_score        = dscore.final_score
                ent.verification_status     = new_status
                ent.architecture_confidence = dscore.architecture_confidence
                ent.syntax_confidence       = dscore.syntax_confidence
                ent.verification_level      = dscore.verification_level
                ent.updated_at              = now_iso
                if new_tier is not None:
                    ent.skill_tier = new_tier

                results.append({
                    "entity_id":           ent.entity_id,
                    "name":                ent.name,
                    "confidence_score":    dscore.final_score,
                    "architecture":        dscore.architecture_confidence,
                    "syntax":              dscore.syntax_confidence,
                    "verification_level":  dscore.verification_level,
                    "evidence_multiplier": dscore.evidence_multiplier,
                    "evidence_count":      dscore.evidence_count,
                })

            db.commit()

        logger.info(
            "[profile/force-recalculate] user=%s  recalculated=%d",
            user_id, len(results),
        )
        return {
            "recalculated": len(results),
            "entities":     results,
        }

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("[profile/force-recalculate] Failed for user=%s", user_id)
        raise HTTPException(
            status_code=500,
            detail="Recalculation failed. Please try again shortly.",
        ) from exc


# ── Conversational Onboarding ─────────────────────────────────────────────────

class InterviewMessageRequest(BaseModel):
    session_id: str
    message:    str


class StartInterviewRequest(BaseModel):
    """
    Optional context hints from the frontend (e.g. from a future auth session).
    If omitted, the backend reads authoritative data from USER_PROFILE directly.
    """
    user_name:    Optional[str] = None   # e.g. "Jamie Smith" or just "Jamie"
    current_role: Optional[str] = None   # e.g. "Team Lead – Partnerships & Support at Acme Co"
    intent:       Optional[str] = None   # e.g. "optimize_gaps" for the gap-drill flow


@router.post("/interview/start")
async def start_interview(
    req:  StartInterviewRequest = StartInterviewRequest(),
    user: CurrentUser = Depends(get_current_user),
):
    """
    Create a new profile interview session for the authenticated user.

    The opening message is generated dynamically — Adam addresses the user by
    name and skips redundant onboarding questions by loading the user's existing
    CV/profile data from the backend.

    Accepts an optional JSON body with user_name and current_role hints.
    The backend's own USER_PROFILE always takes precedence over these hints.

    Returns the session_id and the agent's personalized opening message.
    """
    from backend.agents.profile_interviewer import start_session
    try:
        state = await start_session(
            user_id               = user.user_id,
            user_name_override    = req.user_name,
            current_role_override = req.current_role,
            user_email            = user.email or None,
            intent                = req.intent,
        )
        return state
    except Exception as exc:
        logger.exception("[profile/interview/start] Failed")
        raise HTTPException(status_code=500, detail="Failed to start interview session. Please try again shortly.") from exc


@router.post("/interview/message")
async def send_interview_message(
    req:  InterviewMessageRequest,
    user: CurrentUser = Depends(get_current_user),
):
    """
    Send a user message to an active interview session.

    The session must belong to the authenticated user — returns 403 otherwise.
    """
    from backend.agents.profile_interviewer import process_message
    try:
        state = await process_message(req.session_id, req.message, user_id=user.user_id)
        return state
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except Exception as exc:
        logger.exception("[profile/interview/message] Failed")
        raise HTTPException(status_code=500, detail="Failed to process message. Please try again shortly.") from exc


@router.get("/interview/{session_id}")
async def get_interview_session(
    session_id: str,
    user:       CurrentUser = Depends(get_current_user),
):
    """Fetch the current state of an interview session owned by the caller."""
    from backend.agents.profile_interviewer import get_session
    try:
        return get_session(session_id, user_id=user.user_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))


@router.post("/interview/{session_id}/resume")
async def resume_interview_session(
    session_id: str,
    user:       CurrentUser = Depends(get_current_user),
):
    """
    Resume an existing profile interview session owned by the caller.

    Generates a context-aware "Resume & Status" message.
    Returns 404 if the session does not exist, 403 if it belongs to another user.
    """
    from backend.agents.profile_interviewer import resume_session
    try:
        state = await resume_session(session_id, user_id=user.user_id)
        return state
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except Exception as exc:
        logger.exception("[profile/interview/resume] Failed")
        raise HTTPException(status_code=500, detail="Failed to resume interview session. Please try again shortly.") from exc


@router.post("/interview/{session_id}/upload")
async def upload_verification_document(
    session_id: str,
    claim:      str        = Form(..., max_length=500, description="The exact claim being verified"),
    doc_type:   str        = Form("document", max_length=50, description="transcript | diploma | employment_letter | military_record | certificate"),
    file:       UploadFile = File(...),
    user:       CurrentUser = Depends(get_current_user),
):
    """
    Upload a document (PDF or image) to verify a specific profile claim.

    The document is parsed and cross-referenced with the stated claim.
    If verified, the confidence_map entry for that claim is updated to 100%.

    The session must belong to the authenticated user — returns 403 otherwise.
    Returns the verification result and updated confidence_map.
    """
    from backend.agents.profile_interviewer import get_session
    from backend.services.document_verifier import verify_document
    from backend.repositories import profile_interview_repository

    # Validate session (also enforces ownership)
    try:
        session_state = get_session(session_id, user_id=user.user_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))

    # Read file
    content = await file.read()
    if len(content) > 10 * 1024 * 1024:  # 10 MB cap
        raise HTTPException(status_code=413, detail="File too large (max 10 MB).")

    fname = file.filename or "upload"
    ext   = fname.rsplit(".", 1)[-1].lower() if "." in fname else ""
    if not _content_matches_extension(content, ext):
        raise HTTPException(
            status_code=422,
            detail=f"File content does not match its .{ext} extension.",
        )

    # Verify
    try:
        result = await verify_document(
            file_content  = content,
            filename      = fname,
            claim         = claim,
            document_type = doc_type,
        )
    except Exception as exc:
        logger.exception("[profile/interview/upload] Verification failed")
        raise HTTPException(
            status_code=500,
            detail="Document verification failed. Please try again shortly.",
        ) from exc

    # Update confidence_map in DB if verified/partial
    new_confidence = result.get("confidence")
    if new_confidence is not None:
        # Re-fetch immediately before merging (not the pre-verification
        # session_state) so a concurrent write to this session during the
        # verify_document() LLM call is never clobbered.
        fresh = profile_interview_repository.get(session_id)
        if fresh:
            cmap = dict(fresh["confidence_map"] or {})
            # Find the matching claim by label
            claim_lower = claim.lower()
            for k, v in cmap.items():
                if claim_lower in (v.get("label") or "").lower():
                    cmap[k] = {
                        **v,
                        "score":    new_confidence,
                        "status":   result["status"],
                        "evidence": file.filename,
                    }
                    break
            doc_refs = list(fresh["document_refs"] or [])
            doc_refs.append({
                "filename":        file.filename,
                "claim":           claim,
                "status":          result["status"],
                "confidence":      new_confidence,
                "extracted_facts": result.get("extracted_facts", {}),
                "match_notes":     result.get("match_notes", ""),
            })
            profile_interview_repository.update_confidence_and_docs(
                session_id, confidence_map=cmap, document_refs=doc_refs,
            )

    return {
        "verification": result,
        "session_id":   session_id,
    }


# ── GET /api/profile/{user_id}/confidence-matrix ─────────────────────────────

@router.get("/{user_id}/confidence-matrix")
async def get_confidence_matrix_endpoint(
    user_id: str,
    user: CurrentUser = Depends(get_current_user),
):
    """
    Returns the four-category Confidence Matrix for the RadarChart.

    Categories: Technical | Product_Leadership | Data_Analysis | Customer_Success

    Each category score is computed by:
      1. Grouping profile_entities by semantic category via ENTITY_CATEGORY_MAP
      2. Re-weighting evidence by source credibility (cv_parse=0.4, portfolio=0.8,
         conversation_star=0.9, certification=0.7)
      3. Applying exponential recency decay (via confidence_math.freshness_factor)
      4. Geometric combination → 0-100 score per entity → mean per category

    Response shape (recharts RadarChart ready):
      {
        "user_id": "...",
        "radar_data": [
          { "category": "Technical",          "value": 78.4 },
          { "category": "Product_Leadership", "value": 85.1 },
          { "category": "Data_Analysis",      "value": 62.7 },
          { "category": "Customer_Success",   "value": 91.3 }
        ],
        "entity_breakdown": [
          { "entity_id": "...", "name": "Python", "category": "Technical", "score": 88.2 },
          ...
        ],
        "computed_at": "2026-06-08T..."
      }
    """
    if user.user_id != user_id:
        raise HTTPException(status_code=403, detail="You may only access your own confidence matrix.")

    try:
        radar_data = get_confidence_matrix(user_id, ENGINE)
    except Exception as exc:
        logger.exception(
            "[confidence-matrix] radar scoring failed for user=%s: %s", user_id, exc
        )
        raise HTTPException(status_code=500, detail="Radar scoring failed. Please try again shortly.") from exc

    try:
        entity_breakdown = get_entity_breakdown(user_id, ENGINE)
    except Exception as exc:
        logger.exception(
            "[confidence-matrix] entity breakdown failed for user=%s: %s", user_id, exc
        )
        # Non-fatal — return empty breakdown rather than a 500 so the chart still renders
        entity_breakdown = []

    return {
        "user_id":          user_id,
        "radar_data":       radar_data,
        "entity_breakdown": entity_breakdown,
        "computed_at":      datetime.now(timezone.utc).isoformat(),
    }


# ── POST /api/profile/{user_id}/manual-verify/start ──────────────────────────

class ManualVerifyStartRequest(BaseModel):
    entity_id: str

@router.post("/{user_id}/manual-verify/start")
async def start_manual_verification(
    user_id:  str,
    body:     ManualVerifyStartRequest,
    user:     CurrentUser = Depends(get_current_user),
):
    """
    Initiates a manual (syntax) verification session for a specific entity.

    The session is of type 'manual_assessment' — Ariel delivers a time-boxed
    whiteboard-style quiz (no AI autocomplete, no code execution helpers).
    On completion, a 'manual_assessment' evidence record is written, and
    the entity's syntax_confidence + verification_level are recomputed.

    Returns the new ArielSession id and a first-turn prompt to send to
    POST /api/ariel/probe/message.
    """
    if user.user_id != user_id:
        raise HTTPException(status_code=403, detail="Forbidden.")

    import uuid as _uuid

    entity = profile_entity_repository.get_for_user(body.entity_id, user_id)
    if not entity:
        raise HTTPException(status_code=404, detail="Entity not found.")

    # Guard: don't allow a manual_assessment session to re-promote an
    # already VERIFIED_MANUAL entity to a higher tier — they can only
    # re-verify to refresh freshness.
    if entity.verification_level == "VERIFIED_MANUAL":
        logger.info(
            "[manual-verify/start] entity=%s already VERIFIED_MANUAL — refreshing",
            body.entity_id,
        )

    session_id = str(_uuid.uuid4())
    return {
        "session_id":    session_id,
        "entity_id":     body.entity_id,
        "entity_name":   entity.name,
        "session_type":  "manual_assessment",
        "first_prompt":  (
            f"I'll now ask you to demonstrate your hands-on '{entity.name}' skills "
            f"in a short whiteboard-style session. No AI tools, no autocomplete. "
            f"Ready? Tell me: what is the core concept behind {entity.name}, and "
            f"write a minimal working example from memory."
        ),
        "instructions": (
            "Answer without AI assistance. Your response is scored for correctness "
            "and depth — not syntax perfection. When you submit, Ariel will evaluate "
            f"and write a 'manual_assessment' evidence record for '{entity.name}'."
        ),
    }
