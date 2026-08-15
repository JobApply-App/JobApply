"""
RFC 6902 JSON Patch engine for CV edits.

Ariel used to answer every instruction — "shorten the third bullet" included —
by regenerating the entire CV document. That was expensive, slow, and unsafe:
the only thing stopping the model from quietly rewriting an untouched section
was a prompt line asking it not to. Byte-for-byte fidelity was a request, not a
guarantee.

A patch inverts that. The model names the exact locations it wants to change;
everything it does not name is untouchable by construction, because the apply
step only ever visits the paths in the patch. Fidelity stops depending on the
model's discipline.

Safety model
------------
Three things can go wrong with a model-authored patch, and they need different
answers:

  1. **Malformed patch** — not a list, missing `op`/`path`, unknown op.
     Rejected before anything is applied.
  2. **Broken path** — `/experience/7/bullets/2` when there are three roles, or
     a typo'd key. jsonpatch raises; the original document is returned intact.
  3. **Valid patch, invalid result** — a well-formed patch that produces a CV
     violating CVDataSchema (deletes `experience`, writes a 900-char summary).
     Caught by re-validating the RESULT, not just the patch.

Every failure path returns the ORIGINAL document. A rejected edit costs the user
one retry; a half-applied patch corrupts a CV they may have spent an hour on,
and they would have no way to know which parts are now wrong.

Guarded paths
-------------
`header` is not patchable. Contact details come from the verified profile
(pdf_builder._load_contact) and a patch reaching them would reintroduce exactly
the hallucination risk backend/models/cv.py was built to close. `target_title`
is the one header field the model legitimately authors, so it is allowlisted
individually rather than opening the whole block.
"""
from __future__ import annotations

import copy
import logging
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)

# RFC 6902 §4. `test` is accepted and useful — a model can assert the text it
# believes it is replacing, turning a stale-state edit into a clean failure
# instead of a silent overwrite of something the user changed meanwhile.
VALID_OPS: frozenset[str] = frozenset({"add", "remove", "replace", "move", "copy", "test"})

# Ops that carry a `value`.
_OPS_REQUIRING_VALUE: frozenset[str] = frozenset({"add", "replace", "test"})
# Ops that carry a `from`.
_OPS_REQUIRING_FROM: frozenset[str] = frozenset({"move", "copy"})

# Paths the model may never touch — see module docstring.
_FORBIDDEN_PREFIXES: tuple[str, ...] = ("/header",)
# ...except this one, which is legitimately model-authored positioning.
_ALLOWED_EXCEPTIONS: tuple[str, ...] = ("/header/target_title",)

# A single instruction should not rewrite the document. This is a blast-radius
# ceiling, not a correctness rule: a 40-op "patch" means the model fell back to
# regenerating everything, which is the behaviour this module replaces.
MAX_OPS = 25


@dataclass
class PatchResult:
    """Outcome of applying a patch. `cv_data` is always safe to use."""
    ok: bool
    cv_data: dict
    applied_ops: list[dict] = field(default_factory=list)
    error: Optional[str] = None
    error_kind: Optional[str] = None   # malformed | forbidden | apply_failed | invalid_result

    def as_dict(self) -> dict:
        return {
            "ok": self.ok,
            "applied_ops": self.applied_ops,
            "error": self.error,
            "error_kind": self.error_kind,
        }


def _is_forbidden(path: str) -> bool:
    if any(path == allowed or path.startswith(allowed + "/") for allowed in _ALLOWED_EXCEPTIONS):
        return False
    return any(path == p or path.startswith(p + "/") for p in _FORBIDDEN_PREFIXES)


def validate_patch(patch: Any) -> tuple[bool, Optional[str]]:
    """
    Structural check of a patch before it touches a document.

    Separate from applying it so a bad patch is diagnosable — the caller can
    tell the user *why* the edit was refused rather than reporting a generic
    failure after the fact.
    """
    if not isinstance(patch, list):
        return False, f"patch must be a JSON array, got {type(patch).__name__}"
    if not patch:
        return False, "patch is empty — the model reported a change but described none"
    if len(patch) > MAX_OPS:
        return False, f"patch has {len(patch)} operations, over the {MAX_OPS} limit"

    for i, op in enumerate(patch):
        if not isinstance(op, dict):
            return False, f"operation {i} is not an object"
        name = op.get("op")
        path = op.get("path")
        if name not in VALID_OPS:
            return False, f"operation {i} has unknown op {name!r}"
        if not isinstance(path, str) or not path.startswith("/"):
            return False, f"operation {i} has an invalid path {path!r}"
        if _is_forbidden(path):
            return False, (
                f"operation {i} targets {path!r}, which is populated from the "
                "verified profile and cannot be edited by the assistant"
            )
        if name in _OPS_REQUIRING_VALUE and "value" not in op:
            return False, f"operation {i} ({name}) is missing 'value'"
        if name in _OPS_REQUIRING_FROM:
            src = op.get("from")
            if not isinstance(src, str) or not src.startswith("/"):
                return False, f"operation {i} ({name}) has an invalid 'from' {src!r}"
            if _is_forbidden(src):
                return False, f"operation {i} moves from the protected path {src!r}"
    return True, None


def apply_cv_patch(cv_data: dict, patch: Any, *, context: str = "copilot") -> PatchResult:
    """
    Apply an RFC 6902 patch to a CV, or return the original untouched.

    Operates on a deep copy so a partially-applied patch can never be observed:
    jsonpatch mutates as it goes, and an op that fails halfway through a
    multi-op patch would otherwise leave the caller's document in a state that
    is neither the original nor the intended result.

    The result is re-validated against CVDataSchema, because a syntactically
    perfect patch can still produce a semantically broken CV.
    """
    from backend.models.cv import CVDataSchema

    ok, err = validate_patch(patch)
    if not ok:
        logger.warning("[%s] rejected malformed patch: %s", context, err)
        return PatchResult(ok=False, cv_data=cv_data, error=err,
                           error_kind="forbidden" if "cannot be edited" in (err or "") else "malformed")

    try:
        import jsonpatch
    except ImportError:  # pragma: no cover - declared in backend/requirements.txt
        logger.error("[%s] jsonpatch is not installed — cannot apply CV patches", context)
        return PatchResult(ok=False, cv_data=cv_data,
                           error="patch engine unavailable", error_kind="apply_failed")

    working = copy.deepcopy(cv_data)
    try:
        patched = jsonpatch.JsonPatch(patch).apply(working)
    except Exception as exc:
        # Overwhelmingly a path that does not exist — the model guessed an
        # index. The user's document is returned exactly as it was.
        logger.warning("[%s] patch application failed (%s): %s",
                       context, type(exc).__name__, str(exc)[:200])
        return PatchResult(ok=False, cv_data=cv_data,
                           error=f"could not apply the edit: {str(exc)[:160]}",
                           error_kind="apply_failed")

    try:
        CVDataSchema.model_validate(patched)
    except Exception as exc:
        logger.warning("[%s] patch produced a CV that fails schema validation: %s",
                       context, str(exc).replace("\n", " ")[:200])
        return PatchResult(ok=False, cv_data=cv_data,
                           error="the edit would have produced an invalid CV",
                           error_kind="invalid_result")

    logger.info("[%s] applied %d patch op(s): %s", context, len(patch),
                [f"{o.get('op')} {o.get('path')}" for o in patch][:6])
    return PatchResult(ok=True, cv_data=patched, applied_ops=list(patch))


def diff_cv(before: dict, after: dict) -> list[dict]:
    """
    Compute the RFC 6902 patch between two CVs.

    Used for the full-regeneration fallback path: when the model returns a whole
    document instead of a patch, the client still gets a patch to apply, so the
    frontend has one code path regardless of which mode produced the change.
    """
    try:
        import jsonpatch
        return list(jsonpatch.JsonPatch.from_diff(before, after))
    except Exception as exc:
        logger.warning("[cv-patch] diff failed: %s", exc)
        return []


def summarize_ops(patch: list[dict]) -> list[str]:
    """Human-readable one-liners for logging and the changes summary."""
    out = []
    for op in patch or []:
        name, path = op.get("op"), op.get("path")
        if name == "replace":
            out.append(f"updated {path}")
        elif name == "add":
            out.append(f"added {path}")
        elif name == "remove":
            out.append(f"removed {path}")
        elif name in ("move", "copy"):
            out.append(f"{name}d {op.get('from')} -> {path}")
        elif name == "test":
            continue   # assertions are not user-visible changes
        else:
            out.append(f"{name} {path}")
    return out
