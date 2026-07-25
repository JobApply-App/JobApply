"""
Unit tests — GET /api/profile/{user_id}/trust-score
=====================================================

Coverage:
  1. compute_profile_trust_score()
       - empty profile  →  0.0
       - single-category profile (all skills)
       - mixed-category profile with known weights (weighted geometric "OR"
         combination — see Phase 28 fix in profile_update_service.py)
       - fixed (never renormalised) weights when one category is absent
       - monotonicity regression: adding new (low-confidence) data, whether
         to an existing category or a brand-new one, must never lower the
         overall score

  2. HTTP endpoint  (FastAPI TestClient, auth dependency overridden)
       - 200 with correct JSON structure for a user with 2 entities
         (one 'verified' skill, one 'unverified' skill)
       - overall_trust_score, category_averages, trust_breakdown present
       - manual_review_required mapped to bool
       - 403 when caller requests a different user's data
       - 200 with empty lists for a user with 0 entities

All tests run against an isolated in-memory SQLite database so the real
jobs.db is never touched.

Running
-------
From the project root (JobApply_Venture/):

    backend/.venv/bin/pytest backend/tests/test_profile_trust.py -v

Or, if pytest is on the active PATH:

    pytest backend/tests/test_profile_trust.py -v
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

# ---------------------------------------------------------------------------
# Shared in-memory SQLite engine (isolated per test session)
# ---------------------------------------------------------------------------
# StaticPool is REQUIRED for sqlite:///:memory:. Without it, SQLAlchemy's
# default QueuePool gives every new connection its own in-memory database,
# so tables created during setup are invisible to the route's Session.
# StaticPool forces all checkouts to reuse the single underlying connection,
# keeping one consistent in-memory database throughout the entire test run.

_TEST_ENGINE = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)


def _setup_schema() -> None:
    """Create all tables required by the confidence matrix in the test engine."""
    from backend.core.database import Base
    from backend.models import application, ariel, job, kv, matching, profile  # noqa: F401

    # Create the standard ORM-mapped tables (jobs, applications, etc.)
    Base.metadata.create_all(_TEST_ENGINE)

    # Create the confidence-matrix tables that are managed by raw SQL migrations.
    with _TEST_ENGINE.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS profile_entities (
                entity_id              TEXT PRIMARY KEY,
                user_id                TEXT NOT NULL,
                entity_type            TEXT NOT NULL,
                name                   TEXT NOT NULL,
                normalized_name        TEXT NOT NULL,
                confidence_score       REAL NOT NULL DEFAULT 0.0,
                verification_status    TEXT NOT NULL DEFAULT 'unverified',
                manual_review_required INTEGER NOT NULL DEFAULT 0,
                proficiency_level      TEXT,
                last_evidence_at       TEXT,
                created_at             TEXT NOT NULL,
                updated_at             TEXT NOT NULL
            )
        """))

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS evidence_records (
                evidence_id     TEXT PRIMARY KEY,
                entity_id       TEXT NOT NULL,
                user_id         TEXT NOT NULL,
                source_type     TEXT NOT NULL,
                base_weight     REAL NOT NULL,
                raw_content     TEXT,
                verified_at     TEXT NOT NULL,
                hard_expires_at TEXT,
                session_id      TEXT,
                event_id        TEXT,
                extra_metadata  TEXT
            )
        """))

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS ariel_sessions (
                session_id              TEXT PRIMARY KEY,
                user_id                 TEXT NOT NULL,
                session_type            TEXT NOT NULL,
                target_job_id           TEXT,
                target_entities         TEXT,
                ariel_goal              TEXT,
                status                  TEXT NOT NULL DEFAULT 'active',
                transcript_json         TEXT,
                confidence_delta_total  REAL NOT NULL DEFAULT 0.0,
                started_at              TEXT NOT NULL,
                ended_at                TEXT
            )
        """))


# Run schema setup once when the module loads.
_setup_schema()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _uid() -> str:
    return str(uuid.uuid4())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _insert_entity(
    conn,
    *,
    user_id: str,
    entity_type: str,
    name: str,
    confidence_score: float,
    manual_review_required: int = 0,
    verification_status: str | None = None,
    proficiency_level: str | None = None,
) -> str:
    """
    Insert a profile_entities row and return its entity_id.

    verification_status defaults to 'verified' when confidence ≥ 75 else
    'unverified'. Pass an explicit value to decouple the two. proficiency_level
    mirrors the chat-clarified level (Phase 30/31) — set it to exercise the
    Holistic Familiarity depth/engagement pillars.
    """
    entity_id = _uid()
    now = _now()
    status = (
        verification_status
        if verification_status is not None
        else ("verified" if confidence_score >= 75 else "unverified")
    )
    conn.execute(
        text("""
            INSERT INTO profile_entities
                (entity_id, user_id, entity_type, name, normalized_name,
                 confidence_score, verification_status, manual_review_required,
                 proficiency_level, created_at, updated_at)
            VALUES
                (:eid, :uid, :etype, :name, :norm,
                 :score, :status, :manual,
                 :prof, :now, :now)
        """),
        {
            "eid":    entity_id,
            "uid":    user_id,
            "etype":  entity_type,
            "name":   name,
            "norm":   name.lower().replace(" ", "_"),
            "score":  confidence_score,
            "status": status,
            "manual": manual_review_required,
            "prof":   proficiency_level,
            "now":    now,
        },
    )
    return entity_id


def _insert_evidence(
    conn,
    *,
    entity_id: str,
    user_id: str,
    source_type: str = "cv_parse",
    base_weight: float = 25.0,
    raw_content: str = "",
    hard_expires_at: str | None = None,
) -> str:
    """Insert an evidence_records row and return its evidence_id."""
    ev_id = _uid()
    conn.execute(
        text("""
            INSERT INTO evidence_records
                (evidence_id, entity_id, user_id, source_type,
                 base_weight, raw_content, verified_at, hard_expires_at)
            VALUES
                (:evid, :eid, :uid, :src, :w, :raw, :now, :exp)
        """),
        {
            "evid": ev_id,
            "eid":  entity_id,
            "uid":  user_id,
            "src":  source_type,
            "w":    base_weight,
            "raw":  raw_content,
            "now":  _now(),
            "exp":  hard_expires_at,
        },
    )
    return ev_id


# ---------------------------------------------------------------------------
# Unit tests: compute_profile_trust_score  (Phase 31 — Holistic Familiarity)
# ---------------------------------------------------------------------------

def _complete_profile() -> dict:
    """A base profile with all three identity anchors present (full identity
    context bonus). Passed explicitly so unit tests don't read/write the disk
    store."""
    return {
        "personal": {"full_name": "Ada Lovelace", "phone": "+1-555-0100"},
        "role_preferences": {"target_titles": ["Senior Product Manager"]},
    }


def _no_identity_profile() -> dict:
    """A base profile the system knows nothing about (0 identity bonus)."""
    return {"personal": {}, "role_preferences": {"target_titles": []}}


class TestComputeProfileTrustScore:
    """
    Direct unit tests for the Phase 31 Holistic Familiarity score.

    The score measures how well the system KNOWS the user, not how skilled they
    are. It sums three additive, monotonically non-decreasing pillars:
      BREADTH  — saturating in the entity count (volume of known data),
      DEPTH    — saturating in graded verification (+ chat-clarified levels),
      CONTEXT  — category coverage + identity completeness + proficiency
                 engagement, all positive bonuses (never penalties).
    Raw confidence_score is intentionally NOT read.
    """

    def _service(self):
        from backend.services.profile_update_service import ProfileUpdateService
        return ProfileUpdateService(_TEST_ENGINE)

    def test_empty_profile_returns_zero(self):
        """A user with no entities must return 0.0 — never a crash."""
        svc = self._service()
        score = svc.compute_profile_trust_score(
            "nonexistent-user-" + _uid(), profile=_complete_profile()
        )
        assert score == 0.0

    def test_breadth_volume_secures_a_solid_baseline(self):
        """
        The headline Phase 31 fix: a large parsed profile that is entirely
        UNVERIFIED must still secure a solid baseline (40–55), never collapse
        to ~33. 150 unverified skills + full identity → ~47.4.
        """
        uid = "test-breadth-" + _uid()
        with _TEST_ENGINE.begin() as conn:
            for i in range(150):
                _insert_entity(conn, user_id=uid, entity_type="skill",
                               name=f"CV Skill {i}", confidence_score=50.0,
                               verification_status="unverified")

        svc = self._service()
        score = svc.compute_profile_trust_score(uid, profile=_complete_profile())
        assert 40.0 <= score <= 55.0
        assert score == pytest.approx(47.4, abs=0.3)

    def test_raw_confidence_score_is_ignored(self):
        """
        Familiarity does NOT measure skill: two structurally identical profiles
        (5 verified skills, one category) score the same whether the parsed
        confidence is 10 or 95. Only structure (count/verification) matters.
        """
        uid_low  = "test-conf-low-"  + _uid()
        uid_high = "test-conf-high-" + _uid()
        with _TEST_ENGINE.begin() as conn:
            for i in range(5):
                _insert_entity(conn, user_id=uid_low, entity_type="skill",
                               name=f"S{i}", confidence_score=10.0,
                               verification_status="verified")
                _insert_entity(conn, user_id=uid_high, entity_type="skill",
                               name=f"S{i}", confidence_score=95.0,
                               verification_status="verified")

        svc = self._service()
        low  = svc.compute_profile_trust_score(uid_low,  profile=_complete_profile())
        high = svc.compute_profile_trust_score(uid_high, profile=_complete_profile())
        assert low == high

    def test_verification_adds_depth(self):
        """Verifying claims lifts the score above the unverified baseline."""
        uid_unv = "test-depth-unv-" + _uid()
        uid_ver = "test-depth-ver-" + _uid()
        with _TEST_ENGINE.begin() as conn:
            for i in range(10):
                _insert_entity(conn, user_id=uid_unv, entity_type="skill",
                               name=f"S{i}", confidence_score=50.0,
                               verification_status="unverified")
                _insert_entity(conn, user_id=uid_ver, entity_type="skill",
                               name=f"S{i}", confidence_score=50.0,
                               verification_status="verified")

        svc = self._service()
        unv = svc.compute_profile_trust_score(uid_unv, profile=_complete_profile())
        ver = svc.compute_profile_trust_score(uid_ver, profile=_complete_profile())
        assert ver > unv
        assert ver == pytest.approx(46.5, abs=0.3)

    def test_honesty_never_penalizes_and_correction_raises_score(self):
        """
        The core philosophy: a user admitting a weakness must RAISE familiarity,
        not lower it. Start with 20 unverified skills; flip one to
        'verified' + proficiency_level='beginner' (a Phase 30 chat correction).
        The corrected profile scores HIGHER, not lower.
        """
        uid = "test-honesty-" + _uid()
        with _TEST_ENGINE.begin() as conn:
            for i in range(20):
                _insert_entity(conn, user_id=uid, entity_type="skill",
                               name=f"S{i}", confidence_score=50.0,
                               verification_status="unverified")

        svc = self._service()
        before = svc.compute_profile_trust_score(uid, profile=_complete_profile())

        # Simulate the chat correction: one skill becomes verified + beginner.
        with _TEST_ENGINE.begin() as conn:
            conn.execute(text("""
                UPDATE profile_entities
                SET verification_status='verified', proficiency_level='beginner'
                WHERE user_id=:uid AND name='S0'
            """), {"uid": uid})

        after = svc.compute_profile_trust_score(uid, profile=_complete_profile())
        assert after > before

    def test_adding_low_data_entity_never_lowers_score(self):
        """
        Monotonic growth: adding ANY entity (even a brand-new, unverified,
        beginner one) can only raise or hold the score — never lower it.
        """
        uid = "test-mono-" + _uid()
        with _TEST_ENGINE.begin() as conn:
            for i in range(8):
                _insert_entity(conn, user_id=uid, entity_type="skill",
                               name=f"S{i}", confidence_score=50.0,
                               verification_status="verified")

        svc = self._service()
        before = svc.compute_profile_trust_score(uid, profile=_complete_profile())

        with _TEST_ENGINE.begin() as conn:
            _insert_entity(conn, user_id=uid, entity_type="skill",
                           name="Weak New", confidence_score=5.0,
                           verification_status="unverified",
                           proficiency_level="beginner")

        after = svc.compute_profile_trust_score(uid, profile=_complete_profile())
        assert after >= before

    def test_category_coverage_adds_context(self):
        """
        Breadth aside, spreading the same number of entities across more
        categories increases familiarity (coverage bonus). 10 entities in one
        category < 10 entities spread across all four.
        """
        uid_one  = "test-cov-one-"  + _uid()
        uid_four = "test-cov-four-" + _uid()
        with _TEST_ENGINE.begin() as conn:
            for i in range(10):
                _insert_entity(conn, user_id=uid_one, entity_type="skill",
                               name=f"S{i}", confidence_score=50.0,
                               verification_status="unverified")
            spread = (["skill"] * 4 + ["trait"] * 2
                      + ["experience"] * 2 + ["domain"] * 2)
            for i, etype in enumerate(spread):
                _insert_entity(conn, user_id=uid_four, entity_type=etype,
                               name=f"E{i}", confidence_score=50.0,
                               verification_status="unverified")

        svc = self._service()
        one  = svc.compute_profile_trust_score(uid_one,  profile=_complete_profile())
        four = svc.compute_profile_trust_score(uid_four, profile=_complete_profile())
        assert four > one

    def test_missing_identity_is_a_withheld_bonus_not_a_penalty(self):
        """
        Missing base-profile identity data withholds a fixed +6 context bonus —
        it is NOT a multiplicative penalty. The gap between full and zero
        identity is exactly the identity bonus (≈6.0), and the no-identity score
        is never dragged below the breadth+depth the entities already earned.
        """
        uid = "test-identity-" + _uid()
        with _TEST_ENGINE.begin() as conn:
            for i in range(150):
                _insert_entity(conn, user_id=uid, entity_type="skill",
                               name=f"S{i}", confidence_score=50.0,
                               verification_status="unverified")

        svc = self._service()
        full = svc.compute_profile_trust_score(uid, profile=_complete_profile())
        none = svc.compute_profile_trust_score(uid, profile=_no_identity_profile())
        assert full - none == pytest.approx(6.0, abs=0.1)
        assert none == pytest.approx(41.4, abs=0.3)   # still a solid baseline

    def test_proficiency_engagement_raises_score(self):
        """
        User-clarified proficiency levels feed the engagement bonus. Same 10
        verified skills score higher when 5 of them carry a stated level.
        """
        uid_plain = "test-eng-plain-" + _uid()
        uid_eng   = "test-eng-rich-"  + _uid()
        with _TEST_ENGINE.begin() as conn:
            for i in range(10):
                _insert_entity(conn, user_id=uid_plain, entity_type="skill",
                               name=f"S{i}", confidence_score=50.0,
                               verification_status="verified")
            for i in range(10):
                _insert_entity(conn, user_id=uid_eng, entity_type="skill",
                               name=f"S{i}", confidence_score=50.0,
                               verification_status="verified",
                               proficiency_level=("intermediate" if i < 5 else None))

        svc = self._service()
        plain = svc.compute_profile_trust_score(uid_plain, profile=_complete_profile())
        eng   = svc.compute_profile_trust_score(uid_eng,   profile=_complete_profile())
        assert eng > plain

    def test_deep_verified_profile_approaches_100(self):
        """
        The path to 100 is verification + breadth + coverage + engagement. A
        large, fully-verified, well-covered profile with clarified proficiencies
        approaches (and clamps at) 100.
        """
        uid = "test-clamp-" + _uid()
        spread = (["skill"] * 100 + ["trait"] * 40
                  + ["experience"] * 30 + ["domain"] * 30)
        with _TEST_ENGINE.begin() as conn:
            for i, etype in enumerate(spread):
                _insert_entity(conn, user_id=uid, entity_type=etype,
                               name=f"E{i}", confidence_score=80.0,
                               verification_status="verified",
                               proficiency_level="advanced")

        svc = self._service()
        score = svc.compute_profile_trust_score(uid, profile=_complete_profile())
        assert 95.0 <= score <= 100.0

    def test_unknown_types_count_for_breadth_but_not_coverage(self):
        """
        An entity of an unrecognised type still counts toward breadth volume
        (the system knows *something* more about the user) but does not add a
        coverage category. It never lowers the score.
        """
        uid_base = "test-unk-base-" + _uid()
        uid_plus = "test-unk-plus-" + _uid()
        with _TEST_ENGINE.begin() as conn:
            for i in range(5):
                _insert_entity(conn, user_id=uid_base, entity_type="skill",
                               name=f"S{i}", confidence_score=50.0,
                               verification_status="unverified")
                _insert_entity(conn, user_id=uid_plus, entity_type="skill",
                               name=f"S{i}", confidence_score=50.0,
                               verification_status="unverified")
            _insert_entity(conn, user_id=uid_plus, entity_type="hobby",
                           name="Chess", confidence_score=50.0,
                           verification_status="unverified")

        svc = self._service()
        base = svc.compute_profile_trust_score(uid_base, profile=_complete_profile())
        plus = svc.compute_profile_trust_score(uid_plus, profile=_complete_profile())
        assert plus > base   # extra volume raised breadth, no penalty

    # -----------------------------------------------------------------------
    # compute_profile_familiarity — the pillar breakdown feeding the UI
    # -----------------------------------------------------------------------

    def test_familiarity_breakdown_pillars_sum_to_overall(self):
        """
        The breakdown method returns the same overall value the scalar method
        does, and its three pillars sum to it (within rounding) and respect
        their individual maxes (40 / 40 / 20).
        """
        uid = "test-breakdown-" + _uid()
        with _TEST_ENGINE.begin() as conn:
            for i in range(12):
                _insert_entity(conn, user_id=uid, entity_type="skill",
                               name=f"S{i}", confidence_score=50.0,
                               verification_status="verified",
                               proficiency_level=("expert" if i < 3 else None))
            _insert_entity(conn, user_id=uid, entity_type="experience",
                           name="Lead", confidence_score=50.0,
                           verification_status="verified")
            _insert_entity(conn, user_id=uid, entity_type="domain",
                           name="FinTech", confidence_score=50.0,
                           verification_status="unverified")

        svc = self._service()
        br = svc.compute_profile_familiarity(uid, profile=_complete_profile())

        assert set(br.keys()) == {"overall", "breadth", "depth", "context"}
        assert 0.0 <= br["breadth"] <= 40.0
        assert 0.0 <= br["depth"]   <= 40.0
        assert 0.0 <= br["context"] <= 20.0
        # Pillars sum to the overall (allow 0.1 for independent rounding).
        assert br["breadth"] + br["depth"] + br["context"] == pytest.approx(
            br["overall"], abs=0.1
        )
        # And the scalar method agrees with the breakdown's overall.
        scalar = svc.compute_profile_trust_score(uid, profile=_complete_profile())
        assert scalar == br["overall"]

    def test_familiarity_breakdown_empty_profile_all_zero(self):
        """A user with no entities gets an all-zero breakdown, never a crash."""
        svc = self._service()
        br = svc.compute_profile_familiarity("empty-" + _uid(),
                                             profile=_complete_profile())
        assert br == {"overall": 0.0, "breadth": 0.0, "depth": 0.0, "context": 0.0}


# ---------------------------------------------------------------------------
# HTTP integration tests: GET /api/profile/{user_id}/trust-score
# ---------------------------------------------------------------------------
#
# Strategy
# --------
# We override the get_current_user dependency so the test runner doesn't need
# a real JWT.  The override returns a CurrentUser whose user_id we control.
# The endpoint is wired to ENGINE which we monkey-patch to point at _TEST_ENGINE
# for the duration of the test module.

class TestTrustScoreEndpoint:
    """
    FastAPI TestClient tests exercising the full HTTP stack.

    These tests patch:
      • backend.core.database.ENGINE          →  _TEST_ENGINE (in-memory SQLite)
      • backend.api.deps.get_current_user   →  returns a synthetic CurrentUser
    """

    @pytest.fixture(autouse=True)
    def _patch_engine(self, monkeypatch):
        """Replace the shared ENGINE with the test-scoped in-memory engine."""
        import backend.core.database as _db_module
        import backend.api.routes.profile as _profile_module
        import backend.repositories.profile_entity_repository as _entity_repo_module
        import backend.repositories.evidence_repository as _evidence_repo_module

        monkeypatch.setattr(_db_module, "ENGINE", _TEST_ENGINE)
        monkeypatch.setattr(_profile_module, "ENGINE", _TEST_ENGINE)
        monkeypatch.setattr(_entity_repo_module, "ENGINE", _TEST_ENGINE)
        monkeypatch.setattr(_evidence_repo_module, "ENGINE", _TEST_ENGINE)

    def _make_client(self, caller_user_id: str) -> TestClient:
        """Return a TestClient whose auth dependency returns caller_user_id."""
        from backend.main import app
        from backend.api.deps import CurrentUser, get_current_user

        def _override():
            return CurrentUser(user_id=caller_user_id, email="test@example.com")

        app.dependency_overrides[get_current_user] = _override
        client = TestClient(app, raise_server_exceptions=False)
        return client

    def _teardown_client(self, client: TestClient) -> None:
        from backend.main import app
        from backend.api.deps import get_current_user
        app.dependency_overrides.pop(get_current_user, None)

    # ── Test: canonical 2-entity case ────────────────────────────────────────

    def test_two_entities_correct_structure(self):
        """
        Core acceptance test per spec:
          • 2 entities: one 'verified' (confidence 80), one 'unverified' (confidence 20)
          • Response contains correct JSON structure
          • overall_trust_score, category_averages, trust_breakdown all present
          • manual_review_required is a bool
        """
        uid = "http-test-" + _uid()
        ev_id_a = ev_id_b = None

        with _TEST_ENGINE.begin() as conn:
            eid_a = _insert_entity(conn, user_id=uid, entity_type="skill",
                                   name="Product Vision", confidence_score=80.0)
            ev_id_a = _insert_evidence(
                conn, entity_id=eid_a, user_id=uid,
                source_type="conversation_star", base_weight=72.0,
                raw_content="Led a 6-month roadmap rebuild for a 40-person engineering org.",
            )

            eid_b = _insert_entity(conn, user_id=uid, entity_type="skill",
                                   name="SQL", confidence_score=20.0)
            ev_id_b = _insert_evidence(
                conn, entity_id=eid_b, user_id=uid,
                source_type="cv_parse", base_weight=25.0,
                raw_content="Wrote complex SQL queries for BI reporting.",
            )

        client = self._make_client(uid)
        try:
            resp = client.get(f"/api/profile/{uid}/trust-score")
        finally:
            self._teardown_client(client)

        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        body = resp.json()

        # ── Top-level keys ────────────────────────────────────────────────────
        assert body["user_id"] == uid
        assert "overall_trust_score" in body
        assert "category_averages" in body
        assert "entities" in body
        assert "fetched_at" in body

        # ── score_breakdown: the three Holistic Familiarity pillars (Phase 32).
        assert "score_breakdown" in body
        sb = body["score_breakdown"]
        assert set(sb.keys()) == {"breadth", "depth", "context"}
        assert 0.0 <= sb["breadth"] <= 40.0
        assert 0.0 <= sb["depth"]   <= 40.0
        assert 0.0 <= sb["context"] <= 20.0
        # Pillars reconstruct the overall (within rounding).
        assert sb["breadth"] + sb["depth"] + sb["context"] == pytest.approx(
            body["overall_trust_score"], abs=0.2
        )

        # ── overall_trust_score: Phase 31 Holistic Familiarity.
        #    A thin, 2-entity profile (1 verified + 1 unverified skill, one
        #    category) with no saved base profile. Familiarity is genuinely low:
        #      breadth  = 40·(1−e^(−2/35))       ≈ 2.2
        #      depth    = 40·(1−e^(−1.0/8))      ≈ 4.7   (one verified entity)
        #      context  = coverage 8·(1/4)=2.0 + identity 0 + proficiency 0
        #    → ≈ 8.9. Raw confidence_score is not read; this reflects how
        #    little the system yet knows this user, not their skill.
        # (category_averages below is a SEPARATE plain-average field used
        #  only for display — e.g. the radar chart — and is unaffected.)
        assert body["overall_trust_score"] == pytest.approx(8.9, abs=0.3)

        # ── category_averages ────────────────────────────────────────────────
        cat = body["category_averages"]
        assert set(cat.keys()) == {"skill", "trait", "domain", "experience"}
        assert cat["skill"] == pytest.approx(50.0, abs=0.2)   # (80+20)/2
        assert cat["trait"]      == 0.0
        assert cat["domain"]     == 0.0
        assert cat["experience"] == 0.0

        # ── entities ─────────────────────────────────────────────────────────
        assert len(body["entities"]) == 2

        # Entities sorted confidence DESC → [80.0, 20.0]
        high, low = body["entities"][0], body["entities"][1]

        assert high["name"]             == "Product Vision"
        assert high["confidence_score"] == pytest.approx(80.0, abs=0.1)
        assert high["entity_type"]      == "skill"
        assert isinstance(high["manual_review_required"], bool)
        assert high["manual_review_required"] is False

        assert low["name"]             == "SQL"
        assert low["confidence_score"] == pytest.approx(20.0, abs=0.1)

        # ── trust_breakdown ──────────────────────────────────────────────────
        tb_high = high["trust_breakdown"]
        assert len(tb_high) == 1
        assert tb_high[0]["source_type"]  == "conversation_star"
        assert tb_high[0]["source_label"] == "STAR Behavioral Probe"
        assert tb_high[0]["evidence_id"]  == ev_id_a
        assert "verified_at" in tb_high[0]
        assert "raw_content" in tb_high[0]
        assert "base_weight" in tb_high[0]

        tb_low = low["trust_breakdown"]
        assert len(tb_low) == 1
        assert tb_low[0]["source_type"]  == "cv_parse"
        assert tb_low[0]["source_label"] == "CV Parse"
        assert tb_low[0]["evidence_id"]  == ev_id_b

    # ── Test: zero-entity guard ───────────────────────────────────────────────

    def test_empty_profile_returns_200_not_500(self):
        """A user with 0 entities must return HTTP 200 with empty lists."""
        uid = "http-empty-" + _uid()

        client = self._make_client(uid)
        try:
            resp = client.get(f"/api/profile/{uid}/trust-score")
        finally:
            self._teardown_client(client)

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["overall_trust_score"] == 0.0
        assert body["entities"] == []
        cat = body["category_averages"]
        assert cat["skill"] == 0.0
        assert cat["experience"] == 0.0

    # ── Test: 403 when accessing another user's data ─────────────────────────

    def test_cross_user_access_returns_403(self):
        """Authenticated as user A, requesting user B's trust score → 403."""
        caller_uid = "caller-" + _uid()
        target_uid = "target-" + _uid()

        client = self._make_client(caller_uid)
        try:
            resp = client.get(f"/api/profile/{target_uid}/trust-score")
        finally:
            self._teardown_client(client)

        assert resp.status_code == 403

    # ── Test: hard-expired evidence excluded ─────────────────────────────────

    def test_hard_expired_evidence_excluded_from_breakdown(self):
        """Evidence rows with hard_expires_at in the past must not appear."""
        uid = "http-expiry-" + _uid()
        past_iso = "2000-01-01T00:00:00+00:00"   # safely in the past

        with _TEST_ENGINE.begin() as conn:
            eid = _insert_entity(conn, user_id=uid, entity_type="experience",
                                 name="Engineering Director", confidence_score=90.0)
            # Valid evidence
            _insert_evidence(conn, entity_id=eid, user_id=uid,
                             source_type="certification", base_weight=55.0,
                             raw_content="Active cert.")
            # Hard-expired evidence — must not appear in breakdown
            _insert_evidence(conn, entity_id=eid, user_id=uid,
                             source_type="certification", base_weight=55.0,
                             raw_content="Expired cert.",
                             hard_expires_at=past_iso)

        client = self._make_client(uid)
        try:
            resp = client.get(f"/api/profile/{uid}/trust-score")
        finally:
            self._teardown_client(client)

        assert resp.status_code == 200
        body = resp.json()
        assert len(body["entities"]) == 1
        # Only the non-expired evidence should appear
        breakdown = body["entities"][0]["trust_breakdown"]
        assert len(breakdown) == 1
        assert breakdown[0]["raw_content"] == "Active cert."

    # ── Test: manual_review_required bool casting ─────────────────────────────

    def test_manual_review_required_is_bool(self):
        """The INTEGER 0/1 stored in SQLite must be returned as a JSON bool."""
        uid = "http-manual-" + _uid()

        with _TEST_ENGINE.begin() as conn:
            _insert_entity(conn, user_id=uid, entity_type="skill",
                           name="Leadership", confidence_score=15.0,
                           manual_review_required=1)

        client = self._make_client(uid)
        try:
            resp = client.get(f"/api/profile/{uid}/trust-score")
        finally:
            self._teardown_client(client)

        assert resp.status_code == 200
        entity = resp.json()["entities"][0]
        # Must be a proper Python bool in JSON, not the integer 1
        assert entity["manual_review_required"] is True
        assert type(entity["manual_review_required"]) is bool
