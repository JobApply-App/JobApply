"""
Does a job's seniority fit the levels the user asked for?

Onboarding asks for a seniority per role (junior / mid / senior / lead /
director / executive) and stores it in role_preferences.roles, but nothing
used it: a senior engineer's feed held internships and VP roles alike, and the
handful of jobs that fit both role AND level were buried.

This is a feed-admission filter, never scoring (match_score_service and the
Core Scoring Principles are untouched — overqualification still costs nothing
in a score). It keeps a job when its level is within one step of a level the
user picked, and ALWAYS keeps a job whose level it cannot tell — most titles
say nothing about level, and dropping those would empty the feed.

Levels: 0 intern · 1 junior/entry · 2 mid · 3 senior · 4 lead · 5 director · 6 executive
"""
from __future__ import annotations

import re
from typing import Iterable, Optional

USER_LEVELS: dict[str, int] = {
    "entry": 1, "junior": 1, "mid": 2, "senior": 3,
    "lead": 4, "director": 5, "executive": 6,
}

# LinkedIn's own seniority field (all_jobs.seniority_level).
# "Mid-Senior level" spans mid to lead, so it is a range.
_LINKEDIN_LEVELS: dict[str, tuple[int, int]] = {
    "internship": (0, 0),
    "entry level": (1, 1),
    "associate": (2, 2),
    "mid-senior level": (2, 4),
    "director": (5, 5),
    "executive": (6, 6),
}

# Title words, checked highest level first so "Senior Director" is a director
# and "VP Engineering" an executive. Word-bounded; Hebrew forms included.
_TITLE_LEVELS: list[tuple[int, re.Pattern]] = [
    (6, re.compile(r"\b(vp|vice president|chief|cto|ceo|coo|cfo|cpo|cmo|c-level|evp|svp)\b|סמנכ\"?ל|סמנכ״ל|מנכ\"?ל|מנכ״ל")),
    (5, re.compile(r"\b(director|head of)\b|דירקטור|ראש תחום|ראש מחלקה|מנהל(?:/ת)? מחלקה")),
    (4, re.compile(r"\b(lead|principal|staff|team leader|tech lead)\b|ראש צוות|ראש/ת צוות|מוביל(?:/ה)? טכנולוגי")),
    (3, re.compile(r"\b(senior|sr\.?)\b|בכיר|סניור")),
    (1, re.compile(r"\b(junior|jr\.?|entry[- ]level|graduate|new grad)\b|ג'וניור|ג׳וניור|זוטר|ללא ניסיון|בוגר(?:/ת)?")),
    (0, re.compile(r"\b(intern|internship|student|trainee)\b|סטודנט|מתמחה|התמחות")),
]


def title_level(title: str) -> Optional[int]:
    t = (title or "").lower()
    for level, pattern in _TITLE_LEVELS:
        if pattern.search(t):
            return level
    return None


def job_level_range(title: str, seniority_level: Optional[str] = None) -> Optional[tuple[int, int]]:
    """(low, high) level for a job, or None when nothing says. The title wins:
    it is what the employer wrote, the LinkedIn field is often a default."""
    lvl = title_level(title)
    if lvl is not None:
        return lvl, lvl
    return _LINKEDIN_LEVELS.get((seniority_level or "").strip().lower())


def user_levels(roles: Iterable) -> set[int]:
    """Levels from role_preferences.roles ([{role, seniority}]); empty = no preference."""
    out: set[int] = set()
    for r in roles or []:
        if isinstance(r, dict):
            lvl = USER_LEVELS.get(str(r.get("seniority") or "").strip().lower())
            if lvl is not None:
                out.add(lvl)
    return out


def fits(levels: set[int], title: str, seniority_level: Optional[str] = None) -> bool:
    """True when the job is within one level of any level the user picked,
    or when either side says nothing about level."""
    if not levels:
        return True
    rng = job_level_range(title, seniority_level)
    if rng is None:
        return True
    low, high = rng
    return any(low - 1 <= lvl <= high + 1 for lvl in levels)
