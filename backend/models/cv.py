"""
CVDataSchema — the single source of truth for the shape of a generated CV.

Before this module the CV shape existed in three unsynchronised places, none of
which could validate the others:

  1. backend/agents/tailor.py's _SYSTEM_PROMPT — a hand-written JSON template
     that is what the LLM actually obeys, and therefore the de-facto contract.
  2. frontend/src/components/LiveEditor.tsx's `CvData` interface — the wire
     type, kept in sync by hand.
  3. frontend/src/lib/cv.ts's RawCvInputSchema — a lenient Zod mirror of (2).

Adding a field meant editing three files in two languages with nothing failing
if you missed one; the failure surfaced later as a silently-dropped section.
This module is (1) mechanically, and generates the JSON Schema handed to the
LLM, so the prompt can no longer drift from the validator.

Two design decisions worth reading before extending this
==========================================================

**The header is server-populated and deliberately hidden from the LLM.**
`header` carries the candidate's real identity and contact details. Those are
read from the user's own profile by pdf_builder._load_contact() and any
contact-shaped keys in the model's output are stripped before rendering
(pdf_builder._CONTACT_KEYS). That is a zero-hallucination guarantee, not an
oversight: an invented phone number or a subtly wrong name is worse than a
weak bullet, because it is undetectable to the reader and fatal to the
application. `llm_json_schema()` therefore emits the schema WITHOUT `header`,
so the model is never invited to author those fields, while `CVDataSchema`
itself still describes the whole document for the frontend and the renderer.
Adding a contact-like field here means adding it to `_LLM_EXCLUDED_FIELDS`.

**Legacy payloads must keep parsing.** Stored CVs (user_job_matches.tailored_cv)
use the pre-unification names: top-level `title`, and `military: {role, unit,
dates}`. Those are accepted via validation aliases and a pre-validator rather
than migrated, so no stored document breaks and no backfill is required. New
output uses the canonical names.

Field length limits mirror backend/agents/tailor.py's `_LIM` exactly. They are
expressed as `max_length` so validation and the prompt-facing JSON Schema state
the same numbers, instead of the prompt describing one limit and the
post-processor silently enforcing another.
"""
from __future__ import annotations

from typing import Any, List, Optional

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    model_validator,
)

# ── Canonical field limits ────────────────────────────────────────────────────
# Single source for both Pydantic validation and the JSON Schema the LLM sees.
# tailor.py imports these so its _LIM table cannot drift from the model.
LIMITS: dict[str, int] = {
    "target_title":   58,
    "summary":       360,
    "exp_role":       45,
    "exp_company":    35,
    "exp_dates":      22,
    "exp_bullet":    240,
    "edu_degree":     60,
    "edu_inst":       35,
    "edu_dates":      20,
    "edu_honors":     60,
    "edu_course":     80,
    "mil_role":       45,
    "mil_unit":       60,
    "mil_dates":      20,
    "mil_resp":      200,
    "skill_label":    20,
    "skill_item":     25,
    "lang_name":      20,
    "lang_level":     35,
    "volunteering":  120,
}

# Sections the LLM must never author — see the module docstring. Stripped from
# llm_json_schema() so the prompt cannot even suggest inventing them.
_LLM_EXCLUDED_FIELDS: frozenset[str] = frozenset({"header"})

# The five canonical language proficiency levels. Kept as a plain tuple rather
# than an Enum: real profiles contain unmapped strings ("Mother tongue"), and
# rejecting a whole CV over one language label would be a worse failure than
# normalising it downstream (tailor._normalize_language_level).
LANGUAGE_LEVELS: tuple[str, ...] = (
    "Native", "Fluent", "Professional Working", "Limited Working", "Elementary",
)


class _Base(BaseModel):
    """Shared config: tolerate unknown keys so a newer producer never hard-fails
    an older consumer, and strip incidental whitespace from every string."""
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)


# ── Header (server-populated) ────────────────────────────────────────────────

class CVHeader(_Base):
    """
    Identity and contact block.

    NOT authored by the LLM (see module docstring). pdf_builder._load_contact()
    fills this from the user's profile at render time. Present in the model so
    the frontend and renderer share one complete document type.
    """
    full_name:    str = Field(default="", max_length=80,
                              description="Candidate's real name, from their profile. Never LLM-authored.")
    target_title: str = Field(
        default="", max_length=LIMITS["target_title"],
        validation_alias=AliasChoices("target_title", "title"),
        description=(
            "Role-specific positioning line — what the candidate IS, not what they are "
            "applying for. The one header field the LLM DOES author, because it is "
            "positioning rather than fact."
        ),
    )
    email:        str = Field(default="", max_length=120)
    phone:        str = Field(default="", max_length=40)
    location:     str = Field(default="", max_length=60)
    linkedin:     str = Field(default="", max_length=120)


# ── Experience ───────────────────────────────────────────────────────────────

class ExperienceEntry(_Base):
    company: str = Field(default="", max_length=LIMITS["exp_company"])
    role:    str = Field(default="", max_length=LIMITS["exp_role"])
    dates:   str = Field(default="", max_length=LIMITS["exp_dates"],
                         description="Copied verbatim from the profile. Never inferred.")
    bullets: List[str] = Field(
        default_factory=list,
        description=(
            "XYZ-structured achievement bullets: achievement + measurable proof + method. "
            f"Target {LIMITS['exp_bullet']} chars; not hard-truncated, because mid-word "
            "truncation reads worse than a slightly long line."
        ),
    )


# ── Education ────────────────────────────────────────────────────────────────

class EducationEntry(_Base):
    degree:      str = Field(default="", max_length=LIMITS["edu_degree"])
    institution: str = Field(default="", max_length=LIMITS["edu_inst"])
    dates:       str = Field(default="", max_length=LIMITS["edu_dates"])
    honors:      str = Field(default="", max_length=LIMITS["edu_honors"],
                             description="Factual credentials only (Dean's List, GPA). No narrative.")
    coursework:  str = Field(default="", max_length=LIMITS["edu_course"])


# ── Military service (Israeli market) ────────────────────────────────────────

class MilitaryService(_Base):
    """
    IDF / National Service, expressed in professional business language.

    Israeli CVs list service as substantive early-career experience — for many
    candidates it is where they first led people or owned a system, and for a
    recent graduate it may be the strongest leadership evidence on the page. It
    is modelled with real responsibility content (`key_responsibilities`) rather
    than as a one-line credential, so a reader outside Israel can read the scope
    without knowing what the unit name means.

    `role_title`/`unit_type` accept the legacy `role`/`unit` keys so stored CVs
    keep parsing.
    """
    role_title: str = Field(
        default="", max_length=LIMITS["mil_role"],
        validation_alias=AliasChoices("role_title", "role"),
        description=(
            "Business-language rendering of the role. Translate function, never transliterate: "
            "a literal rank or unit translation is meaningless to a non-Israeli reader and "
            "reads as unpolished to an Israeli one."
        ),
    )
    unit_type: str = Field(
        default="", max_length=LIMITS["mil_unit"],
        validation_alias=AliasChoices("unit_type", "unit"),
        description="Unit or corps, in the form the candidate's profile states it.",
    )
    dates: str = Field(default="", max_length=LIMITS["mil_dates"])
    key_responsibilities: List[str] = Field(
        default_factory=list,
        description=(
            "Optional scope lines, same XYZ discipline as experience bullets. Omitted "
            "entirely when the candidate has civilian experience worth the page space — "
            "the page budget decides, not this schema."
        ),
    )

    def is_present(self) -> bool:
        """True when there is real service content worth rendering."""
        return bool(self.role_title.strip())


# ── Skills ───────────────────────────────────────────────────────────────────

class SkillCategory(_Base):
    label: str = Field(default="", max_length=LIMITS["skill_label"],
                       description="Mirrors JD vocabulary, e.g. Tools, Methodologies, Domains.")
    items: List[str] = Field(default_factory=list)


class SkillsSection(_Base):
    """
    Categorised skills.

    Categories are free-form rather than a fixed tools/methodologies/languages
    triple on purpose: the labels are meant to mirror the target JD's own
    vocabulary, and a fixed set would force empty or mislabelled buckets for
    candidates whose field does not divide that way. Canonical starting labels
    live in CANONICAL_SKILL_CATEGORIES for callers that want a default.
    """
    categories: List[SkillCategory] = Field(default_factory=list)


CANONICAL_SKILL_CATEGORIES: tuple[str, ...] = ("Tools", "Methodologies", "Domains")


class LanguageEntry(_Base):
    language: str = Field(default="", max_length=LIMITS["lang_name"])
    level:    str = Field(default="", max_length=LIMITS["lang_level"],
                          description=f"One of: {', '.join(LANGUAGE_LEVELS)}.")


# ── Root document ────────────────────────────────────────────────────────────

class CVDataSchema(_Base):
    """
    A complete generated CV.

    Every section except `experience` is optional in practice: a career-changer
    may have no degree, a non-Israeli candidate no service record, a new
    graduate no employment history. Sections are therefore empty-by-default
    rather than required, and the renderer omits empty ones entirely instead of
    printing a bare heading.
    """
    header:  CVHeader = Field(default_factory=CVHeader)
    summary: str = Field(default="", max_length=LIMITS["summary"],
                         description="2-3 sentences, opening with a quantified strength.")

    experience: List[ExperienceEntry] = Field(default_factory=list)
    education:  List[EducationEntry]  = Field(default_factory=list)

    military_service: Optional[MilitaryService] = Field(
        default=None,
        validation_alias=AliasChoices("military_service", "military"),
        description="Omitted entirely (null) when the candidate did not serve.",
    )

    skills:       SkillsSection       = Field(default_factory=SkillsSection)
    languages:    List[LanguageEntry] = Field(default_factory=list)
    volunteering: str = Field(default="", max_length=LIMITS["volunteering"])

    # ── Legacy compatibility ──────────────────────────────────────────────────

    @model_validator(mode="before")
    @classmethod
    def _absorb_legacy_shape(cls, data: Any) -> Any:
        """
        Accept pre-unification documents unchanged.

        Two shapes exist in stored data (user_job_matches.tailored_cv):
          - a top-level `title`, which is now header.target_title
          - `military: {}` used as "no service", which is now None

        Handled here rather than by a data migration: the stored documents are
        historical output that should keep rendering exactly as they did, and a
        backfill would rewrite user-visible content to satisfy a naming change.
        """
        if not isinstance(data, dict):
            return data
        out = dict(data)

        # Top-level `title` predates the header block. Only lift it when the
        # header does not already carry positioning, so a caller that sets both
        # keeps the explicit one.
        legacy_title = out.get("title")
        if legacy_title:
            header = out.get("header")
            header = dict(header) if isinstance(header, dict) else {}
            if not header.get("target_title") and not header.get("title"):
                header["target_title"] = legacy_title
                out["header"] = header

        # `military: {}` / `{"role": ""}` meant "no service" in the old shape;
        # an empty object would otherwise validate into a present-but-blank
        # section and render an empty heading.
        mil = out.get("military_service", out.get("military"))
        if isinstance(mil, dict) and not (mil.get("role_title") or mil.get("role")):
            out["military_service"] = None
            out.pop("military", None)

        return out

    # ── Derived helpers ───────────────────────────────────────────────────────

    def present_sections(self) -> list[str]:
        """
        Which optional sections carry real content — the input the page-budget
        engine allocates against, and the reason an absent section costs nothing
        rather than leaving a gap.
        """
        present = []
        if self.summary.strip():
            present.append("summary")
        if self.experience:
            present.append("experience")
        if self.education:
            present.append("education")
        if self.military_service and self.military_service.is_present():
            present.append("military_service")
        if self.skills.categories:
            present.append("skills")
        if self.languages:
            present.append("languages")
        if self.volunteering.strip():
            present.append("volunteering")
        return present

    def to_render_dict(self) -> dict:
        """
        Serialise for the renderer and the wire, using canonical names.

        `by_alias=False` deliberately: aliases exist to READ legacy documents,
        never to write them, so output always moves toward the canonical shape.
        """
        return self.model_dump(mode="json", by_alias=False)

    # ── LLM contract ──────────────────────────────────────────────────────────

    @classmethod
    def llm_json_schema(cls) -> dict:
        """
        JSON Schema for the prompt: the full model minus the sections the LLM
        must not author (see module docstring).

        Generated rather than hand-written so the prompt cannot drift from the
        validator — the exact failure this module exists to remove.
        """
        schema = cls.model_json_schema()
        props = schema.get("properties", {})
        for field in _LLM_EXCLUDED_FIELDS:
            props.pop(field, None)
        if "required" in schema:
            schema["required"] = [r for r in schema["required"] if r not in _LLM_EXCLUDED_FIELDS]
        return schema

    @classmethod
    def llm_schema_hint(cls) -> str:
        """Compact JSON-Schema string for embedding in a system prompt."""
        import json
        return json.dumps(cls.llm_json_schema(), ensure_ascii=False, indent=2)


def _structural_remap(data: dict) -> dict:
    """
    Legacy -> canonical key mapping with NO validation.

    The strict model rejects over-length fields, but length is not this
    function's concern — clamping belongs to tailor._enforce_limits, which runs
    after normalization and expects canonical keys. Without this fallback a
    single over-length title made normalization fail, the document passed
    through still shaped `military`, and _enforce_limits then looked for
    `military_service`, found nothing, and silently dropped the user's entire
    military section. Renaming keys must never depend on the content being
    within limits.
    """
    out = dict(data)

    title = out.pop("title", None)
    if title:
        header = dict(out.get("header") or {})
        header.setdefault("target_title", title)
        out["header"] = header

    mil = out.pop("military", out.get("military_service"))
    if isinstance(mil, dict):
        role = mil.get("role_title") or mil.get("role") or ""
        out["military_service"] = {
            "role_title": role,
            "unit_type":  mil.get("unit_type") or mil.get("unit") or "",
            "dates":      mil.get("dates", ""),
            "key_responsibilities": list(mil.get("key_responsibilities") or []),
        } if role else None
    elif mil is None:
        out["military_service"] = None

    return out


def normalize_cv(data: Any, *, context: str = "cv") -> dict:
    """
    Convert any CV payload — legacy or canonical — into the canonical shape.

    This is the choke point that makes the rename safe. Every boundary where a
    CV enters the system (LLM output, a stored tailored_cv row, a request body
    from the editor) runs through here, so nothing downstream has to know that
    two shapes ever existed: consumers read `header.target_title` and
    `military_service` only.

    Strict validation first, because it also applies defaults and drops junk.
    When that fails — almost always an over-length field, which the downstream
    clamp exists to fix — fall back to the structural remap so the KEYS are
    still canonical. Losing a section to a length quibble would be a far worse
    failure than a slightly long string that _enforce_limits is about to trim.
    """
    import logging

    if not isinstance(data, dict):
        return {}
    try:
        return CVDataSchema.model_validate(data).to_render_dict()
    except Exception as exc:
        logging.getLogger(__name__).info(
            "[%s] strict CV validation failed (%s) — applying structural remap; "
            "downstream limit enforcement will clamp the offending field.",
            context, str(exc).replace("\n", " ")[:160],
        )
        return _structural_remap(data)
