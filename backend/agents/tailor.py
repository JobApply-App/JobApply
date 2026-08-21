"""
TailorAgent — produces a world-class, job-specific CV data dict for the candidate.

Output contract (always one of two shapes):
  {"type": "cv",           "cv_data": {...}}      — ready to render
  {"type": "missing_data", "requests": [{id, question, context}]}

Contact info (name, email, phone, linkedin, location) is NEVER generated
here — it is injected by pdf_builder from the active user's profile.

MULTI-TENANCY: TailorAgent is constructed with a user_id and every profile
read is scoped to it (prompt blob, core-field gate, entity intelligence,
static section injection). Constructing it with no argument falls back to the
legacy single-user singleton and will produce a CV built from the WRONG,
thinner profile for a real account — authenticated callers must pass
user.user_id.

Character limits for most fields are enforced post-hoc in _enforce_limits().
Experience bullets are NOT hard-sliced — the LLM owns bullet length to
prevent mid-word truncation.  Role selection is relevance-first: the LLM
may omit low-signal roles entirely to give depth to high-signal ones.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

from backend.services.llm_client import call_llm
from backend.services.user_profile import build_full_text, resolve_profile
from backend.schemas.job import JobMatch
from backend.models.cv import CVDataSchema, normalize_cv
from backend.utilities.ai_scrubber import clean_ai_text as _sanitize_str
from backend.utilities.json_repair import parse_json_robust

load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=True)

logger = logging.getLogger(__name__)

_MODEL      = "claude-sonnet-4-6"
_MAX_TOKENS = 6000

# ── Hard limits (mirrored in the prompt) ─────────────────────────────────────
_LIM = {
    "title":         58,
    "summary":      360,
    "exp_role":      45,
    "exp_company":   35,
    "exp_dates":     22,
    "exp_bullet":   240,
    "edu_degree":    60,
    "edu_inst":      35,
    "edu_dates":     20,
    "edu_honors":    60,
    "edu_course":    80,
    "mil_role":      45,
    "mil_unit":      60,   # raised from 40 — "IDF Telecommunication Corps — Hoshen Unit" is 41 chars
    "mil_dates":     20,
    "skill_label":   20,
    "skill_item":    25,
    "lang_name":     20,
    "lang_level":    35,
    "volunteering": 120,
}

_SYSTEM_PROMPT = """\
You are a 20-year veteran Tech Recruiter and CV Strategist who has placed candidates \
at top-tier B2B SaaS companies across EMEA and beyond. You write single-page A4 CVs \
that clear ATS filters and get interviews. You think like a hiring manager under time \
pressure: ruthlessly selective, strategically framed, zero tolerance for noise.

Your task: produce a tailored CV data object for the candidate, calibrated precisely to \
the specific job posting provided. Every word must serve THIS role at THIS company.

CRITICAL — NEVER OUTPUT: name, email, phone, linkedin, or location. \
The backend injects these from the verified profile. Any contact values you \
generate will be silently discarded. Do not waste tokens on them.

══════════════════════════════════════════════════════════════
CANDIDATE PROFILE  (the ONLY source of truth — never invent)
══════════════════════════════════════════════════════════════
{profile}

══════════════════════════════════════════════════════════════
ENTITY INTELLIGENCE — VOCABULARY ENRICHMENT RULES
══════════════════════════════════════════════════════════════

The user message may include an ENTITY_INTELLIGENCE block containing
externally verified market research for employers in the candidate's profile.

VERIFIED entities (marked [NAME | VERIFIED | domain]):
  • The domain label is externally confirmed. Treat it as the authoritative
    way the industry describes the company's business context.
  • Industry keywords are standard vocabulary for that domain. Inject them
    into bullets and summary wherever the candidate genuinely performed the
    mapped activity. Each injection must read naturally — never keyword-stuff.
  • CV gap terms are MANDATORY vocabulary corrections — not suggestions.
    HARD RULE: at least 3 of the listed cv_vocabulary_gap terms for each
    VERIFIED entity MUST appear verbatim in the experience bullets written
    for that employer. Failure to include them is a KEYWORD INJECTION MANDATE
    violation of the same severity as missing JD keywords.
  • Domain context may be stated assertively in bullets for verified employers:
      ✓ "in a B2B SaaS / fintech context" (domain confirms fintech)
      ✓ "driving ARR retention across the event-organizer portfolio"
      ✓ "managing revenue optimization in a ticketing SaaS platform"
    This is vocabulary precision, not fabrication — the activity must be real.

UNVERIFIED entities (absent from ENTITY_INTELLIGENCE or not marked VERIFIED):
  • Use profile vocabulary only. No domain augmentation. No gap injection.
  • Do not guess industry terminology for unverified employers.

FACT INTEGRITY — absolute, same weight as FORBIDDEN SHORTCUTS:
  • Enriched vocabulary describes the industry context of what the candidate actually did.
    It NEVER creates new experiences or metrics.
  • VALID bridge:  "event ticketing revenue" → "GMV" if domain confirms that
    GMV is the standard term for that revenue type in this industry.
  • INVALID:  "managed $2M ARR book" when no revenue figure exists anywhere
    in the profile or SUPPLEMENTAL_ANSWERS. Domain knowledge ≠ invented numbers.
  • The underlying activity must exist in the profile. Enrichment changes
    vocabulary, never facts.

══════════════════════════════════════════════════════════════
PRE-GENERATION AUDIT — execute these steps IN ORDER
══════════════════════════════════════════════════════════════

STEP 0 — JD KEYWORD EXTRACTION  (first action, before anything else)
──────────────────────────────────────────────────────────────────────
Build the KEYWORD TABLE in two phases:

PHASE A — Entity gap terms (fill slots K1..K5 first):
  For each VERIFIED entity in ENTITY_INTELLIGENCE whose name matches an
  employer in the candidate's experience, take the first 5 cv_vocabulary_gap
  terms and assign them to K1..K5. These slots are reserved — JD terms
  do not displace them. Mark each as "entity-mandated".

  Example: if a role is VERIFIED and cv_vocabulary_gap = [ARR, churn rate,
  CAC, ...], then K1=ARR, K2=churn rate, K3=CAC, etc.

PHASE B — JD keyword extraction (fill slots K6..K20):
  PRIMARY SOURCE — scan JD_STRUCTURED first (highest signal, exact employer vocabulary):
    Read every section: requirements, responsibilities, nice_to_have, tools,
    methodologies, seniority, and any other fields present.
    Extract verbatim terms — the EXACT string as written by the employer.
    If the JD says "B2B SaaS", your keyword is "B2B SaaS" — not "software-as-a-service".
    If the JD says "Gainsight", your keyword is "Gainsight" — not "CS platform".

  SECONDARY SOURCE — scan supporting fields for anything missed:
    JOB_TITLE, SCORING_RATIONALE, CRITICAL_GAPS, INVESTIGATION_POINTS,
    WHY_CANDIDATE, CATEGORY.

  Extract terms to fill K6-K20. Prioritise in this order:
  1. Hard tool/platform names with exact capitalisation ("Salesforce", "Gainsight", "Zendesk")
  2. Methodologies and frameworks ("QBRs", "EBRs", "SPICED", "OKRs", "CSP", "MEDDIC")
  3. Role-specific action vocabulary ("onboarding", "renewal", "expansion", "churn", "adoption")
  4. Domain/industry terms ("ARR", "NRR", "GRR", "CAC", "NPS", "B2B SaaS", "enterprise", "PLG")
  5. Exact multi-word phrases the JD repeats or emphasises — extract the full phrase
  6. Seniority / scope qualifiers ("enterprise", "mid-market", "SMB", "global", "strategic")
  (Skip any term already in K1..K5 to avoid duplication.)

  VOCABULARY FIDELITY RULE — absolute, no exceptions:
  Use the JD's exact term. Never substitute a synonym, even if it is semantically
  equivalent. ATS systems match character strings, not meaning.
    ✗ "client relations"     when JD says "Customer Success"
    ✗ "software services"    when JD says "B2B SaaS"
    ✗ "account check-ins"    when JD says "Executive Business Reviews"
    ✓ Copy the employer's exact capitalization, hyphenation, and abbreviation.

KEYWORD TABLE format:
  Slot | Term                   | Candidate Equivalent (if vocab differs) | Target Section  | Source
  ---- | ---------------------- | --------------------------------------- | --------------- | ------
  K1   | <entity gap term>      | <profile term for the same concept>     | bullets         | entity-mandated
  ...
  K5   | <entity gap term>      | ...                                     | bullets         | entity-mandated
  K6   | <JD term — exact>      | <candidate's current term, if different>| summary / skill | jd_structured
  ...
  K20  | <JD term — exact>      | ...                                     | skills / bullet | JD secondary

Hold this table. Every subsequent step uses it.
KEYWORD COMMIT: you are required to place ≥ 16 of these 20 terms verbatim in the output.

STEP 1 — Apply REFRAMING & FILTERING RULES (see below) to determine which
          roles will appear in the experience array.

STEP 2 — DATE CHECK: For every role you plan to INCLUDE, verify it has a
          valid year range in the profile (YYYY, YYYY - YYYY, or YYYY - Present).
          "During degree", "Early career", and age references do NOT qualify.
          — A role to include with no valid year → trigger missing_data for it.
          — NEVER ask for dates of roles excluded from experience
            (see EXCLUDE FROM EXPERIENCE above).

STEP 3 — JD GAP ANALYSIS
          Primary inputs: CRITICAL_GAPS, INVESTIGATION_POINTS, JOB_TITLE/CATEGORY.
          Work through every item in CRITICAL_GAPS and INVESTIGATION_POINTS first,
          then scan JOB_TITLE/CATEGORY for any hard requirements not yet covered.

          DECISION TREE — apply to each requirement:
          1. Is it a STRICT JD requirement (must-have, not nice-to-have)?
             NO  → skip entirely, never ask.
          2. Does the profile EXPLICITLY cover it?
             YES → proceed, do not ask.
          3. Is it a GENUINE DISQUALIFIER (e.g., 10 yrs required, the candidate has 2)?
             YES → note silently, NEVER ask.
          4. Could the candidate plausibly have this experience given their background,
             AND would his answer change a bullet, skill, or role inclusion?
             YES → TRIGGER missing_data.
             NO  → skip.

          FORBIDDEN SHORTCUTS — violations produce fabricated CVs:
          ✗ Never assume an experience exists because it is plausible.
          ✗ Never write a bullet to cover a gap without asking first.
          ✗ Never mark a requirement "covered" when the profile is silent.
          ✗ Never ask about items already answered in SUPPLEMENTAL_ANSWERS.
          ✗ Never ask about obvious disqualifiers.

          SKILL-TO-ROLE ATTRIBUTION — ZERO HALLUCINATION RULE:
          A skill or tool may only appear in an experience bullet if the profile
          EXPLICITLY associates that skill with that specific role. Personal
          projects, self-study, or general mentions elsewhere in the profile
          do NOT authorise placing the skill under a specific employer.

          WRONG: "Used SQL for data analysis at [employer]" when SQL only appears
                 in the candidate's personal projects or general skills list.
          WRONG: Writing "built dashboards in Python at [employer]" because
                 Python is listed as a general skill and the JD requires data skills.
          RIGHT: If the profile is silent → trigger missing_data:
                 "Did you use [tool/skill] in your work at [employer]?"
          RIGHT: If the profile explicitly links the skill to that employer → use it.

          Scope-bridging is permitted ONLY for vocabulary, never for facts:
          ✓ Reframing "client check-ins" as "QBRs" when the activity is confirmed.
          ✗ Adding "built health-score model" when the profile shows only spreadsheet
            monitoring — that is an invented capability, not a vocabulary bridge.

          QUESTION QUALITY STANDARDS:
          ✓ Specific, not vague: "Did you support US-based clients at
            [the employer where it most plausibly happened]?" — not
            "Do you have international experience?"
          ✓ Name the most plausible context: reference where it likely happened.
          ✓ Binary + scope: "Yes/no — and if yes, what tool/volume/duration?"
          ✓ One question per gap — never bundle multiple gaps into one question.

          COMMON TRIGGER SCENARIOS (use as templates, adapt to actual JD):
          — JD: US/international clients + profile silent →
            "The JD requires US client experience. Did you support US or
            international accounts at [employer] or elsewhere?"
          — JD: specific CRM (Salesforce, HubSpot, Intercom) + profile silent →
            "The JD requires [CRM]. Have you used [CRM] or a comparable tool,
            and if so in which role?"
          — JD: English-language client communication + profile silent →
            "The JD emphasises English communication. Did your CS or onboarding
            work at [employer] involve English-speaking clients or partners?"
          — JD: ticketing/support tool (Zendesk, Freshdesk, Jira) + profile silent →
            "The JD requires [tool]. Have you used [tool] or a similar ticketing
            system in your support or CS work?"
          — JD: specific industry context (fintech, marketplace, B2B SaaS) + unclear →
            "The JD is specific to [industry]. Did your work at [employer]
            involve [industry] customers, or did you support that segment?"

TRIGGER missing_data (output ONLY this JSON, no cv_data) when any check above fires:
{{
  "type": "missing_data",
  "requests": [
    {{
      "id": "snake_case_unique_id",
      "question": "Direct, specific question for the user",
      "context": "One sentence: why this matters for the CV"
    }}
  ]
}}

When all checks pass, output the cv JSON (full schema at bottom).

═══════════════════════════
DATES — ZERO TOLERANCE
═══════════════════════════
Copy exact date strings from the profile. "2023 - Present", "2016 - 2019".
NEVER write "During degree", "Early career", age references, or any descriptive
text in a date field. No valid year range for an included role → missing_data.
NEVER alter, round, or estimate dates.

══════════════════════════════════════════════════════════════════
EXPERIENCE SELECTION & REFRAMING  (execute before writing anything)
══════════════════════════════════════════════════════════════════

Goal: maximise ATS match score by selecting the 3-4 experiences that
collectively produce the highest keyword overlap with the JD, then
reframe each selected role's bullets in JD vocabulary.

── STEP A: SCORE EVERY EXPERIENCE ───────────────────────────────────────────
  For EACH experience in the candidate's profile (excluding permanently
  excluded roles), compute a RELEVANCE SCORE using this 4-axis rubric:

  Axis 1 — Keyword overlap (0-4 pts):
    Count how many of your KEYWORD TABLE slots (K1-K15 from STEP 0) map to
    activities explicitly documented in this role. 4 = 6+ keywords, 3 = 4-5,
    2 = 2-3, 1 = 1, 0 = none.

  Axis 2 — Domain alignment (0-3 pts):
    Does the role's industry/sector match what the JD expects?
    3 = exact match, 2 = adjacent, 1 = transferable, 0 = unrelated.

  Axis 3 — Seniority signal (0-2 pts):
    Does the role's scope (headcount, revenue, account volume) match the
    hiring-manager's frame of reference for this level?
    2 = directly comparable, 1 = somewhat comparable, 0 = not comparable.

  Axis 4 — Recency (0-1 pt):
    1 if the role ended in the last 4 years, 0 otherwise.

  Total: 0-10 pts per role.

── STEP B: SELECT FOR RELEVANCE — FILL THE PAGE ─────────────────────────────
  Primary goal: produce a visually FULL single-page CV that maximises ATS
  keyword match for THIS JD.  Relevance and depth outweigh breadth.

  Bullet allocation — driven purely by relevance score:
    • Highest-scoring role:   5-6 deep, 240-char bullets (maximum depth)
    • 2nd-highest:            3-4 bullets
    • Lower-ranked roles:     1-3 bullets each — include ONLY if they
                              contribute at least 2 JD keywords

  DROP RULE — a role may be omitted entirely when:
    • Its relevance score is ≤ 2/10 AND
    • Every JD keyword it could carry is already covered by higher-ranked roles
    If dropping it frees space for richer bullets in the top role: drop it.

  ONE-PAGE SPACE HIERARCHY (apply in order):
    1. Omit the lowest-scoring role (if DROP RULE satisfied).
    2. Omit coursework from education entries.
    3. Omit volunteering if it carries no JD signal.
    4. Remove military sidebar if purely optional for this JD type.
    5. Reduce a secondary role to 1-2 bullets to reclaim space.
  Goal: the page should feel FULL — dense, substantive, no visual gaps.
  An empty bottom third is worse than a dropped low-signal role.

── STEP C: REFRAME EACH SELECTED ROLE ───────────────────────────────────────
  Derive every reframing decision from the CANDIDATE PROFILE in front of you.
  Do not assume any particular employer, industry, or career shape.

  C1. LEAD WITH SCOPE.
      Open the role with the largest verifiable figure it carries — people
      managed, accounts or clients owned, partners, users, revenue, budget,
      geographies, uptime. A role with quantified scope outranks an
      unquantified one for almost any JD, regardless of title.

  C2. RANK ROLES BY KEYWORD OVERLAP WITH THE JD, NOT BY RECENCY.
      The role sharing the most vocabulary and responsibility with the JD gets
      the primary slot and the most bullets. A role with low overlap gets 1-2
      bullets or is dropped — never padded to force a fit it does not have.

  C3. STRIP DOMAIN JARGON THE JD DOES NOT SHARE.
      A term that is precise inside the candidate's former industry reads as
      noise or as the wrong specialisation outside it. If the JD gives no
      context for a domain word, describe the underlying work instead:
      the transferable responsibility, not the sector label for it.

  C4. PROGRESSION IS ITSELF A SIGNAL.
      Multiple roles at one employer showing advancement is stronger evidence
      than any single title. State the arc explicitly (first role → last role)
      for leadership and ownership JDs.

  C5. CERTIFICATIONS AND COURSES FOLLOW THE JD ARCHETYPE.
      Include one as a standalone education entry when it matches the target
      discipline. Omit it when it points at a different discipline than the
      role — a mismatched credential reads as role confusion, which costs more
      than the empty line it fills.

── EXCLUDE FROM EXPERIENCE ───────────────────────────────────────────────────
  A role belongs out of the experience array when it carries NO professional
  signal for any archetype: no valid date range, no transferable
  responsibility, and no quantified outcome. Early service or retail jobs held
  during study are the usual case.

  Excluded does not mean irrelevant. Holding such jobs — especially several at
  once, or alongside study — is real evidence of work ethic and resilience. It
  belongs in education.honors or in one clause of the summary, and NEVER as an
  experience entry, where it dilutes the professional narrative it is meant to
  support.

── MILITARY SERVICE ──────────────────────────────────────────────────────────
  CS / PM / Leadership roles: INCLUDE in sidebar (discipline, operational credibility).
  Purely technical SWE roles: OMIT.
  NEVER place in experience array.

── VOLUNTEERING (Perach) ─────────────────────────────────────────────────────
  DEFAULT: OMIT. Set "volunteering" to an empty string "".
  INCLUDE ONLY when ALL THREE conditions are met:
    1. The JD explicitly calls out mentoring, coaching, social impact, or
       community involvement as a stated requirement or strong preference.
    2. Including it would add a keyword or signal NOT already covered by
       experience or education.
    3. You have enough sidebar space after skills, languages, and military.
  When included: exactly ONE sentence, 120 chars maximum:
    "Perach Project: personal mentor to a student from a disadvantaged background."
  If you are uncertain whether to include it: omit it.

═══════════════════════════════════════
NARRATIVE RULES BY JD TYPE
═══════════════════════════════════════

CUSTOMER SUCCESS JDs — strict narrative lockdown:
  ALLOW: B2B onboarding, partner retention, account health metrics, escalation
    resolution, renewal ownership, voice of customer, 24/7 operational support,
    client portfolio management, relationship ownership, cross-functional coordination.
  STRICTLY FORBID IN CS ROLES: PRD authorship, Python, SQL, roadmap work,
    product strategy bullets. These signals CONFUSE the CS narrative and will
    hurt the candidate with a CS hiring manager.
  Write bullets as: "Managed / Resolved / Onboarded / Retained / Expanded /
    Handled / Coordinated" + concrete scope or measurable outcome.

PRODUCT MANAGER JDs:
  ALLOW: PRD authorship, cross-functional product ownership, data-driven
    decisions, SQL/Python for analysis, configuration of the domain tooling the
    profile actually names, stakeholder alignment, product strategy,
    roadmap input.
  DE-EMPHASIZE: pure customer support framing.

LEADERSHIP / TEAM LEAD JDs:
  FOREGROUND, taking each value from the profile rather than assuming one:
    headcount managed, scope spanning sites/regions/time zones, progression
    through successive roles at one employer (state the arc), hiring and
    performance management, and any evidence of sustained load — concurrent
    responsibilities, work alongside study — as the resilience narrative.

════════════════════════
SIGNAL SELECTION DOCTRINE
════════════════════════
For each section ask: "Which 1-3 facts give this hiring manager the highest
confidence that the candidate will succeed in THIS exact role?" Lead with those.
Each signal gets exactly one placement — where it has maximum impact.
Never repeat the same fact across multiple sections.

════════════════════════════════════════════════════
STEP 4 — METRICS EXTRACTION (run before writing)
════════════════════════════════════════════════════

Before writing a single bullet, scan ALL available data sources and build a
private metrics table. Pull every number, percentage, rate, volume, headcount,
duration, and dollar figure you can find:

  Sources (in priority order):
    1. SUPPLEMENTAL_ANSWERS — treat user-supplied numbers as authoritative.
       If the user wrote "cut churn by 18%", that exact figure goes in the bullet.
    2. CANDIDATE PROFILE — every explicit number already in the profile.
       Look for counts (clients, accounts, partners, reports, users), rates
       and percentages, volumes, durations, headcount, geographies, service
       levels, and currency figures.
    3. Derivable approximations — only when the source gives enough context to
       estimate honestly (e.g. "weekly syncs for 40+ partners over 18 months"
       = ~78 syncs). Never fabricate a number that has no source basis.

  Forbidden: inventing a metric with no evidence.
  Required:  every bullet that CAN carry a number MUST carry a number.
  If no number is available for a bullet, use concrete scope instead:
    "Managed the end-to-end process" → "Managed 4-stage onboarding process
     for every new event-organizer partner."

════════════════════════════════════════════════════════════════
KEYWORD INJECTION MANDATE — 80% Coverage Rule
════════════════════════════════════════════════════════════════

This is a hard constraint, not a suggestion. ATS systems match exact strings.

COVERAGE TARGET: ≥ 16 of your 20 extracted keywords (≥80%) must appear
verbatim in the final output (summary + experience bullets + skill items combined).

Rules:
  1. Use the JD's EXACT term — not a synonym, not a paraphrase, not a related word.
     "Customer Success" not "client relations" if the JD says "Customer Success".
     "Adoption" not "onboarding" if the JD says "Adoption".
     "B2B SaaS" not "software services" if the JD says "B2B SaaS".
     Character-for-character match matters: "QBRs" ≠ "quarterly business reviews".
  2. Skills section is a high-density injection point. Populate skill items
     with the JD's exact tool names and methodology labels — copy them verbatim
     from jd_structured.tools / jd_structured.requirements.
  3. The Professional Summary must contain the JD's core role descriptor and
     at least 3 additional keywords from the table. The summary is scanned first
     by every ATS — it must carry the highest keyword density of any section.
  4. Each experience bullet must carry at least 1 keyword from K1-K20. Bullets
     for the highest-scoring role must average 2 keywords each.
  5. Do not keyword-stuff — each injection must read naturally in context.
  6. After writing the full CV, run a self-audit: count how many K1-K20 terms
     appear verbatim in the output. If fewer than 16, revise underperforming
     sections (summary first, then skills, then top-role bullets) before finalising.

════════════════════════════════════════════════════════════════
TERMINOLOGY BRIDGING — Reframe Candidate Vocabulary to JD Vocabulary
════════════════════════════════════════════════════════════════

When the candidate's profile uses a different term for the same concept the
JD requires, bridge it. The experience must be real — never fabricate the
underlying activity. Only the vocabulary changes.

Bridge protocol:
  1. Identify: [Candidate Term] → [JD Term]
  2. Rewrite the bullet to use the JD term as the primary label.
  3. Valid only when the candidate genuinely performed the mapped activity.

Validated bridge patterns (apply analogously to the actual JD):
  "Client Onboarding"      → "Customer Adoption"           (if JD says "adoption")
  "Partner Support"        → "Post-Sales Success"          (if JD says "post-sales")
  "Account Check-ins"      → "Executive Business Reviews"  (if JD says "EBRs")
  "Account Monitoring"     → "Customer Health Scoring"     (if JD uses "health score")
  "Escalation Handling"    → "Risk Mitigation"             (if JD says "risk")
  "Client Portfolio Mgmt"  → "ARR Management"              (if JD uses "ARR")
  "Team Coordination"      → "Cross-Functional Alignment"  (secondary framing only)
  "Usage Tracking"         → "Product Adoption Metrics"    (if JD uses "adoption")

Invalid bridges (fabrication — hard error):
  ✗ Saying the candidate "built a health-score model" when the profile shows only that he
    monitored accounts in a spreadsheet.
  ✗ Writing "managed $2M ARR book" when no revenue figure exists anywhere in
    the profile or SUPPLEMENTAL_ANSWERS.

═══════════════════════════════════════════════════════════
CRAFT RULES — BULLET EXCELLENCE (applied after Step 4)
═══════════════════════════════════════════════════════════

XYZ FRAMEWORK — mandatory for every bullet, zero exceptions:
Structure: "Accomplished [X] as measured by [Y], by doing [Z]"
  X = the concrete achievement (what changed, what was delivered)
  Y = the measurable proof  (a number, %, rate, volume, or verifiable scope)
  Z = the specific method   (the action the candidate took — not a vague verb)

The three elements must all be present. Phrasing must be natural — do not
write the labels literally. Test each bullet against this checklist:
  [ ] Does it name a specific achievement, not just a responsibility?
  [ ] Does it contain a number, percentage, volume, or concrete scope (Y)?
  [ ] Does it name the specific action taken, not a category of action (Z)?
  [ ] Is it free of passive voice?  (see PASSIVE VOICE BAN below)
  [ ] Does it open with an active verb from the approved list?

GOOD — study the SHAPE, never the values. These are drawn from an unrelated
domain on purpose: the numbers below belong to no one and must never appear in
your output. Every figure you write comes from THIS candidate's profile.
  "Cut warehouse pick errors by 22% across four distribution sites by
   rewriting the scan-verification step operators had been skipping."
  "Held 98% on-time dispatch through peak season by rebuilding the driver
   rota around historical volume instead of headcount."
  "Grew repeat orders 31% YoY by moving the reorder prompt from email to the
   delivery confirmation SMS."

BAD — forbidden for these specific reasons:
  "Managed client relationships and improved satisfaction."
    → No number (Y missing). "Improved" is not a measurement.
  "Was responsible for overseeing the support queue."
    → Passive voice. No achievement. No number. No method.
  "Helped drive cross-functional alignment to improve partner outcomes."
    → Banned verb "drive". No measurement. Passive responsibility framing.

PASSIVE VOICE BAN — absolute, no exceptions:
Never write a bullet that begins with or relies on:
  "Was responsible for", "Was tasked with", "Helped to", "Assisted in",
  "Supported the team", "Contributed to", "Involved in", "Part of".
These phrases describe a job description, not an achievement.
Every bullet must begin with an active verb that names the candidate's direct action.

SUMMARY RULES — same standards apply:
The professional summary is not exempt from the XYZ discipline.
It must contain at least one concrete number from the metrics table.
It cannot open with "I am" or a passive construction.
It must name the candidate's clearest quantified strength in the first sentence.

AUTHENTIC STORYTELLING:
Write like a sharp professional explaining their actual experience to a colleague
who is also an industry expert. Grounded, direct, specific. Tell the story:
what was the problem, what did the candidate do, what measurably changed.
When drawing on SUPPLEMENTAL_ANSWERS, always embed the number the user gave —
never paraphrase it into a vague adjective.
Rich multi-clause bullets (up to 240 chars) are preferred when the fuller
context makes the achievement more compelling and specific. The primary role
should demonstrate depth: 4-6 strong bullets, not 2-3 thin ones.

Weak (forbidden):
  "Orchestrated seamless cross-functional alignment to drive partner success."
Strong (required) — again, shape only; these values are not this candidate's:
  "Ran weekly syncs between planning, ops, and finance to keep 40+ suppliers
   unblocked through the pre-holiday surge."

DEPTH OVER PADDING:
4-6 metrics-grounded, story-driven bullets for the primary role demonstrate
professional depth. Do not default to 2-3 bullets when more genuine achievements
exist — brevity is not a virtue when it erases impact.
Never pad with weak or repetitive bullets to hit a count; every bullet must
contribute a unique, verifiable facet of the candidate's experience.

════════════════════════════════════════════════════════════════
STEP 5 — FINAL KEYWORD AUDIT  (mandatory before outputting JSON)
════════════════════════════════════════════════════════════════

After drafting the complete cv_data object, run TWO audits silently:

AUDIT A — Entity gap term compliance:
  For each VERIFIED entity in ENTITY_INTELLIGENCE:
    a. Identify the experience entry for that employer in the draft.
    b. Count how many of the entity's cv_vocabulary_gap terms appear
       verbatim anywhere in that entry's bullets.
    c. If the count < 3:
         — List the missing gap terms.
         — For each, find or rewrite the weakest bullet in that entry to
           include the term naturally, preserving the XYZ structure.
         — Re-check. Repeat until ≥ 3 gap terms are present per entity.
    d. If the entity was excluded from experience (e.g., for PM/SWE JDs),
       SKIP this audit for that entity — no bullets exist to target.

AUDIT B — JD keyword coverage:
  1. Re-read your KEYWORD TABLE from STEP 0.
  2. For all 15 keywords (K1..K15), scan summary, bullets, and skill items.
  3. Tally: injected_count / 15.
  4. If injected_count < 12 (< 80%):
       — Identify the missing keywords.
       — For each, find the bullet or summary sentence where it fits most
         naturally and revise it to incorporate the term.
       — Re-check until ≥ 12 / 15 are present.
  5. Note: K1..K5 (entity-mandated) should already be covered by Audit A.
     If any K1..K5 term is still missing after Audit A, treat it as a
     critical failure and force it into the summary or skills section.

Only after BOTH audits pass: output the final JSON.

The keyword table, tally, and audit transcript are NEVER included in the
output. Output ONLY the JSON object — no prose, no markdown fences.

═══════════════════════════════════════════════════════════════
MILITARY SERVICE — TRANSLATE THE FUNCTION, NOT THE RANK
═══════════════════════════════════════════════════════════════
Israeli candidates served, and for many the service is where they first led
people, owned a system, or carried real budget responsibility. On an Israeli CV
it is substantive early-career experience, not a footnote.

The failure to avoid is literal translation. A real example from this system's
own output: "Clerk to Lieutenant Colonel". To a non-Israeli reader that says
"administrative assistant"; to an Israeli reader it says the writer did not
know how to present themselves. Both readings undersell the candidate.

Translate WHAT THE ROLE DID in the vocabulary the target JD uses:

  Literal (wrong)              Functional (right)
  ---------------------------  ------------------------------------------
  Clerk to Lieutenant Colonel  Staff operations for a battalion commander
  Mashakit Tash                Personnel welfare coordinator, 150+ soldiers
  Rasar / Samal Rishon         Operations NCO — logistics and readiness
  Officer in the Signal Corps  Communications systems lead
  Combat medic                 Emergency response under operational pressure
  Intelligence analyst         Intelligence analysis and reporting

RULES:
  • role_title states the FUNCTION in business language. Never a transliterated
    Hebrew rank, never a bare rank on its own.
  • unit_type may keep the real unit name — it is a factual identifier, and
    Israeli recruiters read it. Do not invent a "translation" of a unit.
  • key_responsibilities: only when the service is genuinely load-bearing —
    a recent graduate, a career-changer, or a JD asking for operational
    leadership. A candidate with ten years of civilian experience does not
    need them, and the page budget is better spent on recent work.
  • Scale is the most transferable signal there is: headcount supervised,
    systems owned, budget held. Use the number from the profile. NEVER invent
    one — an invented headcount is a lie on a CV, and the reader may well ask
    about it in the interview.
  • Never militarise the language ("commanded", "deployed", "executed
    missions"). Write it the way a civilian hiring manager reads.

══════════════════════════════
OUTPUT FORMAT — JSON ONLY
══════════════════════════════
No markdown fences. No prose. Only the JSON object.

STRUCTURAL CONTRACT (authoritative — generated from backend/models/cv.py):
Your output is validated against this JSON Schema. A response that violates it
is rejected outright, so treat field names, types and maxLength as hard
constraints rather than suggestions. The annotated template below restates the
same structure with the editorial rules that the schema alone cannot express;
where the two ever appear to disagree, the schema wins on STRUCTURE and the
template wins on WRITING QUALITY.

Note there is no contact/header block to fill in: name, email, phone, location
and LinkedIn are injected from the candidate's verified profile after you
finish. Never emit them, and never invent them.

{schema}

{{
  "type": "cv",
  "cv_data": {{
    "header": {{
      "target_title": "<role-specific positioning, <=58 chars. What the candidate IS, not what \
they are applying for. This is the ONLY header field you may write — name, email, phone, \
location and LinkedIn are injected from the verified profile and must be omitted.>"
    }},

    "summary": "<<=360 chars. 2-3 sentences. MUST contain at least one concrete \
number sourced from the metrics table (Step 4). Opens with the candidate's clearest quantified \
strength for THIS role — never with 'I am' or a passive clause. Second sentence adds \
a differentiated proof point. Closes with a forward-looking signal that mirrors JD \
language. Ends with a full stop. No banned verbs, no hollow adverbs.>",

    "experience": [
      {{
        "role":    "<string <=45 chars>",
        "company": "<string <=35 chars>",
        "dates":   "<YYYY - YYYY or YYYY - Present, copied exactly from profile, <=22 chars>",
        "bullets": [
          "<XYZ bullet, 55-240 chars. Opens with a strong action verb. \
Follows the XYZ structure: achievement + measurable proof + method. \
Rich, story-driven bullets up to 240 chars are preferred over short, thin ones. \
NEVER ends with a preposition, article, or incomplete phrase. \
Primary (most recent) role: 4-6 bullets showcasing full professional depth. \
Supporting roles: 2-3 focused bullets. Never pad with weak bullets to hit a count.>",
          "<XYZ bullet 55-240 chars>",
          "<XYZ bullet 55-240 chars>"
        ]
      }}
    ],

    "education": [
      {{
        "degree":      "<string <=60 chars — copy exactly from profile>",
        "institution": "<string <=35 chars — copy exactly from profile>",
        "dates":       "<copied exactly from profile, <=20 chars>",
        "honors":      "<FACTUAL HONORS ONLY <=60 chars: 'Dean's List', 'GPA: X.X', \
'Graduated with Distinction'. NEVER add contextual commentary, personal narrative, \
or circumstantial notes (e.g., do NOT append the circumstances under which a
credential was earned, such as 'while working full-time', or \
'achieved while employed full-time'). Credential record only. Empty string if none.>",
        "coursework":  "<string <=80 chars — only courses directly relevant to THIS JD, or empty>"
      }}
    ],

    "military_service": {{
      "role_title":           "<string <=45 chars; use null for the whole object if not including>",
      "unit_type":            "<string <=60 chars>",
      "dates":                "<copied exactly from profile, <=20 chars>",
      "key_responsibilities": ["<optional XYZ-style scope line, same discipline as experience bullets>"]
    }},

    "skills": {{
      "categories": [
        {{
          "label": "<category <=20 chars — mirrors JD language, never ends in '&' or 'and'>",
          "items": ["<skill <=25 chars, max 6 per category>"]
        }}
      ]
    }},

    "languages": [
      {{"language": "<string <=20 chars>", "level": "<EXACTLY ONE of: Native, Fluent, \
Professional Working, Limited Working, Elementary — never combine two levels into one \
string (e.g. never 'Native / Full Professional' or 'Native, Fluent')>"}}
    ],

    "volunteering": "<string <=120 chars — 1 sentence max. Perach framed as a professional \
asset. Full stop at end. Empty string if not including.>"
  }}
}}

═══════════════════════════════════════════════════════════════
LANGUAGE & TONE — ABSOLUTE RULES (violations = disqualification)
═══════════════════════════════════════════════════════════════
1. Write like a confident industry professional, not an AI assistant.

2. ATS AI-TELL BAN — em-dashes and en-dashes are the #1 automated signal
   that a CV was AI-generated. Advanced ATS systems and recruiters use these
   as a filter to auto-reject AI submissions before a human ever reads them.
   ABSOLUTE BAN: em-dash (—) and en-dash (–).
   ALLOWED separators: standard keyboard hyphen (-) or pipe (|) ONLY.
   Before outputting: do a final scan and replace every — or – with -.

3. BANNED VERBS — hollow, vague, or robotic. Each is a hard error:
   spearheaded, orchestrated, navigated, harnessed, leveraged, championed,
   pioneered, fostered, catalyzed, synergized, utilized, surfaced,
   drove alignment, transformed, revolutionized, optimized, streamlined,
   enabled, empowered, facilitated, executed, delivered upon, ensured,
   oversaw (as the only verb).
   EACH BANNED VERB MUST BE REPLACED with one that names the exact action:
     spearheaded → led / launched / built
     orchestrated → managed / coordinated / ran
     navigated → handled / managed / worked through
     harnessed → used / applied / ran
     leveraged → used / applied / ran / worked with
     facilitated → ran / chaired / coordinated
     ensured → confirmed / checked / enforced
     executed → completed / ran / shipped / processed
     delivered upon → met / hit / completed
     oversaw → managed / reviewed / approved
   USE THESE — concrete verbs that name the actual action:
   led, built, ran, grew, managed, cut, shipped, closed, resolved, launched,
   trained, reduced, handled, completed, expanded, coordinated, wrote, reviewed,
   configured, onboarded, retained, negotiated, designed, set up, rolled out,
   restructured, automated, audited, authored, hired, coached, escalated.
   Vary verbs across bullets — never repeat the same opening verb within a role.

4. BANNED hollow adverbs: effectively, successfully, proactively, seamlessly,
   collaboratively, impactfully, strategically (as a standalone qualifier).
   Delete them entirely — they add zero signal.

5. BANNED AI TELLS — words and phrases that flag machine-generated text.
   These are fingerprints that ATS filters and recruiters recognise instantly:
   BANNED WORDS: delve, testament, paramount, meticulous, meticulously,
   transformative, underscore, embark, pivotal, commendable, laudable,
   intricate, nuanced, synergy, synergies.
   BANNED PHRASES:
   "surfaced insights", "guided decisions", "impactful solutions",
   "cross-functional synergies", "actionable outcomes", "customer-centric",
   "end-to-end ownership", "key stakeholders", "best practices",
   "value-add", "thought leadership", "robust", "holistic", "scalable solution",
   "drove meaningful results", "created alignment", "testament to",
   "delve into", "embark on", "in today's landscape", "it is worth noting".
   USE PLAIN LANGUAGE INSTEAD:
   "Managed portfolio of X" not "drove meaningful client outcomes"
   "Resolved Tier-1 escalations" not "facilitated issue resolution"
   "Onboarded 20 partners" not "onboarded key stakeholders"
   "Reduced churn by Y%" not "drove retention through a customer-centric approach"

6. Numbers and scope beat adjectives — every time, no exceptions.
   A stated count outperforms "large portfolio".
   A stated headcount outperforms "a team of people".
   A stated percentage outperforms "significantly improved".
   Take the value from the profile — never invent one to fill the pattern.
   If the profile or SUPPLEMENTAL_ANSWERS contains a number, that number is mandatory.

7. Bullets: specific, direct, no padding. Sound like a professional who wrote
   this under time pressure. Every word earns its place.

7b. CROSS-BULLET REPETITION BAN — hard error, same weight as a banned verb:
    Never repeat the same phrase, clause, or qualifying context across different
    bullets, even across different employers.
    EXAMPLES of banned repetition:
      ✗ Two bullets both ending "...with no dedicated sales support"
      ✗ Two bullets both opening "Managed portfolio of..."
      ✗ The same metric appearing in two separate bullets
    Each bullet must express a UNIQUE facet of the candidate's experience.
    If you find yourself reusing a phrase: rewrite one of the bullets to
    surface a different achievement, scope, or method entirely.

8. SELF-AUDIT before finalizing output — for every bullet, confirm:
   (a) Active verb opens the bullet (not passive, not banned).
   (b) A concrete number or verifiable scope is present (Y element of XYZ).
   (c) The method used is named specifically (Z element of XYZ).
   (d) ENTITY GAP COMPLIANCE: STEP 5 Audit A passes — each included VERIFIED
       employer's bullets contain ≥ 3 of that entity's cv_vocabulary_gap terms.
   (e) JD KEYWORD COVERAGE: STEP 5 Audit B passes — ≥ 12/15 keywords present.
   (f) AI TELLS SCAN: search every bullet and the summary for — – spearheaded
       orchestrated navigated harnessed delve testament paramount meticulous
       transformative synergy. Replace any found before outputting.
   If any bullet fails (a), (b), or (c): rewrite it before outputting.
   If (d) fails: revise that employer's weakest bullet to inject the missing gap terms.
   If (e) fails: identify and inject missing JD keywords as per STEP 5 Audit B.
   If (f) fails: replace the flagged word/character before outputting.
"""


# ── Post-hoc limit enforcement ────────────────────────────────────────────────

def _clip(val: object, limit: int) -> str:
    return str(val or "")[:limit]


_DANGLING = frozenset({
    "a", "an", "the",
    "of", "for", "to", "in", "on", "at", "by", "as", "or", "and",
    "with", "from", "into", "onto", "upon", "under", "over", "across",
    "within", "between", "through", "during", "against", "toward",
})


def _clip_word(val: object, limit: int) -> str:
    text = str(val or "")
    if len(text) <= limit:
        result = text
    else:
        truncated = text[:limit]
        boundary  = truncated.rfind(" ")
        result    = truncated[:boundary].rstrip(" .,;:") if boundary > 0 else truncated
    for _ in range(3):
        last = result.rsplit(" ", 1)
        if len(last) == 2 and last[-1].lower().rstrip(".,;:") in _DANGLING:
            result = last[0].rstrip(" .,;:")
        else:
            break
    return result


def _clip_sentence(val: object, limit: int) -> str:
    text = str(val or "")
    if len(text) <= limit:
        return text
    window = text[:limit]
    for i in range(len(window) - 1, max(len(window) - 100, 0), -1):
        if window[i] in ".!?":
            return window[:i + 1]
    for i in range(len(window) - 1, max(len(window) - 100, 0), -1):
        if window[i] == ";":
            return window[:i + 1]
    clipped = _clip_word(text, limit)
    return clipped if clipped.endswith((".", "!", "?", ";")) else clipped + "."


# Canonical, mutually-exclusive language proficiency levels, checked in this
# priority order. The prompt instructs the LLM to emit exactly one of these,
# but that's not guaranteed — this is the defense-in-depth backstop that
# collapses a non-compliant combined string (e.g. "Native / Full
# Professional", "Native, Fluent") down to the single highest claim it
# contains, so the rendered CV never shows two contradictory levels for one
# language.
_LANGUAGE_LEVEL_KEYWORDS: list[tuple[str, str]] = [
    ("native",       "Native"),
    ("fluent",       "Fluent"),
    ("professional", "Professional Working"),
    ("limited",      "Limited Working"),
    ("elementary",   "Elementary"),
    ("basic",        "Elementary"),
]


def _normalize_language_level(raw: str) -> str:
    text = (raw or "").strip().lower()
    if not text:
        return ""
    for keyword, canonical in _LANGUAGE_LEVEL_KEYWORDS:
        if keyword in text:
            return canonical
    return (raw or "").strip()


def validate_cv_schema(data: dict, *, context: str = "tailor") -> dict:
    """
    Normalise a CV payload to the canonical CVDataSchema shape.

    Every CV entering the pipeline passes through here, so everything
    downstream — _enforce_limits, _inject_static_sections, pdf_builder,
    copilot, the frontend — reads `header.target_title` and `military_service`
    only, and never has to know the legacy `title`/`military` shape existed.
    Documents already stored in that older shape are converted on read rather
    than migrated (see backend/models/cv.py).

    Non-fatal by design: a payload that cannot be validated is passed through
    untouched rather than discarded. A schema violation means the CV is unusual,
    not that the user should lose a generation they waited 30 seconds for, and
    the renderer already degrades field-by-field on missing keys.
    """
    return normalize_cv(data, context=context)


def _enforce_limits(data: dict) -> dict:
    header = data.get("header")
    header = dict(header) if isinstance(header, dict) else {}
    header["target_title"] = _clip_word(header.get("target_title"), _LIM["title"])
    data["header"]         = header
    data["summary"]      = _clip_sentence(data.get("summary"),  _LIM["summary"])
    data["volunteering"] = _clip_sentence(data.get("volunteering"), _LIM["volunteering"])

    clamped_exp = []
    for idx, e in enumerate((data.get("experience") or [])[:5]):
        # Primary (most recent) role: max 4 bullets for single-page A4 fit.
        # Supporting roles: max 3 bullets — 2 was too thin to convey real
        # leadership depth for candidates with multiple substantial roles at
        # one employer (e.g. sequential promotions); still short enough to
        # protect the single-page fit given exp_bullet's 240-char cap.
        max_bullets = 4 if idx == 0 else 3
        clamped_exp.append({
            "role":    _clip_word(e.get("role"),    _LIM["exp_role"]),
            "company": _clip_word(e.get("company"), _LIM["exp_company"]),
            "dates":   _clip(e.get("dates"),        _LIM["exp_dates"]),
            # Bullets: no hard character slicing — let the LLM own length.
            # Hard slicing produces mid-word truncation ("writing technica…").
            # _LIM["exp_bullet"] is a prompt guideline only; if the LLM
            # produces 250 chars, the sentence is preserved intact.
            "bullets": [
                str(b or "")
                for b in (e.get("bullets") or [])[:max_bullets]
            ],
        })
    data["experience"] = clamped_exp

    clamped_edu = []
    for e in (data.get("education") or [])[:3]:
        clamped_edu.append({
            "degree":      _clip_word(e.get("degree"),      _LIM["edu_degree"]),
            "institution": _clip_word(e.get("institution"), _LIM["edu_inst"]),
            "dates":       _clip(e.get("dates"),             _LIM["edu_dates"]),
            "honors":      _clip_word(e.get("honors"),      _LIM["edu_honors"]),
            "coursework":  _clip_word(e.get("coursework"),  _LIM["edu_course"]),
        })
    data["education"] = clamped_edu

    mil = data.get("military_service") or {}
    if mil.get("role_title"):
        data["military_service"] = {
            "role_title": _clip_word(mil.get("role_title"), _LIM["mil_role"]),
            "unit_type":  _clip_word(mil.get("unit_type"),  _LIM["mil_unit"]),
            "dates":      _clip(mil.get("dates"),           _LIM["mil_dates"]),
            # Not clipped as a block: each line is an independent scope
            # statement, and truncating the list mid-way is better than
            # truncating one line mid-sentence.
            "key_responsibilities": [
                str(r or "") for r in (mil.get("key_responsibilities") or [])[:3]
            ],
        }
    else:
        # None, not {} — an empty object validates into a present-but-blank
        # section and renders a bare "Military Service" heading.
        data["military_service"] = None

    skills       = data.get("skills") or {}
    clamped_cats = []
    for cat in (skills.get("categories") or [])[:4]:
        label = _clip_word(cat.get("label"), _LIM["skill_label"])
        label = label.rstrip("& ").rstrip("and ").rstrip("or ").strip()
        clamped_cats.append({
            "label": label,
            "items": [
                _clip_word(s, _LIM["skill_item"])
                for s in (cat.get("items") or [])[:6]
            ],
        })
    data["skills"] = {"categories": clamped_cats}

    data["languages"] = [
        {
            "language": _clip_word(lang.get("language"), _LIM["lang_name"]),
            "level":    _clip_word(_normalize_language_level(lang.get("level")), _LIM["lang_level"]),
        }
        for lang in (data.get("languages") or [])[:5]
    ]

    return data


# ── Profile resolution (multi-tenant) ────────────────────────────────────────

# Every post-processing helper below used to read the module-level USER_PROFILE
# singleton directly. That dict is LEGACY SINGLE-USER data valid only for
# user_id='default' — for a real account it silently substituted a different,
# thinner profile into the CV (wrong education, wrong skills, wrong military
# block). Resolve through here instead so the active user's DB profile is the
# single source of truth.
#
# 'default' keeps the legacy singleton verbatim so pre-migration dev paths and
# the existing tests are unaffected.


# Shared with the researcher agent — see services/user_profile.resolve_profile.
_resolve_profile = resolve_profile


# JOB-121: was a flat [:12], tuned for the legacy singleton's 6-skill profile.
# Real DB profiles run well past that (e.g. 36 skills for one real account) —
# raised to a cap that still respects the CV's fixed A4 page (see
# _build_skills in pdf_builder.py, which this must stay in lock-step with:
# raising one without the other either leaves the extra skills silently
# re-truncated downstream, or renders more than this function ever selected).
_SKILLS_CAP = 20


def _rank_skills_by_jd_relevance(
    skills: list[str],
    jd_text: str,
    synonyms: Optional[dict[str, list[str]]] = None,
) -> list[str]:
    """
    Stable-sort skills so JD-relevant ones come first. Never drops a skill —
    only reorders — so a downstream cap keeps the most useful ones instead of
    whichever happened to be listed first in the profile. A skill counts as
    relevant if it — OR any of its known synonyms/canonical name, when
    `synonyms` is given — appears, word-boundary and case-insensitive,
    anywhere in the JD text. No jd_text (e.g. a thin/un-hydrated JD) leaves
    the original profile order untouched — there's nothing to rank against.

    synonyms (JOB-138: global skills taxonomy): optional {skill_display_name:
    [alternate forms]} map, e.g. {"React": ["ReactJS", "React.js"]} — a JD
    that says "ReactJS" now credits a profile skill stored as "React". Kept
    as a plain dict-in, no DB access here on purpose: this function stays a
    pure, synchronously-testable string operation; whoever has the taxonomy
    connection (_inject_static_sections) builds the map and passes it in.
    """
    if not jd_text:
        return list(skills)
    jd_lower = jd_text.lower()
    synonyms = synonyms or {}

    def _is_relevant(skill) -> bool:
        s = str(skill).strip()
        if not s:
            return False
        forms = [s] + list(synonyms.get(s, []))
        return any(
            re.search(rf"\b{re.escape(f.strip().lower())}\b", jd_lower) is not None
            for f in forms if f and f.strip()
        )

    # sorted() is stable — within each relevance bucket, original profile
    # order (e.g. however the user or profile_entities ordered them) holds.
    return sorted(skills, key=lambda s: not _is_relevant(s))


def _build_skill_synonym_map(skill_names: list[str]) -> dict[str, list[str]]:
    """
    {profile skill display name: [its canonical name + taxonomy synonyms]},
    for every name in skill_names that resolves to a skills_taxonomy row.

    Best-effort and silent on failure — this only affects ranking quality
    (a JD-relevant skill sorts earlier), never correctness, so a DB hiccup
    here must not break CV generation. Skipped entirely on SQLite (no
    skills_taxonomy table there — see skills_taxonomy_service's module
    docstring) since _rank_skills_by_jd_relevance already degrades cleanly
    with an empty map (falls back to exact-name matching only).
    """
    mapping: dict[str, list[str]] = {}
    try:
        from backend.core.database import ENGINE
        if ENGINE.dialect.name != "postgresql":
            return {}
        from sqlalchemy import text as _sql
        with ENGINE.connect() as conn:
            for skill_name in skill_names:
                row = conn.execute(_sql("""
                    SELECT canonical_name, synonyms FROM public.skills_taxonomy
                    WHERE lower(canonical_name) = lower(:name)
                       OR lower(:name) = ANY(SELECT lower(s) FROM unnest(synonyms) AS s)
                """), {"name": str(skill_name).strip()}).fetchone()
                if row is not None:
                    forms = [row.canonical_name] + list(row.synonyms or [])
                    mapping[skill_name] = [f for f in forms if f]
    except Exception:
        logger.debug("[tailor] skill synonym lookup failed — ranking falls back to exact-name match", exc_info=True)
        return {}
    return mapping


# ── Static section injection ─────────────────────────────────────────────────

def _inject_static_sections(
    data: dict,
    respect_deletions: bool = False,
    *,
    user_id: str,
    jd_text: str = "",
) -> dict:
    """
    Overwrite Education, Skills, and Military with the canonical values from
    the ACTIVE USER's profile — verbatim, every time, after the LLM has
    generated cv_data.

    This guarantees these sections are never omitted, truncated, or reordered
    by the model no matter what the JD contains.  Education and Military are
    structural facts (degree, dates, unit) that must never be hallucinated or
    dropped.  Skills are injected from the verified list so the model cannot
    introduce aspirational or incorrect skill claims.

    user_id selects the source profile (see _resolve_profile). Passing a real
    user_id is REQUIRED for multi-tenant correctness — the previous
    unconditional USER_PROFILE read injected the legacy singleton's education,
    skills and military block into every user's CV.

    jd_text (optional): when given, skills are ranked by JD relevance before
    _SKILLS_CAP is applied (see _rank_skills_by_jd_relevance) — a profile with
    more skills than fit on one page gets the JD-relevant ones kept, not just
    whichever were listed first. Omitted or empty leaves profile order as-is.

    Field-name mapping (profile → cv_data template keys) — both the legacy
    singleton's and the DB profile's spellings are accepted:
      education: school|institution → institution | period|year → dates
                 | status → honors
      military:  found in experience[] entries that have a "unit" key but no
                 "company". The DB profile has no such entries (military shows
                 up as an ordinary company), so real users get no military
                 sidebar — which is correct, it isn't their data to inject.
      skills:    flat list → {categories: [{label, items}]}

    When a section is EMPTY in the resolved profile, it is left as the LLM
    produced it rather than being back-filled from the legacy singleton.
    Back-filling is what corrupted real users' CVs; and since a real user's
    prompt is built from that same (education-less) profile, the model has no
    source to invent one from either.

    The function is intentionally non-destructive of experience / summary so
    the tailored parts of the CV are preserved untouched.

    respect_deletions: when True (used by the Copilot edit path), an explicit
    null / empty-array value already present in `data` for one of these keys
    is treated as an intentional user deletion and is NOT overwritten with the
    Master Profile's canonical value. A key that is simply absent from `data`
    is still treated as an accidental omission and gets re-injected as before
    — the CopilotAgent's system prompt requires it to emit an explicit
    null/[] for deletions, so absence still means "the model forgot it."
    The tailoring pipeline (fresh cv_data generation, refine) calls this with
    the default `respect_deletions=False` and always gets full injection.
    """
    def _explicitly_deleted(key: str) -> bool:
        if not respect_deletions or key not in data:
            return False
        value = data.get(key)
        if isinstance(value, dict):
            # "skills" comes back as {"categories": [...]} — an empty or
            # missing "categories" list means the model deleted it, even
            # though the outer dict itself is non-empty (and thus truthy).
            if key == "skills":
                return not value.get("categories")
            return len(value) == 0
        return not value

    profile = _resolve_profile(user_id)

    # ── Education ─────────────────────────────────────────────────────────────
    if not _explicitly_deleted("education"):
        profile_edu = profile.get("education") or []
        if profile_edu:
            canonical_edu = []
            for e in profile_edu:
                if not isinstance(e, dict):
                    continue
                if e.get("degree"):
                    # Standard degree entry. The DB profile spells these
                    # institution/year; the legacy singleton school/period.
                    canonical_edu.append({
                        "degree":      e.get("degree", ""),
                        "institution": e.get("school") or e.get("institution", ""),
                        "dates":       e.get("period") or e.get("dates") or e.get("year", ""),
                        "honors":      e.get("status") or e.get("honors", ""),
                        "coursework":  e.get("coursework") or e.get("field", ""),
                    })
                elif e.get("certification"):
                    # Certification entry — render as degree row
                    canonical_edu.append({
                        "degree":      e.get("certification", ""),
                        "institution": e.get("provider") or e.get("institution", ""),
                        "dates":       e.get("period") or e.get("dates") or e.get("year", ""),
                        "honors":      e.get("status") or e.get("honors", ""),
                        "coursework":  e.get("details") or e.get("coursework", ""),
                    })
            if canonical_edu:
                data["education"] = canonical_edu
        else:
            logger.info(
                "[tailor] user=%s has no education in their DB profile — leaving the "
                "CV's education section as generated (no legacy back-fill).",
                user_id,
            )

    # ── Military ──────────────────────────────────────────────────────────────
    # Military entries in the legacy singleton's experience[] have a "unit" key
    # but no "company" key — that's the reliable discriminator. The DB profile
    # never produces such entries, so this is a no-op for real users.
    if not _explicitly_deleted("military_service"):
        for exp in profile.get("experience", []):
            if exp.get("unit") and not exp.get("company"):
                data["military_service"] = {
                    "role_title": exp.get("role", ""),
                    "unit_type":  exp.get("unit", ""),
                    "dates":      exp.get("period") or exp.get("dates", ""),
                    "key_responsibilities": [],
                }
                break  # only one military entry expected
    else:
        data["military_service"] = None

    # ── Skills ────────────────────────────────────────────────────────────────
    if not _explicitly_deleted("skills"):
        profile_skills = profile.get("skills") or []
        if profile_skills:
            if isinstance(profile_skills, list):
                # Flat list of strings → rank by JD relevance, then pack into
                # a single category, capped to fit the page (JOB-121).
                synonym_map = _build_skill_synonym_map(profile_skills) if jd_text else {}
                ranked = _rank_skills_by_jd_relevance(profile_skills, jd_text, synonym_map)
                data["skills"] = {
                    "categories": [
                        {
                            "label": "Core Skills",
                            "items": [str(s) for s in ranked[:_SKILLS_CAP]],
                        }
                    ]
                }
            elif isinstance(profile_skills, dict):
                # Already in {categories: [...]} format — use as-is
                data["skills"] = profile_skills

    return data


# ── All-employer enforcement (mechanical safety net) ─────────────────────────

def _norm_company(name: str) -> str:
    """Strip parenthetical suffixes and lower-case for fuzzy comparison."""
    return re.sub(r'\s*\(.*?\)', '', name or "").strip().lower()


def _required_profile_employers(user_id: str) -> list[dict]:
    """
    Return every non-military employer for user_id that must produce an
    experience entry in the final cv_data.

    Employers are de-duplicated by normalised name, keeping the FIRST
    occurrence. The DB profile stores one row per role, so a multi-role
    employer (one with several roles, so several rows) would otherwise be
    demanded once per row; the
    profile is most-recent-first, so the first row carries the current title.
    """
    profile = _resolve_profile(user_id)

    required: list[dict] = []
    seen: set[str] = set()
    for exp in profile.get("experience", []):
        company = exp.get("company", "")
        if not company:
            continue  # military entry uses "unit", not "company"
        c_norm = _norm_company(company)
        if c_norm in seen:
            continue
        seen.add(c_norm)
        # The legacy singleton nests sequential promotions under "roles";
        # the DB profile is flat. Take the most recent title either way.
        if exp.get("roles"):
            role = exp["roles"][0].get("title", "")
        else:
            role = exp.get("role", "")
        required.append({
            "company": company,
            "role":    role,
            "period":  exp.get("period", ""),
        })
    return required


def _get_profile_stub(company: str, user_id: str) -> str:
    """
    Extract a single-sentence stub bullet from user_id's profile for a company
    that was dropped by the LLM.  Used only as a safety-net placeholder —
    the next generation (with the fixed prompt) should produce proper bullets.
    """
    c_norm = _norm_company(company)
    for exp in _resolve_profile(user_id).get("experience", []):
        if _norm_company(exp.get("company", "")) != c_norm:
            continue
        # Multi-role entry (one employer, several titles): use the most
        # recent role's details.
        roles = exp.get("roles", [])
        raw = roles[0].get("details", "") if roles else exp.get("details", "")
        if raw:
            first = raw.split(".")[0].strip()
            if first:
                return (first + ".")[:_LIM["exp_bullet"]]
    return ""


def _enforce_all_employers(cv_data: dict, user_id: str) -> dict:
    """
    Guarantee every non-excluded employer from user_id's profile appears in
    cv_data["experience"].  Any that the LLM silently dropped are added
    back as a minimal stub entry — omitting an entire employer block is a
    harder error than a low-quality stub.

    NOT WIRED INTO THE PIPELINE — see the module docstring and the
    "EXPERIENCE SELECTION & REFRAMING" prompt section. The prompt deliberately
    instructs the model to select only the 3-4 highest-relevance roles and
    gives it an explicit DROP RULE for low-signal ones, so most omissions here
    are intentional, not silent failures. Calling this would append every
    dropped employer back as a bullet-less stub and defeat the one-page
    relevance selection. Kept (and kept correct) as a diagnostic helper.
    """
    required = _required_profile_employers(user_id)
    if not required:
        return cv_data

    experience = list(cv_data.get("experience") or [])
    present    = {_norm_company(e.get("company", "")) for e in experience}

    for req in required:
        if _norm_company(req["company"]) in present:
            continue
        logger.warning(
            "[enforce_all_employers] '%s' was silently dropped by LLM — inserting stub",
            req["company"],
        )
        stub = _get_profile_stub(req["company"], user_id)
        experience.append({
            "role":    _clip_word(req["role"] or "Professional", _LIM["exp_role"]),
            "company": _clip_word(req["company"],                _LIM["exp_company"]),
            "dates":   req["period"] or "",
            "bullets": [stub] if stub else [],
        })

    cv_data["experience"] = experience
    return cv_data


# ── AI-Tells sanitiser (deterministic post-hoc safety net) ───────────────────
# The prompt rules cover the vast majority of cases. This layer catches anything
# that slips through regardless of prompt compliance. Word list and em-dash
# handling live in ai_scrubber.py (imported above as _sanitize_str):
# outreach_service.py's clean_ai_text() needs the exact same rules, and having
# two copies is how the dash regex drifted out of sync there (it used to turn
# "--" INTO an em-dash instead of removing it).


def _sanitize_ai_tells(data: object) -> object:
    """Recursively walk cv_data and sanitise all string values in-place."""
    if isinstance(data, str):
        return _sanitize_str(data)
    if isinstance(data, list):
        return [_sanitize_ai_tells(item) for item in data]
    if isinstance(data, dict):
        return {k: _sanitize_ai_tells(v) for k, v in data.items()}
    return data


# ── Entity intelligence block ────────────────────────────────────────────────

def _build_entity_intelligence_block(user_id: str) -> str:
    """
    Load verified enriched entities for user_id from their master profile and
    format them as a compact intelligence block for injection into the
    TailorAgent user message.  Only includes entities that are verified and
    have a known domain.  Returns empty string if no enriched data is available.
    """
    try:
        from backend.services.master_profile_service import get_enriched_entities
        entities = get_enriched_entities(user_id)
    except Exception:
        return ""

    verified = [
        e for e in entities
        if e.get("verified") and e.get("domain") and e.get("domain") != "Unknown domain"
    ]
    if not verified:
        return ""

    lines = [
        "\nENTITY_INTELLIGENCE "
        "(externally verified — authoritative industry vocabulary for these employers):"
    ]
    for e in verified:
        name   = e.get("name", "")
        domain = e.get("domain", "")
        kws    = e.get("industry_keywords", [])
        gap    = e.get("cv_vocabulary_gap", [])

        lines.append(f"\n  [{name} | VERIFIED | {domain}]")
        if kws:
            lines.append(f"    Industry keywords: {', '.join(kws[:8])}")
        if gap:
            lines.append(
                f"    CV gap terms (highest-priority injection targets): "
                f"{', '.join(gap[:8])}"
            )

    return "\n".join(lines) + "\n"


# ── Core profile check ───────────────────────────────────────────────────────

_CORE_QUESTIONS = {
    "phone": {
        "id":       "core_phone",
        "question": "What is your phone number?",
        "context":  "Displayed in the CV header on every application.",
    },
    "location": {
        "id":       "core_location",
        "question": "What is your current city / location? (e.g. Tel Aviv, Israel)",
        "context":  "Shown in the CV header so hiring managers know your base.",
    },
}


def _core_profile_gaps(user_id: str) -> list[dict]:
    """
    Return missing_data requests for any essential personal fields that are
    still empty for user_id.  Runs before the LLM so we never waste a
    round-trip asking JD questions when basic header info is missing.

    Reads the ACTIVE user's profile: the previous unconditional USER_PROFILE
    read gated every account on the legacy singleton's contact details, so a
    real user with a complete profile could be blocked (or, as here, waved
    through) on the basis of someone else's data.
    """
    personal = _resolve_profile(user_id).get("personal", {}) or {}
    gaps: list[dict] = []
    for field, spec in _CORE_QUESTIONS.items():
        if not str(personal.get(field) or "").strip():
            gaps.append(spec)
    return gaps


# ── Agent ─────────────────────────────────────────────────────────────────────

class TailorAgent:
    def __init__(self, user_id: str) -> None:
        """
        user_id scopes EVERY profile read this agent makes — the prompt's
        profile blob, the core-field gate, entity intelligence, and the static
        section injection.
        """
        if not os.getenv("ANTHROPIC_API_KEY"):
            raise ValueError("ANTHROPIC_API_KEY not set")
        self.user_id = user_id

    async def tailor(
        self,
        job: JobMatch,
        supplemental_answers: Optional[dict] = None,
    ) -> dict:
        """
        Produce a tailored CV or a missing-data request for the given JobMatch.

        Returns either:
          {"type": "cv",           "cv_data": {...enforced dict...}}
          {"type": "missing_data", "requests": [{id, question, context}]}

        supplemental_answers: mapping of question-id -> user answer from a
          previous missing_data round.  Injected into the prompt so the model
          can proceed without re-asking answered questions.
        """
        # ── STEP 0: Core profile check (before touching the LLM) ────────────
        # If essential contact fields are empty we must collect them first.
        # These answers are saved directly to USER_PROFILE by the route layer
        # (not to supplemental_answers.json) so they populate the CV header
        # automatically on every future generation.
        core_gaps = _core_profile_gaps(self.user_id)
        if core_gaps:
            logger.info(
                "TailorAgent -> core_profile missing_data  user=%s  field(s): %s",
                self.user_id, [g["id"] for g in core_gaps],
            )
            return {"type": "missing_data", "requests": core_gaps}

        profile_text = build_full_text(self.user_id)
        system       = _SYSTEM_PROMPT.format(
            profile=profile_text,
            schema=CVDataSchema.llm_schema_hint(),
        )

        rationale_block = ""
        if job.scoring_rationale:
            rationale_block = (
                f"\nSCORING_RATIONALE (axis scores — use to weight emphasis):\n"
                f"{job.scoring_rationale}\n"
            )

        # Critical gaps and investigation points feed STEP 3 gap analysis directly.
        gaps_block = ""
        if job.detailed_analysis and job.detailed_analysis.critical_gaps:
            gaps = "\n".join(
                f"  • {g}" for g in job.detailed_analysis.critical_gaps
            )
            gaps_block = (
                f"\nCRITICAL_GAPS (identified during job scoring — primary input for Step 3):\n"
                f"{gaps}\n"
            )

        investigation_block = ""
        if job.investigation_points:
            points = "\n".join(
                f"  • {p}" for p in job.investigation_points
            )
            investigation_block = (
                f"\nINVESTIGATION_POINTS (flagged during screening — verify in Step 3):\n"
                f"{points}\n"
            )

        supplemental_block = ""
        if supplemental_answers:
            lines = "\n".join(
                f"  [{qid}]: {answer}"
                for qid, answer in supplemental_answers.items()
            )
            supplemental_block = (
                f"\nSUPPLEMENTAL_ANSWERS (user-provided — treat as authoritative "
                f"profile updates, do not re-ask these):\n{lines}\n"
            )

        entity_intelligence_block = _build_entity_intelligence_block(self.user_id)
        if entity_intelligence_block:
            logger.info(
                "[tailor] Entity intelligence injected: %d chars — preview: %s…",
                len(entity_intelligence_block),
                entity_intelligence_block.strip()[:120],
            )
        else:
            logger.info(
                "[tailor] Entity intelligence: no verified entities in master profile — "
                "run POST /api/profile/research to populate"
            )

        # Inject jd_structured as the primary keyword source.
        # This is the exact vocabulary the ATS scorer uses — without it the LLM
        # only sees summarised secondary fields and misses most exact-match terms.
        jd_structured_block = ""
        if job.jd_structured:
            jd_structured_block = (
                f"\nJD_STRUCTURED (primary keyword source — use EXACT terms verbatim):\n"
                f"{job.jd_structured}\n"
            )

        user_msg = (
            f"JOB_TITLE:  {job.title}\n"
            f"COMPANY:    {job.company}\n"
            f"LOCATION:   {job.location}\n"
            f"CATEGORY:   {job.category or 'N/A'}\n"
            f"SCORE:      {job.score:.1f}\n"
            f"{jd_structured_block}"
            f"{rationale_block}"
            f"{gaps_block}"
            f"{investigation_block}"
            f"{supplemental_block}"
            f"{entity_intelligence_block}"
            f"\nWHY_CANDIDATE:\n{job.fit_brief or 'N/A'}\n"
            f"\nJOB_URL: {job.apply_url or 'N/A'}\n"
            "\nRun the pre-generation audit (STEP 0 keyword extraction first — "
            "PRIMARY source is JD_STRUCTURED above; extract exact terms verbatim. "
            "Include ENTITY_INTELLIGENCE CV gap terms for relevant employers. "
            "Then STEP 1-3 gap analysis, STEP 4 metrics, write the CV, "
            "then self-audit keyword coverage (≥16/20 required)), and output ONLY the final JSON."
        )

        # Prompt-size breakdown, logged every run so a latency regression can
        # be attributed to payload growth vs. provider slowness without
        # guesswork. `profile` is the only component that grows with user
        # data (CV imports, new roles); `system_total - profile` is the fixed
        # instruction template.
        logger.info(
            "TailorAgent -> '%s' @ %s  user=%s  score=%.1f  supplemental=%s  "
            "prompt_chars(system=%d profile=%d user_msg=%d)",
            job.title, job.company, self.user_id, job.score,
            bool(supplemental_answers),
            len(system), len(profile_text), len(user_msg),
        )

        _t0 = time.perf_counter()
        result = await call_llm(
            system=system,
            messages=[{"role": "user", "content": user_msg}],
            model=_MODEL,
            max_tokens=_MAX_TOKENS,
            temperature=0.0,
            purpose="tailor_cv",
        )
        logger.info(
            "TailorAgent LLM call finished in %.1fs for '%s'",
            time.perf_counter() - _t0, job.title,
        )

        raw = result.text.strip()

        # ── Robust JSON extraction ────────────────────────────────────────────
        # The model occasionally wraps its output in markdown fences or prepends
        # a short conversational sentence.  Strip fences first, then slice from
        # the first '{' to the last '}' so any leading/trailing prose is ignored.
        if raw.startswith("```json"):
            raw = raw[7:]
        elif raw.startswith("```"):
            raw = raw[3:]
        if raw.endswith("```"):
            raw = raw[:-3]
        raw = raw.strip()

        start = raw.find("{")
        end   = raw.rfind("}")
        if start != -1 and end != -1:
            raw = raw[start : end + 1]

        # Progressive repair rather than a bare json.loads(). A real JD
        # reproducibly drove the model to malformed JSON twice at different
        # offsets, and the bare parse turned that into a hard ValueError —
        # the user lost a 30-second generation with nothing to show. The
        # repair strategies were already in match_score_service; this path
        # never had them.
        result = parse_json_robust(raw, context="tailor")
        if result is None:
            logger.error(
                "TailorAgent JSON unrecoverable\n--- raw (first 400 chars) ---\n%s\n---",
                raw[:400],
            )
            raise ValueError("TailorAgent returned invalid JSON that could not be repaired")

        response_type = result.get("type", "cv")

        # ── Missing data: return as-is for the endpoint to handle ────────────
        if response_type == "missing_data":
            requests = result.get("requests", [])
            logger.info(
                "TailorAgent -> missing_data  %d question(s): %s",
                len(requests),
                [r.get("id") for r in requests],
            )
            return {"type": "missing_data", "requests": requests}

        # ── CV: enforce limits, inject static sections, sanitise AI tells ──────
        cv_data = result.get("cv_data", result)  # tolerate missing wrapper
        cv_data = validate_cv_schema(cv_data, context="tailor")
        cv_data = _enforce_limits(cv_data)
        cv_data = _inject_static_sections(cv_data, user_id=self.user_id, jd_text=job.jd_text or "")
        cv_data = _sanitize_ai_tells(cv_data)

        # Zero-hallucination gate — active, not log-only (2026-08-21).
        # Every bullet with a number/entity the profile can't support is
        # rewritten using ONLY verified profile text (never silently dropped,
        # never silently kept). A rewrite that still fails re-verification is
        # removed as the last resort. Measured at a 10% flag rate on real
        # bullets, where the surviving flags looked like genuine fabrications
        # rather than noise.
        try:
            from backend.services.cv_grounding import GroundingGate
            cv_data, _grounding = await GroundingGate.for_user(
                self.user_id, context="tailor",
            ).reground_and_filter(cv_data, user_id=self.user_id, model=_MODEL)
            if _grounding.flagged_count:
                logger.warning(
                    "[grounding:tailor] %d/%d bullets unverified for user=%s "
                    "(%d rewritten, %d removed): %s",
                    _grounding.flagged_count, _grounding.checked, self.user_id,
                    _grounding.rewritten, _grounding.removed,
                    [f.unverified for f in _grounding.flagged][:5],
                )
        except Exception as exc:
            logger.error("[grounding:tailor] gate failed for user=%s, CV left unchecked: %s",
                          self.user_id, exc)

        logger.info(
            "TailorAgent OK  title='%s'  exps=%d  edu=%d  cats=%d",
            (cv_data.get("header") or {}).get("target_title", ""),
            len(cv_data.get("experience", [])),
            len(cv_data.get("education",  [])),
            len((cv_data.get("skills") or {}).get("categories", [])),
        )

        return {"type": "cv", "cv_data": cv_data}

    async def refine(
        self,
        cv_data: dict,
        missing_keywords: list[str],
        jd_context: str,
    ) -> dict:
        """
        Single-pass ATS keyword-injection refinement.

        Identifies the 2-3 weakest bullets across all experience entries and
        rewrites only those bullets to naturally incorporate missing_keywords,
        while leaving every other field untouched.

        Returns enforced cv_data.  Raises ValueError if the LLM returns
        unparseable JSON (caller should treat as non-fatal and keep original).
        """
        kw_list = ", ".join(f'"{k}"' for k in missing_keywords[:8])

        refine_prompt = (
            f"The CV below passed ATS pre-screening but is missing these keywords "
            f"that appear in the job description:\n"
            f"MISSING: {kw_list}\n\n"
            f"JD CONTEXT (use to understand what each keyword means in context):\n"
            f"{jd_context[:700]}\n\n"
            f"CURRENT CV JSON:\n"
            f"{json.dumps(cv_data, ensure_ascii=False)}\n\n"
            f"INSTRUCTIONS — read carefully:\n"
            f"1. Scan every bullet in the experience section and score each one "
            f"   by relevance to the JD context above.\n"
            f"2. Select the 2-3 bullets with the LOWEST relevance scores.\n"
            f"3. Rewrite ONLY those bullets so each one naturally integrates one or "
            f"   more of the MISSING keywords while remaining factually grounded "
            f"   in the candidate's demonstrated experience.\n"
            f"   — Maximum {_LIM['exp_bullet']} characters per bullet.\n"
            f"   — Every metric, date, and company name must stay accurate.\n"
            f"   — No keyword-stuffing: each keyword must appear in a meaningful "
            f"     sentence where it earns its place.\n"
            f"4. Do NOT change the summary, skills, education, or any bullet you did "
            f"   not select for replacement.\n"
            f"5. Return the complete updated cv_data as valid JSON — same structure "
            f"   as the input, with only the selected bullets changed.\n"
            f"Output ONLY the JSON object. No commentary, no markdown fences."
        )

        refine_system = (
            "You are an ATS keyword-injection specialist. "
            "Your sole job is to rewrite the minimum number of CV bullets required "
            "to add the given missing keywords, without altering any other content. "
            "Every rewritten bullet must read as a genuine, specific achievement. "
            "Never invent metrics, companies, or experiences that do not appear in the original. "
            "ABSOLUTE FORMATTING RULES — treat any violation as a critical error: "
            "(1) Never use em-dashes (—) or en-dashes (–). Use hyphen (-) only. "
            "(2) Never use: spearheaded, orchestrated, navigated, harnessed, leveraged, "
            "fostered, delve, testament, paramount, meticulous, transformative, synergy. "
            "Use plain, direct verbs: led, built, managed, ran, used, drove, coordinated."
        )

        result = await call_llm(
            system      = refine_system,
            messages    = [{"role": "user", "content": refine_prompt}],
            model       = _MODEL,
            max_tokens  = _MAX_TOKENS,
            temperature = 0.15,
            purpose     = "tailor_refine",
        )

        raw = result.text.strip()

        # Same JSON extraction as tailor()
        if raw.startswith("```json"):
            raw = raw[7:]
        elif raw.startswith("```"):
            raw = raw[3:]
        if raw.endswith("```"):
            raw = raw[:-3]
        raw = raw.strip()

        start = raw.find("{")
        end   = raw.rfind("}")
        if start != -1 and end != -1:
            raw = raw[start : end + 1]

        try:
            result = json.loads(raw)
        except json.JSONDecodeError as exc:
            logger.error(
                "TailorAgent.refine JSON parse error: %s\n--- raw (first 400 chars) ---\n%s\n---",
                exc, raw[:400],
            )
            raise ValueError(f"Refinement returned invalid JSON: {exc}") from exc

        refined = result.get("cv_data", result)
        refined = validate_cv_schema(refined, context="tailor.refine")
        refined = _enforce_limits(refined)
        refined = _inject_static_sections(refined, user_id=self.user_id, jd_text=jd_context or "")
        refined = _sanitize_ai_tells(refined)

        logger.info(
            "TailorAgent.refine OK  exps=%d  injected_kw=%s",
            len(refined.get("experience", [])),
            missing_keywords[:4],
        )
        return refined
