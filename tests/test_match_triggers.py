"""
Tests for the high-match trigger logic (JOB-43).

Covers:
  • Threshold boundaries (inclusive at the threshold, exclusive below).
  • Thin-JD / non-LLM-validated exclusion (CLAUDE.md Principle 4).
  • Exactly-once dedup per (user, job) pair across re-scores.
  • Async fire-and-forget execution that never blocks or raises into the
    scoring pipeline.
  • The consumer API (fetch pending → mark consumed).

Uses an isolated on-disk SQLite engine per test — never the production
backend/jobs.db.
"""
import asyncio

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.core.database import Base
from backend.models.matching import MatchTriggerRow
from backend.models import application, ariel, job, kv, matching, profile  # noqa: F401
from backend.services.match_trigger_service import (
    evaluate_match_trigger,
    fetch_pending_triggers,
    mark_triggers_consumed,
    schedule_match_trigger,
    should_trigger,
)

THRESHOLD = 85.0


@pytest.fixture
def engine(tmp_path):
    eng = create_engine(f"sqlite:///{tmp_path / 'triggers_test.db'}")
    Base.metadata.create_all(eng)
    return eng


def _score(total: float, *, llm_validated: bool = True, semantic: float = 70.0) -> dict:
    """Minimal MatchScoreResult.as_dict()-compatible payload."""
    return {
        "total":          total,
        "llm_validated":  llm_validated,
        "semantic_score": semantic,
        "why_ron":        "Strong PM fit with direct B2B SaaS background.",
    }


def _row_count(engine) -> int:
    with Session(engine) as s:
        return s.query(MatchTriggerRow).count()


# ── Decision layer: threshold boundaries ─────────────────────────────────────

def test_fires_exactly_at_threshold():
    assert should_trigger(_score(85.0), THRESHOLD).fired is True


def test_does_not_fire_just_below_threshold():
    assert should_trigger(_score(84.9), THRESHOLD).fired is False


def test_fires_above_threshold():
    assert should_trigger(_score(97.3), THRESHOLD).fired is True


def test_threshold_is_configurable_not_hardcoded():
    # 87 qualifies at the default 85 but must NOT at an explicit 90.
    assert should_trigger(_score(87.0), 90.0).fired is False
    assert should_trigger(_score(91.0), 90.0).fired is True


# ── Decision layer: thin-JD / Principle 4 protection ─────────────────────────

def test_thin_jd_high_total_never_fires():
    # The thin-JD path returns llm_validated=False with semantic=0. Even a
    # (hypothetical) high total must never trigger.
    d = should_trigger(_score(95.0, llm_validated=False, semantic=0.0), THRESHOLD)
    assert d.fired is False
    assert d.reason == "not_llm_validated"


def test_phase1_only_fast_path_never_fires():
    # run_llm_validation=False paths produce llm_validated=False.
    assert should_trigger(_score(99.0, llm_validated=False), THRESHOLD).fired is False


def test_zero_semantic_never_fires_even_if_validated():
    d = should_trigger(_score(95.0, llm_validated=True, semantic=0.0), THRESHOLD)
    assert d.fired is False
    assert d.reason == "no_semantic_signal"


# ── Trigger execution + persistence ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_evaluate_persists_qualifying_trigger(engine):
    fired = await evaluate_match_trigger(
        "job-1", "user-1", _score(92.0),
        job_title="Senior Product Manager", company_name="Acme",
        threshold=THRESHOLD, engine=engine,
    )
    assert fired is True
    assert _row_count(engine) == 1

    with Session(engine) as s:
        row = s.query(MatchTriggerRow).one()
        assert row.user_id == "user-1"
        assert row.job_id == "job-1"
        assert row.score == 92.0          # 1-decimal precision preserved
        assert row.threshold == THRESHOLD
        assert row.status == "pending"


@pytest.mark.asyncio
async def test_evaluate_below_threshold_writes_nothing(engine):
    fired = await evaluate_match_trigger(
        "job-1", "user-1", _score(70.0), threshold=THRESHOLD, engine=engine,
    )
    assert fired is False
    assert _row_count(engine) == 0


@pytest.mark.asyncio
async def test_exactly_once_per_user_job_pair(engine):
    # First qualifying score fires…
    first = await evaluate_match_trigger(
        "job-1", "user-1", _score(90.0), threshold=THRESHOLD, engine=engine,
    )
    # …re-scores of the same job (same, higher, or lower value) never re-fire.
    second = await evaluate_match_trigger(
        "job-1", "user-1", _score(90.0), threshold=THRESHOLD, engine=engine,
    )
    third = await evaluate_match_trigger(
        "job-1", "user-1", _score(96.5), threshold=THRESHOLD, engine=engine,
    )
    assert (first, second, third) == (True, False, False)
    assert _row_count(engine) == 1


@pytest.mark.asyncio
async def test_dedup_is_scoped_per_user_and_per_job(engine):
    assert await evaluate_match_trigger(
        "job-1", "user-1", _score(90.0), threshold=THRESHOLD, engine=engine)
    # Same job, different user → independent trigger.
    assert await evaluate_match_trigger(
        "job-1", "user-2", _score(90.0), threshold=THRESHOLD, engine=engine)
    # Same user, different job → independent trigger.
    assert await evaluate_match_trigger(
        "job-2", "user-1", _score(90.0), threshold=THRESHOLD, engine=engine)
    assert _row_count(engine) == 3


# ── Async / non-blocking behaviour ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_schedule_returns_immediately_and_completes_in_background(engine):
    task = schedule_match_trigger(
        "job-1", "user-1", _score(90.0),
        job_title="PM", company_name="Acme",
        threshold=THRESHOLD, engine=engine,
    )
    # Fire-and-forget: the caller gets a Task, not a result — the scoring
    # pipeline does not await persistence.
    assert isinstance(task, asyncio.Task)
    assert await task is True
    assert _row_count(engine) == 1


@pytest.mark.asyncio
async def test_schedule_swallows_persistence_failures(engine, caplog):
    # A broken engine must not raise into the pipeline — only log.
    class ExplodingEngine:
        def connect(self):        # pragma: no cover - never reached via Session
            raise RuntimeError("db down")

    task = schedule_match_trigger(
        "job-1", "user-1", _score(90.0),
        threshold=THRESHOLD, engine=ExplodingEngine(),
    )
    assert task is not None
    # Awaiting the task must not propagate; the done-callback logs the error.
    with caplog.at_level("WARNING"):
        await asyncio.gather(task, return_exceptions=True)
        await asyncio.sleep(0)   # let the done-callback run
    assert any("non-fatal" in r.message for r in caplog.records)


def test_schedule_without_event_loop_is_a_safe_noop(engine):
    # Pure-sync callers (no running loop) skip trigger evaluation entirely.
    assert schedule_match_trigger(
        "job-1", "user-1", _score(90.0), threshold=THRESHOLD, engine=engine,
    ) is None
    assert _row_count(engine) == 0


# ── Consumer API ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_pending_fetch_and_consume_roundtrip(engine):
    await evaluate_match_trigger(
        "job-1", "user-1", _score(91.0),
        job_title="Senior PM", company_name="Acme",
        threshold=THRESHOLD, engine=engine,
    )
    await evaluate_match_trigger(
        "job-2", "user-1", _score(88.0),
        job_title="Product Lead", company_name="Globex",
        threshold=THRESHOLD, engine=engine,
    )

    pending = fetch_pending_triggers("user-1", engine=engine)
    assert len(pending) == 2
    assert pending[0]["job_id"] == "job-2"          # newest first
    assert pending[0]["title"] == "Product Lead"    # payload usable without a join
    assert pending[0]["company"] == "Globex"
    assert pending[0]["score"] == 88.0

    consumed = mark_triggers_consumed([p["id"] for p in pending], engine=engine)
    assert consumed == 2
    assert fetch_pending_triggers("user-1", engine=engine) == []

    # Consuming must not delete rows — the row is the dedup record, so the
    # same job still cannot re-fire afterwards.
    assert _row_count(engine) == 2
    refire = await evaluate_match_trigger(
        "job-1", "user-1", _score(95.0), threshold=THRESHOLD, engine=engine,
    )
    assert refire is False


@pytest.mark.asyncio
async def test_pending_fetch_is_scoped_to_user(engine):
    await evaluate_match_trigger(
        "job-1", "user-1", _score(91.0), threshold=THRESHOLD, engine=engine)
    await evaluate_match_trigger(
        "job-1", "user-2", _score(91.0), threshold=THRESHOLD, engine=engine)

    assert len(fetch_pending_triggers("user-1", engine=engine)) == 1
    assert len(fetch_pending_triggers("user-2", engine=engine)) == 1
    assert fetch_pending_triggers("user-3", engine=engine) == []
