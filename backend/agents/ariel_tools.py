"""
Ariel Tool Definitions and Execution Handlers
==============================================

This module owns everything the Ariel agent needs to perform No-UI CRUD
operations against the master_profiles table.

Two layers are exposed:

  ARIEL_TOOLS
      A list of Anthropic-compatible tool definitions (JSON Schema) that is
      passed verbatim to the `tools=` parameter of an Anthropic Messages API
      call.  Ariel uses these to decide when and how to update the user's
      master profile during a conversation.

  execute_tool(tool_name, tool_input, user_id, db_session)
      Dispatches a tool call returned by the model to the correct handler.
      Each handler validates its input, applies the mutation to the DB, and
      returns a plain-text result string that is fed back to the model as a
      tool_result content block.

Design rules
------------
• All DB writes are scoped to the authenticated user_id — never touch another
  user's row.
• Handlers are idempotent where possible (upsert semantics).
• No handler raises; they return a descriptive error string on failure so the
  model can surface a friendly message instead of crashing.
• The finalize_onboarding tool is the *only* path that sets
  onboarding_status = 'complete'.  No other code should modify that field.
"""
from __future__ import annotations

import copy
import json
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from backend.core.database import ENGINE
from backend.models.profile import MasterProfileRow
from backend.services.profile_update_service import ProfileUpdateService

logger = logging.getLogger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def _sync_self_assertion(user_id: str, entity_type: str, name: str, raw_content: str = "") -> None:
    """
    Mirror a master_profile edit into the Confidence Matrix as low-weight,
    unverified evidence — so the System Confidence Score reflects facts the
    user states directly in chat (via update_experience/update_skills)
    instead of only ones that arrived through a CV upload.

    Best-effort: master_profile is the authoritative store for the edit
    itself (already committed by the caller), so a failure here is logged
    and swallowed rather than surfacing an error back to the model — a
    Confidence Matrix hiccup should never make a successful profile edit
    look like it failed.
    """
    try:
        ProfileUpdateService(ENGINE).ingest_self_assertion(user_id, entity_type, name, raw_content)
    except Exception as exc:
        logger.error(
            "[ariel_tools] _sync_self_assertion failed user=%s entity_type=%s name=%r: %s",
            user_id, entity_type, name, exc,
        )


def _refresh_baseline(user_id: str) -> None:
    """
    Rebuild the persisted profiling baseline after a profile mutation, so
    every profiling interaction updates the central User Profile record
    (CLAUDE.md global rule / JOB-18). Best-effort, same contract as
    _sync_self_assertion: a snapshot failure never makes a successful
    profile edit look like it failed.
    """
    try:
        from backend.services.profile_baseline_service import refresh_baseline_snapshot
        refresh_baseline_snapshot(user_id)
    except Exception as exc:
        logger.error("[ariel_tools] _refresh_baseline failed user=%s: %s", user_id, exc)


def _empty_master_profile() -> dict:
    """Return the canonical empty master_profile structure."""
    return {
        "professional_summary": "",
        "experience":   [],
        "skills":       [],
        "education":    [],
        "career_goals": {
            "target_roles":        [],
            "preferred_locations": [],
            "work_environment":    "any",
            "notes":               "",
        },
    }


def _get_or_create_row(user_id: str, session: Session) -> MasterProfileRow:
    """
    Return the MasterProfileRow for user_id, creating it if absent.
    The caller is responsible for committing the session.
    """
    from backend.repositories import master_profile_repository
    row, _created = master_profile_repository.get_or_create(session, user_id, now=_now_iso())
    return row


# ── Tool Definitions (Anthropic JSON Schema format) ───────────────────────────

ARIEL_TOOLS: list[dict[str, Any]] = [
    {
        "name": "get_full_candidate_profile",
        "description": (
            "Retrieve the candidate's complete, up-to-date professional profile. "
            "Call this before answering ANY career, strategy, gap-analysis, or "
            "profile-related question to ensure you are working with live data. "
            "Returns the full USER_PROFILE JSON: experience (all roles), skills, "
            "education, personal details, career goals, and key narratives. "
            "Never rely on memory of a previous tool call — always re-fetch when "
            "the user asks something that depends on their profile."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "update_experience",
        "description": (
            "Add a new role to the user's work history, or update an existing one "
            "if the company and role already appear in their profile. "
            "Call this whenever the user shares details about a past or current job."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "company": {
                    "type": "string",
                    "description": "Full legal or common name of the employer.",
                },
                "role": {
                    "type": "string",
                    "description": "Job title held at this employer.",
                },
                "start": {
                    "type": "string",
                    "description": "Start month/year in YYYY-MM format (e.g. '2021-03'). "
                                   "Use the closest approximation if only a year is known.",
                },
                "end": {
                    "type": "string",
                    "description": "End month/year in YYYY-MM format, or the string 'present' "
                                   "if this is the user's current role.",
                },
                "bullets": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Achievement or responsibility bullets for this role. "
                                   "Write in first-person, past tense for past roles "
                                   "and present tense for current ones. "
                                   "Each bullet should be a single concise sentence.",
                },
            },
            "required": ["company", "role", "start", "end", "bullets"],
        },
    },
    {
        "name": "update_skills",
        "description": (
            "Add, remove, OR update skills on the user's profile. Three "
            "independent actions, any combination per call:\n"
            "  • add    — new skills the user mentions they possess.\n"
            "  • remove — skills that are wrong or irrelevant to this profile.\n"
            "  • update — adjust an EXISTING skill's proficiency level and/or "
            "confidence score in place (no delete + re-add). Use this whenever "
            "the user clarifies how strong they actually are at a skill — "
            "especially when they admit they are LESS experienced than the "
            "profile shows (e.g. 'my Python is only beginner level'). Do NOT "
            "remove-and-re-add for this: removing loses the skill's history."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "add": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Skills to add. Normalise to title-case (e.g. 'React', 'SQL', "
                                   "'Product Strategy'). Deduplicate against what's already stored.",
                },
                "remove": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Skills to remove (exact match, case-insensitive).",
                },
                "update": {
                    "type": "array",
                    "description": "Existing skills whose proficiency/confidence should be "
                                   "adjusted in place. One object per skill.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "skill": {
                                "type": "string",
                                "description": "Name of the EXISTING skill to update "
                                               "(case-insensitive match against the profile).",
                            },
                            "proficiency_level": {
                                "type": "string",
                                "enum": ["beginner", "novice", "intermediate",
                                         "proficient", "advanced", "expert"],
                                "description": "The user's self-reported proficiency. When set "
                                               "without an explicit score, the confidence is "
                                               "anchored DOWN to this level's honest ceiling "
                                               "(e.g. 'beginner' caps it at ~30) — a self-claim "
                                               "never inflates the score.",
                            },
                            "suggested_confidence_modifier": {
                                "type": "number",
                                "description": "Signed delta to apply to the current confidence "
                                               "score (e.g. -20 to lower it). Use when you want a "
                                               "relative adjustment rather than a level anchor.",
                            },
                            "new_confidence": {
                                "type": "number",
                                "description": "Explicit new confidence score (0-100). Overrides "
                                               "proficiency_level and suggested_confidence_modifier "
                                               "when you have a precise target in mind.",
                            },
                        },
                        "required": ["skill"],
                    },
                },
            },
            "required": [],
        },
    },
    {
        "name": "update_career_goals",
        "description": (
            "Record the user's career preferences, target roles, and desired work environment. "
            "Call this when the user states what kind of job they are looking for, "
            "where they want to work, or any other forward-looking career preference."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "target_roles": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Job titles or role types the user is targeting "
                                   "(e.g. ['Head of Product', 'Senior PM']).",
                },
                "preferred_locations": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Cities, regions, or countries the user prefers "
                                   "(e.g. ['Tel Aviv', 'Remote']).",
                },
                "work_environment": {
                    "type": "string",
                    "enum": ["remote", "hybrid", "onsite", "any"],
                    "description": "Preferred work arrangement.",
                },
                "notes": {
                    "type": "string",
                    "description": "Any free-form career goal context that doesn't fit "
                                   "the structured fields above (e.g. industry preferences, "
                                   "salary expectations, company-size preferences).",
                },
            },
            "required": [],
        },
    },
    {
        "name": "update_profile_base",
        "description": (
            "Directly write the user's professional summary and/or target job "
            "title into their profile. Call this the moment you and the user "
            "land on new or revised summary/title text — do not print the new "
            "text and ask the user to paste it into the profile UI themselves; "
            "write it yourself, then confirm in your own words."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "summary": {
                    "type": "string",
                    "description": "The full replacement professional summary "
                                   "text, ready to store verbatim.",
                },
                "target_title": {
                    "type": "string",
                    "description": "The user's current primary target job title "
                                   "(e.g. 'Senior Product Manager'). Replaces "
                                   "career_goals.target_roles with this single title.",
                },
            },
            "required": [],
        },
    },
    {
        "name": "get_tailored_cv_for_review",
        "description": (
            "READ the tailored CV the user is currently reviewing. Returns the "
            "positioning summary and every experience section with 0-based bullet "
            "indices. You MUST call this before any edit_tailored_cv_bullet call — "
            "edits reference the exact company names and bullet indices this tool "
            "returns; never edit from memory. Omit job_id to target the most "
            "recently generated tailored CV."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "job_id": {
                    "type": "string",
                    "description": "Job identifier. Omit to use the most recently "
                                   "generated tailored CV.",
                },
            },
            "required": [],
        },
    },
    {
        "name": "edit_tailored_cv_bullet",
        "description": (
            "WRITE one surgical edit to the tailored CV the user is reviewing: "
            "replace a single bullet or the positioning summary. "
            "The backend re-validates the new text through the zero-hallucination "
            "gate: any number, company, product, or named entity that is not "
            "already in the text being replaced AND not backed by a verified "
            "evidence record causes the edit to be REJECTED — the document is "
            "not modified. Therefore never write invented metrics or employers "
            "into new_text, even if the user asks for them. "
            "One bullet per call. Call get_tailored_cv_for_review first to get "
            "the exact company name and bullet_index."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "job_id": {
                    "type": "string",
                    "description": "Job identifier of the CV being edited. Omit to "
                                   "target the most recently generated tailored CV.",
                },
                "section": {
                    "type": "string",
                    "enum": ["summary", "bullet"],
                    "description": "'summary' edits the positioning summary; "
                                   "'bullet' edits one experience bullet.",
                },
                "company": {
                    "type": "string",
                    "description": "Company name of the experience section holding the "
                                   "bullet (as returned by the review tool). "
                                   "Required when section='bullet'.",
                },
                "bullet_index": {
                    "type": "integer",
                    "description": "0-based index of the bullet within that section "
                                   "(as returned by the review tool). "
                                   "Required when section='bullet'.",
                },
                "new_text": {
                    "type": "string",
                    "description": "The full replacement text (max 240 chars). Must only "
                                   "contain facts already present in the current text or "
                                   "in the user's verified evidence.",
                },
            },
            "required": ["section", "new_text"],
        },
    },
    {
        "name": "finalize_onboarding",
        "description": (
            "Mark the user's onboarding as complete. "
            "Call this ONLY when the user explicitly states they have no more background "
            "information to add — for example: 'That's everything', 'I think we're done', "
            "'Nothing else to add'. "
            "Do NOT call this speculatively or mid-conversation. "
            "After this call, onboarding_status will be set to 'complete' and the "
            "full profile will be unlocked for the matching and tailoring pipeline."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "confirmation_phrase": {
                    "type": "string",
                    "description": "The exact phrase or sentence the user used to confirm "
                                   "they are done providing information.",
                },
            },
            "required": ["confirmation_phrase"],
        },
    },
]


# ── Execution Handlers ────────────────────────────────────────────────────────

def _handle_get_full_candidate_profile(
    tool_input: dict[str, Any],
    user_id:    str,
    session:    Session,
) -> str:
    """
    Return the full USER_PROFILE singleton as a JSON string.

    Reads from the in-memory singleton in backend.services.user_profile,
    which is kept current by master_profile_service.py.  The session
    parameter is unused here but kept for dispatcher signature compatibility.

    Returning the raw JSON (not a summary) lets Ariel reason over any field
    without information being lost in a summarisation step.
    """
    try:
        from backend.services.user_profile import get_profile
        from backend.services.llm_validation import sanitize_text
        # Profile text (CV-derived, user-controlled) re-enters Ariel's context as
        # a tool result — sanitize it so a hostile CV can't smuggle instructions.
        payload = sanitize_text(json.dumps(get_profile(user_id), ensure_ascii=False, indent=2))
        logger.info(
            "[ariel_tools] get_full_candidate_profile user=%s payload_len=%d",
            user_id, len(payload),
        )
        return payload
    except Exception as exc:
        logger.error(
            "[ariel_tools] get_full_candidate_profile failed user=%s: %s", user_id, exc,
        )
        return f"error: could not load candidate profile — {exc}"


def _handle_update_experience(
    tool_input: dict[str, Any],
    user_id:    str,
    session:    Session,
) -> str:
    """
    Upsert a role in master_profile["experience"].

    Match is by (company, role) — case-insensitive.  If found, the existing
    entry is replaced.  If not found, the new entry is appended.
    Preserves all other experience entries.
    """
    company = (tool_input.get("company") or "").strip()
    role    = (tool_input.get("role")    or "").strip()
    start   = (tool_input.get("start")   or "").strip()
    end     = (tool_input.get("end")     or "").strip()
    bullets = tool_input.get("bullets") or []

    if not company or not role:
        return "error: 'company' and 'role' are required fields."

    if not isinstance(bullets, list):
        return "error: 'bullets' must be an array of strings."

    bullets = [str(b).strip() for b in bullets if str(b).strip()]

    try:
        row     = _get_or_create_row(user_id, session)
        profile = copy.deepcopy(row.master_profile or _empty_master_profile())

        experience = profile.setdefault("experience", [])

        # Find existing entry by case-insensitive (company, role) match
        match_idx = next(
            (i for i, e in enumerate(experience)
             if e.get("company", "").lower() == company.lower()
             and e.get("role",    "").lower() == role.lower()),
            None,
        )

        entry = {
            "company": company,
            "role":    role,
            "start":   start,
            "end":     end,
            "bullets": bullets,
        }

        if match_idx is not None:
            experience[match_idx] = entry
            action = "updated"
        else:
            experience.append(entry)
            action = "added"

        # Sort experience: current roles first, then by start date descending
        def _sort_key(e: dict) -> tuple:
            is_current = 1 if (e.get("end") or "").lower() == "present" else 0
            return (-is_current, -(int(e.get("start", "0000-00").replace("-", "")) or 0))

        experience.sort(key=_sort_key)

        profile["experience"] = experience
        row.master_profile    = profile
        row.updated_at        = _now_iso()
        session.commit()

        _sync_self_assertion(
            user_id, "experience", f"{role} at {company}",
            " ".join(bullets),
        )
        _refresh_baseline(user_id)

        logger.info(
            "[ariel_tools] update_experience user=%s %s '%s' @ '%s'",
            user_id, action, role, company,
        )
        return (
            f"Experience entry {action}: '{role}' at '{company}' "
            f"({start} – {end}) with {len(bullets)} bullet(s)."
        )

    except Exception as exc:
        session.rollback()
        logger.error("[ariel_tools] update_experience failed user=%s: %s", user_id, exc)
        return f"error: could not save experience — {exc}"


def _handle_update_skills(
    tool_input: dict[str, Any],
    user_id:    str,
    session:    Session,
) -> str:
    """
    Add, remove, and/or update skills.

    add/remove mutate master_profile["skills"] (additions deduplicated,
    removals matched case-insensitively). update adjusts an existing skill's
    proficiency/confidence on the Confidence Matrix entity in place, via
    ProfileUpdateService.apply_chat_proficiency_update.
    """
    to_add    = [str(s).strip() for s in (tool_input.get("add")    or []) if str(s).strip()]
    to_remove = [str(s).strip() for s in (tool_input.get("remove") or []) if str(s).strip()]
    to_update = [u for u in (tool_input.get("update") or []) if isinstance(u, dict) and u.get("skill")]

    if not to_add and not to_remove and not to_update:
        return "No skills to add, remove, or update were specified."

    try:
        row     = _get_or_create_row(user_id, session)
        profile = copy.deepcopy(row.master_profile or _empty_master_profile())

        current: list[str] = profile.setdefault("skills", [])
        lower_current = {s.lower(): s for s in current}

        added, skipped, removed = [], [], []

        for skill in to_add:
            if skill.lower() not in lower_current:
                current.append(skill)
                lower_current[skill.lower()] = skill
                added.append(skill)
            else:
                skipped.append(skill)

        for skill in to_remove:
            canonical = lower_current.get(skill.lower())
            if canonical and canonical in current:
                current.remove(canonical)
                del lower_current[skill.lower()]
                removed.append(canonical)

        current.sort(key=str.lower)
        profile["skills"] = current
        row.master_profile = profile
        row.updated_at     = _now_iso()
        session.commit()

        for skill in added:
            _sync_self_assertion(user_id, "skill", skill)
        # Removed skills aren't synced as negative evidence here — removal
        # usually means "not relevant to this profile," not "this claim was
        # false." A genuine contradiction is handled by ingest_negative_flag
        # via the STAR-probe path, not by this best-effort CRUD tool.

        # ── UPDATE: adjust proficiency / confidence of existing entities ──────
        # Runs against the Confidence Matrix (profile_entities), a separate
        # store from master_profile["skills"] handled above. This is the path
        # for "my Python is only beginner level" — lower the score in place.
        updated, update_failures = [], []
        svc = ProfileUpdateService(ENGINE)
        for item in to_update:
            skill_name = str(item.get("skill") or "").strip()
            if not skill_name:
                continue
            result = svc.apply_chat_proficiency_update(
                user_id,
                skill_name,
                entity_type="skill",
                proficiency_level=item.get("proficiency_level"),
                new_confidence=item.get("new_confidence"),
                confidence_modifier=item.get("suggested_confidence_modifier"),
            )
            if result.get("status") == "updated":
                updated.append(
                    f"{result['name']} → {result['old_score']}→{result['new_score']}"
                    + (f" ({result['proficiency_level']})" if result.get("proficiency_level") else "")
                )
            elif result.get("status") == "not_found":
                update_failures.append(
                    f"{skill_name} (no existing skill entity to update — add it first)"
                )
            else:
                update_failures.append(f"{skill_name} (update error)")

        if added or removed or updated:
            _refresh_baseline(user_id)

        logger.info(
            "[ariel_tools] update_skills user=%s +%d -%d ~%d (skipped %d, failed %d)",
            user_id, len(added), len(removed), len(updated), len(skipped),
            len(update_failures),
        )
        parts = []
        if added:   parts.append(f"Added: {', '.join(added)}")
        if removed: parts.append(f"Removed: {', '.join(removed)}")
        if updated: parts.append(f"Updated: {', '.join(updated)}")
        if skipped: parts.append(f"Already present (skipped): {', '.join(skipped)}")
        if update_failures:
            parts.append(f"Could not update: {', '.join(update_failures)}")
        return " | ".join(parts) or "No changes made."

    except Exception as exc:
        session.rollback()
        logger.error("[ariel_tools] update_skills failed user=%s: %s", user_id, exc)
        return f"error: could not save skills — {exc}"


def _handle_update_career_goals(
    tool_input: dict[str, Any],
    user_id:    str,
    session:    Session,
) -> str:
    """
    Merge career goal fields into master_profile["career_goals"].

    Only fields present in tool_input are updated; missing keys leave the
    existing values untouched (partial update semantics).

    Not synced to the Confidence Matrix (see _sync_self_assertion): target
    roles/locations/work-environment are stated intent, not evidence of a
    skill/trait/domain/experience the entity taxonomy scores capability on.
    """
    target_roles        = tool_input.get("target_roles")
    preferred_locations = tool_input.get("preferred_locations")
    work_environment    = tool_input.get("work_environment")
    notes               = tool_input.get("notes")

    if all(v is None for v in [target_roles, preferred_locations, work_environment, notes]):
        return "No career goal fields were provided."

    try:
        row     = _get_or_create_row(user_id, session)
        profile = copy.deepcopy(row.master_profile or _empty_master_profile())

        goals: dict = profile.setdefault("career_goals", {
            "target_roles": [], "preferred_locations": [],
            "work_environment": "any", "notes": "",
        })

        updated_fields = []

        if target_roles is not None and isinstance(target_roles, list):
            goals["target_roles"] = [str(r).strip() for r in target_roles if str(r).strip()]
            updated_fields.append("target_roles")

        if preferred_locations is not None and isinstance(preferred_locations, list):
            goals["preferred_locations"] = [
                str(loc).strip() for loc in preferred_locations if str(loc).strip()
            ]
            updated_fields.append("preferred_locations")

        if work_environment in ("remote", "hybrid", "onsite", "any"):
            goals["work_environment"] = work_environment
            updated_fields.append("work_environment")

        if notes is not None:
            goals["notes"] = str(notes).strip()
            updated_fields.append("notes")

        profile["career_goals"] = goals
        row.master_profile      = profile
        row.updated_at          = _now_iso()
        session.commit()

        _refresh_baseline(user_id)

        logger.info(
            "[ariel_tools] update_career_goals user=%s fields=%s",
            user_id, updated_fields,
        )
        return f"Career goals updated: {', '.join(updated_fields)}."

    except Exception as exc:
        session.rollback()
        logger.error("[ariel_tools] update_career_goals failed user=%s: %s", user_id, exc)
        return f"error: could not save career goals — {exc}"


def _handle_update_profile_base(
    tool_input: dict[str, Any],
    user_id:    str,
    session:    Session,
) -> str:
    """
    Directly write professional_summary and/or career_goals.target_roles —
    the fields Ariel previously could only recommend and rely on the user to
    paste into the profile UI by hand.

    Partial update semantics: only keys present in tool_input are touched.
    """
    summary      = tool_input.get("summary")
    target_title = tool_input.get("target_title")

    if summary is None and target_title is None:
        return "No summary or target_title was provided."

    try:
        row     = _get_or_create_row(user_id, session)
        profile = copy.deepcopy(row.master_profile or _empty_master_profile())

        updated_fields = []

        if summary is not None:
            profile["professional_summary"] = str(summary).strip()
            updated_fields.append("summary")

        if target_title is not None:
            title = str(target_title).strip()
            goals: dict = profile.setdefault("career_goals", {
                "target_roles": [], "preferred_locations": [],
                "work_environment": "any", "notes": "",
            })
            goals["target_roles"] = [title] if title else []
            profile["career_goals"] = goals
            updated_fields.append("target_title")

        row.master_profile = profile
        row.updated_at     = _now_iso()
        session.commit()

        logger.info(
            "[ariel_tools] update_profile_base user=%s fields=%s",
            user_id, updated_fields,
        )
        return f"Profile updated: {', '.join(updated_fields)}."

    except Exception as exc:
        session.rollback()
        logger.error("[ariel_tools] update_profile_base failed user=%s: %s", user_id, exc)
        return f"error: could not save profile base fields — {exc}"


def _handle_finalize_onboarding(
    tool_input: dict[str, Any],
    user_id:    str,
    session:    Session,
) -> str:
    """
    Set onboarding_status = 'complete'.

    This is the sole authorised writer of that field.  The handler logs the
    confirmation phrase for audit purposes and returns a summary of what was
    collected so the model can relay it to the user.
    """
    phrase = (tool_input.get("confirmation_phrase") or "").strip()

    try:
        row = _get_or_create_row(user_id, session)

        if row.onboarding_status == "complete":
            return "Onboarding was already marked complete. No change made."

        row.onboarding_status = "complete"
        row.updated_at        = _now_iso()
        session.commit()

        profile    = row.master_profile or {}
        exp_count  = len(profile.get("experience", []))
        skill_count = len(profile.get("skills", []))

        logger.info(
            "[ariel_tools] finalize_onboarding user=%s phrase='%s' "
            "experience=%d skills=%d",
            user_id, phrase, exp_count, skill_count,
        )
        return (
            f"Onboarding marked complete. "
            f"Profile summary: {exp_count} experience role(s), "
            f"{skill_count} skill(s) recorded. "
            f"The profile is now unlocked for the matching and CV tailoring pipeline."
        )

    except Exception as exc:
        session.rollback()
        logger.error("[ariel_tools] finalize_onboarding failed user=%s: %s", user_id, exc)
        return f"error: could not finalize onboarding — {exc}"


def _handle_get_tailored_cv_for_review(
    tool_input: dict[str, Any],
    user_id:    str,
    session:    Session,
) -> str:
    """READ side of the CV edit loop — index-addressed view of the live document."""
    try:
        from backend.services.cv_tailor_service import describe_tailored_cv
        view = describe_tailored_cv(job_id=tool_input.get("job_id") or None, user_id=user_id)
        logger.info(
            "[ariel_tools] get_tailored_cv_for_review user=%s job=%s status=%s",
            user_id, view.get("job_id"), view.get("status"),
        )
        return json.dumps(view, ensure_ascii=False, indent=2)
    except Exception as exc:
        logger.error("[ariel_tools] get_tailored_cv_for_review failed user=%s: %s", user_id, exc)
        return f"error: could not load the tailored CV — {exc}"


def _handle_edit_tailored_cv_bullet(
    tool_input: dict[str, Any],
    user_id:    str,
    session:    Session,
) -> str:
    """
    WRITE side of the CV edit loop.

    Delegates to cv_tailor_service.edit_tailored_cv_bullet, which enforces the
    zero-hallucination gate (validate_bullet from cv_assembly_engine) BEFORE
    touching the document. A "rejected" result is a hard logic-level refusal —
    the model must relay it, not retry with the same invented content.
    """
    try:
        from backend.services.cv_tailor_service import edit_tailored_cv_bullet

        bullet_index = tool_input.get("bullet_index")
        result = edit_tailored_cv_bullet(
            user_id      = user_id,
            section      = str(tool_input.get("section") or ""),
            new_text     = str(tool_input.get("new_text") or ""),
            job_id       = tool_input.get("job_id") or None,
            company      = tool_input.get("company") or None,
            bullet_index = int(bullet_index) if bullet_index is not None else None,
        )

        status = result.get("status")
        if status == "applied":
            return (
                "EDIT APPLIED.\n"
                f"Section: {result['section']}"
                + (f" | {result['company']} bullet #{result['bullet_index']}"
                   if result.get("company") else "")
                + f"\nOld: {result['old_text']}\nNew: {result['new_text']}\n"
                + (f"Newly introduced facts licensed by evidence records: "
                   f"{', '.join(result['licensed_by'])}"
                   if result.get("licensed_by")
                   else "No new factual claims introduced (rephrasing only).")
            )
        if status == "rejected":
            return (
                "EDIT REJECTED — ZERO-HALLUCINATION GATE.\n"
                f"{result['refusal']}\n"
                "Do NOT retry with the same unverified content. Relay this refusal "
                "to the user and offer to verify the claim via a STAR probe or "
                "Whiteboard Challenge first."
            )
        return f"error: {result.get('message', 'edit failed for an unknown reason.')}"

    except Exception as exc:
        logger.error("[ariel_tools] edit_tailored_cv_bullet failed user=%s: %s", user_id, exc)
        return f"error: could not apply the CV edit — {exc}"


# ── Dispatcher ────────────────────────────────────────────────────────────────

_HANDLERS = {
    "get_full_candidate_profile": _handle_get_full_candidate_profile,
    "update_experience":          _handle_update_experience,
    "update_skills":              _handle_update_skills,
    "update_career_goals":        _handle_update_career_goals,
    "update_profile_base":        _handle_update_profile_base,
    "finalize_onboarding":        _handle_finalize_onboarding,
    "get_tailored_cv_for_review": _handle_get_tailored_cv_for_review,
    "edit_tailored_cv_bullet":    _handle_edit_tailored_cv_bullet,
}


def execute_tool(
    tool_name:  str,
    tool_input: dict[str, Any],
    user_id:    str,
    session:    Session,
) -> str:
    """
    Dispatch a model-requested tool call to the correct handler.

    Parameters
    ----------
    tool_name   : Name as returned in the model's tool_use content block.
    tool_input  : Parsed input dict from the model's tool_use content block.
    user_id     : Authenticated user_id — all writes are scoped to this value.
    session     : SQLAlchemy Session (caller manages lifecycle / commit scope).

    Returns
    -------
    A plain-text result string to feed back as a tool_result content block.
    Never raises.
    """
    handler = _HANDLERS.get(tool_name)
    if handler is None:
        logger.warning("[ariel_tools] Unknown tool '%s' requested by model.", tool_name)
        return f"error: unknown tool '{tool_name}'."

    logger.info(
        "[ariel_tools] execute_tool tool=%s user=%s input_keys=%s",
        tool_name, user_id, list(tool_input.keys()),
    )
    return handler(tool_input, user_id, session)
