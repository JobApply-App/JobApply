---
title: "CV writer's invalid JSON is a bracket left open where military_service ends; repaired by indentation"
author: RonMorim
date: 2026-11-21
branch: claude/tailor-invalid-json
cost: { minutes: 39, tokens: 280708 }
id: l-7b426390
scope: repo
status: active
src: agent
touches:
  - backend/utilities/json_repair.py
  - backend/tests/test_json_repair_unclosed_bracket.py
---

## Decided
- The 14 "TailorAgent returned invalid JSON that could not be repaired" failures in the stage 7 runs (2026-11-17 to 11-20, gemini-flash-latest) were all "Expecting ',' delimiter" at column 5, at 74-78% of the output: where `military_service` closes. Not truncation (outputs ~900-1200 tokens of 6000), not Hebrew (most were English).
- Fix in `backend/utilities/json_repair.py`: `_close_by_indent`, the last strategy in `parse_json_robust`. When the parser stops at a line start indented no deeper than the innermost open bracket's line, it closes that bracket. It only inserts characters. All 120 single-closer drops across 9 captured outputs repair to the exact original.
- The failure log now prints the text around the failure, not only the first 400 chars, which are always the same header.

## Tried and ruled out
- Re-running the failing pairs to capture a bad output: 0 of 12 live runs failed (~6% rate). The cause was located from the logged line/column/char offsets compared with good outputs.
- Gemini JSON mode (response_mime_type) was not used: call_llm is shared with the Anthropic fallback, and constrained decoding could silently cut a Hebrew string at a bare gershayim quote instead of failing.

## Watch out
- The prompt's schema example writes `key_responsibilities` as a one-line array; the model expands it and drops the `]`. Changing the example may cut the rate, but it was not measured.
