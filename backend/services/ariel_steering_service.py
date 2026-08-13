"""
Ariel Steering Service — conversational flow control for the profile-building agent.

Ariel's job is to close gaps in the candidate's profile. Left to itself, an LLM
conversation drifts: the user asks something tangential, Ariel helpfully answers,
and the question that actually mattered is never returned to. This module is the
control layer that keeps a session on-goal without making it feel like an
interrogation.

Three mechanisms, in escalating order of firmness:

  1. HARD BLOCK (check_identity_gate)
     Some data isn't a "gap" to be scored around — it's a precondition. Without
     a name and a contact address there is no application to send, so no amount
     of downstream scoring or CV tailoring is worth doing. This gate stops the
     flow outright and returns the exact prompt Ariel should lead with.

  2. CONDITIONAL SCORE (assess_score_readiness)
     Weaker signal, softer response. A profile can be scored with thin
     experience data — the score just means less, and the honest thing is to
     say so rather than present a confident-looking number built on two lines
     of CV. Returns caveats + a disclaimer to attach to the score, never
     blocks.

  3. DEFERRAL & RE-PIVOT (record_deferral / build_repivot)
     When the user diverges from a critical question, the answer is NOT to
     repeat the question — that reads as not listening. Answer what they asked,
     then re-pivot back. A question the user has visibly stepped around is
     recorded as an explicit deferral so the next turn knows it is owed, and so
     repeated deferrals can eventually be taken as a "no" rather than nagged
     forever.

Where deferrals are stored, and why it isn't ariel_gap_queue
-------------------------------------------------------------
ariel_gap_queue looks like the obvious home — it is literally Ariel's work
queue and its `status` column has no CHECK constraint, so a 'deferred' value
would be free. It can't be the primary store: `entity_id` carries a real FK to
profile_entities, and the most important deferrals are the ones with no entity
at all (a skipped contact-details question references nothing in the knowledge
graph). Forcing those through would mean inventing placeholder entity rows to
satisfy a foreign key, which is how phantom data gets into a profile.

So deferrals live in profile_answers under `_DEFERRAL_KEY`, which is
user-scoped, schema-free, and already the documented home for exactly this kind
of open-ended agent state. When a deferral *does* concern a real entity, the
matching gap_queue row is additionally flipped to 'deferred' so the existing gap
machinery stops re-surfacing a question the user just stepped around — a
secondary index into the same fact, not a competing source of truth.
"""
from __future__ import annotations

import logging
import uuid as _uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from sqlalchemy import text

from backend.core.database import ENGINE

logger = logging.getLogger(__name__)

# Top-level profile-document key holding the deferral ledger.
_DEFERRAL_KEY = "ariel_deferrals"

# ── Identity gate ─────────────────────────────────────────────────────────────
# REQUIRED is deliberately minimal. Every field here blocks the entire flow, so
# the bar is "an application literally cannot be sent without this", not "this
# would be nice to have". A name and a way to reach the candidate clear that
# bar; a LinkedIn URL does not.
REQUIRED_IDENTITY_FIELDS: tuple[str, ...] = ("full_name", "email")
RECOMMENDED_IDENTITY_FIELDS: tuple[str, ...] = ("phone", "location", "linkedin_url")

_FIELD_LABELS = {
    "full_name":    "your full name",
    "email":        "an email address",
    "phone":        "a phone number",
    "location":     "your location",
    "linkedin_url": "your LinkedIn URL",
}

# ── Score readiness thresholds ────────────────────────────────────────────────
_MIN_EXPERIENCE_ENTRIES = 1     # below this the score is not meaningful at all
_THIN_EXPERIENCE_ENTRIES = 2    # at/below this it is computable but caveated
_MIN_SKILLS = 3
_MIN_SUMMARY_CHARS = 80

# Repeated deferrals of the same question stop being an oversight and start
# being an answer. After this many, callers should let it go rather than
# re-pivot again.
MAX_REPIVOTS = 3

CommunicationMode = Literal["one_by_one", "batch"]
_VALID_MODES: tuple[str, ...] = ("one_by_one", "batch")
_DEFAULT_COMMUNICATION_STYLE: dict[str, Any] = {
    "mode":           "one_by_one",
    "tone":           "neutral",
    "responsiveness": "normal",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ═════════════════════════════════════════════════════════════════════════════
# 1. Hard block — identity / contact completeness
# ═════════════════════════════════════════════════════════════════════════════

@dataclass
class IdentityGateResult:
    """Outcome of the precondition check that gates the whole Ariel flow."""
    blocked: bool
    missing_required: list[str] = field(default_factory=list)
    missing_recommended: list[str] = field(default_factory=list)
    prompt: str = ""

    def as_dict(self) -> dict:
        return {
            "blocked":             self.blocked,
            "missing_required":    self.missing_required,
            "missing_recommended": self.missing_recommended,
            "prompt":              self.prompt,
        }


def _read_identity(user_id: str, engine=None) -> dict[str, str]:
    """
    Identity fields from the typed `profiles` columns — the authoritative copy.

    profile_answers also carries a 'personal' dict (save() projects one into the
    other), but that mirror is written by whatever last called save(), whereas
    these columns are what auth and every export actually read. On disagreement
    the column wins, so the gate reads columns.
    """
    eng = engine or ENGINE
    with eng.connect() as conn:
        row = conn.execute(
            text("""
                SELECT full_name, email, phone, location, linkedin_url
                FROM public.profiles WHERE id = CAST(:uid AS uuid)
            """),
            {"uid": user_id},
        ).fetchone()
    if row is None:
        return {}
    return {
        "full_name":    (row.full_name or "").strip(),
        "email":        (row.email or "").strip(),
        "phone":        (row.phone or "").strip(),
        "location":     (row.location or "").strip(),
        "linkedin_url": (row.linkedin_url or "").strip(),
    }


def check_identity_gate(user_id: str, engine=None) -> IdentityGateResult:
    """
    Block the flow when identity/contact basics are absent.

    Returns blocked=True with a ready-to-send prompt when any REQUIRED field is
    empty. Missing RECOMMENDED fields are reported but never block — they are
    worth asking for opportunistically, not worth stopping a session over.
    """
    identity = _read_identity(user_id, engine)

    missing_required = [f for f in REQUIRED_IDENTITY_FIELDS if not identity.get(f)]
    missing_recommended = [f for f in RECOMMENDED_IDENTITY_FIELDS if not identity.get(f)]

    if not missing_required:
        return IdentityGateResult(
            blocked=False,
            missing_required=[],
            missing_recommended=missing_recommended,
            prompt="",
        )

    labels = [_FIELD_LABELS.get(f, f) for f in missing_required]
    if len(labels) == 1:
        needed = labels[0]
    else:
        needed = ", ".join(labels[:-1]) + f" and {labels[-1]}"

    return IdentityGateResult(
        blocked=True,
        missing_required=missing_required,
        missing_recommended=missing_recommended,
        prompt=(
            f"Before we go further I need {needed} — without it there's nothing "
            f"to put on an application. Once that's in, we can get straight to "
            f"your experience."
        ),
    )


# ═════════════════════════════════════════════════════════════════════════════
# 2. Conditional score — compute, but say what it's worth
# ═════════════════════════════════════════════════════════════════════════════

@dataclass
class ScoreReadiness:
    """Whether a match score is worth computing, and what to caveat it with."""
    can_score: bool
    completeness: float                              # 0.0-1.0
    caveats: list[str] = field(default_factory=list)
    disclaimer: Optional[str] = None

    def as_dict(self) -> dict:
        return {
            "can_score":    self.can_score,
            "completeness": self.completeness,
            "caveats":      self.caveats,
            "disclaimer":   self.disclaimer,
        }


def assess_score_readiness(profile: dict) -> ScoreReadiness:
    """
    Judge how much a match score computed from *profile* actually means.

    Pure — takes the profile document rather than a user_id so it can be
    exercised against constructed profiles without a database, and so callers
    that already hold the document don't re-read it.

    Never blocks scoring outright unless there is genuinely nothing to score
    against (no experience at all). Everything else degrades to a caveat: a
    number with an honest disclaimer beats withholding the number, and beats a
    confident number built on nothing.
    """
    experience = profile.get("experience") or []
    skills     = profile.get("skills") or []
    summary    = (profile.get("professional_summary") or "").strip()

    if not isinstance(experience, list):
        experience = []
    if isinstance(skills, dict):
        # tailor.py's categorised shape: {"categories": [{"items": [...]}]}
        skills = [i for cat in skills.get("categories", []) for i in cat.get("items", [])]
    if not isinstance(skills, list):
        skills = []

    caveats: list[str] = []
    signals_met = 0
    total_signals = 4

    if len(experience) >= _THIN_EXPERIENCE_ENTRIES:
        signals_met += 1
    elif experience:
        caveats.append(
            f"Only {len(experience)} role on file — the score reflects a partial career history."
        )

    # Roles present but undated/undescribed score almost as poorly as absent
    # ones, because seniority and depth are both derived from those fields.
    detailed = [
        e for e in experience
        if isinstance(e, dict) and (e.get("summary") or e.get("bullets")) and (e.get("start") or e.get("end"))
    ]
    if experience and len(detailed) == len(experience):
        signals_met += 1
    elif experience:
        caveats.append(
            f"{len(experience) - len(detailed)} of {len(experience)} roles are missing dates "
            f"or a description — seniority and depth are estimated for those."
        )

    if len(skills) >= _MIN_SKILLS:
        signals_met += 1
    else:
        caveats.append(
            f"Only {len(skills)} skill(s) on file — skill matching is unreliable below "
            f"{_MIN_SKILLS}."
        )

    if len(summary) >= _MIN_SUMMARY_CHARS:
        signals_met += 1
    else:
        caveats.append("No professional summary — domain and seniority signals are weaker.")

    completeness = round(signals_met / total_signals, 2)

    if len(experience) < _MIN_EXPERIENCE_ENTRIES:
        return ScoreReadiness(
            can_score=False,
            completeness=completeness,
            caveats=["No work experience on file — there is nothing to match against yet."],
            disclaimer=(
                "I can't give you a meaningful match score yet — there's no work "
                "experience on your profile. Add even one role and I'll score it."
            ),
        )

    disclaimer = None
    if caveats:
        disclaimer = (
            "Heads up: this score is based on an incomplete profile, so treat it as "
            "indicative rather than final. " + " ".join(caveats)
        )

    return ScoreReadiness(
        can_score=True,
        completeness=completeness,
        caveats=caveats,
        disclaimer=disclaimer,
    )


# ═════════════════════════════════════════════════════════════════════════════
# 3. Deferral & re-pivot
# ═════════════════════════════════════════════════════════════════════════════

@dataclass
class Deferral:
    """One critical question the user stepped around."""
    deferral_id: str
    topic: str                       # stable key, e.g. "identity.phone" / entity_id
    question: str                    # the question that went unanswered
    entity_id: Optional[str] = None  # set when the topic maps to a real entity
    job_id: Optional[str] = None
    status: str = "deferred"         # deferred | answered | abandoned
    repivot_count: int = 0
    first_deferred_at: str = ""
    last_deferred_at: str = ""

    def as_dict(self) -> dict:
        return {
            "deferral_id":       self.deferral_id,
            "topic":             self.topic,
            "question":          self.question,
            "entity_id":         self.entity_id,
            "job_id":            self.job_id,
            "status":            self.status,
            "repivot_count":     self.repivot_count,
            "first_deferred_at": self.first_deferred_at,
            "last_deferred_at":  self.last_deferred_at,
        }

    @classmethod
    def from_dict(cls, raw: dict) -> "Deferral":
        return cls(
            deferral_id       = str(raw.get("deferral_id") or ""),
            topic             = str(raw.get("topic") or ""),
            question          = str(raw.get("question") or ""),
            entity_id         = raw.get("entity_id"),
            job_id            = raw.get("job_id"),
            status            = str(raw.get("status") or "deferred"),
            repivot_count     = int(raw.get("repivot_count") or 0),
            first_deferred_at = str(raw.get("first_deferred_at") or ""),
            last_deferred_at  = str(raw.get("last_deferred_at") or ""),
        )


def _load_profile(user_id: str, engine=None) -> dict:
    from backend.repositories import profile_repository
    return profile_repository.get_profile_json(user_id, engine=engine) or {}


def _save_profile_key(user_id: str, key: str, value: Any, engine=None) -> None:
    """Persist one top-level profile-document key, leaving the rest untouched."""
    from sqlalchemy.orm import Session
    from backend.repositories import profile_repository

    eng = engine or ENGINE
    with Session(eng) as session:
        handle, _ = profile_repository.get_or_create(session, user_id, now=_now_iso())
        doc = dict(handle.master_profile)
        doc[key] = value
        handle.master_profile = doc
        profile_repository.save(session, handle)
        session.commit()


def get_deferrals(user_id: str, engine=None, *, include_closed: bool = False) -> list[Deferral]:
    """Every recorded deferral for this user, open ones only unless asked."""
    raw = _load_profile(user_id, engine).get(_DEFERRAL_KEY) or []
    if not isinstance(raw, list):
        return []
    out = [Deferral.from_dict(d) for d in raw if isinstance(d, dict)]
    if include_closed:
        return out
    return [d for d in out if d.status == "deferred"]


def record_deferral(
    user_id: str,
    *,
    topic: str,
    question: str,
    entity_id: Optional[str] = None,
    job_id: Optional[str] = None,
    engine=None,
) -> Deferral:
    """
    Record that the user stepped around *question*, or bump the re-pivot count
    if this topic was already outstanding.

    Idempotent per topic: asking the same thing twice does not create two
    ledger entries, it increments repivot_count on the one that exists. That
    counter is what lets a caller stop asking (MAX_REPIVOTS) instead of
    nagging indefinitely.
    """
    existing = get_deferrals(user_id, engine, include_closed=True)
    now = _now_iso()

    match = next((d for d in existing if d.topic == topic and d.status == "deferred"), None)
    if match is not None:
        match.repivot_count += 1
        match.last_deferred_at = now
        match.question = question or match.question
    else:
        match = Deferral(
            deferral_id       = f"defer-{_uuid.uuid4().hex[:12]}",
            topic             = topic,
            question          = question,
            entity_id         = entity_id,
            job_id            = job_id,
            status            = "deferred",
            repivot_count     = 0,
            first_deferred_at = now,
            last_deferred_at  = now,
        )
        existing.append(match)

    _save_profile_key(user_id, _DEFERRAL_KEY, [d.as_dict() for d in existing], engine)

    # Secondary index: stop the gap machinery re-raising something the user
    # just stepped around. Non-fatal — the ledger above is the source of truth,
    # and a gap row may legitimately not exist for this topic.
    if entity_id:
        _mark_gap_deferred(user_id, entity_id, job_id, engine)

    return match


def resolve_deferral(user_id: str, topic: str, engine=None, *, status: str = "answered") -> bool:
    """Close an outstanding deferral. Returns True if one was open to close."""
    if status not in ("answered", "abandoned"):
        raise ValueError(f"status must be 'answered' or 'abandoned', got {status!r}")

    all_deferrals = get_deferrals(user_id, engine, include_closed=True)
    match = next((d for d in all_deferrals if d.topic == topic and d.status == "deferred"), None)
    if match is None:
        return False

    match.status = status
    _save_profile_key(user_id, _DEFERRAL_KEY, [d.as_dict() for d in all_deferrals], engine)
    return True


def _mark_gap_deferred(user_id: str, entity_id: str, job_id: Optional[str], engine=None) -> None:
    """Flip a matching open ariel_gap_queue row to 'deferred'. Never raises."""
    eng = engine or ENGINE
    try:
        with eng.begin() as conn:
            conn.execute(
                text("""
                    UPDATE ariel_gap_queue
                    SET    status = 'deferred'
                    WHERE  user_id = :uid
                      AND  entity_id = :eid
                      AND  (job_id = :jid OR (:jid IS NULL AND job_id IS NULL))
                      AND  status IN ('pending', 'in_session')
                """),
                {"uid": user_id, "eid": entity_id, "jid": job_id},
            )
    except Exception as exc:
        logger.warning(
            "[ariel-steering] could not mark gap deferred (non-fatal) user=%s entity=%s: %s",
            user_id, entity_id, exc,
        )


def build_repivot(answer: str, deferral: Optional[Deferral]) -> str:
    """
    Compose Ariel's reply: answer what was actually asked, then steer back.

    The ordering is the whole point. Leading with the unanswered question
    ignores what the user said and reads as a bot on rails; answering and then
    re-pivoting is what a person does. When there is nothing outstanding, or
    the topic has been deferred too many times, the answer is returned
    untouched — at some point continuing to ask is just not listening either.
    """
    answer = (answer or "").strip()
    if deferral is None or deferral.status != "deferred":
        return answer
    if deferral.repivot_count >= MAX_REPIVOTS:
        logger.info(
            "[ariel-steering] topic=%s hit MAX_REPIVOTS (%d) — dropping the re-pivot",
            deferral.topic, MAX_REPIVOTS,
        )
        return answer

    question = (deferral.question or "").strip()
    if not question:
        return answer
    if not answer:
        return question

    connector = "Circling back though — " if deferral.repivot_count == 0 else "Still need to pin this down though — "
    return f"{answer}\n\n{connector}{question}"


# ═════════════════════════════════════════════════════════════════════════════
# Communication style
# ═════════════════════════════════════════════════════════════════════════════

def normalize_communication_style(raw: Any) -> dict:
    """
    Coerce whatever is stored into the documented shape, filling defaults.

    Unknown modes fall back to 'one_by_one' rather than raising: this value
    steers prose, and a bad stored value should degrade to the safe default,
    never break a conversation mid-session.
    """
    out = dict(_DEFAULT_COMMUNICATION_STYLE)
    if not isinstance(raw, dict):
        return out

    mode = str(raw.get("mode") or "").strip().lower()
    if mode in _VALID_MODES:
        out["mode"] = mode
    elif mode:
        logger.warning("[ariel-steering] unknown communication mode %r — defaulting to %s",
                       mode, out["mode"])

    for key in ("tone", "responsiveness"):
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            out[key] = value.strip()[:120]
    return out


def get_communication_style(user_id: str, engine=None) -> dict:
    """Ariel's turn-taking preference for this user, defaults filled in."""
    eng = engine or ENGINE
    with eng.connect() as conn:
        row = conn.execute(
            text("SELECT communication_style FROM public.user_preferences WHERE user_id = CAST(:uid AS uuid)"),
            {"uid": user_id},
        ).fetchone()
    return normalize_communication_style(row[0] if row else None)


def set_communication_style(
    user_id: str,
    *,
    mode: Optional[str] = None,
    tone: Optional[str] = None,
    responsiveness: Optional[str] = None,
    engine=None,
) -> dict:
    """
    Update the stated preference, merging over whatever is already there.

    Writes the typed user_preferences column directly rather than going through
    the profile document, so a preference stated mid-conversation takes effect
    on the very next turn without waiting for a full profile save.
    """
    import json as _json

    current = get_communication_style(user_id, engine)
    merged = normalize_communication_style({
        "mode":           mode           if mode           is not None else current["mode"],
        "tone":           tone           if tone           is not None else current["tone"],
        "responsiveness": responsiveness if responsiveness is not None else current["responsiveness"],
    })

    eng = engine or ENGINE
    with eng.begin() as conn:
        conn.execute(
            text("""
                INSERT INTO public.user_preferences (user_id, communication_style, updated_at)
                VALUES (CAST(:uid AS uuid), CAST(:style AS jsonb), now())
                ON CONFLICT (user_id) DO UPDATE
                SET communication_style = EXCLUDED.communication_style, updated_at = now()
            """),
            {"uid": user_id, "style": _json.dumps(merged)},
        )
    return merged


def batch_size_for(user_id: str, engine=None) -> int:
    """
    How many gap questions Ariel may ask in one turn.

    'one_by_one' is the default because an unprompted wall of questions is the
    fastest way to get a session abandoned — but a user who has explicitly said
    they'd rather get it over with should be taken at their word.
    """
    return 4 if get_communication_style(user_id, engine)["mode"] == "batch" else 1
