"""
Source-of-Truth User Profile for the Deep Profile Engine.

All agent nodes must ground their claims exclusively in this data.
Nothing may be asserted about the candidate that is not present here.
"""
from __future__ import annotations

import logging

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

def get_candidate_name() -> str:
    return USER_PROFILE["personal"]["name"]


def get_all_companies() -> list[str]:
    companies: list[str] = []
    for exp in USER_PROFILE.get("experience", []):
        name = exp.get("company") or exp.get("unit", "")
        if name:
            companies.append(name)
    return companies


def get_all_roles_text() -> list[str]:
    """Flat list of every role + details as a searchable string."""
    lines: list[str] = []
    for exp in USER_PROFILE.get("experience", []):
        company = exp.get("company") or exp.get("unit", "")
        period  = exp.get("period", "")
        if "roles" in exp:
            for r in exp["roles"]:
                lines.append(
                    f"{r['title']} at {company} ({r['period']}): {r['details']}"
                )
        else:
            role    = exp.get("role", "")
            details = exp.get("details", "")
            lines.append(f"{role} at {company} ({period}): {details}")
    return lines


def get_volunteering_summary() -> str:
    v = USER_PROFILE.get("volunteering", {})
    if isinstance(v, str):
        return v
    return (
        f"{v.get('organization', '')} — {v.get('role', '')} "
        f"({v.get('duration', '')}): {v.get('description', '')}"
    )


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
    """Load the onboarding profile dict from master_profiles for user_id ({} if absent)."""
    try:
        from backend.repositories import master_profile_repository
        return master_profile_repository.get_profile_json(user_id)
    except Exception:
        return {}


def _master_profile_verified_email(user_id: str) -> str:
    """
    The verified-email COLUMN on master_profiles (set from the Supabase JWT
    at /api/auth/sync-user — see backend/api/routes/auth.py), not the
    master_profile JSON blob. Reliable for every real account regardless of
    whether onboarding ever asked for contact info, so this is the primary
    email source — the JSON blob's personal.email (if ever set some other
    way) is checked first by get_profile() and this is only the fallback.
    """
    try:
        from backend.repositories import master_profile_repository
        row = master_profile_repository.get(user_id)
        return (row.email or "") if row else ""
    except Exception:
        return ""


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


def get_profile(user_id: str) -> dict:
    """
    Per-user profile in the legacy USER_PROFILE shape (personal / education /
    experience / skills / key_narratives), so existing consumers (orchestrator
    nodes, tailor context builders) work unchanged.

    user_id='default' returns the legacy singleton verbatim. Other users get
    an adapter over their master_profiles onboarding row: Ariel-shaped
    experience entries ({company, role, start, end, bullets}) are mapped onto
    the singleton shape ({company, role, period, details}).
    """
    if user_id == "default":
        return USER_PROFILE

    onboarding = _onboarding_row_profile(user_id)
    experience = []
    for e in onboarding.get("experience", []):
        experience.append({
            "company": e.get("company", ""),
            "role":    e.get("role", ""),
            "period":  f"{e.get('start', '')} - {e.get('end', '')}".strip(" -"),
            "start":   e.get("start", ""),
            "end":     e.get("end", ""),
            "details": " ".join(str(b) for b in e.get("bullets", [])),
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

    personal = {
        "name":     onboarding_personal.get("name", "")     or metrics_personal.get("name", ""),
        "title":    "",
        "email":    onboarding_personal.get("email", "")    or metrics_personal.get("email", "")
                    or _master_profile_verified_email(user_id),
        "phone":    onboarding_personal.get("phone", "")    or metrics_personal.get("phone", ""),
        "linkedin": onboarding_personal.get("linkedin", "") or metrics_personal.get("linkedin", ""),
        "location": onboarding_personal.get("location", "") or metrics_personal.get("location", ""),
    }

    # Missing-data guard — never fail CV generation over this (a CV with a
    # gap is still usable; a 500 isn't), but make an incomplete header loud
    # in the logs instead of silently shipping it, per every source checked.
    missing = [k for k in ("name", "phone", "linkedin", "location") if not personal[k]]
    if missing:
        logger.warning(
            "[user_profile] get_profile(%s): contact field(s) %s are blank in every source "
            "checked (onboarding.personal, metrics_doc.personal) — CV header will render "
            "without them.",
            user_id, missing,
        )

    return {
        "personal":       personal,
        "summary":        onboarding.get("professional_summary", ""),
        "education":      onboarding.get("education", []),
        "experience":     experience,
        "skills":         onboarding.get("skills", []),
        "career_goals":   onboarding.get("career_goals", {}),
        "key_narratives": {},
        "volunteering":   "",
    }


def resolve_profile(user_id: str = "default") -> dict:
    """
    get_profile(user_id) that degrades instead of raising.

    Post-processing helpers (tailor's static-section injection and employer
    enforcement, researcher's entity extraction) used to read the module-level
    USER_PROFILE singleton directly, which silently substituted the legacy
    single-user data into every real account's output. They resolve through
    here instead.

    A DB lookup failure falls back to the legacy singleton rather than raising:
    a CV built from a stale profile is still deliverable, a 500 is not. The
    fallback is logged loudly because it silently degrades output quality.
    """
    if user_id == "default":
        return USER_PROFILE
    try:
        return get_profile(user_id)
    except Exception:
        logger.exception(
            "[user_profile] resolve_profile(%s) failed — falling back to the LEGACY "
            "singleton. Downstream output may not match this user.",
            user_id,
        )
        return USER_PROFILE


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
            parts = [
                str(ed.get("degree", "") or ""), str(ed.get("field", "") or ""),
                str(ed.get("institution", "") or ""), str(ed.get("year", "") or ""),
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


def build_full_text(user_id: str = "default") -> str:
    """
    Single searchable blob of all profile facts for user_id.

    DEPRECATED zero-arg form: calling with no argument returns the legacy
    'default' singleton text — kept only for pre-migration dev paths.
    """
    if user_id != "default":
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
        return "\n".join(p for p in parts if p.strip())

    parts: list[str] = [f"Candidate: {get_candidate_name()}"]

    for edu in USER_PROFILE.get("education", []):
        if "degree" in edu:
            parts.append(
                f"Degree: {edu['degree']} at {edu.get('school', '')} "
                f"— {edu.get('status', '')}. "
                f"{edu.get('resilience_note', '')}"
            )
        if "certification" in edu:
            parts.append(
                f"Certification: {edu['certification']} from "
                f"{edu.get('provider', '')} — {edu.get('details', '')}"
            )

    parts.extend(get_all_roles_text())
    parts.append(f"Volunteering: {get_volunteering_summary()}")
    parts.append(f"Skills: {', '.join(USER_PROFILE.get('skills', []))}")

    for key, narrative in USER_PROFILE.get("key_narratives", {}).items():
        parts.append(
            f"Narrative [{key}]: {narrative.get('headline', '')} — "
            + "; ".join(narrative.get("evidence", []))
        )

    # ── Append any answers the user gave in previous sessions ────────────────
    # These are treated as authoritative profile facts by TailorAgent so it
    # never re-asks a question the user has already answered.
    try:
        from backend.services.supplemental_store import get_as_text
        saved = get_as_text()
        if saved:
            parts.append(saved)
    except Exception:  # never let a store failure break profile loading
        pass

    return "\n".join(parts)
