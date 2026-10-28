"""
confidence_matrix_service.py — Category Confidence Matrix

Aggregates profile_entities into profession-neutral buckets:
  Technical | Leadership | Data | Product | Business | Domain
Only the buckets a user has entities in are returned (at least three).

Each entity's raw score is re-weighted by a Source Weight multiplier that
reflects the credibility of the evidence type:

  cv_parse              0.40  — stated on CV, moderate credibility
  portfolio             0.80  — live artifact (JobApply codebase, project)
  conversation_star     0.90  — Ariel STAR-validated behavioral proof
  certification         0.70  — academic / formal cert
  contextual_reinforcement 0.30 — incidental mention across sessions
  self_assertion        0.20  — lowest, unvalidated claim

Recency decay is applied via confidence_math.freshness_factor() (exponential
half-life). Evidence at full age still contributes — it never reaches zero.

Output contract (recharts RadarChart):
  [
    { "category": "Technical",  "value": 78.4, "count": 21 },
    { "category": "Leadership", "value": 85.1, "count": 4 },
    { "category": "Data",       "value": 62.7, "count": 9 },
  ]

Key implementation note
-----------------------
SQLAlchemy text() + SQLite does not expand Python tuples for IN clauses
automatically. We use bindparam(..., expanding=True) which rewrites
  WHERE entity_id IN :ids
into
  WHERE entity_id IN (?, ?, ?, ...)
at execution time with the correct number of placeholders.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import TypedDict

from sqlalchemy import bindparam, text
from sqlalchemy.engine import Engine

from backend.services.confidence_math import AI_AUGMENTATION_PENALTY, freshness_factor

logger = logging.getLogger(__name__)

# ── Source weight multipliers ─────────────────────────────────────────────────

SOURCE_WEIGHT: dict[str, float] = {
    "cv_parse":                0.40,
    "portfolio":               0.80,
    "conversation_star":       0.90,
    "certification":           0.70,
    "contextual_reinforcement": 0.30,
    "self_assertion":          0.20,
}

# Per-source contribution caps (after weight multiplier)
SOURCE_CAP: dict[str, float] = {
    "cv_parse":                12.0,   # 30 × 0.4
    "portfolio":               40.0,   # 50 × 0.8
    "conversation_star":       72.0,   # 80 × 0.9
    "certification":           38.5,   # 55 × 0.7
    "contextual_reinforcement": 12.0,  # 40 × 0.3
    "self_assertion":           3.0,   # 15 × 0.2
}

NEGATIVE_CAP: float = 50.0
PENALTY_CAP_RATIO: float = 0.80

# ── Entity → semantic category mapping ───────────────────────────────────────
#
# Profession-neutral categories. The previous four axes (Technical /
# Product_Leadership / Data_Analysis / Customer_Success) were the founder's own
# career, and anything unrecognised fell into them by entity type: every
# "experience" entity became Product Leadership and every "domain" Customer
# Success. A senior software engineer's radar showed Product Leadership and
# Customer Success, which read as another user's data in her account. Matching
# was also by bare substring, so "Go" landed in "go_to_market".
#
# Classification: keyword lists matched on word boundaries, checked in order
# (more specific categories first), then a fallback by entity type.

CATEGORIES: list[str] = [
    "Technical",
    "Leadership",
    "Data",
    "Product",
    "Business",
    "Domain",
]

_CATEGORY_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("Leadership", (
        "lead", "leader", "leadership", "team lead", "tech lead", "manager",
        "management", "managing", "head", "director", "vp", "chief", "cto",
        "ceo", "coo", "mentoring", "mentor", "coaching", "people management",
        "hiring", "recruiting", "stakeholder", "stakeholders", "communication",
        "negotiation", "ownership", "teamwork", "collaboration",
        "ניהול", "מנהל", "מנהלת", "ראש צוות", "הובלה", "הנהלה",
    )),
    ("Product", (
        "product", "product management", "product strategy", "roadmap",
        "agile", "scrum", "kanban", "sprint", "jira", "confluence",
        "user research", "ux", "ui ux", "figma", "prd", "requirements",
        "acceptance criteria", "go to market", "project management",
        "program management", "delivery", "pmp", "מוצר", "אפיון",
    )),
    ("Data", (
        "data", "analytics", "analysis", "analyst", "bi",
        "business intelligence", "etl", "data warehousing", "warehouse",
        "power bi", "powerbi", "tableau", "informatica", "biee", "obiee", "looker", "excel", "dax",
        "statistics", "machine learning", "ml", "data mining", "kpi",
        "a b testing", "pandas", "spark", "sql reporting", "dashboards",
        "נתונים", "ניתוח",
    )),
    ("Business", (
        "customer", "customers", "customer success", "client", "clients",
        "account management", "account", "sales", "business development",
        "business", "partnership", "partnerships", "partner", "marketing",
        "seo", "sem", "crm", "salesforce", "hubspot", "onboarding",
        "retention", "churn", "upsell", "renewal", "operations", "finance",
        "budget", "procurement", "legal", "compliance", "hr",
        "לקוחות", "מכירות", "שיווק", "תפעול", "כספים",
    )),
    ("Technical", (
        "python", "java", "javascript", "typescript", "node", "node js",
        "react", "angular", "vue", "html", "css", "c", "c++", "c#", "go",
        "golang", "rust", "kotlin", "swift", "android", "ios", "php", "ruby",
        "sql", "nosql", "mongodb", "postgresql", "mysql", "oracle", "dba",
        "database", "stored procedures", "queries", "docker", "kubernetes",
        "openshift", "aws", "azure", "gcp", "cloud", "linux", "git",
        "ci cd", "devops", "microservices", "architecture", "api", "apis",
        "rest", "graphql", "kafka", "elk", "software", "development",
        "developer", "engineer", "engineering", "programming", "code",
        "testing", "qa", "security", "network", "embedded", "frontend",
        "backend", "full stack", "פיתוח", "מפתח", "מהנדס", "תוכנה",
    )),
]

_TYPE_FALLBACK: dict[str, str] = {
    "skill":      "Technical",
    "domain":     "Domain",
    "experience": "Domain",
    "trait":      "Leadership",
}


def _kw_regex(kw: str) -> str:
    escaped = re.escape(kw)
    return rf"(?<![\w]){escaped}(?![\w])"


_CATEGORY_PATTERNS: list[tuple[str, "re.Pattern[str]"]] = [
    (cat, re.compile("|".join(_kw_regex(k) for k in sorted(kws, key=len, reverse=True))))
    for cat, kws in _CATEGORY_KEYWORDS
]


def _name_for_matching(name: str) -> str:
    """'Node.js' / 'node_js' / 'CI/CD' -> 'node js' / 'ci cd' (lowercase, single spaces)."""
    n = (name or "").lower().replace("_", " ").replace(".", " ").replace("/", " ").replace("-", " ")
    return " ".join(n.split())


# ── TypedDicts ────────────────────────────────────────────────────────────────

_MIN_AXES = 3


class RadarDatum(TypedDict, total=False):
    category:   str
    value:      float   # final blended score (stored confidence_score)
    arch_value: float   # Architecture_Confidence average for the category
    syn_value:  float   # Syntax_Confidence average for the category


class EntityScore(TypedDict):
    entity_id:               str
    name:                    str
    category:                str
    score:                   float
    architecture_confidence: float
    syntax_confidence:       float
    verification_level:      str
    skill_tier:              str | None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _resolve_category(normalized_name: str, entity_type: str, name: str = "") -> str:
    """Category for one entity — keyword match on its name, else by entity type."""
    text_ = _name_for_matching(name or normalized_name)
    if text_:
        for cat, pattern in _CATEGORY_PATTERNS:
            if pattern.search(text_):
                return cat
    return _TYPE_FALLBACK.get(entity_type, "Technical")


resolve_category = _resolve_category


def _compute_weighted_score(evidence_rows: list[dict], entity_name: str = "") -> float:
    """
    Geometric combination of source-weighted, decay-adjusted evidence.

    Positive phase:
      1. For each source_type bucket: sum(base_weight × SOURCE_WEIGHT × freshness)
      2. Cap each bucket at SOURCE_CAP[source_type]
      3. Geometric: score = 100 × (1 − ∏(1 − capped_i / 100))

    Negative phase:
      penalty = Σ(|base_weight| × freshness), capped at NEGATIVE_CAP per type
      and at PENALTY_CAP_RATIO × positive_score overall.
    """
    if not evidence_rows:
        return 0.0

    pos_rows = [r for r in evidence_rows if r["base_weight"] >= 0]
    neg_rows = [r for r in evidence_rows if r["base_weight"] < 0]

    pos_by_source: dict[str, float] = {}
    for r in pos_rows:
        stype   = r["source_type"]
        decay   = freshness_factor(r["verified_at"], stype)
        src_wt  = SOURCE_WEIGHT.get(stype, 0.25)
        ai_mult = AI_AUGMENTATION_PENALTY if r.get("is_ai_assisted") else 1.0
        weight  = r["base_weight"] * src_wt * ai_mult * decay
        pos_by_source[stype] = pos_by_source.get(stype, 0.0) + weight

    contributions = [
        min(raw, SOURCE_CAP.get(stype, 30.0))
        for stype, raw in pos_by_source.items()
    ]

    complement = 1.0
    for c in contributions:
        complement *= 1.0 - (c / 100.0)
    positive_score = 100.0 * (1.0 - complement)

    logger.debug(
        "[confidence_matrix] entity=%r  sources=%s  contributions=%s  positive=%.1f",
        entity_name,
        {k: round(v, 2) for k, v in pos_by_source.items()},
        [round(c, 2) for c in contributions],
        positive_score,
    )

    if not neg_rows:
        return round(min(max(positive_score, 0.0), 100.0), 1)

    neg_by_source: dict[str, float] = {}
    for r in neg_rows:
        stype  = r["source_type"]
        decay  = freshness_factor(r["verified_at"], stype)
        neg_by_source[stype] = neg_by_source.get(stype, 0.0) + abs(r["base_weight"]) * decay

    raw_penalty = sum(min(v, NEGATIVE_CAP) for v in neg_by_source.values())
    penalty = min(raw_penalty, positive_score * PENALTY_CAP_RATIO)
    final = round(min(max(positive_score - penalty, 0.0), 100.0), 1)

    logger.debug("[confidence_matrix] entity=%r  penalty=%.1f  final=%.1f", entity_name, penalty, final)
    return final


def parse_dt(value) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        dt = datetime.fromisoformat(str(value))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return datetime.now(timezone.utc)


def _fetch_evidence(conn, entity_ids: list[str]) -> dict[str, list[dict]]:
    """
    Fetch all non-expired evidence rows for the given entity_ids.

    Uses bindparam(expanding=True) so SQLAlchemy correctly expands the list
    into individual IN-clause placeholders for SQLite:
      WHERE entity_id IN (?, ?, ?)
    rather than the broken  WHERE entity_id IN ?  form.
    """
    if not entity_ids:
        return {}

    now_iso = datetime.now(timezone.utc).isoformat()

    stmt = text("""
        SELECT entity_id, source_type, base_weight, verified_at, is_ai_assisted
        FROM   evidence_records
        WHERE  entity_id IN :ids
          AND  (hard_expires_at IS NULL OR hard_expires_at > :now)
    """).bindparams(bindparam("ids", expanding=True))

    rows = conn.execute(stmt, {"ids": entity_ids, "now": now_iso}).fetchall()

    result: dict[str, list[dict]] = {eid: [] for eid in entity_ids}
    for row in rows:
        eid = row[0]
        if eid in result:
            result[eid].append({
                "source_type":    row[1],
                "base_weight":    float(row[2]),
                "verified_at":    parse_dt(row[3]),
                "is_ai_assisted": bool(row[4]) if row[4] is not None else False,
            })

    logger.debug(
        "[confidence_matrix] fetched %d evidence rows for %d entities",
        len(rows), len(entity_ids),
    )
    return result


# ── Public API ────────────────────────────────────────────────────────────────
#
# get_confidence_matrix() and get_entity_breakdown() both read profile_entities
# + evidence_records for the same user, just projecting different columns and
# aggregating differently — so each, called standalone (as several callers
# across the codebase do: match_score_service, cv_tailor_service,
# profile_baseline_service, feed_service all call get_entity_breakdown() on
# its own), still does its own two-query load via load_entities_and_evidence().
# Callers that need BOTH outputs for the same user in the same request (only
# profile.py's confidence-matrix route today) should call
# load_entities_and_evidence() once themselves and pass the result to
# compute_radar()/compute_breakdown() directly (or use
# get_confidence_matrix_and_breakdown() below for the common case) — either
# way, evidence and profile_entities are only loaded once instead of twice.

# Superset of the columns both outputs need, so one query serves both.
_ENTITY_COLUMNS = """
    entity_id, name, entity_type, normalized_name, confidence_score,
    architecture_confidence, syntax_confidence, skill_tier, verification_level
"""


def load_entities_and_evidence(engine: Engine, user_id: str):
    """Single load of profile_entities + their evidence for `user_id`.

    Both queries run on ONE checked-out connection (one pool checkout, one
    close) rather than one per query — halves the connection-lifecycle
    overhead (checkout + pre-ping + implicit-rollback-on-close) on top of the
    query count reduction.

    Returns (entity_rows, evidence_by_entity) — entity_rows is `[]` when the
    user has no entities (evidence_by_entity is then also `{}`), same
    empty-profile behavior both public functions already relied on.
    """
    with engine.connect() as conn:
        entity_rows = conn.execute(
            text(f"""
                SELECT {_ENTITY_COLUMNS}
                FROM   profile_entities
                WHERE  user_id = :uid
                ORDER  BY name
            """),
            {"uid": user_id},
        ).fetchall()

        if not entity_rows:
            return [], {}

        entity_ids = [r[0] for r in entity_rows]
        evidence_by_entity = _fetch_evidence(conn, entity_ids)

    return entity_rows, evidence_by_entity


def compute_radar(entity_rows, evidence_by_entity, user_id: str) -> list[RadarDatum]:
    """Categories the user has entities in (at least three axes). An empty
    profile gets every category at 0.0."""
    if not entity_rows:
        logger.warning("[confidence_matrix] no entities found for user_id=%s", user_id)
        return [{"category": c, "value": 0.0, "arch_value": 0.0, "syn_value": 0.0, "count": 0}
                for c in CATEGORIES]

    logger.info("[confidence_matrix] user=%s  entity_count=%d", user_id, len(entity_rows))

    cat_scores: dict[str, list[float]] = {c: [] for c in CATEGORIES}
    cat_arch:   dict[str, list[float]] = {c: [] for c in CATEGORIES}
    cat_syn:    dict[str, list[float]] = {c: [] for c in CATEGORIES}

    for row in entity_rows:
        (entity_id, name, entity_type, normalized_name, fallback_score,
         arch_col, syn_col, _skill_tier, _vl) = row
        evidence = evidence_by_entity.get(entity_id, [])
        score = (
            _compute_weighted_score(evidence, entity_name=normalized_name or entity_id)
            if evidence
            else float(fallback_score or 0.0)
        )
        cat = _resolve_category(normalized_name or "", entity_type or "skill", name or "")
        cat_scores[cat].append(score)
        cat_arch[cat].append(float(arch_col or 0.0))
        cat_syn[cat].append(float(syn_col  or 0.0))
        logger.debug(
            "[confidence_matrix] entity=%r  cat=%s  ev=%d  score=%.1f  arch=%.1f  syn=%.1f",
            normalized_name, cat, len(evidence), score,
            float(arch_col or 0.0), float(syn_col or 0.0),
        )

    def _avg(scores: list[float]) -> float:
        return round(sum(scores) / len(scores), 1) if scores else 0.0

    # Only the categories this user actually has entities in — an engineer's
    # radar has no empty "Business" axis. A radar needs at least three axes,
    # so a narrow profile is padded with the next categories (value 0).
    present = [c for c in CATEGORIES if cat_scores[c]]
    shown = present + [c for c in CATEGORIES if c not in present][: max(0, _MIN_AXES - len(present))]
    result = [
        {
            "category":   cat,
            "value":      _avg(cat_scores[cat]),
            "arch_value": _avg(cat_arch[cat]),
            "syn_value":  _avg(cat_syn[cat]),
            "count":      len(cat_scores[cat]),
        }
        for cat in CATEGORIES if cat in shown
    ]

    logger.info("[confidence_matrix] result for user=%s: %s", user_id, result)
    return result


def compute_breakdown(entity_rows, evidence_by_entity) -> list[EntityScore]:
    result: list[EntityScore] = []
    for row in entity_rows:
        (entity_id, name, entity_type, normalized_name, _confidence_score,
         arch_conf, syn_conf, skill_tier, vl) = row
        evidence = evidence_by_entity.get(entity_id, [])
        score = (
            _compute_weighted_score(evidence, entity_name=name)
            if evidence
            else 0.0
        )
        cat = _resolve_category(normalized_name or "", entity_type or "skill", name or "")
        result.append({
            "entity_id":               entity_id,
            "name":                    name,
            "category":                cat,
            "score":                   score,
            "architecture_confidence": float(arch_conf or 0.0),
            "syntax_confidence":       float(syn_conf  or 0.0),
            "verification_level":      vl or "UNVERIFIED",
            "skill_tier":              skill_tier,
        })
    return result


def get_confidence_matrix(user_id: str, engine: Engine) -> list[RadarDatum]:
    """
    Compute the four-category Confidence Matrix for `user_id`.

    Every category is always present in the output with value ≥ 0.0 so that
    recharts RadarChart renders all four axes even when some have no evidence.
    """
    entity_rows, evidence_by_entity = load_entities_and_evidence(engine, user_id)
    return compute_radar(entity_rows, evidence_by_entity, user_id)


def get_entity_breakdown(user_id: str, engine: Engine) -> list[EntityScore]:
    """
    Per-entity scores with resolved category — used for RadarChart axis tooltips.
    Always returns a list (empty when the user has no entities).
    """
    entity_rows, evidence_by_entity = load_entities_and_evidence(engine, user_id)
    return compute_breakdown(entity_rows, evidence_by_entity)


def entities_from_profile_entities(entity_rows, evidence_by_entity) -> tuple[list, dict[str, list[dict]]]:
    """
    Adapt profile_entity_repository.get_all_for_user()'s `list[ProfileEntity]`
    + evidence_repository.get_active_for_entities()'s `dict[str, list[Evidence]]`
    (the objects backend/api/routes/profile.py's trust-score endpoint already
    loads) into the row-tuple + evidence-dict shapes compute_radar()/
    compute_breakdown() expect.

    Lets a caller that already loaded entities+evidence for trust-score (e.g.
    dashboard.py's aggregated endpoint) also drive the confidence-matrix
    computation from that SAME in-memory data — no extra DB round trip, only
    reshaping already-fetched objects. Both `ProfileEntity` and `Evidence`
    happen to carry every column this module's own raw-SQL rows do
    (including normalized_name), so no data is lost in the conversion.
    """
    cm_entity_rows = [
        (
            e.entity_id, e.name, e.entity_type, e.normalized_name,
            e.confidence_score, e.architecture_confidence, e.syntax_confidence,
            e.skill_tier, e.verification_level,
        )
        for e in entity_rows
    ]
    cm_evidence_by_entity = {
        entity_id: [
            {
                "source_type":    ev.source_type,
                "base_weight":    float(ev.base_weight),
                "verified_at":    parse_dt(ev.verified_at),
                "is_ai_assisted": bool(ev.is_ai_assisted),
            }
            for ev in evidence_list
        ]
        for entity_id, evidence_list in evidence_by_entity.items()
    }
    return cm_entity_rows, cm_evidence_by_entity


def get_confidence_matrix_and_breakdown(
    user_id: str, engine: Engine
) -> tuple[list[RadarDatum], list[EntityScore]]:
    """
    Both get_confidence_matrix() and get_entity_breakdown() outputs for
    `user_id`, computed from ONE load of profile_entities + evidence instead
    of the two independent loads calling them separately would cost.

    For the same caller that needs both (profile.py's confidence-matrix
    route) — every other call site only ever needs get_entity_breakdown()
    alone, and keeps using that standalone function unchanged.
    """
    entity_rows, evidence_by_entity = load_entities_and_evidence(engine, user_id)
    radar_data = compute_radar(entity_rows, evidence_by_entity, user_id)
    entity_breakdown = compute_breakdown(entity_rows, evidence_by_entity)
    return radar_data, entity_breakdown
