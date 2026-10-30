"""
Localize a finished CV into professional Israeli-market Hebrew.

Why a separate step
-------------------
The tailoring prompt is built around mirroring the job description: its
keywords, its title, its skill names. When the JD is in English, that pull
beat the "write in Hebrew" directive — a CV generated in Hebrew came back
with Hebrew bullets under English role titles, English skill categories,
English education and an English target title (founder's export,
2026-10-29). A dedicated pass that does only this, with its own style guide,
is reliable where one instruction among hundreds was not.

What "Hebrew" means here
------------------------
Not a literal translation. Israeli CVs, in tech especially, are written in
Hebrew sentences that keep the industry's own English terms (Customer
Success, Onboarding, B2B SaaS, UAT, API) — that is how the market speaks,
and it is also what keeps an English job description's keywords findable by
an applicant tracking system: a CV that renders "Onboarding" as "קליטה"
stops matching the posting that asked for Onboarding (keyword overlap fell
to 2/40 on exactly that CV). Words with a natural Hebrew professional term
use it; calques ("מקצועי" for "professional", "אחראי על" chains) are out.

Safety
------
The pass may change wording only. It is rejected — and the input CV kept,
loudly logged — when it changes any number, date, company name, or the
number of roles, bullets, degrees or skill groups.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

_MODEL = "claude-sonnet-4-6"

_SYSTEM = """\
You are a senior Israeli CV editor. You turn a finished CV (JSON) into the \
professional Hebrew an Israeli recruiter expects — written by a native \
speaker for the Israeli job market, never a literal translation.

STYLE
- Summary ("תמצית"): 2-3 lines, concrete, packed with the job's key terms. \
No filler ("בעל/ת מוטיבציה גבוהה", "יחסי אנוש מצוינים" are banned).
- Bullets: start with a first-person past-tense verb (הובלתי, ניהלתי, \
הטמעתי, בניתי, צמצמתי, הגדלתי) — these are gender-neutral. Keep every \
number and result exactly. One idea per bullet, tight Hebrew, no "אחראי/ת על".
- Use the established Hebrew professional term when one exists \
(Team Lead → ראש צוות; Account Manager → מנהל/ת לקוחות; Implementation → \
הטמעה; Partnerships → שותפויות; Stakeholders → ממשקים / בעלי עניין; \
Project Management → ניהול פרויקטים; Intern → מתמחה / סטודנט/ית; \
Bachelor's degree / B.A. → תואר ראשון (B.A.); Master's → תואר שני).
- Never calque: "Professional summary" is "תמצית", not "סיכום מקצועי"; \
"Experience" is "ניסיון תעסוקתי"; "delivered" is not "סיפקתי" when it \
means "הובלתי / השלמתי".

KEEP IN ENGLISH, inside the Hebrew sentence, exactly as written:
- Every term in KEY_TERMS below (the job description's own keywords) — \
e.g. "ניהול תהליכי Onboarding", "בדיקות UAT", "לקוחות B2B SaaS". This is \
how Israeli tech writes, and it keeps the CV findable by an applicant \
tracking system searching the posting's words.
- Company, product, project, tool and technology names (Jira, Postman, \
Monday.com, Salesforce, API), certifications, and acronyms.

FIELDS
- header.target_title: a Hebrew title; when it is an industry title that \
Israel uses in English, keep that term inside it ("מומחה/ית הטמעה \
טכנולוגית", "ראש צוות Customer Success").
- experience[].role: Hebrew, same rule. experience[].company: unchanged.
- education[].degree: Hebrew with the degree letters ("תואר ראשון (B.A.) \
במנהל עסקים וחדשנות דיגיטלית"). education[].institution: the institution's \
Hebrew name when it has one ("אוניברסיטת רייכמן", "הטכניון"); a foreign \
institution keeps its name.
- skills.categories[].label: Hebrew. items: tools, technologies and \
KEY_TERMS unchanged; generic skills in Hebrew.
- military_service: Hebrew role and unit as the IDF names them.
- languages: leave as they are.

GENDER
{gender_rule}

OUTPUT
Return ONLY the same JSON object with the same keys, the same number of \
roles, bullets, degrees and skill groups, in the same order. Change wording \
only: every number, date, company name and URL stays exactly as it is. \
Write Hebrew acronyms with the gershayim ״ (צה״ל, בע״מ), never a plain \
double quote, which breaks the JSON.\
"""

_GENDER_RULES = {
    "m": "The candidate writes in the masculine form: use masculine titles (מנהל, מומחה, ראש צוות).",
    "f": "The candidate writes in the feminine form: use feminine titles (מנהלת, מומחית, ראש צוות).",
    None: (
        "The candidate's grammatical gender is unknown — do not guess it from "
        "the name or anything else. Prefer titles that are the same in both "
        "genders (ראש צוות, ראש תחום); when a title is gendered, use the slash "
        "form (מנהל/ת לקוחות, מומחה/ית הטמעה)."
    ),
}

_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")


def _shape(cv: dict) -> tuple:
    exp = cv.get("experience") or []
    return (
        len(exp),
        tuple(len(e.get("bullets") or []) for e in exp if isinstance(e, dict)),
        len(cv.get("education") or []),
        len((cv.get("skills") or {}).get("categories") or []),
    )


def _facts(cv: dict) -> dict:
    """What a localization must not touch: numbers anywhere in the prose,
    dates, and company names."""
    text = json.dumps(
        {k: cv.get(k) for k in ("summary", "experience", "military_service")},
        ensure_ascii=False,
    )
    exp = cv.get("experience") or []
    return {
        "numbers": sorted(_NUMBER.findall(text)),
        "companies": [str(e.get("company") or "") for e in exp if isinstance(e, dict)],
        "dates": [str(e.get("dates") or "") for e in exp if isinstance(e, dict)]
                 + [str(e.get("dates") or "") for e in cv.get("education") or [] if isinstance(e, dict)],
    }


def validate_localization(before: dict, after: dict) -> Optional[str]:
    """None when `after` is a faithful localization of `before`, else why not."""
    if not isinstance(after, dict):
        return "not a JSON object"
    if _shape(before) != _shape(after):
        return f"structure changed {_shape(before)} -> {_shape(after)}"
    fb, fa = _facts(before), _facts(after)
    for key in ("companies", "dates"):
        if fb[key] != fa[key]:
            return f"{key} changed"
    if fb["numbers"] != fa["numbers"]:
        lost = sorted(set(fb["numbers"]) - set(fa["numbers"]))
        added = sorted(set(fa["numbers"]) - set(fb["numbers"]))
        return f"numbers changed (lost {lost}, added {added})"
    return None


async def localize_cv_to_hebrew(
    cv_data: dict,
    jd_text: str,
    key_terms: list[str],
    *,
    gender: Optional[str] = None,
    user_id: Optional[str] = None,
) -> dict:
    """
    The CV in professional Hebrew, or the input unchanged (with an error
    logged) when the model's output is unusable or changes a fact.
    """
    from backend.services.llm_client import call_llm
    from backend.utilities.json_repair import parse_json_robust

    system = _SYSTEM.replace("{gender_rule}", _GENDER_RULES.get(gender, _GENDER_RULES[None]))
    terms = ", ".join(dict.fromkeys(t for t in key_terms if t)) or "(none extracted)"
    user_msg = (
        f"KEY_TERMS (keep in English): {terms}\n\n"
        f"JOB DESCRIPTION (for terminology only, do not copy from it):\n{(jd_text or '')[:4000]}\n\n"
        f"CV JSON:\n{json.dumps(cv_data, ensure_ascii=False)}"
    )
    try:
        result = await call_llm(
            system=system,
            messages=[{"role": "user", "content": user_msg}],
            model=_MODEL,
            max_tokens=6000,
            temperature=0.2,
            purpose="cv_localize_he",
            user_id=user_id,
        )
        raw = result.text.strip()
        start, end = raw.find("{"), raw.rfind("}")
        localized = parse_json_robust(raw[start:end + 1] if start != -1 else raw, context="cv_localize")
    except Exception as exc:
        logger.error("[cv_localize] Hebrew pass failed for user=%s — CV left as generated: %s", user_id, exc)
        return cv_data

    problem = validate_localization(cv_data, localized)
    if problem:
        logger.error("[cv_localize] Hebrew pass rejected for user=%s (%s) — CV left as generated",
                     user_id, problem)
        return cv_data

    # Fields the pass must never own, whatever it returned.
    for key in ("header",):
        if isinstance(cv_data.get(key), dict) and isinstance(localized.get(key), dict):
            localized[key] = {**cv_data[key], "target_title": localized[key].get("target_title")
                              or cv_data[key].get("target_title")}
    localized["languages"] = cv_data.get("languages", localized.get("languages"))
    return localized
