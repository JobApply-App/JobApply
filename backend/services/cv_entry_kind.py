"""
What kind of entry a CV "experience" really is: a job, a degree, or military
service.

The CV extraction has one "experiences" list, and the model files degrees and
army service there too. In production the founder's CV produced "B.A. Business
Administration & Digital Innovation" and "Clerk to Lieutenant Colonel" as two
of his three most recent "jobs": they became his job search terms, appeared as
work experience in his profile, and counted as experience entities.

- A degree is education. It is moved out of experiences (at extraction, and
  when an already-stored CV is read).
- Military service stays in the work history — in Israel it is often real
  professional work (a developer in an Air Force tech unit), and the full
  timeline must reach scoring and the CV (CLAUDE.md principle 1). It is tagged
  kind="military" so job-title search can skip it.
"""
from __future__ import annotations

import re

DEGREE = re.compile(
    r"^\s*(b\.?\s?a|b\.?\s?sc|b\.?\s?ed|m\.?\s?a|m\.?\s?sc|mba|ph\.?\s?d|ll\.?\s?b|ll\.?\s?m)\b\.?"
    r"|\b(bachelor|master)('?s)? (of|degree|in)\b|\bdegree\b|תואר",
    re.IGNORECASE,
)
MILITARY = re.compile(
    r"\b(idf|i\.d\.f|israel defen[cs]e forces?|military|army|air force|"
    r"lieutenant|colonel|sergeant|corporal|brigadier)\b"
    r"|צה[\"״']?ל|צבא|שירות סדיר|סא[\"״]ל|אל[\"״]ם|רס[\"״]ן|תא[\"״]ל",
    re.IGNORECASE,
)


def _title(exp: dict) -> str:
    return str(exp.get("role") or exp.get("title") or "").strip()


def is_degree(exp: dict) -> bool:
    return bool(DEGREE.search(_title(exp)))


def is_military(exp: dict) -> bool:
    if str(exp.get("kind") or "").lower() == "military":
        return True
    return bool(MILITARY.search(f"{_title(exp)} {exp.get('company') or ''}"))


def as_education(exp: dict) -> dict:
    """A degree filed as an experience, in the education entry shape."""
    start, end = str(exp.get("start") or "").strip(), str(exp.get("end") or "").strip()
    years = "-".join(p for p in (start, end) if p)
    return {"degree": _title(exp), "institution": str(exp.get("company") or "").strip(), "years": years}


def separate_degrees(experiences: list, education: list) -> tuple[list, list]:
    """
    (experiences without degrees, education with them added), military entries
    tagged kind="military". Never drops anything: a degree already listed in
    education (same title) is just not added twice.
    """
    jobs: list = []
    edu = list(education or [])
    have = {str((e.get("degree") if isinstance(e, dict) else e) or "").strip().lower() for e in edu}
    for exp in experiences or []:
        if not isinstance(exp, dict):
            jobs.append(exp)
            continue
        if is_degree(exp):
            if _title(exp).lower() not in have:
                edu.append(as_education(exp))
                have.add(_title(exp).lower())
            continue
        if is_military(exp) and not exp.get("kind"):
            exp = {**exp, "kind": "military"}
        jobs.append(exp)
    return jobs, edu
