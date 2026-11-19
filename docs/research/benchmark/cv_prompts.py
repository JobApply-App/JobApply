"""The two CV-writing prompts compared in part C.

"today" is backend/agents/tailor.py's _SYSTEM_PROMPT as it is. "noquota" is the
same prompt with the quotas that docs/research/06-cv-generation.md section 2
names (rows 1, 2, 3, 4, 6 and 8) replaced by plain no-addition rules. Nothing
else changes, so a difference between the two is the effect of the quotas.

Every replacement must find its original text exactly once. If the product
prompt is edited, the runner stops here instead of testing a prompt that is
neither of the two.
"""
from __future__ import annotations

# (original, replacement) pairs, or (start, end, replacement) spans.
_PAIRS: list[tuple[str, str]] = [
    # row 1: keyword commit
    ("KEYWORD COMMIT: you are required to place ≥ 16 of these 20 terms verbatim in the output.\n",
     "Use a term from this table only where the profile supports it.\n"),
    # row 6: "feel FULL"
    ("  Goal: the page should feel FULL — dense, substantive, no visual gaps.\n"
     "  An empty bottom third is worse than a dropped low-signal role.\n",
     "  Goal: the relevant roles, and nothing added to fill space.\n"),
    # row 3: a number in every bullet
    ("  Required:  every bullet that CAN carry a number MUST carry a number.\n"
     "  If no number is available for a bullet, use concrete scope instead:",
     "  Use a number where a source states one. Where none does, describe the\n"
     "  scope in words instead:"),
    ("XYZ FRAMEWORK — mandatory for every bullet, zero exceptions:",
     "XYZ FRAMEWORK — use it where the profile states a measurable result:"),
    ("The three elements must all be present. ",
     "Without a stated result, X and Z are enough. "),
    ("It must contain at least one concrete number from the metrics table.\n",
     "It includes a number only if the metrics table has one.\n"),
    # self-audit items tied to the quotas (rows 1, 2, 3, 8)
    ("   (b) A concrete number or verifiable scope is present (Y element of XYZ).\n",
     "   (b) Any number is one the profile or SUPPLEMENTAL_ANSWERS states.\n"),
    ("   (d) ENTITY GAP COMPLIANCE: STEP 5 Audit A passes — each included VERIFIED\n"
     "       employer's bullets contain ≥ 3 of that entity's cv_vocabulary_gap terms.\n"
     "   (e) JD KEYWORD COVERAGE: STEP 5 Audit B passes — ≥ 12/15 keywords present.\n",
     "   (d) Every claim is supported by the profile or SUPPLEMENTAL_ANSWERS.\n"
     "   (e) No job-description term appears that the profile does not support.\n"),
    ("   If (d) fails: revise that employer's weakest bullet to inject the missing gap terms.\n"
     "   If (e) fails: identify and inject missing JD keywords as per STEP 5 Audit B.\n",
     "   If (d) or (e) fails: remove the unsupported claim or term.\n"),
    ("KEYWORD INJECTION MANDATE — 80% Coverage Rule\n", "KEYWORD USE\n"),
]

_SPANS: list[tuple[str, str, str]] = [
    # row 2: mandatory vocabulary-gap terms
    ("  • CV gap terms are MANDATORY vocabulary corrections",
     "as missing JD keywords.\n",
     "  • CV gap terms are optional vocabulary. Use one only where it names what\n"
     "    the candidate actually did.\n"),
    # row 4: derived numbers
    ("    3. Derivable approximations",
     "no source basis.\n",
     "    3. Nothing else: never estimate or compute a number the sources do not state.\n"),
    # rows 1 and 8: the 80% coverage rule
    ("This is a hard constraint, not a suggestion. ATS systems match exact strings.",
     "sections (summary first, then skills, then top-role bullets) before finalising.\n",
     "Use the JD's exact term where the candidate did that thing, in the summary,\n"
     "bullets or skills. Never add a term the profile does not support. There is\n"
     "no coverage target.\n"),
    # rows 1, 2 and 8: the final keyword audits
    ("After drafting the complete cv_data object, run TWO audits silently:",
     "Only after BOTH audits pass: output the final JSON.",
     "After drafting the complete cv_data object, check silently that every claim\n"
     "is supported by the profile or SUPPLEMENTAL_ANSWERS. There is no keyword count.\n\n"
     "Then output the final JSON."),
]


def _once(text: str, needle: str) -> int:
    n = text.count(needle)
    if n != 1:
        raise SystemExit(f"cv_prompts: expected the prompt to contain this text once, found {n}:\n{needle[:120]}")
    return text.index(needle)


def without_quotas(prompt: str) -> str:
    out = prompt
    for old, new in _PAIRS:
        _once(out, old)
        out = out.replace(old, new)
    for start, end, new in _SPANS:
        i = _once(out, start)
        j = out.index(end, i) + len(end)
        out = out[:i] + new + out[j:]
    # The prompt goes through str.format(profile=...); a stray brace would break it.
    if out.count("{") != prompt.count("{") or out.count("}") != prompt.count("}"):
        raise SystemExit("cv_prompts: replacement changed the number of braces")
    return out
