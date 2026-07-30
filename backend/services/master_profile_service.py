"""
MasterProfileService — B2C structured user profile store.

Persists the metrics/supplemental document into master_profiles.master_profile
(under the "metrics_doc" key). This module is intentionally separate from:
  backend/engines/master_profile.py   — bullet-improvement placeholder system
  backend/supplemental_answers.json   — flat Q&A list for LLM context injection
  backend/personal_overrides.json     — phone/location overrides for USER_PROFILE

merge_answers() writes to BOTH this structured store AND supplemental_store.py
to keep the two persistence layers in sync.  The flat supplemental store feeds
build_full_text() so the TailorAgent always sees answered questions as
established profile facts.

Public API
----------
load()                                -> dict
save(profile)                         -> None          (atomic)
get_cached_answer(question_id)        -> str | None
merge_answers(answers)                -> int           (count of new entries)
bootstrap_from_supplemental()         -> int           (count imported)
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

# ── Paths ─────────────────────────────────────────────────────────────────────
# backend/services/master_profile_service.py
#   .parents[0] = backend/services/
#   .parents[1] = backend/
#   .parents[2] = project root
_PROJECT_ROOT = Path(__file__).resolve().parents[2]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def _empty_profile() -> dict:
    """Return a fresh profile scaffold seeded from USER_PROFILE where possible."""
    try:
        from backend.services.user_profile import USER_PROFILE
        p = USER_PROFILE.get("personal", {})
        personal = {
            "full_name":    p.get("name",     ""),
            "email":        p.get("email",    ""),
            "phone":        p.get("phone",    ""),
            "linkedin_url": p.get("linkedin", ""),
            "location":     p.get("location", ""),
        }
    except Exception:
        personal = {
            "full_name": "", "email": "", "phone": "",
            "linkedin_url": "", "location": "",
        }

    return {
        "version":          1,
        "last_updated":     _now_iso(),
        "personal":         personal,
        "metrics":          {},
        "role_preferences": {
            "target_titles":       [],
            "preferred_locations": [],
            "work_type":           "any",   # "remote" | "hybrid" | "onsite" | "any"
            "salary_min_usd":      None,
            # Languages the candidate can work in — evaluated by the ATS Match
            # Engine's knockout layer against JD language requirements.
            "languages":           [],      # e.g. ["hebrew", "english"]
        },
        # Populated by ResearcherAgent — keyed by entity name (lowercase)
        "enriched_entities": {},
    }


# ── Core persistence — per-user, DB-backed (multi-tenant) ─────────────────────
#
# The metrics/supplemental document lives in master_profiles.master_profile
# under the dedicated "metrics_doc" key, so it never collides with the
# onboarding profile fields that ariel_tools maintains in the same JSON column.

def _get_or_create_profile_row(user_id: str, session):
    """Return the MasterProfileRow for user_id, creating an empty one if absent."""
    from backend.repositories import master_profile_repository
    row, _created = master_profile_repository.get_or_create(session, user_id, now=_now_iso())
    return row


def load(user_id: str) -> dict:
    """
    Load the metrics/supplemental document for user_id from master_profiles.

    Returns a fresh scaffold when the user has none.
    """
    from sqlalchemy.orm import Session
    from backend.core.database import ENGINE

    try:
        with Session(ENGINE) as session:
            row = _get_or_create_profile_row(user_id, session)
            doc = (row.master_profile or {}).get("metrics_doc")
            if isinstance(doc, dict) and doc.get("version"):
                return doc

            # No doc yet — seed a fresh scaffold.
            doc = _empty_profile()
            merged = dict(row.master_profile or {})
            merged["metrics_doc"] = doc
            row.master_profile = merged
            row.updated_at     = _now_iso()
            session.commit()
            return doc
    except Exception as exc:
        logger.error("[master_profile] load failed for user=%s: %s", user_id, exc)
        return _empty_profile()


def save(profile: dict, user_id: str) -> None:
    """
    Persist the metrics document for user_id into master_profiles.
    Updates last_updated timestamp before writing.
    """
    from sqlalchemy.orm import Session
    from backend.core.database import ENGINE

    profile["last_updated"] = _now_iso()
    with Session(ENGINE) as session:
        row = _get_or_create_profile_row(user_id, session)
        merged = dict(row.master_profile or {})
        merged["metrics_doc"] = profile
        row.master_profile = merged
        row.updated_at     = _now_iso()
        session.commit()


# ── Answer cache ──────────────────────────────────────────────────────────────

def get_cached_answer(question_id: str, user_id: str) -> str | None:
    """
    Return the stored answer for question_id for this user, or None.

    MVP: answers are returned regardless of confidence level.
    P2: low-confidence answers (updated_at > 180 days) should be surfaced
        to the user for verification before re-use.
    """
    if not question_id:
        return None
    try:
        profile = load(user_id)
        entry = profile.get("metrics", {}).get(question_id)
        if entry and isinstance(entry, dict):
            value = str(entry.get("value", "")).strip()
            if value:
                return value
    except Exception as exc:
        logger.warning("[master_profile] get_cached_answer failed for '%s': %s", question_id, exc)
    return None


def merge_answers(answers: dict[str, str], user_id: str) -> int:
    """
    Write new question_id -> answer pairs into profile["metrics"].

    Behaviour:
    - Always updates "updated_at" for any key that is already present.
    - Sets source="supplemental", confidence="high" for all merged entries.
    - Writes to master_profile.json (structured) AND supplemental_store
      (flat, for LLM context injection) to keep both stores in sync.
    - Returns the count of *newly written* entries (existing keys that are
      merely updated are not counted).

    Never raises — write failures are logged and silently swallowed so a
    profile persistence error never blocks CV generation.
    """
    if not answers:
        return 0

    newly_written = 0
    try:
        profile = load(user_id)
        metrics = profile.setdefault("metrics", {})

        for qid, raw_answer in answers.items():
            answer = str(raw_answer or "").strip()
            if not answer:
                continue
            now = _now_iso()
            if qid in metrics:
                # Update timestamp only — preserve the original created_at
                metrics[qid]["value"]      = answer
                metrics[qid]["updated_at"] = now
                metrics[qid]["confidence"] = "high"
            else:
                metrics[qid] = {
                    "value":      answer,
                    "source":     "supplemental",
                    "confidence": "high",
                    "created_at": now,
                    "updated_at": now,
                }
                newly_written += 1

        save(profile, user_id)

        logger.info(
            "[master_profile] merge_answers: %d new / %d updated (total metrics: %d)",
            newly_written,
            len(answers) - newly_written,
            len(metrics),
        )
    except Exception as exc:
        logger.error("[master_profile] merge_answers failed: %s", exc)
        # Fall through to supplemental_store write regardless

    # ── Keep supplemental_store in sync ───────────────────────────────────────
    # supplemental_store feeds build_full_text() → TailorAgent context.
    # It de-duplicates on its own (skips already-present IDs).
    try:
        from backend.services.supplemental_store import save as save_supplemental
        save_supplemental(answers)
    except Exception as exc:
        logger.warning("[master_profile] supplemental_store sync failed: %s", exc)

    return newly_written


# ── Skill proficiency extraction ─────────────────────────────────────────────

_ACADEMIC_SIGNALS: frozenset[str] = frozenset({
    "academic", "study", "studies", "studied", "course", "coursework",
    "university", "school", "college", "classroom", "thesis",
    "only in", "not professionally", "no professional",
})
_NONE_SIGNALS: frozenset[str] = frozenset({
    "no experience", "never used", "not familiar", "no knowledge",
    "haven't used", "have not used", "no background", "no formal",
    "don't have", "do not have",
})
_PROFESSIONAL_SIGNALS: frozenset[str] = frozenset({
    "professional", "work experience", "industry", "company",
    "client", "production", "shipped", "deployed", "years of", "at work",
})
_SKILL_KEY_STOP_WORDS: frozenset[str] = frozenset({
    "usage", "context", "experience", "level", "proficiency",
    "background", "knowledge", "skill", "details", "info", "history",
})


def get_knockout_prefs(user_id: str) -> dict:
    """
    Return the hard-constraint preferences consumed by the ATS Match Engine's
    knockout layer (ats_match_engine.evaluate_knockouts).

    Shape:
        {
          "work_model": "remote_only" | None,   # None = flexible → never knocks out
          "languages":  ["hebrew", "english", ...],
        }

    "remote_only" is set ONLY when work_type is explicitly "remote" — "any",
    "hybrid", and "onsite" all map to None so the on-site-only knockout can
    never fire against a flexible candidate.
    """
    profile = load(user_id)
    prefs   = profile.get("role_preferences", {}) or {}
    work    = str(prefs.get("work_type", "any")).lower()
    return {
        "work_model": "remote_only" if work == "remote" else None,
        "languages":  [str(l).lower() for l in prefs.get("languages", []) if str(l).strip()],
    }


def get_skill_proficiencies(user_id: str) -> dict[str, str]:
    """
    Return {skill_name: proficiency_level} extracted from verify_* entries
    in master_profile["metrics"].

    proficiency_level values:
      "academic"     — used in studies/education but not professionally
      "professional" — confirmed professional experience
      "none"         — no experience at all
      "unknown"      — fact stored but level cannot be determined

    Skill name is derived from the metric key:
      "verify_python_usage_context"     → "python"
      "verify_machine_learning_context" → "machine learning"
    """
    try:
        profile = load(user_id)
        return extract_skill_proficiencies(profile.get("metrics", {}))
    except Exception as exc:
        logger.warning("[master_profile] get_skill_proficiencies failed: %s", exc)
        return {}


def extract_skill_proficiencies(metrics: dict) -> dict[str, str]:
    """
    Pure form of get_skill_proficiencies: parse proficiency levels straight
    from a metrics dict, no store round-trip. Used by callers that already
    hold the loaded document (profile_baseline_service) and by tests.
    """
    try:
        result: dict[str, str] = {}

        for key, entry in (metrics or {}).items():
            if not key.startswith("verify_"):
                continue

            # Build skill name from the key words before any stop word
            remainder = key[len("verify_"):]          # e.g. "python_usage_context"
            words     = remainder.split("_")
            skill_words: list[str] = []
            for w in words:
                if w in _SKILL_KEY_STOP_WORDS:
                    break
                skill_words.append(w)
            skill = " ".join(skill_words).strip()
            if not skill or len(skill) < 2:
                continue

            value = str(entry.get("value", "")).lower()

            if any(sig in value for sig in _NONE_SIGNALS):
                level = "none"
            elif any(sig in value for sig in _ACADEMIC_SIGNALS):
                level = "academic"
            elif any(sig in value for sig in _PROFESSIONAL_SIGNALS):
                level = "professional"
            else:
                level = "unknown"

            result[skill] = level
            logger.debug("[master_profile] proficiency: %s → %s", skill, level)

        return result

    except Exception as exc:
        logger.warning("[master_profile] extract_skill_proficiencies failed: %s", exc)
        return {}


# ── Profile update from verify/chat interaction ───────────────────────────────

async def update_profile_from_interaction(
    history: list[dict],
    verdict: str,
    summary: str,
    user_id: str,
) -> int:
    """
    Parse a verify/chat Q&A transcript and persist factual corrections the
    candidate stated (e.g. "I only used Python in studies, not professionally")
    into master_profile["metrics"] via merge_answers().

    Uses claude-haiku for fast, cheap extraction. Returns the number of new
    profile entries written. Never raises.
    """
    if not history or verdict not in ("verified", "failed"):
        return 0

    try:
        import os
        from backend.services.llm_client import call_llm

        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            logger.warning("[master_profile] update_profile_from_interaction: ANTHROPIC_API_KEY not set")
            return 0

        lines: list[str] = []
        for entry in history:
            role    = entry.get("role", "")
            content = entry.get("content", "")
            if role == "agent":
                lines.append(f"Agent: {content}")
            elif role == "user":
                lines.append(f"Candidate: {content}")
        transcript = "\n".join(lines)

        prompt = (
            "You are analyzing a job-fit interview transcript to extract factual statements "
            "the candidate made about their own experience.\n\n"
            f"TRANSCRIPT:\n{transcript}\n\n"
            f"VERDICT: {verdict}\nSUMMARY: {summary}\n\n"
            "Extract ONLY concrete, factual statements the candidate made about themselves — "
            "specific skills, tools, years of experience, projects, or context limitations "
            "(e.g. 'only used X in studies', 'led a team of N', 'certified in Y').\n\n"
            "Return a JSON object where each key is a short snake_case identifier "
            "(e.g. 'python_usage_context', 'team_leadership_size') and each value is "
            "the candidate's exact factual statement.\n\n"
            "Return ONLY the JSON object. If no concrete facts were stated, return {}."
        )

        result = await call_llm(
            messages    = [{"role": "user", "content": prompt}],
            model       = "claude-haiku-4-5-20251001",
            max_tokens  = 400,
            temperature = 0.0,
            purpose     = "master_profile_update_from_interaction",
            user_id     = user_id,
        )
        raw = result.text.strip()
        if raw.startswith("```"):
            raw_lines = raw.splitlines()
            raw = "\n".join(raw_lines[1:-1] if raw_lines[-1].strip() == "```" else raw_lines[1:])
        raw = raw.strip()

        facts = json.loads(raw)
        if not isinstance(facts, dict) or not facts:
            return 0

        prefixed = {f"verify_{k}": str(v) for k, v in facts.items() if k and v}
        count = merge_answers(prefixed, user_id)
        logger.info("[master_profile] update_profile_from_interaction: %d fact(s) stored", count)
        return count

    except Exception as exc:
        logger.warning("[master_profile] update_profile_from_interaction failed: %s", exc)
        return 0


# ── Bootstrap migration ───────────────────────────────────────────────────────

def bootstrap_from_supplemental(user_id: str) -> int:
    """
    One-time migration: import all entries from the flat supplemental_answers.json
    into the user's metrics document, skipping keys already present.

    Idempotent — safe to call on every application startup. The supplemental
    file is legacy single-user data, so callers should pass 'default'.
    Returns the count of entries imported.
    """
    try:
        from backend.services.supplemental_store import load_all
        entries = load_all()
    except Exception as exc:
        logger.warning("[master_profile] bootstrap: could not read supplemental store: %s", exc)
        return 0

    if not entries:
        return 0

    try:
        profile = load(user_id)
        metrics = profile.setdefault("metrics", {})
        imported = 0
        now = _now_iso()

        for entry in entries:
            qid    = str(entry.get("id",     "") or "").strip()
            answer = str(entry.get("answer", "") or "").strip()
            if not qid or not answer:
                continue
            if qid in metrics:
                continue  # already present — skip
            metrics[qid] = {
                "value":      answer,
                "source":     "supplemental",
                "confidence": "high",
                "created_at": now,
                "updated_at": now,
            }
            imported += 1

        if imported:
            save(profile, user_id)
            logger.info(
                "[master_profile] bootstrap: imported %d answer(s) from supplemental store",
                imported,
            )
        return imported

    except Exception as exc:
        logger.warning("[master_profile] bootstrap failed: %s", exc)
        return 0


# ── Enriched entities (Researcher Agent output) ───────────────────────────────

def save_enriched_entities(entities: list[dict], user_id: str) -> None:
    """
    Persist the list of EnrichedEntity dicts (from ResearcherAgent) into
    profile["enriched_entities"], keyed by lowercased entity name.
    Merges with any existing entries — does not replace the whole section.
    Never raises.
    """
    if not entities:
        return
    try:
        profile = load(user_id)
        bucket: dict = profile.setdefault("enriched_entities", {})
        for entity in entities:
            name = str(entity.get("name", "")).strip()
            if name:
                bucket[name.lower()] = entity
        save(profile, user_id)
        logger.info(
            "[master_profile] save_enriched_entities: stored %d entity/entities",
            len(entities),
        )
    except Exception as exc:
        logger.error("[master_profile] save_enriched_entities failed: %s", exc)


def get_enriched_entities(user_id: str) -> list[dict]:
    """Return all enriched entities for user_id as a list, sorted by name. Never raises."""
    try:
        profile = load(user_id)
        return sorted(
            profile.get("enriched_entities", {}).values(),
            key=lambda e: str(e.get("name", "")),
        )
    except Exception as exc:
        logger.warning("[master_profile] get_enriched_entities failed: %s", exc)
        return []


def get_enriched_entity(name: str, user_id: str) -> dict | None:
    """Return the enriched entity for a given name (case-insensitive), or None."""
    try:
        profile = load(user_id)
        return profile.get("enriched_entities", {}).get(name.lower())
    except Exception:
        return None


_PERSONAL_FIELDS = ("full_name", "phone", "email", "linkedin_url", "location")


def merge_parsed_contact(personal: dict, user_id: str) -> dict:
    """
    Non-destructively merge CV-parsed contact details into the user's
    metrics_doc["personal"] block, and return {field: value} for what was
    actually written.

    Fill-blanks-only: a field already holding a value is NEVER overwritten by
    a parse. Re-uploading a CV can therefore only ever ADD missing contact
    details, never clobber a value the user has verified or corrected — the
    raw cv_data blob is overwritten wholesale on every upload (that's the
    parse record), but this curated contact block is not.
    """
    incoming = {
        field: str((personal or {}).get(field, "") or "").strip()
        for field in _PERSONAL_FIELDS
    }
    if not any(incoming.values()):
        return {}

    doc      = load(user_id)
    existing = doc.get("personal") or {}
    if not isinstance(existing, dict):
        existing = {}

    applied: dict = {}
    for field in _PERSONAL_FIELDS:
        value = incoming[field]
        if value and not str(existing.get(field, "") or "").strip():
            existing[field] = value
            applied[field]  = value

    if applied:
        doc["personal"] = existing
        save(doc, user_id)
        logger.info(
            "[master_profile] Merged CV-parsed contact field(s) for user=%s: %s",
            user_id, sorted(applied),
        )
    return applied




# ═══════════════════════════════════════════════════════════════════════════════
# User Persona extraction — implicit profile from Ariel interaction history
# ═══════════════════════════════════════════════════════════════════════════════
#
# Distinct from the explicit master profile (facts the user stated): the persona
# captures HOW the user operates — strengths they keep returning to, their
# communication style, and their action-orientation — inferred from their own
# messages in Ariel conversations (chat_sessions table).
#
# Used by the CV tailoring pipeline for tone and framing decisions ONLY. Like
# CompanyProfile, the persona never becomes a factual claim on the CV: it steers
# which VerifiedFacts lead and how bullets are phrased, and every bullet still
# passes the cv_assembly_engine validation gate.

_PERSONA_MODEL       = "claude-opus-4-8"
_PERSONA_TTL_DAYS    = 7
_PERSONA_MAX_CHARS   = 8000    # cap on user-message corpus sent to the LLM
_PERSONA_MAX_SESSIONS = 12

_PERSONA_SYSTEM = """\
You infer a professional persona from a job seeker's own chat messages with
their career agent. Work ONLY from what the user actually wrote — their word
choices, what they emphasise, what they push back on. Do not flatter and do
not invent: if the corpus is too thin to support a field, use an empty string
or empty list.

Respond with ONLY a JSON object (no markdown fences, no prose):
{
  "strengths": ["<recurring strength the user demonstrably leans on>", "..."],
  "communication_style": "<1-2 sentences: direct/narrative, data-first/story-first, formal/casual>",
  "action_orientation": "<1 sentence: builder/optimizer/strategist/firefighter etc., with the evidence pattern>",
  "notes_for_cv_tone": "<1 sentence of guidance for phrasing their CV in a voice that sounds like them>"
}"""


def _collect_user_corpus(user_id: str) -> str:
    """Concatenate the user's OWN messages from recent Ariel chat sessions."""
    from sqlalchemy import text as _text
    from backend.core.database import ENGINE

    stmt = _text("""
        SELECT messages_json FROM chat_sessions
        WHERE user_id = :uid
        ORDER BY updated_at DESC
        LIMIT :lim
    """)
    chunks: list[str] = []
    total = 0
    try:
        with ENGINE.connect() as conn:
            rows = conn.execute(stmt, {"uid": user_id, "lim": _PERSONA_MAX_SESSIONS}).fetchall()
    except Exception as exc:
        logger.warning("[persona] chat_sessions unavailable (%s)", exc)
        return ""

    for (messages_json,) in rows:
        try:
            messages = json.loads(messages_json or "[]")
        except json.JSONDecodeError:
            continue
        for m in messages:
            if m.get("role") != "user":
                continue
            content = str(m.get("content", "")).strip()
            if not content:
                continue
            chunks.append(content)
            total += len(content)
            if total >= _PERSONA_MAX_CHARS:
                return "\n---\n".join(chunks)[:_PERSONA_MAX_CHARS]
    return "\n---\n".join(chunks)


def _load_cached_persona(user_id: str) -> dict | None:
    """Return the cached persona from master_profiles if fresh (< TTL)."""
    from sqlalchemy.orm import Session
    from backend.core.database import ENGINE
    from backend.models.profile import MasterProfileRow

    with Session(ENGINE) as s:
        row = s.get(MasterProfileRow, user_id)
        persona = (row.master_profile or {}).get("user_persona") if row else None
    if not isinstance(persona, dict) or not persona.get("extracted_at"):
        return None
    try:
        age = datetime.now(timezone.utc) - datetime.fromisoformat(persona["extracted_at"])
    except ValueError:
        return None
    return persona if age.days < _PERSONA_TTL_DAYS else None


def _save_persona(user_id: str, persona: dict) -> None:
    import copy as _copy
    from sqlalchemy.orm import Session
    from backend.core.database import ENGINE
    from backend.models.profile import MasterProfileRow

    with Session(ENGINE) as s:
        row = s.get(MasterProfileRow, user_id)
        if row is None:
            return   # no master profile row yet — persona is cache-only, skip
        profile = _copy.deepcopy(row.master_profile or {})
        profile["user_persona"] = persona
        row.master_profile = profile
        s.commit()


async def extract_user_persona(user_id: str, force_refresh: bool = False) -> dict | None:
    """
    Extract (or return cached) the user's persona from their Ariel history.

    Returns a dict with strengths / communication_style / action_orientation /
    notes_for_cv_tone / extracted_at, or None when there is no usable history
    or extraction fails. Callers must treat None as "tailor without persona".
    """
    if not force_refresh:
        cached = _load_cached_persona(user_id)
        if cached:
            return cached

    corpus = _collect_user_corpus(user_id)
    if len(corpus) < 200:   # too thin to say anything defensible
        logger.info("[persona] insufficient chat history for user=%s (%d chars)", user_id, len(corpus))
        return None

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return None

    import re as _re
    from backend.services.llm_client import call_llm

    try:
        result_llm = await call_llm(
            system     = _PERSONA_SYSTEM,
            messages   = [{"role": "user", "content": f"USER'S MESSAGES (newest sessions first):\n\n{corpus}"}],
            model      = _PERSONA_MODEL,
            max_tokens = 800,
            purpose    = "master_profile_extract_persona",
            user_id    = user_id,
        )
        # .raw is the full anthropic.types.Message — preserved so the
        # multi-block join below (not just the first block) still works
        # exactly as it did with the direct SDK call.
        raw  = "".join(b.text for b in result_llm.raw.content if b.type == "text")
        text = _re.sub(r"```(?:json)?", "", raw).strip()
        start, end = text.find("{"), text.rfind("}")
        data = json.loads(text[start:end + 1]) if (start != -1 and end > start) else json.loads(text)

        persona = {
            "strengths":           [str(x)[:200] for x in data.get("strengths", [])][:6],
            "communication_style": str(data.get("communication_style", ""))[:400],
            "action_orientation":  str(data.get("action_orientation", ""))[:400],
            "notes_for_cv_tone":   str(data.get("notes_for_cv_tone", ""))[:400],
            "extracted_at":        datetime.now(timezone.utc).isoformat(),
        }
        _save_persona(user_id, persona)
        logger.info("[persona] extracted for user=%s: %d strengths", user_id, len(persona["strengths"]))
        return persona
    except Exception as exc:
        logger.warning("[persona] extraction failed for user=%s: %s", user_id, exc)
        return None


def format_persona_for_prompt(persona: dict) -> str:
    """Render the persona as a compact prompt block for the tailoring LLM."""
    lines = []
    if persona.get("strengths"):
        lines.append("Recurring strengths: " + "; ".join(persona["strengths"]))
    if persona.get("communication_style"):
        lines.append(f"Communication style: {persona['communication_style']}")
    if persona.get("action_orientation"):
        lines.append(f"Action orientation: {persona['action_orientation']}")
    if persona.get("notes_for_cv_tone"):
        lines.append(f"CV tone guidance: {persona['notes_for_cv_tone']}")
    return "\n".join(lines)
