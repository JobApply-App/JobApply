"""
ArielProbeService
=================
Drives Ariel's structured discovery sessions for entities whose confidence
score is below the probe threshold.

Probe methodology branches on entity_type
------------------------------------------
  skill      → STAR (Situation / Action / Result)
                Validates concrete execution: measurable outcome required.
  domain /
  experience → SCOPE (Scale / Cross-functional / Trade-off)
                Validates contextual mastery: breadth, structural clarity,
                judgment.  Quantitative metrics are OPTIONAL, not required.
  trait      → SIGNAL (Observable behaviour / Personal ownership / Change)
                Validates authentic behavioural patterns.  Scores on
                authenticity and demonstrated change, not hard metrics.

Design contract
---------------
• get_pending_probes()     — find entities that need probing (score < 70,
                             no probe in the last PROBE_COOLDOWN_H hours,
                             no manual_review_required block).
• get_probe_question()     — return the type-appropriate turn question for
                             the current probe turn (1–3).
• evaluate_probe_response()— LLM-backed rubric evaluation; selects the
                             correct evaluator based on entity_type.
• record_probe_outcome()   — writes ariel_probe_log, then calls either
                             ingest_conversation_event() (positive) or
                             ingest_negative_flag() (shallow/contradiction).

Safety invariant
----------------
Only one entity may be actively probed per session.  The caller must finish
(or abandon) the current probe before requesting the next one.

Integration
-----------
All evidence mutations go through ProfileUpdateService to guarantee that the
audit log and confidence re-computation are always triggered.

Usage sketch
------------
    service = ArielProbeService(engine, ProfileUpdateService(engine))
    targets = service.get_pending_probes(user_id)
    if targets:
        entity  = targets[0]
        session = profile_update_service.open_session(user_id, "star_probe",
                      target_entities=[entity["entity_id"]])

        q1 = service.get_probe_question(entity, turn=1)
        # ... collect user answers over 3 turns ...
        result = await service.evaluate_probe_response(transcript, entity, session_id=session)
        service.record_probe_outcome(user_id, entity, session, result)
        profile_update_service.close_session(session)
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import text

from backend.services.llm_client import call_llm

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────

PROBE_CONFIDENCE_THRESHOLD = 70.0   # probe entities below this score
PROBE_COOLDOWN_H           = 48     # hours between probes of the same entity
POSITIVE_CONFIDENCE_FLOOR  = 0.55   # extraction_confidence below this → negative flag
LLM_EVAL_TIMEOUT_S         = 28.0   # seconds before we give up on the LLM call

# Soft message returned to the user when the LLM call times out or errors.
_RETRY_MESSAGE = (
    "I couldn't fully evaluate your answer. "
    "Let's try one more specific example — focus on a single situation, "
    "a concrete decision or judgment call you personally made, and what changed as a result."
)

# ── Entity-type routing ────────────────────────────────────────────────────────
# Maps entity_type strings (lowercase) to probe methodology.
# "skill"      → STAR-based (concrete execution + measurable outcome)
# "domain" /
# "experience" → SCOPE-based (scale, cross-functional complexity, trade-offs)
# "trait"      → SIGNAL-based (observable behaviour, ownership, change)
# Anything unknown defaults to STAR.

def _probe_method(entity_type: str) -> str:
    t = (entity_type or "skill").lower().strip()
    if t in ("domain", "experience"):
        return "scope"
    if t == "trait":
        return "signal"
    return "star"


# ══════════════════════════════════════════════════════════════════════════════
# STAR  (entity_type = skill)
# Validates concrete technical / functional execution.
# Turn 1 = Situation, Turn 2 = Action, Turn 3 = Result (metric required)
# ══════════════════════════════════════════════════════════════════════════════

_STAR_PROMPTS = {
    1: (
        "You mentioned **{name}** as a strength. "
        "Can you walk me through a specific project where this skill was the deciding factor?"
    ),
    2: (
        "That's a good start. "
        "What was your specific role in that project? "
        "What was a decision you had to make that went against the grain?"
    ),
    3: (
        "What was the measurable outcome of that decision? "
        "How did you validate success?"
    ),
}

_STAR_EVALUATOR_SYSTEM = """\
You are a behavioral interview evaluator assessing a 3-turn STAR (Situation /
Task / Action / Result) candidate response for a specific SKILL entity.

Evaluation rubric — score each dimension 0.0–1.0:
  specificity  : Does the answer name real people, dates, metrics, or projects?
                 Generic "we improved X" with no numbers → low score.
  depth        : Does the Action turn reveal a real decision or trade-off the
                 candidate personally owned?  Vague participation → low score.
  consistency  : Are all three turns about the same situation without
                 contradictions?

Return ONLY valid JSON — no prose, no markdown fences.
Required schema:
{
  "star_components": {
    "situation": "<extracted situation text, or empty string>",
    "task":      "<extracted task / challenge text, or empty string>",
    "action":    "<extracted action / decision text, or empty string>",
    "result":    "<extracted measurable result text, or empty string>"
  },
  "rubric": {
    "specificity":  0.0-1.0,
    "depth":        0.0-1.0,
    "consistency":  0.0-1.0
  },
  "extraction_confidence": 0.0-1.0,
  "flag_type": "none" | "shallow_star" | "contradiction",
  "flag_reason": "<see rules below>"
}

extraction_confidence = mean of the three rubric dimensions.

flag_type rules:
  "contradiction"  — turns describe clearly different situations, time periods,
                     or contain internally inconsistent claims.
  "shallow_star"   — specificity < 0.4 OR depth < 0.4 (no concrete details).
  "none"           — evidence is credible and internally consistent.

flag_reason rules (CRITICAL — stored verbatim in the audit log and shown to
the user to explain why their answer was flagged):
  • MUST be empty string "" when flag_type is "none".
  • MUST be a single, specific sentence quoting the candidate's actual words
    and naming the exact gap or contradiction.
  • For "contradiction": start with "Contradiction:" and cite the conflicting
    claims from different turns.
  • For "shallow_star": start with "Shallow response:" and name the missing
    concrete element (metric, date, decision, project name).
  • Never write generic phrases like "the answer lacked detail".
    Always reference the specific skill being probed and what was said.
"""

_STAR_USER_TEMPLATE = """\
Skill being probed: {name}

--- TRANSCRIPT START ---
Turn 1 (Situation):
User: {t1}

Turn 2 (Action):
User: {t2}

Turn 3 (Result):
User: {t3}
--- TRANSCRIPT END ---

Evaluate the transcript and return JSON only.
"""


# ══════════════════════════════════════════════════════════════════════════════
# SCOPE  (entity_type = domain | experience)
# Validates contextual mastery: breadth, structural clarity, judgment.
# Quantitative metrics are evidence of quality but NOT required for a pass.
# Turn 1 = Scale / Scope, Turn 2 = Cross-functional complexity, Turn 3 = Trade-off
# ══════════════════════════════════════════════════════════════════════════════

_SCOPE_PROMPTS = {
    1: (
        "You have experience in **{name}**. "
        "Describe the scale and complexity of the environment you operated in — "
        "the size of the system, team, customer base, or market you were responsible for."
    ),
    2: (
        "That gives good context. "
        "Walk me through a cross-functional challenge you navigated in that domain. "
        "Which teams or stakeholders were involved, and what was the core tension between them?"
    ),
    3: (
        "What was the most significant strategic trade-off or prioritisation decision you made "
        "or directly influenced in that space? "
        "How did you evaluate the options and what drove your recommendation?"
    ),
}

_SCOPE_EVALUATOR_SYSTEM = """\
You are an expert interviewer evaluating a candidate's depth of experience in a
DOMAIN or EXPERIENCE entity.  This is NOT a STAR behavioural interview — do NOT
penalise for the absence of a single quantitative outcome metric.  Instead,
assess structural understanding, breadth of context, and quality of judgment.

Evaluation rubric — score each dimension 0.0–1.0:
  breadth          : Does Turn 1 demonstrate real operational scale or scope?
                     Indicators: team sizes, ARR/GMV ranges, system complexity,
                     customer segments, geographic spread, market context.
                     Vague generalities ("I worked in SaaS") without any scale
                     indicators → low score.
  structural_clarity: Does Turn 2 show understanding of how different functions
                     interact and where the real tensions lie?  "Worked with
                     engineering" without naming the friction → low score.
                     Naming the specific cross-functional conflict or dependency
                     and why it was hard → high score.
  judgment         : Does Turn 3 reveal genuine analytical trade-off reasoning?
                     The candidate should name at least two options considered
                     and explain the basis for the recommendation.  "We decided
                     to do X" without framing the alternative → low score.

Return ONLY valid JSON — no prose, no markdown fences.
Required schema:
{
  "star_components": {
    "situation": "<scope/scale description from Turn 1, or empty string>",
    "task":      "<cross-functional challenge from Turn 2, or empty string>",
    "action":    "<trade-off reasoning / recommendation from Turn 3, or empty string>",
    "result":    "<outcome or signal of the decision's impact, or empty string — may be absent>"
  },
  "rubric": {
    "breadth":           0.0-1.0,
    "structural_clarity": 0.0-1.0,
    "judgment":          0.0-1.0
  },
  "extraction_confidence": 0.0-1.0,
  "flag_type": "none" | "shallow_scope" | "contradiction",
  "flag_reason": "<see rules below>"
}

extraction_confidence = mean of the three rubric dimensions.

flag_type rules:
  "contradiction"  — turns describe clearly different domains, contexts, or
                     contain internally inconsistent claims.
  "shallow_scope"  — breadth < 0.4 OR structural_clarity < 0.4 (no real
                     contextual anchors).
  "none"           — the candidate demonstrates credible domain exposure.
                     NOTE: absence of a precise metric does NOT trigger a flag.

flag_reason rules:
  • MUST be empty string "" when flag_type is "none".
  • MUST be a single, specific sentence quoting the candidate's actual words
    and naming the exact gap or contradiction.
  • For "shallow_scope": start with "Shallow response:" and name the missing
    contextual anchor (scale indicator, named stakeholder tension, trade-off options).
  • Never penalise the candidate for not providing a revenue figure or KPI.
    Only penalise for genuinely absent context or vague non-answers.
"""

_SCOPE_USER_TEMPLATE = """\
Domain / Experience entity being probed: {name}

--- TRANSCRIPT START ---
Turn 1 (Scale / Scope):
User: {t1}

Turn 2 (Cross-functional complexity):
User: {t2}

Turn 3 (Strategic trade-off):
User: {t3}
--- TRANSCRIPT END ---

Evaluate the transcript and return JSON only.
"""


# ══════════════════════════════════════════════════════════════════════════════
# SIGNAL  (entity_type = trait)
# Validates authentic behavioural patterns: ownership, observable change.
# Turn 1 = Observable behaviour, Turn 2 = Personal ownership, Turn 3 = Change
# ══════════════════════════════════════════════════════════════════════════════

_SIGNAL_PROMPTS = {
    1: (
        "You listed **{name}** as a defining trait. "
        "Think of a moment when this quality was critical to a project or team outcome — "
        "what was the situation, and why did it require this trait specifically?"
    ),
    2: (
        "What was your specific, personal contribution in that moment "
        "that demonstrated **{name}** — separate from what the team did collectively?"
    ),
    3: (
        "What changed as a direct result of how you showed up? "
        "That could be a project outcome, a team dynamic, or your own professional development."
    ),
}

_SIGNAL_EVALUATOR_SYSTEM = """\
You are a behavioural interview evaluator assessing a candidate's TRAIT entity.
This is not a skills or domain interview — focus on authentic patterns of
behaviour, not measurable KPIs.

Evaluation rubric — score each dimension 0.0–1.0:
  authenticity     : Does Turn 1 describe a real, specific situation where this
                     trait was genuinely tested, or does it read like a textbook
                     example?  Specific names, friction, or stakes → high score.
                     Generic "I always show this trait" → low score.
  personal_ownership: Does Turn 2 clearly separate the candidate's own
                     contribution from the group effort?  "We did" without
                     distinguishing the candidate's individual decision →
                     low score.
  demonstrated_change: Does Turn 3 articulate a concrete change — even a
                     qualitative one — that resulted from this moment?
                     "Nothing changed" or "things improved" → low score.

Return ONLY valid JSON — no prose, no markdown fences.
Required schema:
{
  "star_components": {
    "situation": "<observable situation from Turn 1, or empty string>",
    "task":      "<personal contribution from Turn 2, or empty string>",
    "action":    "<specific behaviour demonstrated, or empty string>",
    "result":    "<change that resulted from Turn 3, or empty string>"
  },
  "rubric": {
    "authenticity":       0.0-1.0,
    "personal_ownership": 0.0-1.0,
    "demonstrated_change": 0.0-1.0
  },
  "extraction_confidence": 0.0-1.0,
  "flag_type": "none" | "shallow_signal" | "contradiction",
  "flag_reason": "<see rules below>"
}

extraction_confidence = mean of the three rubric dimensions.

flag_type rules:
  "contradiction"  — turns describe clearly different situations or persons,
                     or contain internally inconsistent claims.
  "shallow_signal" — authenticity < 0.4 OR personal_ownership < 0.4
                     (no distinct personal contribution).
  "none"           — the pattern is credible and personally owned.

flag_reason rules:
  • MUST be empty string "" when flag_type is "none".
  • MUST be a single, specific sentence referencing the candidate's own words.
  • For "shallow_signal": start with "Shallow response:" and name the missing
    personal element (individual action, named friction, personal stakes).
  • Do NOT penalise for absent metrics — traits are validated through
    authentic narrative, not numbers.
"""

_SIGNAL_USER_TEMPLATE = """\
Trait entity being probed: {name}

--- TRANSCRIPT START ---
Turn 1 (Observable behaviour):
User: {t1}

Turn 2 (Personal ownership):
User: {t2}

Turn 3 (Demonstrated change):
User: {t3}
--- TRANSCRIPT END ---

Evaluate the transcript and return JSON only.
"""


# ══════════════════════════════════════════════════════════════════════════════
# Dispatch tables — keyed by probe method
# ══════════════════════════════════════════════════════════════════════════════

_PROMPTS_BY_METHOD: dict[str, dict[int, str]] = {
    "star":   _STAR_PROMPTS,
    "scope":  _SCOPE_PROMPTS,
    "signal": _SIGNAL_PROMPTS,
}

_SYSTEM_BY_METHOD: dict[str, str] = {
    "star":   _STAR_EVALUATOR_SYSTEM,
    "scope":  _SCOPE_EVALUATOR_SYSTEM,
    "signal": _SIGNAL_EVALUATOR_SYSTEM,
}

_USER_TEMPLATE_BY_METHOD: dict[str, str] = {
    "star":   _STAR_USER_TEMPLATE,
    "scope":  _SCOPE_USER_TEMPLATE,
    "signal": _SIGNAL_USER_TEMPLATE,
}

# Flag types that map to a "shallow" signal for each method.
_SHALLOW_FLAG_BY_METHOD: dict[str, str] = {
    "star":   "shallow_star",
    "scope":  "shallow_scope",
    "signal": "shallow_signal",
}


# ── Service ───────────────────────────────────────────────────────────────────

class ArielProbeService:
    """
    Stateless service that wraps probe-lifecycle logic.

    Parameters
    ----------
    engine
        SQLAlchemy Engine (shared from backend.core.database.ENGINE).
    profile_update_service
        A ProfileUpdateService instance.  All confidence mutations are
        delegated to it so the audit log is always kept consistent.
    """

    def __init__(self, engine, profile_update_service):
        self._engine  = engine
        self._profile = profile_update_service

    # ─────────────────────────────────────────────────────────────────────────
    # Public: find entities to probe
    # ─────────────────────────────────────────────────────────────────────────

    def get_pending_probes(self, user_id: str) -> list[dict]:
        """
        Return profile entities that are eligible for a probe session.

        Eligibility criteria:
        1. confidence_score < PROBE_CONFIDENCE_THRESHOLD (70)
        2. manual_review_required = 0
        3. No probe log entry for this entity within the last PROBE_COOLDOWN_H hours

        Results are ordered by confidence_score ascending so the weakest entity
        is presented first.

        Returns
        -------
        list[dict]  — each dict has:
            entity_id, name, entity_type, confidence_score, last_probed_at (or None)
        """
        cooldown_cutoff = (
            datetime.now(timezone.utc) - timedelta(hours=PROBE_COOLDOWN_H)
        ).isoformat()

        with self._engine.connect() as conn:
            rows = conn.execute(
                text("""
                    SELECT
                        pe.entity_id,
                        pe.name,
                        pe.entity_type,
                        pe.confidence_score,
                        MAX(apl.probed_at) AS last_probed_at
                    FROM profile_entities pe
                    LEFT JOIN ariel_probe_log apl
                           ON apl.entity_id = pe.entity_id
                          AND apl.user_id   = pe.user_id
                    WHERE pe.user_id               = :uid
                      AND pe.confidence_score       < :threshold
                      AND pe.manual_review_required = 0
                    GROUP BY pe.entity_id
                    HAVING last_probed_at IS NULL
                        OR last_probed_at < :cutoff
                    ORDER BY pe.confidence_score ASC
                """),
                {
                    "uid":       user_id,
                    "threshold": PROBE_CONFIDENCE_THRESHOLD,
                    "cutoff":    cooldown_cutoff,
                },
            ).fetchall()

        result = [
            {
                "entity_id":        row[0],
                "name":             row[1],
                "entity_type":      row[2],
                "confidence_score": row[3],
                "last_probed_at":   row[4],
            }
            for row in rows
        ]
        logger.info(
            "get_pending_probes: user=%s  %d eligible entities", user_id, len(result)
        )
        return result

    # ─────────────────────────────────────────────────────────────────────────
    # Public: generate turn-specific question
    # ─────────────────────────────────────────────────────────────────────────

    def get_probe_question(self, entity: dict, turn: int) -> str:
        """
        Return the turn question appropriate for entity['entity_type'] at `turn` (1–3).

        Dispatches to the correct question bank:
          skill      → STAR turn question
          domain /
          experience → SCOPE turn question
          trait      → SIGNAL turn question

        Parameters
        ----------
        entity : dict
            Must contain at least 'name' and 'entity_type'.
        turn : int
            1 = opening / scope/situation, 2 = depth question, 3 = outcome/trade-off.

        Raises
        ------
        ValueError if turn is not 1, 2, or 3.
        """
        if turn not in (1, 2, 3):
            raise ValueError(f"turn must be 1, 2, or 3; got {turn!r}")

        method  = _probe_method(entity.get("entity_type", "skill"))
        prompts = _PROMPTS_BY_METHOD[method]
        return prompts[turn].format(name=entity["name"])

    # ─────────────────────────────────────────────────────────────────────────
    # Public: LLM evaluation of the 3-turn transcript
    # ─────────────────────────────────────────────────────────────────────────

    async def evaluate_probe_response(
        self,
        transcript: dict[str, str],
        entity: dict,
        session_id: Optional[str] = None,
    ) -> dict:
        """
        Run the type-appropriate LLM rubric evaluator over a 3-turn transcript.

        Selects STAR / SCOPE / SIGNAL evaluator based on entity['entity_type'].

        Parameters
        ----------
        transcript : dict
            Must contain keys "turn_1", "turn_2", "turn_3" (user answers).
        entity : dict
            Must contain "name", "entity_id", and "entity_type".
        session_id : str | None
            Used for logging context only.

        Returns
        -------
        dict with keys:
            entity_id             : str
            probe_method          : str  ("star" | "scope" | "signal")
            star_components       : {situation, task, action, result}
            rubric                : dict of dimension scores
            extraction_confidence : float [0.0, 1.0]
            flag_type             : str
            flag_reason           : str
        """
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            logger.warning(
                "ariel_probe LLM: ANTHROPIC_API_KEY not set — returning neutral fallback"
            )
            return self._fallback_result(entity)

        method          = _probe_method(entity.get("entity_type", "skill"))
        system_prompt   = _SYSTEM_BY_METHOD[method]
        user_tmpl       = _USER_TEMPLATE_BY_METHOD[method]

        user_prompt = user_tmpl.format(
            name=entity["name"],
            t1=transcript.get("turn_1", ""),
            t2=transcript.get("turn_2", ""),
            t3=transcript.get("turn_3", ""),
        )

        try:
            result_llm = await asyncio.wait_for(
                call_llm(
                    system      = system_prompt,
                    messages    = [{"role": "user", "content": user_prompt}],
                    model       = "claude-haiku-4-5-20251001",
                    max_tokens  = 600,
                    temperature = 0.0,
                    purpose     = "ariel_probe_evaluate",
                ),
                timeout=LLM_EVAL_TIMEOUT_S,
            )
            raw = result_llm.text.strip()
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$",           "", raw)
            parsed = json.loads(raw)

        except asyncio.TimeoutError:
            logger.warning(
                "ariel_probe LLM: evaluation timed out after %.0fs — "
                "entity=%s session=%s method=%s",
                LLM_EVAL_TIMEOUT_S, entity.get("entity_id"), session_id, method,
            )
            return self._retry_fallback(entity, method)

        except Exception as exc:
            logger.error(
                "ariel_probe LLM: evaluation failed for entity=%s session=%s method=%s — %s",
                entity.get("entity_id"), session_id, method, exc,
            )
            return self._retry_fallback(entity, method)

        result = {
            "entity_id":             entity["entity_id"],
            "probe_method":          method,
            "star_components":       parsed.get("star_components", {}),
            "rubric":                parsed.get("rubric", {}),
            "extraction_confidence": float(parsed.get("extraction_confidence", 0.5)),
            "flag_type":             parsed.get("flag_type", "none"),
            "flag_reason":           parsed.get("flag_reason", ""),
            "retry_suggested":       False,
            "retry_message":         None,
        }

        logger.info(
            "ariel_probe evaluate: entity=%s method=%s conf=%.2f flag=%s session=%s",
            entity["entity_id"],
            method,
            result["extraction_confidence"],
            result["flag_type"],
            session_id,
        )
        return result

    # Backwards-compat alias used by existing callers
    async def evaluate_star_response(
        self,
        transcript: dict[str, str],
        entity: dict,
        session_id: Optional[str] = None,
    ) -> dict:
        """Alias for evaluate_probe_response() — kept for backwards compatibility."""
        return await self.evaluate_probe_response(transcript, entity, session_id)

    # ─────────────────────────────────────────────────────────────────────────
    # Public: persist probe outcome → confidence mutations
    # ─────────────────────────────────────────────────────────────────────────

    def record_probe_outcome(
        self,
        user_id: str,
        entity: dict,
        session_id: str,
        evaluation: dict,
    ) -> None:
        """
        Persist the probe outcome and trigger the appropriate confidence path.

        The evaluation schema is identical for all probe methods — only the
        semantic meaning of the rubric dimensions differs.  Storage is unchanged:
        star_components fields are mapped to the canonical evidence columns
        regardless of probe method, allowing confidence_math to score them
        identically.

        • Positive (flag_type="none", extraction_confidence ≥ 0.55):
          → ingest_conversation_event()  — raises confidence
        • Negative (flag_type != "none" OR extraction_confidence < 0.55):
          → ingest_negative_flag()       — lowers confidence, may set manual_review

        A row is always written to ariel_probe_log for cooldown tracking.
        """
        entity_id   = entity["entity_id"]
        flag_type   = evaluation.get("flag_type", "none")
        conf        = float(evaluation.get("extraction_confidence", 0.5))
        star        = evaluation.get("star_components", {})
        flag_reason = evaluation.get("flag_reason", "")
        method      = evaluation.get("probe_method", _probe_method(
            entity.get("entity_type", "skill")
        ))

        # Normalise the flag type to the evidence-layer vocabulary.
        # "shallow_scope" and "shallow_signal" are treated identically to
        # "shallow_star" for confidence scoring — only the probe_log stores
        # the method-specific flag name.
        is_positive = (flag_type == "none") and (conf >= POSITIVE_CONFIDENCE_FLOOR)

        if is_positive:
            event = {
                "extracted_entity_ids":   [entity_id],
                "extraction_confidence":  conf,
                "star_situation":         star.get("situation", ""),
                "star_task":              star.get("task", ""),
                "star_action":            star.get("action", ""),
                "star_result":            star.get("result", ""),
                "raw_quote":              json.dumps(evaluation.get("star_components", {})),
            }
            self._profile.ingest_conversation_event(user_id, session_id, event)
            outcome = "positive_star"
            logger.info(
                "ariel_probe: positive %s recorded — entity=%s conf=%.2f session=%s",
                method, entity_id, conf, session_id,
            )
        else:
            # Map method-specific shallow flags → evidence-layer canonical flag
            shallow_flag = _SHALLOW_FLAG_BY_METHOD.get(method, "shallow_star")
            effective_flag_type = (
                flag_type if flag_type in ("contradiction", "shallow_star",
                                           "shallow_scope", "shallow_signal",
                                           "inconsistency")
                else shallow_flag
            )

            self._profile.ingest_negative_flag(
                user_id    = user_id,
                entity_id  = entity_id,
                session_id = session_id,
                flag_type  = effective_flag_type,
                raw_content= json.dumps(evaluation.get("star_components", {})),
                flag_reason= flag_reason or f"extraction_confidence={conf:.2f} below threshold",
            )
            outcome = effective_flag_type
            logger.info(
                "ariel_probe: negative flag recorded — entity=%s method=%s "
                "flag=%s conf=%.2f session=%s",
                entity_id, method, effective_flag_type, conf, session_id,
            )

        # Write probe log for cooldown tracking
        probe_id = str(uuid.uuid4())
        now      = datetime.now(timezone.utc).isoformat()
        with self._engine.begin() as conn:
            conn.execute(
                text("""
                    INSERT INTO ariel_probe_log
                        (probe_id, user_id, entity_id, session_id, outcome, probed_at)
                    VALUES
                        (:pid, :uid, :eid, :sid, :outcome, :now)
                """),
                {
                    "pid":     probe_id,
                    "uid":     user_id,
                    "eid":     entity_id,
                    "sid":     session_id,
                    "outcome": outcome,
                    "now":     now,
                },
            )

    # ─────────────────────────────────────────────────────────────────────────
    # Internal helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _retry_fallback(self, entity: dict, method: str = "star") -> dict:
        """
        Return a retry-safe result when the LLM call times out or errors.

        retry_suggested = True → the route will NOT ingest any evidence and
        will NOT close the session.  No negative flag is recorded — a network
        failure is not evidence of a shallow answer.
        """
        return {
            "entity_id":             entity.get("entity_id", ""),
            "probe_method":          method,
            "star_components":       {"situation": "", "task": "", "action": "", "result": ""},
            "rubric":                {"specificity": 0.5, "depth": 0.5, "consistency": 0.5},
            "extraction_confidence": 0.5,
            "flag_type":             "none",
            "flag_reason":           "",
            "retry_suggested":       True,
            "retry_message":         _RETRY_MESSAGE,
        }

    def _fallback_result(self, entity: dict) -> dict:
        """
        Neutral result for the no-API-key case (local dev).  Treated as a
        low-confidence positive that falls below POSITIVE_CONFIDENCE_FLOOR and
        therefore produces a negative flag — correct for an un-evaluated answer.
        """
        method = _probe_method(entity.get("entity_type", "skill"))
        return {
            "entity_id":             entity.get("entity_id", ""),
            "probe_method":          method,
            "star_components":       {"situation": "", "task": "", "action": "", "result": ""},
            "rubric":                {"specificity": 0.5, "depth": 0.5, "consistency": 0.5},
            "extraction_confidence": 0.5,
            "flag_type":             "none",
            "flag_reason":           "",
            "retry_suggested":       False,
            "retry_message":         None,
        }
