"""
The industries a user can prefer or avoid, as a short list of groups.

LinkedIn tags companies with ~285 distinct industry names (production,
2026-11-28: "Software Development" 440, "Financial Services" 133, ...). Nobody
picks from 285 English labels, so the questionnaire offers these groups and
each one matches the LinkedIn names that contain one of its words. Labels
live in the frontend dictionaries; this module only knows the ids.
"""
from __future__ import annotations

from typing import Iterable

GROUPS: dict[str, tuple[str, ...]] = {
    "software":   ("software", "internet", "information technology", "it services", "information services", "computer networking"),
    "cyber":      ("computer and network security", "cybersecurity", "network security"),
    "finance":    ("financial", "banking", "insurance", "investment", "venture capital", "accounting", "capital markets"),
    "hardware":   ("semiconductor", "electronic", "computer hardware", "electrical", "appliances"),
    "defense":    ("defense", "aviation", "aerospace"),
    "health":     ("health", "hospital", "medical", "pharmaceutical", "biotechnology", "wellness"),
    "marketing":  ("advertising", "marketing", "public relations", "media"),
    "hr":         ("human resources", "staffing", "recruiting"),
    "telecom":    ("telecommunications", "wireless"),
    "industry":   ("industrial", "machinery", "automation", "chemical", "mining", "construction", "civil engineering", "oil", "energy", "utilities"),
    "logistics":  ("logistics", "transportation", "supply chain", "warehousing", "truck"),
    "retail":     ("retail", "consumer", "food", "beverage", "fashion", "apparel", "hospitality", "travel"),
    "realestate": ("real estate",),
    "games":      ("computer games", "entertainment", "gaming"),
    "gambling":   ("gambling", "casino"),
    "education":  ("education", "e-learning"),
    "public":     ("government", "non-profit", "nonprofit", "civic", "public policy"),
}


def groups_for(industries: Iterable[str] | None) -> set[str]:
    """{'finance', 'software'} for ['Financial Services', 'Software Development']."""
    out: set[str] = set()
    for name in industries or ():
        low = str(name).casefold()
        for group, words in GROUPS.items():
            if any(w in low for w in words):
                out.add(group)
    return out


def clean(ids: Iterable[str] | None) -> list[str]:
    """Known group ids only, in GROUPS order, each once."""
    wanted = set(ids or ())
    return [g for g in GROUPS if g in wanted]
