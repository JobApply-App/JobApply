"""
Source-of-Truth User Profile for the Deep Profile Engine.

All agent nodes must ground their claims exclusively in this data.
Nothing may be asserted about the candidate that is not present here.
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

USER_PROFILE: dict = {
    # "personal" is legacy single-user scaffolding (see the multi-tenant note
    # near get_profile() below) — placeholders only. Real values are loaded
    # at import time from backend/personal_overrides.json (gitignored, never
    # committed) via _load_personal_overrides()/_CORE_PERSONAL_FIELDS below,
    # for whichever of name/dob/email/phone/linkedin/location you want to
    # override locally. See backend/personal_overrides.json.example for the
    # expected shape.
    "personal": {
        "name":     "Your Name",
        "dob":      "",
        # Contact — these are the ONLY authoritative values.
        # pdf_builder reads directly from here; the LLM never generates contact info.
        "email":    "",
        "phone":    "",
        "linkedin": "",
        "location": "",
    },

    # ── Education ─────────────────────────────────────────────────────────────
    "education": [
        {
            "degree":  "BA in Business Administration & Digital Innovation",
            "school":  "Reichman University",
            "period":  "2020 - 2024",
            "status":  "Dean's List, Ranked 4th in class",
            # Resilience context: Ron held three jobs concurrently during his
            # degree (Insurance Agency, Reuveni Pridan, and GO-OUT) while
            # maintaining Dean's List standing — top 4 in his cohort.
            "concurrent_employment": [
                "Insurance Agency — Operations & Pension Referent",
                "Reuveni Pridan — Reception & Admin",
                "GO-OUT — Customer Support (later Partnership Manager)",
            ],
            "resilience_note": (
                "Maintained Dean's List (ranked 4th in class) while working "
                "three simultaneous jobs throughout the degree. "
                "This is not a footnote — it is the defining evidence of "
                "work ethic, time management, and resilience under sustained pressure."
            ),
        },
        {
            "certification": "Product Management",
            "provider":      "Triola (formerly Pitango Academy)",
            "period":        "Late 2024 - Early 2025",
            "details":       "18 sessions, 3 hours each + final project",
        },
    ],

    # ── Experience (chronological, earliest first) ────────────────────────────
    "experience": [

        # ── Early career: proof of leadership instinct before professional roles ──
        {
            "company":     "Aldo (Gelato Shop)",
            "role":        "Shift Manager",
            "period":      "2014 - 2016",
            "progression": "Started as a seller; promoted to Shift Manager within months.",
            "details": (
                "Started as a sales-floor seller and was promoted to Shift Manager within months. "
                "Responsible for staff scheduling and allocation, inventory management, "
                "daily operations, and customer experience. "
                "First formal leadership role; demonstrates an early, "
                "innate pattern of being trusted with management responsibility."
            ),
            "tag": "early_leadership",
        },
        {
            "company": "River (Restaurant)",
            "role":    "Take-Away & Operations Team Lead",
            "period":  "2016 - 2019",
            "details": (
                "Post-military role as Take-Away & Operations Team Lead. "
                "Managed the take-away logistics team and hostess staff. "
                "Coordinated between kitchen staff and front-of-house under time pressure "
                "and high-volume service conditions. "
                "Second consecutive early-career promotion to a leadership position."
            ),
            "tag": "early_leadership",
        },

        # ── Military service ────────────────────────────────────────────────────
        {
            "unit":    "IDF Telecommunication Corps — Hoshen Unit",
            "role":    "Head of Commander's Office",
            "period":  "2017 - 2019",
            "details": (
                "Completed the Operational Telecom Operator course upon enlistment. "
                "Served as Head of Commander's Office (also referred to as Colonel's Assistant): "
                "managed task flow, prepared meeting summaries, oversaw document distribution, "
                "and daily office operations for a senior officer. "
                "Responsible for training and onboarding incoming office personnel."
            ),
        },

        # ── University-era roles (held concurrently during degree) ──────────────
        {
            "company": "Reuveni Pridan (Advertising)",
            "role":    "Reception & Admin",
            "period":  "2020 - 2022",
            "details": (
                "Managed front desk and admin operations at one of Israel's leading "
                "advertising agencies. Held simultaneously with Insurance Agency role "
                "while maintaining Dean's List academic standing at Reichman University."
            ),
            "tag": "concurrent_degree_employment",
        },
        {
            "company": "Insurance Agency",
            "role":    "Operations & Pension Referent",
            "period":  "2020 - 2024",
            "details": (
                "Managed 800+ client files, insurance policies, and pension funds "
                "across a large independent agency portfolio. "
                "Held simultaneously with Reuveni Pridan and later GO-OUT roles "
                "while maintaining Dean's List academic standing."
            ),
            "tag": "concurrent_degree_employment",
        },
        {
            "company": "Microsoft × TAMA AR Web App",
            "role":    "Product & UX Contributor",
            "period":  "2022 - 2023",
            "details": (
                "Led UX review for the TAMA AR Web App — a three-way collaboration "
                "between Microsoft, Reichman University, and the Tel Aviv Museum of Art. "
                "Shipped a consumer-facing augmented-reality digital product from "
                "wireframes to public launch. Project-based role held during academic degree."
            ),
            "tag": "academic_project",
        },

        # ── GO-OUT: primary professional track ─────────────────────────────────
        {
            "company": "GO-OUT",
            "period":  "2023–2026",
            "roles": [
                {
                    "title":   "Team Lead – Partnerships & Support",
                    "period":  "2025 - Feb 2026",
                    "details": (
                        "Managed 7 employees across Israel and Greece. "
                        "Held daily syncs with COO and CFO on operations and partner performance. "
                        "Oversaw SLA management, major B2B account retention, "
                        "and complex payment-gateway escalations — including "
                        "extreme-pressure scenarios involving failed transactions "
                        "during sold-out stadium events. "
                        "Managed the external B2B2C promoters network responsible for "
                        "driving ticket conversion across Israel and Greece. "
                        "Participated in sprint planning; authored and tracked Jira tickets "
                        "for product and integration work. "
                        "Managed Seats.io seating configurations for major Israeli "
                        "football stadiums; responsible for ensuring seat maps, "
                        "capacity rules, and ticketing logic were correctly configured "
                        "under tight event-day deadlines. "
                        "Authored complex PRDs for payment gateway integrations and "
                        "seating map logic. "
                        "Utilized SQL and Python for data-driven decision making "
                        "regarding partner retention. "
                        "Tools: Jira, Monday, Seats.io, SQL, Python."
                    ),
                },
                {
                    "title":   "Partnership Manager & Customer Success Lead",
                    "period":  "2023 - 2025",
                    "details": (
                        "Started in customer support and was promoted to Partnership Manager "
                        "within months. "
                        "Owned B2B onboarding, client success operations, "
                        "and 24/7 technical and operational support for event organizers. "
                        "First point of contact for venue partners during live events; "
                        "handled real-time incident resolution."
                    ),
                },
                {
                    "title":   "Customer Support",
                    "period":  "2023",
                    "details": (
                        "Entry-level role; promoted to Partnership Manager within months. "
                        "Third consecutive rapid promotion to a leadership position "
                        "(following Aldo and River), confirming a career-wide pattern."
                    ),
                },
            ],
        },
    ],

    # ── Volunteering ─────────────────────────────────────────────────────────
    "volunteering": {
        "organization": "Perach Project",
        "role":         "Personal Mentor",
        "duration":     "1 year (weekly one-on-one sessions)",
        "description": (
            "Perach is Israel's national student-mentorship programme, pairing "
            "university students with children from socio-economically disadvantaged "
            "backgrounds for sustained one-on-one mentorship. "
            "Ron was matched with an 8-year-old and met weekly throughout the programme year."
        ),
        "focus_areas": [
            "Emotional development: building confidence, stability, and trust for a "
            "child in a challenging home environment",
            "Academic development: tutoring, homework support, and study-habit formation",
            "Social development: introducing structured play, goal-setting, and "
            "consistent positive reinforcement",
        ],
        "skills_demonstrated": [
            "Emotional intelligence: sustained attunement to a child's emotional state "
            "week over week, adapting approach based on what the child needed — not "
            "what the programme prescribed",
            "Patience and long-term commitment: a full year of weekly contact with "
            "no immediate feedback loop, no performance review, no audience",
            "Influence without authority: achieved measurable developmental outcomes "
            "by building trust, not by issuing instructions",
            "Coordination across adults: aligned with parents, the programme coordinator, "
            "and school where relevant — managing multiple stakeholder perspectives "
            "around the child's wellbeing",
        ],
        "why_it_matters_professionally": (
            "Any hiring manager who lists 'empathy', 'people-first', or 'emotional "
            "intelligence' as a value is describing a trait that is almost impossible "
            "to verify from a CV. Perach is the exception. It is a year-long, "
            "externally verifiable commitment that cannot be faked. "
            "The skills it develops — sustained empathy, influence without authority, "
            "patient stakeholder management — are identical to those required of a "
            "senior PM, team lead, or CS manager operating in complex, ambiguous environments."
        ),
    },

    # ── Skills ────────────────────────────────────────────────────────────────
    "skills": [
        "Product Strategy",
        "Team Leadership",
        "PRD/Jira",
        "SQL/Python",
        "SaaS Ops",
        "Customer Success",
    ],

    # ── Key narratives: cross-cutting stories for the Sourcing Agent ─────────
    # These encode the 'hidden signal' patterns that keyword scanners miss.
    # The Sourcing Agent should surface these when a job description implies
    # the underlying trait, even if it uses different vocabulary.
    "key_narratives": {

        "rapid_promotion": {
            "headline": "Four consecutive rapid promotions across three employers",
            "evidence": [
                "Aldo (2014–2016): started as seller, promoted to Shift Manager within months",
                "River (2016–2019): Take-Away & Operations Team Lead — managing logistics team and hostess staff",
                "GO-OUT (2023–2026): Customer Support → Partnership Manager & CS Lead → Team Lead "
                "across a single company in ~3 years",
            ],
            "what_it_signals": (
                "This is not coincidence — it is a pattern. Three different employers, "
                "at three different life stages, each identified Ron as someone to "
                "promote into leadership ahead of the expected timeline. "
                "For a hiring manager worried about whether a candidate will grow into "
                "a senior role, this is the clearest available evidence."
            ),
            "match_keywords": [
                "growth potential", "high performer", "fast track", "rapid learner",
                "promotion", "leadership potential", "takes initiative",
            ],
        },

        "resilience": {
            "headline": "Maintained Dean's List (top 4 in class) while working three simultaneous jobs",
            "evidence": [
                "During degree at Reichman University, held concurrent roles at: "
                "Insurance Agency (Operations & Pension Referent), "
                "Reuveni Pridan (Reception & Admin), "
                "and GO-OUT (Customer Support → Partnership Manager)",
                "Final academic standing: Dean's List, ranked 4th in class",
            ],
            "what_it_signals": (
                "Most candidates either work part-time or study full-time. "
                "Ron did both, simultaneously, with three employers, and finished "
                "near the top of his class. This is not a time-management anecdote — "
                "it is hard evidence of the ability to sustain high performance under "
                "sustained, multi-directional pressure."
            ),
            "match_keywords": [
                "resilience", "grit", "adaptable", "works under pressure",
                "multitasking", "self-motivated", "independent", "driven",
                "fast-paced environment", "handles ambiguity",
            ],
        },

        "operational_complexity": {
            "headline": "Managed mission-critical logistics for major live events at GO-OUT",
            "evidence": [
                "Configured and managed Seats.io seating maps for major Israeli football stadiums — "
                "responsible for capacity rules, seat categorisation, and ticketing logic",
                "Handled payment-gateway escalations during live sold-out events — "
                "extreme-pressure scenarios where transaction failures affect thousands of fans",
                "24/7 operational support for event organizers as Partnership Manager",
            ],
            "what_it_signals": (
                "Stadium-scale, live-event operations have zero tolerance for error "
                "and no opportunity to pause. The combination of technical system "
                "configuration (Seats.io) and real-time incident response is a "
                "rare pairing that signals both technical literacy and operational "
                "calm under pressure."
            ),
            "match_keywords": [
                "logistics", "operations", "incident management", "live operations",
                "mission critical", "high stakes", "event management", "venue",
                "ticketing", "real-time", "on-call", "escalation",
            ],
        },

        "emotional_intelligence": {
            "headline": "Demonstrated sustained emotional intelligence across both professional and volunteer contexts",
            "evidence": [
                "Perach Project: 1-year weekly mentorship of an 8-year-old focused on "
                "emotional and academic development — sustained empathy without authority",
                "Partnership Manager at GO-OUT: managed distressed event organizers "
                "during live incidents; required de-escalation and emotional attunement "
                "alongside technical problem-solving",
                "Team Lead managing 7 employees across two countries: required cultural "
                "sensitivity and consistent emotional availability",
            ],
            "what_it_signals": (
                "Emotional intelligence is the most over-claimed and least-verified "
                "competency on any CV. Ron's profile provides two independent, "
                "externally verifiable data points: Perach (structured, long-term, "
                "child-focused) and GO-OUT escalation management (commercial, "
                "high-pressure, adult-focused). Together they prove the skill is "
                "not context-specific — it is a stable trait."
            ),
            "match_keywords": [
                "emotional intelligence", "empathy", "people skills", "interpersonal",
                "team morale", "employee wellbeing", "de-escalation", "conflict resolution",
                "relationship management", "coaching", "mentoring",
            ],
        },
    },
}


# ── Trait Clusters ────────────────────────────────────────────────────────────
#
# Each cluster defines ONE core competency and lists every moment in the
# profile where it was independently demonstrated.
#
# Structure per instance:
#   source     — the employer / programme / institution
#   life_stage — early_career | military | academic | professional | personal
#   description — one sentence, grounded in profile facts only
#
# The scoring engine multiplies confidence by life-stage diversity:
# the same trait appearing in 5 unrelated contexts is far stronger evidence
# than the same trait appearing 5 times in the same role.
#
# job_keywords are matched against job-description text to decide which
# clusters are relevant for a given role.

TRAIT_CLUSTERS: dict[str, dict] = {

    "leadership": {
        "label": "Leadership & People Management",
        "job_keywords": [
            r"\blead\b", r"manag", r"\bteam\b", "people manag", "direct report",
            "supervise", "head of", "leadership", "oversaw", "responsible for.*team",
        ],
        "instances": [
            {
                "source":      "Aldo (Gelato Shop)",
                "life_stage":  "early_career",
                "description": "Started as a seller and was promoted to Shift Manager within months at 18 — responsible for staff scheduling, inventory, and daily operations.",
            },
            {
                "source":      "River (Restaurant)",
                "life_stage":  "early_career",
                "description": "Take-Away & Operations Team Lead — managed take-away logistics team and hostess staff under high-volume service pressure.",
            },
            {
                "source":      "IDF — Hoshen Unit (Telecom Corps)",
                "life_stage":  "military",
                "description": "Head of Commander's Office — managed task flow, meeting summaries, document distribution, and trained incoming office personnel.",
            },
            {
                "source":      "GO-OUT — Customer Support",
                "life_stage":  "professional",
                "description": "Promoted from entry-level support to Partnership Manager within months.",
            },
            {
                "source":      "GO-OUT — Partnership Manager & CS Lead",
                "life_stage":  "professional",
                "description": "Owned B2B onboarding, client success operations, and 24/7 support for event organizers.",
            },
            {
                "source":      "GO-OUT — Team Lead",
                "life_stage":  "professional",
                "description": "Managed 7 employees across Israel and Greece; daily syncs with COO/CFO; oversaw SLA, major B2B accounts, B2B2C promoters network, and escalation handling.",
            },
            {
                "source":      "Perach Project",
                "life_stage":  "personal",
                "description": "Led a child's emotional and academic development for a full year — influence without any formal authority.",
            },
        ],
    },

    "resilience": {
        "label": "Resilience & Performance Under Sustained Pressure",
        "job_keywords": [
            "resilience", "grit", r"under pressure", "fast.paced", "multitask",
            "adaptable", "driven", "ambiguit", "self-motivated", "independent",
            "handles stress", "high.pressure", "demanding",
        ],
        "instances": [
            {
                "source":      "Reichman University + three concurrent jobs",
                "life_stage":  "academic",
                "description": "Maintained Dean's List (ranked 4th in class) while simultaneously employed at Insurance Agency, Reuveni Pridan, and GO-OUT throughout the degree.",
            },
            {
                "source":      "GO-OUT — live stadium events",
                "life_stage":  "professional",
                "description": "Managed payment-gateway failures and seating-system incidents during sold-out football stadium events — zero margin for error, thousands of fans affected in real time.",
            },
            {
                "source":      "GO-OUT — 24/7 support",
                "life_stage":  "professional",
                "description": "24/7 first-response technical and operational support as Partnership Manager — no buffer time, no escalation layer above.",
            },
            {
                "source":      "River (Restaurant)",
                "life_stage":  "early_career",
                "description": "Shift lead during high-volume service: kitchen logistics and hosting team coordination under continuous time pressure.",
            },
        ],
    },

    "emotional_intelligence": {
        "label": "Emotional Intelligence & Empathy",
        "job_keywords": [
            "empathy", "emotional intel", "people.first", "interpersonal",
            "coaching", r"\bmentor", "team morale", "wellbeing", "de.escalat",
            "conflict resol", "relationship manag", "care", "compassion",
        ],
        "instances": [
            {
                "source":      "Perach Project",
                "life_stage":  "personal",
                "description": "One year of weekly one-on-one mentorship of an 8-year-old focused on emotional and academic development — required sustained attunement and patience across 50+ sessions.",
            },
            {
                "source":      "GO-OUT — partner escalations",
                "life_stage":  "professional",
                "description": "De-escalated distressed B2B event organizers mid-incident, often resolving emotional tension before solving the technical problem.",
            },
            {
                "source":      "GO-OUT — Team Lead",
                "life_stage":  "professional",
                "description": "Managed emotional wellbeing and performance of 7 employees across Israel and Greece, including navigating cross-cultural communication.",
            },
            {
                "source":      "IDF — Hoshen Unit (Telecom Corps)",
                "life_stage":  "military",
                "description": "Operated at high emotional discipline in a hierarchical, high-stakes military environment as Head of Commander's Office.",
            },
        ],
    },

    "operational_complexity": {
        "label": "Operational Complexity & Logistics",
        "job_keywords": [
            "operations", "logistics", r"\bops\b", "process", "workflow",
            "coordination", "incident", "escalation", "on.call", "live ops",
            "systems", "complex", "infrastructure", "platform",
        ],
        "instances": [
            {
                "source":      "Aldo (Gelato Shop)",
                "life_stage":  "early_career",
                "description": "Managed inventory, staff scheduling, and daily operational flow at 18.",
            },
            {
                "source":      "River (Restaurant)",
                "life_stage":  "early_career",
                "description": "Kitchen logistics and hosting team coordination during high-volume service shifts.",
            },
            {
                "source":      "Insurance Agency",
                "life_stage":  "professional",
                "description": "End-to-end management of 800+ client files, insurance policies, and pension fund records.",
            },
            {
                "source":      "GO-OUT — Seats.io",
                "life_stage":  "professional",
                "description": "Configured seating maps, capacity rules, and ticketing logic for major Israeli football stadiums.",
            },
            {
                "source":      "GO-OUT — payment gateways",
                "life_stage":  "professional",
                "description": "Handled extreme payment-gateway failure scenarios during live sold-out events under real-time pressure.",
            },
        ],
    },

    "stakeholder_management": {
        "label": "Stakeholder & Client Management",
        "job_keywords": [
            "stakeholder", "client", r"\bpartner\b", "account manag", "b2b",
            "enterprise", "customer success", "retention", "executive", "vendor",
            "relationship", "external", "influenc",
        ],
        "instances": [
            {
                "source":      "Reuveni Pridan (Advertising)",
                "life_stage":  "professional",
                "description": "Interface between a leading advertising agency and external clients and contacts during studies.",
            },
            {
                "source":      "Insurance Agency",
                "life_stage":  "professional",
                "description": "Managed ongoing relationships and data integrity for 800+ individual policyholders and pension clients.",
            },
            {
                "source":      "GO-OUT — Partnership Manager",
                "life_stage":  "professional",
                "description": "Primary account owner for B2B event-organizer partners; owned onboarding, support, and relationship health.",
            },
            {
                "source":      "GO-OUT — Team Lead",
                "life_stage":  "professional",
                "description": "Led high-stakes retention conversations with partners at risk of churn; handled escalations at executive level.",
            },
            {
                "source":      "Perach — multi-party coordination",
                "life_stage":  "personal",
                "description": "Aligned parents, school, and programme coordinator around a child's goals — managing competing stakeholder interests without formal authority.",
            },
        ],
    },

    "rapid_growth": {
        "label": "Rapid Learning & Career Acceleration",
        "job_keywords": [
            "growth", r"learn\b", "promot", "fast track", "high performer",
            "potential", "initiative", "ambitious", r"\bscale\b", "driven",
            "hungry", "ownership", "self-starter", "quick",
        ],
        "instances": [
            {
                "source":      "Aldo (Gelato Shop)",
                "life_stage":  "early_career",
                "description": "Started as seller, promoted to Shift Manager within months at 18 — first leadership role, first employer.",
            },
            {
                "source":      "River (Restaurant)",
                "life_stage":  "early_career",
                "description": "Take-Away & Operations Team Lead — second consecutive early-career promotion to management.",
            },
            {
                "source":      "Reichman University",
                "life_stage":  "academic",
                "description": "Dean's List while working 3 simultaneous jobs — finished ranked 4th in class.",
            },
            {
                "source":      "GO-OUT (three-level progression)",
                "life_stage":  "professional",
                "description": "Customer Support → Partnership Manager & CS Lead → Team Lead within a single company in ~3 years.",
            },
        ],
    },
}


# ── Personal field persistence ────────────────────────────────────────────────
#
# All "personal" fields (name/dob/email/phone/linkedin/location) start as
# placeholders in USER_PROFILE above. At import time, _load_personal_overrides()
# reads backend/personal_overrides.json (gitignored — never committed) and
# patches in whatever real values are present locally; see
# backend/personal_overrides.json.example for the expected shape.
#
# Separately, core contact fields (phone, location only) can also be written
# at runtime via the missing-data wizard, which calls save_personal_field()
# below — that write path is unchanged by the broader load above.

import json as _json
from pathlib import Path as _Path

_PERSONAL_OVERRIDES_PATH = _Path(__file__).resolve().parents[1] / "personal_overrides.json"

# Fields this file will load from personal_overrides.json at import time, to
# seed the placeholder USER_PROFILE["personal"] dict above with real local
# values without ever committing them to source. Broader than
# _CORE_PERSONAL_FIELDS below on purpose — this only runs once at process
# start from a gitignored local file, it isn't a runtime write path.
_LOADABLE_PERSONAL_FIELDS = frozenset({"name", "dob", "email", "phone", "linkedin", "location"})

# Fields writable at runtime via save_personal_field() (e.g. the missing-data
# wizard in resumes.py) — intentionally narrower than the load set above so
# this phase doesn't change what that existing write path is allowed to touch.
_CORE_PERSONAL_FIELDS = frozenset({"phone", "location"})


def _load_personal_overrides() -> None:
    """Apply persisted personal-field overrides to the in-memory USER_PROFILE."""
    if not _PERSONAL_OVERRIDES_PATH.exists():
        return
    try:
        overrides = _json.loads(_PERSONAL_OVERRIDES_PATH.read_text(encoding="utf-8"))
        if isinstance(overrides, dict):
            for k, v in overrides.items():
                if k in _LOADABLE_PERSONAL_FIELDS:
                    USER_PROFILE["personal"][k] = v
    except Exception:
        pass


def save_personal_field(field: str, value: str) -> None:
    """
    Persist a core personal field (e.g. 'phone', 'location') to disk and patch
    USER_PROFILE['personal'] in memory so the change is immediately visible to
    pdf_builder and build_full_text without a process restart.
    """
    if field not in _CORE_PERSONAL_FIELDS:
        return
    clean = str(value or "").strip()
    if not clean:
        return

    # Load existing overrides, merge, write back
    try:
        existing = _json.loads(_PERSONAL_OVERRIDES_PATH.read_text(encoding="utf-8")) if _PERSONAL_OVERRIDES_PATH.exists() else {}
    except Exception:
        existing = {}
    existing[field] = clean
    _PERSONAL_OVERRIDES_PATH.write_text(_json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")

    # Patch in-memory profile immediately
    USER_PROFILE["personal"][field] = clean


# Apply any previously saved overrides at import time
_load_personal_overrides()


# ── Helpers ────────────────────────────────────────────────────────────────────

def get_all_companies() -> list[str]:
    companies: list[str] = []
    for exp in USER_PROFILE.get("experience", []):
        name = exp.get("company") or exp.get("unit", "")
        if name:
            companies.append(name)
    return companies


def get_narrative(key: str) -> dict:
    """Return a key narrative dict by name, or empty dict if not found."""
    return USER_PROFILE.get("key_narratives", {}).get(key, {})


# ── Multi-tenant accessors ─────────────────────────────────────────────────────
#
# The module-level USER_PROFILE dict above is LEGACY SINGLE-USER data, valid
# only for user_id='default' (pre-migration local development). Multi-tenant
# code paths must go through get_profile(user_id) / build_full_text(user_id),
# which compose the per-user profile from the master_profiles onboarding row
# that Ariel maintains (see agents/ariel_tools.py handlers).

def _onboarding_row_profile(user_id: str) -> dict:
    """Load the onboarding profile document for user_id ({} if absent)."""
    try:
        from backend.repositories import profile_repository
        return profile_repository.get_profile_json(user_id)
    except Exception:
        return {}


def _master_profile_verified_email(user_id: str) -> str:
    """
    The verified-email COLUMN on profiles (set from the Supabase JWT at
    /api/auth/sync-user — see backend/api/routes/auth.py), not the profile
    document. Reliable for every real account regardless of whether
    onboarding ever asked for contact info, so this is the primary email
    source — the document's personal.email (if ever set some other way) is
    checked first by get_profile() and this is only the fallback.
    """
    try:
        from backend.repositories import profile_repository
        row = profile_repository.get(user_id)
        return (row.email or "") if row else ""
    except Exception:
        return ""


_USER_PERSONAL_FIELDS = frozenset({"name", "phone", "location", "linkedin"})

# Sent as the answer to an optional core question (location, LinkedIn) when
# the user chooses not to give it. Both are recommended, not required: the
# choice is recorded as <field>_skipped so tailoring stops asking, and the CV
# header simply omits the field.
SKIP_ANSWER = "__skip__"
OPTIONAL_PERSONAL_FIELDS = frozenset({"location", "linkedin"})


def save_user_personal_field(user_id: str, field: str, value: str) -> bool:
    """
    Save a contact field the user typed (tailoring asks for missing ones) to
    THIS user's profile — master_profile["personal"], the first source
    get_profile() reads.

    The tailoring route used to call save_personal_field(), which writes a
    process-wide file and the legacy single-user USER_PROFILE dict. The
    user's own profile never changed, so the next tailoring asked for the
    same phone number again — every time — and the answer overwrote shared
    state. Returns True when saved.
    """
    if field not in _USER_PERSONAL_FIELDS:
        return False
    clean = str(value or "").strip()
    if not clean:
        return False
    skipped = field in OPTIONAL_PERSONAL_FIELDS and clean == SKIP_ANSWER
    from datetime import datetime, timezone
    from sqlalchemy.orm import Session
    from backend.core.database import ENGINE
    from backend.repositories import profile_repository
    now = datetime.now(timezone.utc).isoformat()
    with Session(ENGINE) as session:
        row, _ = profile_repository.get_or_create(session, user_id, now=now)
        mp = dict(row.master_profile or {})
        personal = dict(mp.get("personal") or {}) if isinstance(mp.get("personal"), dict) else {}
        if skipped:
            personal[f"{field}_skipped"] = True
        else:
            personal[field] = clean
            personal.pop(f"{field}_skipped", None)
        mp["personal"] = personal
        row.master_profile = mp
        row.updated_at = now
        profile_repository.save(session, row)
        session.commit()
    return True


def _auth_metadata_personal(user_id: str) -> dict:
    """name/phone from the Supabase auth user's metadata (set at sign-up)."""
    try:
        from sqlalchemy import text as _sql
        from backend.core.database import ENGINE
        with ENGINE.connect() as conn:
            row = conn.execute(_sql(
                "SELECT raw_user_meta_data->>'phone', "
                "COALESCE(raw_user_meta_data->>'full_name', raw_user_meta_data->>'name') "
                "FROM auth.users WHERE id = CAST(:uid AS uuid)"
            ), {"uid": user_id}).fetchone()
    except Exception:
        # Not fatal: a CV can still be built from the other sources. Logged so
        # a broken lookup isn't mistaken for "the user never gave a phone".
        logger.warning("[user_profile] auth metadata unreadable for user=%s", user_id, exc_info=True)
        return {}
    if not row:
        return {}
    return {"phone": str(row[0] or "").strip(), "name": str(row[1] or "").strip()}


def _cv_personal(onboarding: dict) -> dict:
    """Contact fields from the stored CV extraction, in the get_profile() key shape."""
    cv = onboarding.get("cv_data") if isinstance(onboarding.get("cv_data"), dict) else {}
    personal = cv.get("personal") if isinstance(cv.get("personal"), dict) else {}
    return {
        "name":     str(personal.get("full_name", "") or "").strip(),
        "email":    str(personal.get("email", "") or "").strip(),
        "phone":    str(personal.get("phone", "") or "").strip(),
        "linkedin": str(personal.get("linkedin_url", "") or "").strip(),
        "location": str(personal.get("location", "") or "").strip(),
    }


def _metrics_doc_personal(user_id: str) -> dict:
    """
    Contact fields from master_profiles.master_profile["metrics_doc"]["personal"]
    (backend/services/master_profile_service.py's `load(user_id)` — the B2C
    onboarding/CV-import flow's own document, keyed "full_name"/"linkedin_url"
    rather than the "name"/"linkedin" keys get_profile() returns). This is
    frequently the ONLY place real contact data ends up for an account created
    via CV import, since the plain onboarding `personal` dict
    (_onboarding_row_profile) is a separate, often-empty field on the same
    row. Normalizes key names to the get_profile() shape here so callers never
    need to know about this second document.
    """
    try:
        from backend.services.master_profile_service import load as _load_metrics_doc
        personal = (_load_metrics_doc(user_id) or {}).get("personal", {})
        if not isinstance(personal, dict):
            return {}
        return {
            "name":     str(personal.get("full_name", "") or "").strip(),
            "email":    str(personal.get("email", "") or "").strip(),
            "phone":    str(personal.get("phone", "") or "").strip(),
            "linkedin": str(personal.get("linkedin_url", "") or "").strip(),
            "location": str(personal.get("location", "") or "").strip(),
        }
    except Exception:
        return {}


# ── Uploaded-CV data in the profile ──────────────────────────────────────────
# get_profile() used to read only the sections Ariel writes during a
# conversation (experience / education / skills on the profile document)
# and ignored `cv_data` — what POST /api/profile/cv-upload extracts from the
# user's CV. For a user who uploaded a CV and had no long chat with Ariel,
# every consumer of this function (Ariel's own context, job scoring via
# feed_service, CV tailoring) saw an empty or near-empty profile: in
# production three testers had 5-7 CV roles each and 0-1 in the profile.
# Ariel asked them for facts their CV already stated, and scoring ran
# without their history, violating the "full experience timeline" rule.
#
# Ariel-written entries win (the user confirmed them in conversation); CV
# entries fill in everything else. A CV role is a duplicate of a profile role
# when it is at the same company over an overlapping period — titles alone
# differ too often ("FP&A Analyst" vs "Senior FP&A Analyst") to match on.

def _norm_company(name: str) -> str:
    return " ".join(str(name or "").lower().replace(".", " ").replace(",", " ").split())


def _year(value) -> Optional[int]:
    import re as _re
    m = _re.search(r"(19|20)\d{2}", str(value or ""))
    return int(m.group(0)) if m else None


def _span(start, end) -> tuple[int, int]:
    from datetime import datetime as _dt
    s = _year(start) or 0
    e_raw = str(end or "").strip().lower()
    e = _dt.now().year if e_raw in ("", "present", "current", "now", "today") else (_year(end) or s)
    return s, max(s, e)


def _overlaps(a: tuple[int, int], b: tuple[int, int]) -> bool:
    if not a[0] or not b[0]:
        return True          # unknown dates: same company is enough
    return a[0] <= b[1] and b[0] <= a[1]


def _merged_experience(onboarding: dict) -> list[dict]:
    """Profile (Ariel) experience plus CV experience, deduped, most recent first."""
    own = [e for e in (onboarding.get("experience") or []) if isinstance(e, dict)]
    cv = onboarding.get("cv_data") if isinstance(onboarding.get("cv_data"), dict) else {}
    merged = list(own)
    for c in cv.get("experiences") or []:
        if not isinstance(c, dict):
            continue
        company, span = _norm_company(c.get("company")), _span(c.get("start"), c.get("end"))
        if company and any(
            _norm_company(o.get("company")) == company and _overlaps(span, _span(o.get("start"), o.get("end")))
            for o in merged
        ):
            continue
        summary = str(c.get("summary") or "").strip()
        merged.append({
            "company": c.get("company", ""),
            "role":    c.get("role") or c.get("title") or "",
            "start":   c.get("start", ""),
            "end":     c.get("end", ""),
            "bullets": [summary] if summary else [],
            "kind":    c.get("kind", ""),
        })
    merged.sort(key=lambda e: _span(e.get("start"), e.get("end")), reverse=True)
    return merged


def _cv_education(cv: dict) -> list[dict]:
    """CV education mapped to the profile's education shape."""
    out = []
    for e in cv.get("education") or []:
        if isinstance(e, dict):
            out.append({
                "degree": e.get("degree", ""),
                "school": e.get("institution") or e.get("school") or "",
                "period": e.get("years") or e.get("period") or "",
                "status": "",
            })
        elif str(e).strip():
            out.append({"degree": str(e).strip(), "school": "", "period": "", "status": ""})
    return out


def _merged_skills(own: list, cv_skills: list) -> list:
    """Profile skills plus CV skills not already present (case-insensitive)."""
    def _name(s):
        return (s.get("name") if isinstance(s, dict) else s) or ""
    seen = {str(_name(s)).strip().lower() for s in own}
    out = list(own)
    for s in cv_skills:
        n = str(_name(s)).strip()
        if n and n.lower() not in seen:
            seen.add(n.lower())
            out.append(s)
    return out


def get_profile(user_id: str) -> dict:
    """
    Per-user profile in the legacy USER_PROFILE shape (personal / education /
    experience / skills / key_narratives), so existing consumers (orchestrator
    nodes, tailor context builders) work unchanged.

    An adapter over the user's master_profiles onboarding row: Ariel-shaped
    experience entries ({company, role, start, end, bullets}) are mapped onto
    the legacy USER_PROFILE shape ({company, role, period, details}).
    """
    onboarding = _onboarding_row_profile(user_id)
    cv = onboarding.get("cv_data") if isinstance(onboarding.get("cv_data"), dict) else {}
    # A degree the CV extraction filed as a job (stored CVs predate the fix in
    # cv_aggregator_service) is shown as education, not work experience
    # (services/cv_entry_kind.py). Army service stays in the history.
    from backend.services.cv_entry_kind import separate_degrees
    merged_jobs, moved_education = separate_degrees(_merged_experience(onboarding), [])
    experience = []
    for e in merged_jobs:
        experience.append({
            "company": e.get("company", ""),
            "role":    e.get("role", ""),
            "period":  f"{e.get('start', '')} - {e.get('end', '')}".strip(" -"),
            "start":   e.get("start", ""),
            "end":     e.get("end", ""),
            "details": " ".join(str(b) for b in e.get("bullets", [])),
            "kind":    e.get("kind", ""),
        })
    # Real per-user contact data, resolved with a fallback chain across every
    # place this app can have written it — previously hardcoded to "" for
    # every field except name, even when data existed:
    #   1. onboarding["personal"] (master_profile top-level "personal" key) —
    #      set by /api/auth/sync-user for name, the missing-data wizard for
    #      phone/location. Often empty — most accounts never populate this.
    #   2. metrics_doc["personal"] (_metrics_doc_personal) — the B2C
    #      onboarding/CV-import flow's OWN document, keyed full_name/
    #      linkedin_url. This is where a CV-imported account's real contact
    #      details usually actually live.
    #   3. Verified email column (master_profiles.email) — email only, always
    #      populated for a real account regardless of onboarding progress.
    onboarding_personal = onboarding.get("personal", {})
    if not isinstance(onboarding_personal, dict):
        onboarding_personal = {}
    metrics_personal = _metrics_doc_personal(user_id)
    #   4. The contact block extracted from the uploaded CV itself
    #      (cv_data["personal"]). The upload route copies it into 1 and 2, but
    #      a CV sent through the Ariel chat never was, nor was one uploaded
    #      before that copy existed — production logs showed phone, LinkedIn,
    #      location (and for one user the name) blank for almost every user,
    #      so tailored CVs went out without a contact header.
    cv_personal = _cv_personal(onboarding)
    #   5. What the user typed at sign-up (Supabase auth user_metadata) — the
    #      phone in particular, which sign-up requires and nothing copied into
    #      the profile, so tailoring asked for it again. Typed beats extracted.
    auth_personal = _auth_metadata_personal(user_id)

    def _first(key: str) -> str:
        return (onboarding_personal.get(key, "") or metrics_personal.get(key, "")
                or auth_personal.get(key, "") or cv_personal.get(key, ""))

    personal = {
        "name":     _first("name"),
        "title":    "",
        "email":    onboarding_personal.get("email", "") or metrics_personal.get("email", "")
                    or _master_profile_verified_email(user_id) or cv_personal.get("email", ""),
        "phone":    _first("phone"),
        "linkedin": _first("linkedin"),
        "location": _first("location"),
        # The user chose not to give these (tailoring offers a Skip).
        "location_skipped": bool(onboarding_personal.get("location_skipped")),
        "linkedin_skipped": bool(onboarding_personal.get("linkedin_skipped")),
    }

    # Missing-data guard — never fail CV generation over this (a CV with a
    # gap is still usable; a 500 isn't), but make an incomplete header loud
    # in the logs instead of silently shipping it, per every source checked.
    missing = [k for k in ("name", "phone", "linkedin", "location")
               if not personal[k] and not personal.get(f"{k}_skipped")]
    if missing:
        logger.warning(
            "[user_profile] get_profile(%s): contact field(s) %s are blank in every source "
            "checked (onboarding.personal, metrics_doc.personal, cv_data.personal) — CV header will render "
            "without them.",
            user_id, missing,
        )

    education = list(onboarding.get("education") or _cv_education(cv))
    have = {str((e.get("degree") if isinstance(e, dict) else e) or "").strip().lower() for e in education}
    for m in moved_education:
        if m["degree"].lower() not in have:
            education.append({"degree": m["degree"], "school": m["institution"], "period": m["years"], "status": ""})
    return {
        "personal":       personal,
        "summary":        onboarding.get("professional_summary", "") or str(cv.get("summary") or ""),
        "education":      education,
        "experience":     experience,
        "skills":         _merged_skills(onboarding.get("skills") or [], cv.get("skills") or []),
        "career_goals":   onboarding.get("career_goals", {}),
        "key_narratives": {},
        "volunteering":   "",
    }


def resolve_profile(user_id: str) -> dict:
    """
    get_profile(user_id) that degrades instead of raising.

    Post-processing helpers (tailor's static-section injection and employer
    enforcement, researcher's entity extraction) used to read the module-level
    USER_PROFILE singleton directly, which silently substituted the legacy
    single-user data into every real account's output. They resolve through
    here instead.

    A DB lookup failure returns an EMPTY dict, never the legacy singleton.

    This used to fall back to USER_PROFILE, reasoning that "a CV built from a
    stale profile is still deliverable, a 500 is not". That reasoning held only
    while there was one user and the singleton was that user. With real
    accounts it is a cross-tenant leak on an error path: a transient DB hiccup
    during CV generation would serve one person's employers, education and
    phone number into a different person's document, silently and plausibly.

    Every caller here reads the result with .get() and iterates, so {} degrades
    cleanly — the CV simply omits the section rather than filling it with
    someone else's facts. gaps_for_missing_core_fields() even improves: it asks
    the user for their own contact details instead of waving them through on
    the singleton's.
    """
    try:
        return get_profile(user_id)
    except Exception:
        logger.exception(
            "[user_profile] resolve_profile(%s) failed — returning an empty profile. "
            "Downstream output will be missing profile-derived sections.",
            user_id,
        )
        return {}


def format_profile_compact(profile: dict) -> str:
    """
    Render the get_profile() shape as compact plain text instead of pretty
    JSON, for injection into the Ariel system prompt. Every experience entry
    and every skill is still included — nothing is capped or sliced — only
    each entry's representation drops JSON's brace/quote/indent overhead.
    """
    lines: list[str] = []

    summary = (profile.get("summary") or "").strip()
    lines.append(f"SUMMARY: {summary or '(none)'}")

    lines.append("")
    lines.append("EXPERIENCE (most recent first):")
    experience = profile.get("experience") or []
    if experience:
        for e in experience:
            role    = e.get("role", "") or "(role unknown)"
            company = e.get("company", "") or "(company unknown)"
            period  = e.get("period", "")
            details = (e.get("details") or "").strip()
            line = f"- {role} @ {company}"
            if period:
                line += f" ({period})"
            if details:
                line += f": {details}"
            lines.append(line)
    else:
        lines.append("- (none)")

    skills = [str(s).strip() for s in (profile.get("skills") or []) if str(s).strip()]
    lines.append("")
    lines.append(f"SKILLS: {', '.join(skills) if skills else '(none)'}")

    education = profile.get("education") or []
    lines.append("")
    lines.append("EDUCATION:")
    if education:
        for ed in education:
            if not isinstance(ed, dict):
                if str(ed).strip():
                    lines.append(f"- {str(ed).strip()}")
                continue
            # get_profile() emits {degree, school, period, status}; older
            # documents used {degree, field, institution, year}. Reading only
            # the old keys dropped the school and the dates, so Ariel saw a
            # bare degree name and asked users for what their CV already said.
            parts = [
                str(ed.get("degree", "") or ""), str(ed.get("field", "") or ""),
                str(ed.get("school") or ed.get("institution") or ""),
                str(ed.get("period") or ed.get("year") or ""),
                str(ed.get("status", "") or ""),
            ]
            lines.append("- " + ", ".join(p for p in parts if p))
    else:
        lines.append("- (none)")

    goals = profile.get("career_goals") or {}
    lines.append("")
    lines.append(
        "CAREER GOALS: target_roles={}; preferred_locations={}; "
        "work_environment={}; notes={}".format(
            ", ".join(goals.get("target_roles") or []) or "(none)",
            ", ".join(goals.get("preferred_locations") or []) or "(none)",
            goals.get("work_environment", "any"),
            (goals.get("notes") or "").strip() or "(none)",
        )
    )

    return "\n".join(lines)


def build_full_text(user_id: str) -> str:
    """Single searchable blob of all profile facts for user_id."""
    profile = get_profile(user_id)
    parts: list[str] = [f"Candidate: {profile['personal'].get('name', '')}"]
    if profile.get("summary"):
        parts.append(f"Summary: {profile['summary']}")
    for edu in profile.get("education", []):
        if isinstance(edu, dict):
            parts.append(" — ".join(str(v) for v in edu.values() if v))
    for exp in profile.get("experience", []):
        parts.append(
            f"{exp.get('role', '')} at {exp.get('company', '')} "
            f"({exp.get('period', '')}): {exp.get('details', '')}"
        )
    if profile.get("skills"):
        parts.append(f"Skills: {', '.join(str(s) for s in profile['skills'])}")
    answers = _saved_answers(user_id)
    if answers:
        # Facts the candidate supplied when tailoring asked about a gap. Kept so
        # the next CV uses them and the agent does not ask the same thing again.
        parts.append("Answers the candidate gave to earlier questions:")
        parts.extend(f"- {qid}: {value}" for qid, value in answers)
    return "\n".join(p for p in parts if p.strip())


def _saved_answers(user_id: str) -> list[tuple[str, str]]:
    """(question_id, answer) pairs saved by merge_answers() for this user."""
    try:
        from backend.services.master_profile_service import load as _load_metrics_doc
        metrics = (_load_metrics_doc(user_id) or {}).get("metrics", {}) or {}
    except Exception:
        logger.warning("[user_profile] saved answers unreadable for user=%s", user_id, exc_info=True)
        return []
    out = []
    for qid, entry in metrics.items():
        if isinstance(entry, dict) and entry.get("source") == "supplemental":
            value = str(entry.get("value", "") or "").strip()
            if value:
                out.append((str(qid), value))
    return out
