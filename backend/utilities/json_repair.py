"""
Progressive JSON repair for LLM responses.

Extracted from match_score_service._parse_json_robust, which had these
strategies while the CV generation path — the one that costs the user a
30-second wait — had a bare json.loads() that raised on any anomaly.

That gap was not theoretical: a real job's JD reliably produced malformed JSON
from the model twice in a row, at different offsets ("Expecting ',' delimiter"
at char 3900, then 3286), killing generation both times. Same input, same hard
failure, no CV.

Deliberately generic. The caller's domain-specific salvage (match_score's
regex extraction of the two score fields, say) stays with the caller — a
shared utility that knows about score fields would not be shareable.

Order matters: each strategy is tried only after the cheaper, less invasive
ones fail, so a well-formed response is never touched.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

logger = logging.getLogger(__name__)


def _strip_fences(raw: str) -> str:
    """Remove ```json fences and any prose outside the outermost object."""
    text = (raw or "").strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end != -1 and end > start:
        text = text[start : end + 1]
    return text


def _drop_trailing_commas(text: str) -> str:
    """`{"a": 1,}` / `[1, 2,]` — valid in JS, invalid in JSON, common from LLMs."""
    return re.sub(r",\s*([}\]])", r"\1", text)


def _escape_raw_newlines_in_strings(text: str) -> str:
    """
    Escape literal newlines that appear INSIDE string values.

    A model writing a multi-line bullet emits a real newline mid-string, which
    is illegal in JSON and surfaces as "Invalid control character" or, when it
    desynchronises the parser, as the "Expecting ',' delimiter" seen in
    production. Walks the text tracking whether it is inside a string, so
    newlines that are legitimate formatting between keys are left alone.
    """
    out: list[str] = []
    in_string = False
    escaped = False
    for ch in text:
        if escaped:
            out.append(ch)
            escaped = False
            continue
        if ch == "\\":
            out.append(ch)
            escaped = True
            continue
        if ch == '"':
            in_string = not in_string
            out.append(ch)
            continue
        if in_string and ch == "\n":
            out.append("\\n")
            continue
        if in_string and ch == "\t":
            out.append("\\t")
            continue
        if in_string and ch == "\r":
            continue
        out.append(ch)
    return "".join(out)


def parse_json_robust(raw: str, *, context: str = "llm") -> Optional[Any]:
    """
    Parse LLM JSON, repairing progressively. None when nothing works.

    Strategies, cheapest first:
      1. direct parse (well-formed responses never get modified)
      2. strip fences / surrounding prose
      3. drop trailing commas
      4. escape raw newlines and tabs inside string values
      5. close an unterminated string and object (truncated output)
      6. close an unterminated object
    """
    if not raw or not raw.strip():
        return None

    attempts: list[tuple[str, str]] = []

    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        pass

    cleaned = _strip_fences(raw)
    attempts.append(("fences-stripped", cleaned))
    attempts.append(("no-trailing-commas", _drop_trailing_commas(cleaned)))
    attempts.append(("escaped-newlines", _escape_raw_newlines_in_strings(cleaned)))
    attempts.append(("escaped+no-trailing-commas",
                     _drop_trailing_commas(_escape_raw_newlines_in_strings(cleaned))))
    attempts.append(("closed-string-and-object", cleaned + '"}'))
    attempts.append(("closed-object", cleaned + "}"))

    for name, candidate in attempts:
        try:
            parsed = json.loads(candidate)
        except (json.JSONDecodeError, TypeError):
            continue
        if name != "fences-stripped":
            logger.warning("[json-repair:%s] recovered malformed LLM JSON via '%s'", context, name)
        return parsed

    logger.error(
        "[json-repair:%s] every repair strategy failed — raw length %d, first 200 chars: %r",
        context, len(raw), raw[:200],
    )
    return None
