"""
CvTailorService — generates a focused, job-specific CV brief for the feed card.

Distinct from TailorAgent (which produces a full PDF-ready CV data dict),
this service produces a lightweight "tailor brief":

  • positioning_summary — 2-3 sentence pitch for this specific role
  • tailored_sections — top 2-3 experience roles with rewritten bullets

Philosophy
----------
The LLM receives THREE grounding sources and is instructed to work ONLY
from them — never to invent experience, metrics, or claims:
  1. build_full_text() — full profile narrative
  2. get_skill_proficiencies() — verified proficiency levels from Q&A sessions
  3. job.jd_text — the raw JD (or a thin proxy if not yet scraped)

Caching
-------
Results are persisted in the existing `tailored_cv` JSON column under the
"tailor_brief" key so subsequent opens are instant:
  {"cv_data": {...}, "match_score": {...}, "tailor_brief": {...}}
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from backend.utilities.ai_scrubber import scrub_dict
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

from backend.repositories import job_repository as job_store
from backend.services.llm_client import call_llm, LLMCallError
from backend.services.user_profile import USER_PROFILE, build_full_text
from backend.services.llm_validation import harden_system_prompt, sanitize_text
from backend.services.master_profile_service import get_skill_proficiencies
from backend.schemas.job import JobMatch

load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=True)

logger = logging.getLogger(__name__)

_MODEL      = "claude-sonnet-4-6"   # quality-sensitive — rewriting real bullets
_MAX_TOKENS = 3000
_MIN_JD_LEN = 60   # chars — below this we warn but still proceed

# ── Prompt ────────────────────────────────────────────────────────────────────

_SYSTEM = """\
You are a strategic matchmaker: a senior tech recruiter and ATS optimization expert \
with 20 years of experience placing candidates at top B2B SaaS companies in EMEA. \
You do not just match keywords — you position a candidate inside the target \
company's CURRENT reality.

Your task is to analyse how a candidate's VERIFIED experience intersects with a job \
description AND the company's present situation, then produce a structured JSON brief that:
  1. Positions the candidate for this specific role at this specific moment in the \
     company's trajectory.
  2. Rewrites 3-5 key experience bullets per relevant role to emphasise genuine overlaps \
     with the JD — using the JD's own terminology where it fits naturally.

STRATEGIC SELECTION & FRAMING (when COMPANY_INTELLIGENCE is provided):
  • lean / turnaround (layoffs, cost discipline, profitability push): lead with the \
    candidate's REAL efficiency evidence — cost savings, automation, consolidation, \
    retention. A hiring manager in cutting mode buys "does more with less".
  • hypergrowth / growth (funding, expansion, aggressive hiring): lead with REAL \
    scaling evidence — growth metrics, launches, 0→1 work, building teams and systems \
    under speed.
  • stable / unknown: balanced framing; do not force a narrative the intelligence \
    does not support.
  • Echo the company's strategic_focus and hiring_persona in the positioning_summary \
    where the candidate's verified history genuinely intersects with them.
  • When USER_PERSONA is provided, phrase bullets and the summary in a voice \
    consistent with it (direct vs narrative, data-first vs story-first).

THE STRATEGY CHANGES THE NARRATIVE, NEVER THE FACTS — ABSOLUTE RULES:
  • NEVER invent experience, metrics, company names, dates, or skills not present \
    in the CANDIDATE_PROFILE or PROFICIENCY_MAP. This applies with full force to \
    strategic framing: if the company needs efficiency and the candidate has no \
    efficiency metrics, you write the honest bullets you have — you do NOT \
    manufacture cost-saving numbers to fit the strategy.
  • COMPANY_INTELLIGENCE and USER_PERSONA are context about the company and the \
    candidate's style. They are NEVER a source of factual claims about the \
    candidate's history.
  • ONLY reframe authentic experience using the JD's language — do not add \
    fictional quantification (e.g. "increased revenue by 40%") unless the number \
    already appears in the profile.
  • Output ONLY the raw JSON object — no markdown fences, no preamble, no explanation.
  • All bullet strings must be under 220 characters.
  • Include only the 2-3 most relevant experience roles in tailored_sections; \
    omit roles with negligible signal for this JD.
  • You MUST output a maximum of 4 bullets for the most recent role and 2 bullets \
    for all older roles. Brevity is critical — the output must fit a single A4 page.
"""

_USER_TMPL = """\
CANDIDATE_PROFILE:
{profile}

PROFICIENCY_MAP (skill → verified level: professional | academic | none | unknown):
{proficiency_block}

COMPANY_INTELLIGENCE (context for SELECTION and FRAMING only — never a source of candidate facts):
{company_intel_block}

USER_PERSONA (the candidate's implicit style — tone guidance only):
{persona_block}

JOB_TITLE: {title}
COMPANY: {company}
LOCATION: {location}

JOB_DESCRIPTION:
{jd_text}

─────────────────────────────────────────────────────────────────────────────
Produce a single JSON object matching this exact schema (no extra keys):

{{
  "positioning_summary": "2-3 sentences specifically positioning this candidate for THIS role at THIS company, in its CURRENT situation per COMPANY_INTELLIGENCE. Reference the company and role explicitly. Be concrete — not generic.",

  "positioning_strategy": "1 sentence naming the strategy you applied (e.g. 'Company in lean mode — led with verified efficiency and retention metrics') or 'No company intelligence available — balanced framing.'",

  "tailored_sections": [
    {{
      "role": "Job title held",
      "company": "Employer name",
      "dates": "Date range",
      "bullets": [
        "Bullet rewritten to highlight JD overlap — max 220 chars. No invented facts.",
        "..."
      ]
    }}
  ]
}}

For tailored_sections, only include the 2-3 roles with the strongest signal for this JD.
BULLET LIMITS (hard): most recent role → max 4 bullets; every other role → max 2 bullets.
"""


# ── Proficiency block builder ─────────────────────────────────────────────────

def _build_proficiency_block(user_id: str) -> str:
    """Format the user's skill→level map into a readable block for the prompt."""
    proficiencies = get_skill_proficiencies(user_id)
    if not proficiencies:
        return "(No verified proficiency data — profile Q&A not yet completed)"

    lines = []
    for skill, level in sorted(proficiencies.items()):
        lines.append(f"  • {skill}: {level}")
    return "\n".join(lines)


# ── JSON extraction ───────────────────────────────────────────────────────────

def _extract_json(raw: str) -> dict:
    """
    Extract the first valid JSON object from the model response.
    Handles cases where the model accidentally wraps output in markdown fences.
    """
    # Strip markdown fences if present
    text = re.sub(r"```(?:json)?", "", raw).strip()

    # Try the whole string first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Fall back: find the outermost {...}
    start = text.find("{")
    end   = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass

    raise ValueError(f"Could not extract valid JSON from model response. "
                     f"Raw (first 400 chars): {raw[:400]}")


# ── Result validation / normalisation ────────────────────────────────────────

def _normalise(raw_dict: dict, job: JobMatch) -> dict:
    """
    Ensure all required keys exist and value types are correct.
    Fills in safe defaults rather than raising, so partial outputs are usable.
    """
    brief: dict = {
        "job_id":              job.job_id,
        "job_title":           job.title,
        "company":             job.company,
        "generated_at":        datetime.now(timezone.utc).isoformat(),
        "positioning_summary": str(raw_dict.get("positioning_summary", "")),
        "positioning_strategy": str(raw_dict.get("positioning_strategy", "")),
        "tailored_sections":   [],
    }

    for section in raw_dict.get("tailored_sections", []):
        if not isinstance(section, dict):
            continue
        brief["tailored_sections"].append({
            "role":    str(section.get("role", "")),
            "company": str(section.get("company", "")),
            "dates":   str(section.get("dates", "")),
            "bullets": [str(b) for b in section.get("bullets", []) if b],
        })

    return brief


# ── Cache helpers ─────────────────────────────────────────────────────────────

def get_cached_tailor_brief(job_id: str, user_id: str) -> Optional[dict]:
    """Return the cached tailor brief for a job owned by user_id, or None."""
    cached = job_store.get_tailored_cv(job_id, user_id)
    if cached and isinstance(cached, dict):
        return cached.get("tailor_brief")
    return None


def _save_tailor_brief(job_id: str, user_id: str, brief: dict) -> None:
    """Persist the brief under the tailor_brief key — only on a row owned by user_id."""
    from backend.core.database import ENGINE
    from backend.models.job import JobRow
    from sqlalchemy.orm import Session

    with Session(ENGINE) as session:
        row = session.get(JobRow, job_id)
        if row and row.user_id == user_id:
            existing = dict(row.tailored_cv or {})
            existing["tailor_brief"] = brief
            row.tailored_cv = existing
            session.commit()


# ── Main entry point ──────────────────────────────────────────────────────────

async def _build_verified_assembly(job: JobMatch, jd_text: str, user_id: str, company_vibe: str | None = None) -> dict:
    """
    Run the Zero-Hallucination CV Assembly Engine for this job.

    Pipeline:
      1. Load VerifiedFacts from the evidence ledger (Confidence Matrix).
      2. Derive JD competency gaps deterministically (heuristic splitter +
         confidence-matrix matching — no LLM call).
      3. assemble_cv() → provenance-validated bullets, unserved gaps.

    Returns a JSON-safe dict attached to the tailor brief as
    brief["verified_assembly"].
    """
    from backend.services.ats_match_engine import (
        extract_competencies, heuristic_structured_jd, score_competencies,
    )
    from backend.services.confidence_matrix_service import get_entity_breakdown
    from backend.services.cv_assembly_engine import assemble_cv, load_verified_facts
    from backend.core.database import ENGINE

    facts    = load_verified_facts(user_id, ENGINE)
    entities = list(get_entity_breakdown(user_id, ENGINE))

    # Gap analysis: which JD must-haves are / aren't evidenced.
    structured = heuristic_structured_jd(jd_text)
    competencies = extract_competencies(structured)
    _, detail, gap_lines = score_competencies(competencies, entities)

    matched  = [m.matched_entity for m in detail if m.matched_entity]
    gap_ents = [
        m.competency.normalized for m in detail
        if m.matched_entity is None and m.competency.tier.value == "must_have"
    ]

    # LLM phrasing layer: only attempt it when the key is configured.
    use_llm_phrasing = bool(os.getenv("ANTHROPIC_API_KEY"))

    assembled = await assemble_cv(
        facts            = facts,
        gap_entities     = gap_ents,
        matched_entities = matched,
        candidate_title  = USER_PROFILE.get("personal", {}).get("title", "") or job.title,
        use_llm_phrasing = use_llm_phrasing,
        company_vibe     = company_vibe,   # strategy biases fact SELECTION only
    )

    return {
        "summary":        assembled.summary,
        "bullets":        [
            {"text": b.text, "entity": b.entity, "fact_ids": b.fact_ids}
            for b in assembled.bullets
        ],
        "skills":         assembled.skills,
        "unserved_gaps":  assembled.unserved_gaps,
        "gap_lines":      gap_lines,
        "rejected_count": assembled.rejected_count,
        "fact_count":     len(facts),
    }


async def generate_tailor_brief(job_id: str, force_refresh: bool = False, *, user_id: str) -> dict:
    """
    Generate (or return cached) a tailor brief for the given job.

    Parameters
    ----------
    job_id        : DB identifier of the job
    force_refresh : when True, bypass the cache and re-generate
    user_id       : REQUIRED owner — from a verified JWT or the pipeline loop.
                    All job access is ownership-checked against this value.

    Returns
    -------
    dict matching the tailor brief schema (see _normalise()).

    Raises
    ------
    ValueError  when the job doesn't exist (or isn't owned by user_id) or has
                no usable JD/profile text.
    RuntimeError on LLM API failure.
    """
    # ── 1. Load job (ownership-checked) ───────────────────────────────────────
    job = job_store.get_by_id(job_id, user_id)
    if not job:
        raise ValueError(f"Job {job_id!r} not found in the store.")

    # ── 2. Check cache ────────────────────────────────────────────────────────
    if not force_refresh:
        cached = get_cached_tailor_brief(job_id, user_id)
        if cached:
            logger.info("[cv_tailor] Cache hit for job_id=%s", job_id)
            return cached

    # ── 3. Prepare context ────────────────────────────────────────────────────
    profile_text      = build_full_text(user_id)
    proficiency_block = _build_proficiency_block(user_id)

    jd_text = (job.jd_text or "").strip()
    if len(jd_text) < _MIN_JD_LEN:
        # Thin proxy — JD not yet scraped. Use what we have.
        jd_text = (
            f"Job title: {job.title}\n"
            f"Company:   {job.company}\n"
            f"Location:  {job.location}\n\n"
            f"(Full job description not yet available — fetch it via 'Fetch Details' "
            f"for a more precise tailoring.)"
        )
        logger.warning(
            "[cv_tailor] JD text too short for job %s (%s @ %s) — using thin proxy",
            job_id, job.title, job.company,
        )

    # ── 3b. Company Intelligence + User Persona (both strictly non-fatal) ────
    # Framing/selection context ONLY — the fact source remains the profile and
    # the VerifiedFact ledger. A failure here degrades to the un-strategic brief.
    company_intel_block = "(no company intelligence available)"
    company_vibe: str | None = None
    try:
        from backend.services.company_intelligence_service import (
            format_for_prompt, get_company_profile,
        )
        intel = await get_company_profile(job.company or "")
        if intel:
            company_intel_block = format_for_prompt(intel)
            company_vibe        = intel.financial_vibe
    except Exception as exc:
        logger.warning("[cv_tailor] company intelligence unavailable (non-fatal): %s", exc)

    persona_block = "(no persona extracted yet — neutral professional tone)"
    try:
        from backend.services.master_profile_service import (
            extract_user_persona, format_persona_for_prompt,
        )
        persona = await extract_user_persona(user_id)
        if persona:
            persona_block = format_persona_for_prompt(persona)
    except Exception as exc:
        logger.warning("[cv_tailor] persona extraction unavailable (non-fatal): %s", exc)

    # ── 4. Build and call the LLM ─────────────────────────────────────────────
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set.")

    # Sanitize untrusted text (profile-derived CV text + scraped JD) before it
    # is formatted into the prompt.
    user_msg = _USER_TMPL.format(
        profile             = sanitize_text(profile_text),
        proficiency_block   = proficiency_block,
        company_intel_block = company_intel_block,
        persona_block       = persona_block,
        title               = job.title,
        company             = job.company,
        location            = job.location or "Israel",
        jd_text             = sanitize_text(jd_text[:4000]),   # cap to avoid token overflow
    )

    logger.info(
        "[cv_tailor] Generating brief for '%s @ %s' (job_id=%s, jd_len=%d)",
        job.title, job.company, job_id, len(jd_text),
    )

    try:
        result_llm = await call_llm(
            system     = harden_system_prompt(_SYSTEM),
            messages   = [{"role": "user", "content": user_msg}],
            model      = _MODEL,
            max_tokens = _MAX_TOKENS,
            purpose    = "cv_tailor_generate_brief",
            user_id    = user_id,
            job_id     = job_id,
        )
    except LLMCallError as exc:
        raise RuntimeError(str(exc)) from exc

    raw_text = result_llm.text

    # ── 5. Parse and normalise ────────────────────────────────────────────────
    try:
        raw_dict = _extract_json(raw_text)
        raw_dict = scrub_dict(raw_dict)
    except ValueError as exc:
        logger.error("[cv_tailor] JSON extraction failed: %s", exc)
        raise RuntimeError(f"Model returned unparseable output: {exc}") from exc

    brief = _normalise(raw_dict, job)

    # ── 5b. Zero-Hallucination assembly layer (LIVE) ──────────────────────────
    # Attach provenance-validated bullets built exclusively from the evidence
    # ledger. The LLM brief above remains for narrative sections; the bullets
    # below are the only content guaranteed fact-backed. Non-fatal on failure —
    # the brief is still returned without the assembly block.
    try:
        brief["verified_assembly"] = await _build_verified_assembly(job, jd_text, user_id, company_vibe=company_vibe)
    except Exception as exc:
        logger.warning("[cv_tailor] verified assembly failed (non-fatal): %s", exc)
        brief["verified_assembly"] = None
    brief["company_intelligence"] = {
        "vibe": company_vibe, "block": company_intel_block,
    } if company_vibe else None

    # ── 6. Cache and return ───────────────────────────────────────────────────
    try:
        _save_tailor_brief(job_id, user_id, brief)
    except Exception as exc:
        logger.warning("[cv_tailor] Failed to cache brief for job %s: %s", job_id, exc)

    logger.info(
        "[cv_tailor] Brief generated for '%s @ %s' — %d sections",
        job.title, job.company,
        len(brief["tailored_sections"]),
    )
    return brief


# ═══════════════════════════════════════════════════════════════════════════════
# Ariel executor — surgical Read-Write edits on an EXISTING tailored CV
# ═══════════════════════════════════════════════════════════════════════════════
#
# Ariel does NOT build CVs (that is generate_tailor_brief / the Tailor engine).
# She performs localized edits on the document the user is currently reviewing:
# the JobRow.tailored_cv JSON ({"cv_data", "match_score", "tailor_brief"}).
#
# Zero-hallucination contract (enforced HERE, at the logic level — never
# delegated to the model's good behaviour):
#   The proposed text is passed through validate_bullet() — the exact same
#   provenance gate assemble_cv() uses. The allowed literal universe is
#     union(VerifiedFact.literals)  ∪  literals(current text being replaced)
#   i.e. rephrasing/tightening what the document already says is always legal,
#   but any NEW number, company, product, or named entity must trace to a
#   VerifiedFact from the evidence ledger. Anything else → status="rejected"
#   with the offending literals listed, and the document is NOT touched.

_EDIT_MAX_CHARS = 240   # mirrors the CopilotAgent / brief bullet ceiling


def _document_fact(text: str) -> "object":
    """
    Wrap existing document text as a synthetic VerifiedFact so its literals are
    admissible during re-validation. Rationale: this text was licensed when the
    document was generated; an edit must not lose that licence just because the
    generation-time evidence has rotated. Only NEW literals need fresh provenance.
    """
    from backend.services.cv_assembly_engine import VerifiedFact
    return VerifiedFact(
        fact_id="__current_document__",
        source_type="current_document",
        entity="__document__",
        action=text,
    )


def resolve_editable_cv(job_id: Optional[str] = None, *, user_id: str) -> tuple[Optional[str], Optional[dict]]:
    """
    Return (job_id, tailored_cv_doc) for the edit target — user_id's rows ONLY.

    With an explicit job_id → that job's document if owned by user_id (else
    (job_id, None) — same response as "no CV yet", never leaking existence).
    Without one → the user's most recently generated tailored CV, resolved by
    the brief's generated_at timestamp ("the CV" in conversation means the one
    THIS user just produced and is reviewing).
    """
    from backend.core.database import ENGINE
    from backend.models.job import JobRow
    from sqlalchemy.orm import Session

    with Session(ENGINE) as session:
        if job_id:
            row = session.get(JobRow, job_id)
            if row and row.user_id == user_id and row.tailored_cv:
                return (job_id, dict(row.tailored_cv))
            return (job_id, None)

        rows = (
            session.query(JobRow)
            .filter(JobRow.tailored_cv.isnot(None), JobRow.user_id == user_id)
            .all()
        )
        best: Optional[JobRow] = None
        best_ts = ""
        for row in rows:
            doc = row.tailored_cv or {}
            ts  = str((doc.get("tailor_brief") or {}).get("generated_at", ""))
            if best is None or ts > best_ts:
                best, best_ts = row, ts
        if best is None:
            return (None, None)
        return (best.job_id, dict(best.tailored_cv))


def describe_tailored_cv(job_id: Optional[str] = None, *, user_id: str) -> dict:
    """
    READ side of Ariel's loop: a compact, index-addressed view of the document
    so the model can reference sections and bullets precisely ("bullet 2 of the
    Go-Out section") instead of editing from memory. Scoped to user_id.
    """
    resolved_id, doc = resolve_editable_cv(job_id, user_id=user_id)
    if not doc:
        return {"status": "not_found", "job_id": resolved_id,
                "message": "No tailored CV exists yet — generate one with the Tailor CV button first."}

    brief   = doc.get("tailor_brief") or {}
    cv_data = doc.get("cv_data") or {}

    sections = []
    for s in brief.get("tailored_sections", []):
        sections.append({
            "company": s.get("company", ""),
            "role":    s.get("role", ""),
            "bullets": {str(i): b for i, b in enumerate(s.get("bullets", []))},
        })
    # Fall back to cv_data.experience when the brief has no sections.
    if not sections:
        for e in cv_data.get("experience", []):
            sections.append({
                "company": e.get("company", ""),
                "role":    e.get("role", ""),
                "bullets": {str(i): b for i, b in enumerate(e.get("bullets", []))},
            })

    return {
        "status":   "ok",
        "job_id":   resolved_id,
        "job_title": brief.get("job_title", ""),
        "target_company": brief.get("company", ""),
        "summary":  brief.get("positioning_summary") or cv_data.get("summary", ""),
        "sections": sections,
    }


def _replace_in_cv_data(cv_data: dict, old_text: str, new_text: str) -> bool:
    """Mirror an applied bullet edit into cv_data.experience when the same text exists there."""
    changed = False
    for e in cv_data.get("experience", []):
        bullets = e.get("bullets")
        if isinstance(bullets, list):
            for i, b in enumerate(bullets):
                if str(b).strip() == old_text.strip():
                    bullets[i] = new_text
                    changed = True
    return changed


def edit_tailored_cv_bullet(
    user_id:      str,
    section:      str,                    # "summary" | "bullet"
    new_text:     str,
    job_id:       Optional[str] = None,
    company:      Optional[str] = None,   # required for section="bullet"
    bullet_index: Optional[int] = None,   # required for section="bullet"
) -> dict:
    """
    WRITE side of Ariel's loop — apply ONE validated edit to the stored document.

    Returns a dict with status:
      "applied"  — document mutated and persisted; includes old/new + provenance.
      "rejected" — zero-hallucination gate refused; includes offending literals
                   and a user-facing refusal. Document untouched.
      "error"    — target not found / bad reference. Document untouched.
    """
    from backend.services.cv_assembly_engine import (
        _extract_literals, load_verified_facts, validate_bullet,
    )
    from backend.core.database import ENGINE
    from backend.models.job import JobRow
    from sqlalchemy.orm import Session

    new_text = " ".join((new_text or "").split())
    if not new_text:
        return {"status": "error", "message": "new_text is empty."}
    if len(new_text) > _EDIT_MAX_CHARS:
        return {"status": "error",
                "message": f"new_text is {len(new_text)} chars — the ceiling is {_EDIT_MAX_CHARS}. Tighten it."}

    resolved_id, doc = resolve_editable_cv(job_id, user_id=user_id)
    if not doc:
        return {"status": "error", "job_id": resolved_id,
                "message": "No tailored CV exists to edit — generate one with the Tailor CV engine first."}

    brief   = doc.get("tailor_brief") or {}
    cv_data = doc.get("cv_data") or {}

    # ── 1. Locate the target text ─────────────────────────────────────────────
    old_text: Optional[str] = None
    apply_fn = None   # closure that mutates `doc` in place once validation passes

    if section == "summary":
        if brief.get("positioning_summary"):
            old_text = str(brief["positioning_summary"])
            def apply_fn() -> None:
                brief["positioning_summary"] = new_text
                if cv_data.get("summary"):
                    cv_data["summary"] = new_text
        elif cv_data.get("summary"):
            old_text = str(cv_data["summary"])
            def apply_fn() -> None:
                cv_data["summary"] = new_text

    elif section == "bullet":
        if not company or bullet_index is None:
            return {"status": "error",
                    "message": "section='bullet' requires both 'company' and 'bullet_index'."}
        needle = company.strip().lower()
        pools: list[list] = [brief.get("tailored_sections", []), cv_data.get("experience", [])]
        for pool in pools:
            for entry in pool:
                if needle in str(entry.get("company", "")).lower():
                    bullets = entry.get("bullets") or []
                    if 0 <= bullet_index < len(bullets):
                        old_text = str(bullets[bullet_index])
                        def apply_fn(entry=entry, bullets=bullets) -> None:
                            bullets[bullet_index] = new_text
                            entry["bullets"] = bullets
                            _replace_in_cv_data(cv_data, old_text, new_text)  # keep both views in sync
                        break
            if old_text is not None:
                break
    else:
        return {"status": "error", "message": f"Unknown section {section!r} — use 'summary' or 'bullet'."}

    if old_text is None or apply_fn is None:
        return {"status": "error", "job_id": resolved_id,
                "message": (f"Could not locate {section} target "
                            f"(company={company!r}, bullet_index={bullet_index}). "
                            "Call the review tool and use its exact indices.")}

    # ── 2. Zero-hallucination gate (assemble_cv's validate_bullet) ────────────
    facts   = load_verified_facts(user_id, ENGINE)
    allowed = facts + [_document_fact(old_text)]
    if not validate_bullet(new_text, allowed):
        allowed_literals = set()
        for f in allowed:
            allowed_literals |= f.literals
        illegal = sorted(_extract_literals(new_text) - allowed_literals)
        logger.warning(
            "[cv_tailor] Ariel edit REJECTED job=%s section=%s illegal=%s",
            resolved_id, section, illegal,
        )
        return {
            "status":  "rejected",
            "job_id":  resolved_id,
            "illegal_literals": illegal,
            "refusal": (
                "Edit rejected by the zero-hallucination gate: "
                f"{', '.join(repr(t) for t in illegal)} do(es) not appear in the current "
                "CV text or in any verified evidence record. This CV only carries claims "
                "that trace to verified facts. To include this, verify it first "
                "(STAR probe / Whiteboard Challenge), then retry the edit."
            ),
        }

    # Provenance report: which verified facts license the NEWLY introduced literals.
    new_literals = _extract_literals(new_text) - _extract_literals(old_text)
    licensed_by  = sorted({
        f.fact_id for f in facts if new_literals & f.literals
    }) if new_literals else []

    # ── 3. Apply + persist ────────────────────────────────────────────────────
    apply_fn()
    with Session(ENGINE) as session:
        row = session.get(JobRow, resolved_id)
        if row is None or row.user_id != user_id:
            return {"status": "error", "message": f"Job {resolved_id!r} vanished mid-edit."}
        merged = dict(row.tailored_cv or {})
        if brief:
            merged["tailor_brief"] = brief
        if cv_data:
            merged["cv_data"] = cv_data
        row.tailored_cv = merged          # reassign — JSON column change detection
        session.commit()

    logger.info(
        "[cv_tailor] Ariel edit APPLIED job=%s section=%s company=%r idx=%s licensed_by=%s",
        resolved_id, section, company, bullet_index, licensed_by,
    )
    return {
        "status":      "applied",
        "job_id":      resolved_id,
        "section":     section,
        "company":     company,
        "bullet_index": bullet_index,
        "old_text":    old_text,
        "new_text":    new_text,
        "licensed_by": licensed_by,   # fact_ids covering newly-introduced literals
    }
