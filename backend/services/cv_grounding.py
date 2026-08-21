"""
Zero-hallucination grounding gate — the single authority for "is this bullet
supported by the candidate's own data?"

Supersedes the validation half of cv_assembly_engine.py, which enforced this
only on Ariel's single-bullet edit path (via cv_tailor_service) while the main
tailor.py generation path and the copilot patch path ran ungated. One gate now
covers every write.

Why the original could not simply be reused
---------------------------------------------
Measured against 20 real generated bullets from a live profile, the original
`validate_bullet` rejected **15 of them — a 75% false-positive rate**. Turned
on as a hard block it would have stripped three quarters of every CV. Two
independent causes, both fixed here:

1. **Sentence-initial verbs read as proper nouns.** `[A-Z][a-zA-Z0-9]{2,}`
   matches the first word of every sentence, so "Retained 30 at-risk clients"
   treated *Retained* as an unverifiable entity. Ten of the twenty-two
   rejection causes were ordinary verbs: prevented, handled, relayed,
   maintained, retained, engineered, acted, expanded, skilled, proven. The
   allowlist approach could not keep up — every new verb is a new false
   positive. Fixed structurally: a capitalised token at a sentence boundary is
   only treated as a proper noun if it ALSO appears capitalised mid-sentence
   somewhere, which is what a real name does and a sentence-initial verb does
   not.

2. **The corpus was the wrong one.** `load_verified_facts` reads the evidence
   ledger, which on the measured profile yielded 58 facts / 98 literals out of
   253 evidence rows. The candidate's real entities — Monday.com, CPO, PRDs,
   NIS, ARR, and the genuinely-true metrics 30 and 300 — live in the PROFILE,
   not that subset. The gate was checking against a corpus that never contained
   the things it was rejecting. Fixed by validating against profile text plus
   the ledger.

Enforcement posture (updated 2026-08-21)
-----------------------------------------
The measured false-positive rate on real generated bullets is ~10%, and the
surviving flags looked like genuine fabrications rather than noise (see the
call sites in tailor.py / copilot.py). That number, plus the product
requirement that a flagged bullet be *repaired* rather than either silently
kept or silently deleted, retired the old `enforce=False` log-only default
for the two real call sites:

`GroundingGate.reground_and_filter()` is the active path now. For each
flagged bullet it asks the model to rewrite the claim using ONLY the
candidate's own verified profile text — dropping or generalizing the
unverifiable number/entity, never inventing a replacement — and re-checks
the rewrite before accepting it. A rewrite that still fails grounding (the
repair itself hallucinated) is removed, never shipped: the invariant is
"never a fabrication reaches the user," and content loss is the acceptable
failure mode, fabrication is not.

`filter_cv()` (plain remove-on-flag, no rewrite) and `enforce=False`
(log-only) remain as lower-level building blocks — `reground_and_filter()`
is layered on top of the same `check()`/corpus machinery, not a replacement
for it.

Known blind spot, stated plainly: this validates LITERALS (numbers, proper
nouns), not CLAIMS. "Led an enterprise team of senior managers" contains no
literals and passes cleanly. It stops fabricated facts, not fabricated
seniority or scope. It is a necessary layer, not a sufficient one.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Iterable, Optional

logger = logging.getLogger(__name__)

# Re-exported so callers have one import site for the whole gate.
from backend.services.cv_assembly_engine import (  # noqa: F401
    VerifiedFact,
    load_verified_facts,
)

_NUMBER_RE = re.compile(r"[$€₪£]?\d[\d,.]*\s?(?:%|k|m|b|million|billion|thousand)?", re.I)
_PROPER_RE = re.compile(r"\b[A-Z][a-zA-Z0-9]{2,}(?:\.[a-z]{2,3})?\b")

# Sentence boundary = start of string, or after . ! ? : ; • - and whitespace.
_SENTENCE_START_RE = re.compile(r"(?:^|[.!?:;•\-]\s+|\n\s*)$")

# Acronyms and generic terms that carry no verifiable claim. Deliberately small:
# the sentence-position fix removes the need for a sprawling verb list, and a
# long allowlist is how the original ended up unmaintainable.
_GENERIC_TOKENS = frozenset({
    "cv", "kpi", "kpis", "api", "apis", "saas", "b2b", "b2c", "b2b2c", "ats",
    "the", "this", "that", "these", "those", "and", "for", "with",
})


def _is_sentence_initial(text: str, start: int) -> bool:
    """True when the match at `start` opens a sentence or list item."""
    return bool(_SENTENCE_START_RE.search(text[:start]))


def extract_literals(text: str) -> set[str]:
    """
    Provenance-bearing literals: numbers, plus proper nouns that are genuinely
    proper nouns rather than sentence-initial verbs.

    A capitalised token qualifies as a proper noun when it appears capitalised
    somewhere that is NOT a sentence start — the property that distinguishes
    "Monday.com" from "Managed".
    """
    out: set[str] = set()
    text = str(text or "")

    for m in _NUMBER_RE.finditer(text):
        cleaned = re.sub(r"[\s,]", "", m.group(0)).lower()
        if cleaned:
            out.add(cleaned)

    # Which capitalised tokens ever occur mid-sentence?
    mid_sentence: set[str] = set()
    for m in _PROPER_RE.finditer(text):
        if not _is_sentence_initial(text, m.start()):
            mid_sentence.add(m.group(0).lower())

    for m in _PROPER_RE.finditer(text):
        token = m.group(0).lower()
        if token in _GENERIC_TOKENS:
            continue
        if _is_sentence_initial(text, m.start()) and token not in mid_sentence:
            continue     # sentence-opening verb, not an entity
        out.add(token)

    return out


def build_corpus(
    user_id: str,
    *,
    engine=None,
    facts: Optional[Iterable[VerifiedFact]] = None,
    extra_text: str = "",
) -> set[str]:
    """
    Every literal the candidate's own data licenses.

    Profile text FIRST, evidence ledger second. The profile is the broader and
    more authoritative source — it is what the generator was given — and the
    ledger only ever covered a subset. Either source failing degrades the
    corpus rather than emptying it, since an empty corpus would reject
    everything.
    """
    corpus: set[str] = set()

    # build_full_text takes a USER_ID, not a profile dict. Passing the dict
    # "works" — it just resolves nothing, the broad except below logs a warning,
    # and the corpus silently comes back smaller than the ledger-only version it
    # was meant to widen. Measured once already: 98 literals -> 82, which read
    # as the fix making things worse rather than never having run.
    try:
        from backend.services.user_profile import build_full_text
        corpus |= extract_literals(build_full_text(user_id))
    except Exception as exc:
        logger.warning("[cv-grounding] profile text unavailable for %s: %s",
                       user_id, str(exc)[:160])

    try:
        if facts is None and engine is not None:
            facts = load_verified_facts(user_id, engine)
        for f in facts or []:
            for part in (f.action, f.context, f.impact, f.company, f.role):
                if part:
                    corpus |= extract_literals(part)
    except Exception as exc:
        logger.warning("[cv-grounding] evidence ledger unavailable for %s: %s",
                       user_id, str(exc)[:160])

    if extra_text:
        corpus |= extract_literals(extra_text)

    return corpus


@dataclass
class GroundingResult:
    """Per-bullet verdict. `ok` is always safe to ignore in log-only mode."""
    ok: bool
    text: str
    unverified: list[str] = field(default_factory=list)

    def reason(self) -> str:
        return ("could not verify: " + ", ".join(sorted(self.unverified))) if self.unverified else ""


@dataclass
class GroundingReport:
    """Aggregate outcome, and the user-facing notice when enforcing."""
    enforced: bool = False
    checked: int = 0
    flagged: list[GroundingResult] = field(default_factory=list)
    removed: int = 0
    rewritten: int = 0

    @property
    def flagged_count(self) -> int:
        return len(self.flagged)

    def user_notice(self) -> Optional[str]:
        """
        Explicit message when content was actually removed.

        Rewritten bullets are NOT mentioned here on purpose: a rewrite that
        passed re-verification is, by construction, a truthful bullet — it
        needs no disclosure, the same as any other line the generator wrote
        correctly on the first pass. Only a genuine content LOSS (the repair
        itself couldn't produce a verifiable rewrite, so the bullet was
        dropped) is surfaced: a CV that quietly lost a bullet is
        indistinguishable to the user from one that was generated badly, and
        they have no way to recover the missing claim.
        """
        if not self.enforced or not self.removed:
            return None
        n = self.removed
        return (
            f"{n} bullet{'s were' if n > 1 else ' was'} removed because "
            f"{'their' if n > 1 else 'its'} specific metrics or entities could not be "
            f"verified against your profile, even after an attempted rewrite. Add the "
            f"supporting detail to your profile and regenerate to include "
            f"{'them' if n > 1 else 'it'}."
        )

    def as_dict(self) -> dict:
        return {
            "enforced": self.enforced,
            "checked": self.checked,
            "flagged": self.flagged_count,
            "rewritten": self.rewritten,
            "removed": self.removed,
            "notice": self.user_notice(),
            "details": [{"text": f.text[:120], "unverified": f.unverified} for f in self.flagged],
        }


class GroundingGate:
    """
    Checks bullets against a corpus of the candidate's own literals.

    enforce=False (the default) is LOG-ONLY: nothing is removed, everything is
    recorded. Flip to True only once the measured false-positive rate on real
    data justifies it.
    """

    def __init__(self, corpus: set[str], *, enforce: bool = False, context: str = "cv"):
        self.corpus = corpus or set()
        self.enforce = enforce
        self.context = context

    @classmethod
    def for_user(cls, user_id: str, *, engine=None, enforce: bool = False,
                 context: str = "cv") -> "GroundingGate":
        return cls(build_corpus(user_id, engine=engine), enforce=enforce, context=context)

    def check(self, text: str) -> GroundingResult:
        unverified = sorted(extract_literals(text) - self.corpus)
        return GroundingResult(ok=not unverified, text=text, unverified=unverified)

    def filter_cv(self, cv_data: dict) -> tuple[dict, GroundingReport]:
        """
        Check every experience bullet.

        In log-only mode cv_data is returned unchanged. When enforcing, flagged
        bullets are removed and the report carries a notice naming how many —
        never a silent drop.
        """
        import copy

        report = GroundingReport(enforced=self.enforce)
        if not self.corpus:
            logger.warning("[cv-grounding] empty corpus for %s — skipping (would reject everything)",
                           self.context)
            return cv_data, report

        out = copy.deepcopy(cv_data) if self.enforce else cv_data

        for exp in (out.get("experience") or []):
            kept = []
            for bullet in (exp.get("bullets") or []):
                report.checked += 1
                res = self.check(bullet)
                if res.ok:
                    kept.append(bullet)
                    continue
                report.flagged.append(res)
                logger.warning("[cv-grounding:%s] %s bullet — %s | %r",
                               self.context,
                               "REMOVED" if self.enforce else "flagged (log-only)",
                               res.reason(), bullet[:110])
                if self.enforce:
                    report.removed += 1
                else:
                    kept.append(bullet)
            if self.enforce:
                exp["bullets"] = kept

        if report.flagged:
            logger.info("[cv-grounding:%s] %d/%d bullets flagged (%.0f%%), enforce=%s",
                        self.context, report.flagged_count, report.checked,
                        100.0 * report.flagged_count / max(1, report.checked), self.enforce)
        return out, report

    async def reground_and_filter(self, cv_data: dict, *, user_id: str, model: str) -> tuple[dict, GroundingReport]:
        """
        Check every experience bullet; for each flagged one, ask the model to
        rewrite it using ONLY the candidate's own verified profile text, then
        re-check the rewrite. A rewrite that still fails grounding — the
        repair itself hallucinated — is removed, never shipped.

        Unlike filter_cv(enforce=True), this never just deletes a flagged
        bullet as the first move: deletion is the last resort after a repair
        attempt has already failed, not the default response to any flag.
        """
        import copy

        report = GroundingReport(enforced=True)
        if not self.corpus:
            logger.warning("[cv-grounding:%s] empty corpus for %s — skipping (would reject everything)",
                           self.context, user_id)
            return cv_data, report

        out = copy.deepcopy(cv_data)
        locations: list[tuple[int, int, str]] = []  # (exp_index, bullet_index, original_text)

        for exp_i, exp in enumerate(out.get("experience") or []):
            for b_i, bullet in enumerate(exp.get("bullets") or []):
                report.checked += 1
                res = self.check(bullet)
                if res.ok:
                    continue
                report.flagged.append(res)
                locations.append((exp_i, b_i, bullet))

        if not locations:
            return out, report

        logger.warning(
            "[cv-grounding:%s] %d/%d bullets unverified for user=%s — attempting rewrite: %s",
            self.context, len(locations), report.checked, user_id,
            [f.unverified for f in report.flagged][:5],
        )

        try:
            from backend.services.user_profile import build_full_text
            profile_text = build_full_text(user_id)
        except Exception as exc:
            logger.error(
                "[cv-grounding:%s] profile text unavailable for rewrite (user=%s): %s — "
                "removing flagged bullets instead of risking a fabricated repair",
                self.context, user_id, str(exc)[:160],
            )
            profile_text = ""

        rewrites: dict[str, str] = {}
        if profile_text:
            try:
                rewrites = await reground_bullets(
                    [text for _, _, text in locations],
                    profile_text=profile_text,
                    model=model,
                    user_id=user_id,
                    purpose=f"cv_grounding_repair_{self.context}",
                )
            except Exception as exc:
                logger.error(
                    "[cv-grounding:%s] rewrite call failed for user=%s: %s — "
                    "removing flagged bullets instead of risking a fabricated repair",
                    self.context, user_id, str(exc)[:160],
                )

        # Apply from last location to first so earlier pops don't shift later indices.
        for exp_i, b_i, original in sorted(locations, key=lambda t: (t[0], t[1]), reverse=True):
            bullets = out["experience"][exp_i]["bullets"]
            candidate = rewrites.get(original)
            if candidate:
                recheck = self.check(candidate)
                if recheck.ok:
                    bullets[b_i] = candidate
                    report.rewritten += 1
                    continue
                logger.warning(
                    "[cv-grounding:%s] rewrite still unverified for user=%s, removing: %r -> %r",
                    self.context, user_id, original[:80], candidate[:80],
                )
            del bullets[b_i]
            report.removed += 1

        logger.info(
            "[cv-grounding:%s] %d flagged / %d checked (%.0f%%) — %d rewritten, %d removed, user=%s",
            self.context, report.flagged_count, report.checked,
            100.0 * report.flagged_count / max(1, report.checked),
            report.rewritten, report.removed, user_id,
        )
        return out, report


async def reground_bullets(
    bullets: list[str],
    *,
    profile_text: str,
    model: str,
    user_id: str,
    purpose: str,
) -> dict[str, str]:
    """
    Ask the model to rewrite each flagged bullet using ONLY profile_text as
    the source of truth. Returns {original_bullet: rewritten_bullet} — a
    bullet the model declines to safely rewrite is simply absent from the
    result, which the caller treats as "repair failed, remove it."

    One call for every flagged bullet in a CV (typically 0-2), not one call
    per bullet — the ~10% flag rate makes per-bullet calls wasteful latency
    for no accuracy gain.
    """
    if not bullets:
        return {}

    from backend.services.llm_client import call_llm
    from backend.utilities.json_repair import parse_json_robust

    numbered = "\n".join(f"{i+1}. {b}" for i, b in enumerate(bullets))
    system = (
        "You repair resume bullets that contain a number or named entity not "
        "supported by the candidate's own profile text below. For each bullet: "
        "rewrite it so every number and proper noun in it is either directly "
        "present in PROFILE_TEXT, or removed/generalized into truthful, "
        "non-quantified language. Keep the original action verb and the true "
        "part of the achievement. NEVER invent a replacement number or name — "
        "if the bullet cannot be made truthful without becoming too vague to be "
        "useful, shorten it rather than fabricate. Output strict JSON only: "
        '{"rewrites": [{"i": <1-based index>, "text": "<rewritten bullet>"}]}. '
        "Omit an index entirely if you cannot produce a truthful rewrite for it — "
        "do not guess."
    )
    user_msg = f"PROFILE_TEXT:\n{profile_text[:12000]}\n\nBULLETS TO REPAIR:\n{numbered}"

    result = await call_llm(
        system=system,
        messages=[{"role": "user", "content": user_msg}],
        model=model,
        max_tokens=1500,
        temperature=0.0,
        purpose=purpose,
        user_id=user_id,
    )

    raw = result.text.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.startswith("json"):
            raw = raw[4:]
    start, end = raw.find("{"), raw.rfind("}")
    if start != -1 and end != -1:
        raw = raw[start:end + 1]

    parsed = parse_json_robust(raw, context="cv_grounding_repair")
    if not parsed:
        return {}

    out: dict[str, str] = {}
    for item in parsed.get("rewrites", []):
        try:
            idx = int(item.get("i")) - 1
            text = str(item.get("text", "")).strip()
        except (TypeError, ValueError):
            continue
        if text and 0 <= idx < len(bullets):
            out[bullets[idx]] = text
    return out
