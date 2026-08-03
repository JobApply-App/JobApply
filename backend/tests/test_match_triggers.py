"""
Tests for the high-match trigger logic (JOB-43).

Covers:
  • Threshold boundaries (inclusive at the threshold, exclusive below).
  • Thin-JD / non-LLM-validated exclusion (CLAUDE.md Principle 4).
  • Exactly-once dedup per (user, job) pair across re-scores.
  • Async fire-and-forget execution that never blocks or raises into the
    scoring pipeline.
  • The consumer API (fetch pending → mark consumed).

Runs against Dev Postgres via the db_available fixture. Trigger state stopped
being its own table in migration 3542b0021d6b and is now columns on
user_job_matches, which is Postgres-only and whose user_id has a hard FK to
auth.users — so an isolated SQLite file can no longer hold it. Two stable QA
accounts stand in for "two users", and every match row these tests create is
removed again afterwards.

One behaviour changed with that fold and is now asserted directly: a trigger
attaches to an existing match, so firing one for a (user, job) pair with no
user_job_matches row is a no-op rather than an orphaned insert.
"""
import asyncio
import uuid

import pytest
from sqlalchemy import text

from backend.core.database import ENGINE
from backend.models import application, ariel, kv, matching, profile  # noqa: F401
from backend.services.match_trigger_service import (
    evaluate_match_trigger,
    fetch_pending_triggers,
    mark_triggers_consumed,
    schedule_match_trigger,
    should_trigger,
)

THRESHOLD = 85.0


_QA_A = "2631c93b-93bb-4313-a2c2-79dbb786d199"   # qa.test2.jobapply.claude@gmail.com
_QA_B = "b0dbf35a-929c-4db3-a04a-24fbe3a3d59d"   # qa-test-linkedin-tab@example.com


def _score(total: float, *, llm_validated: bool = True, semantic: float = 70.0) -> dict:
    """Minimal MatchScoreResult.as_dict()-compatible payload."""
    return {
        "total":          total,
        "llm_validated":  llm_validated,
        "semantic_score": semantic,
        "fit_brief":      "Strong PM fit with direct B2B SaaS background.",
    }


class _Matches:
    """
    The (user, job) match rows a test operates on. `engine` is passed straight
    through to the service so the existing call sites read unchanged.
    """

    def __init__(self):
        self.engine = ENGINE
        self.job_ids: list[str] = []

    def add(self, user_id: str, *, title: str = "Senior PM", company: str = "Acme") -> str:
        """Create a match for user_id and return its external job_id."""
        from backend.repositories import job_repository as job_store
        from backend.schemas.job import DetailedAnalysis, JobMatch

        job_id = f"trigger-test-{uuid.uuid4()}"
        job_store.save_with_source_priority(JobMatch(
            job_id=job_id, title=f"{title} {uuid.uuid4().hex[:6]}", company=company,
            location="Remote", score=80.0, confidence_score=50, culture_fit_score=50,
            trajectory_alignment="", company_dna_inference="",
            detailed_analysis=DetailedAnalysis(strengths=[], critical_gaps=[], strategic_advice=[]),
            investigation_points=[], reasons=[], user_id=user_id, match_score=0.0,
            status="new", is_new=True, posted_at="", source="automatic", is_open=True,
            source_type="other", score_is_proxy=False,
        ))
        self.job_ids.append(job_id)
        return job_id

    def triggered(self) -> int:
        """How many of this test's matches carry trigger state."""
        if not self.job_ids:
            return 0
        with ENGINE.connect() as c:
            return c.execute(text(
                "SELECT count(*) FROM public.user_job_matches "
                "WHERE job_id = ANY(:ids) AND trigger_state IS NOT NULL"
            ), {"ids": self.job_ids}).scalar()

    def cleanup(self) -> None:
        if not self.job_ids:
            return
        with ENGINE.begin() as c:
            postings = c.execute(text(
                "SELECT job_posting_id FROM public.user_job_matches WHERE job_id = ANY(:ids)"
            ), {"ids": self.job_ids}).fetchall()
            c.execute(text("DELETE FROM public.user_job_matches WHERE job_id = ANY(:ids)"),
                      {"ids": self.job_ids})
            for (pid,) in postings:
                c.execute(text("DELETE FROM public.job_postings WHERE id = :p"), {"p": pid})


@pytest.fixture
def matches(db_available):
    m = _Matches()
    yield m
    m.cleanup()


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
async def test_evaluate_persists_qualifying_trigger(matches):
    job = matches.add(_QA_A, title="Senior Product Manager")
    fired = await evaluate_match_trigger(
        job, _QA_A, _score(92.0),
        job_title="Senior Product Manager", company_name="Acme",
        threshold=THRESHOLD, engine=matches.engine,
    )
    assert fired is True
    assert matches.triggered() == 1

    with ENGINE.connect() as c:
        row = c.execute(text(
            "SELECT user_id, trigger_score, trigger_threshold, trigger_state "
            "FROM public.user_job_matches WHERE job_id = :j"), {"j": job}).one()
    assert str(row.user_id) == _QA_A
    assert row.trigger_score == 92.0          # 1-decimal precision preserved
    assert row.trigger_threshold == THRESHOLD
    assert row.trigger_state == "pending"


@pytest.mark.asyncio
async def test_evaluate_below_threshold_writes_nothing(matches):
    job = matches.add(_QA_A)
    fired = await evaluate_match_trigger(
        job, _QA_A, _score(70.0), threshold=THRESHOLD, engine=matches.engine,
    )
    assert fired is False
    assert matches.triggered() == 0


@pytest.mark.asyncio
async def test_exactly_once_per_user_job_pair(matches):
    job = matches.add(_QA_A)
    # First qualifying score fires…
    first = await evaluate_match_trigger(
        job, _QA_A, _score(90.0), threshold=THRESHOLD, engine=matches.engine,
    )
    # …re-scores of the same job (same, higher, or lower value) never re-fire.
    second = await evaluate_match_trigger(
        job, _QA_A, _score(90.0), threshold=THRESHOLD, engine=matches.engine,
    )
    third = await evaluate_match_trigger(
        job, _QA_A, _score(96.5), threshold=THRESHOLD, engine=matches.engine,
    )
    assert (first, second, third) == (True, False, False)
    assert matches.triggered() == 1


@pytest.mark.asyncio
async def test_dedup_is_scoped_per_user_and_per_job(matches):
    a_job = matches.add(_QA_A, title="Shared Role", company="Globex")
    # Same posting, different user → its own match row, its own trigger.
    b_job = matches.add(_QA_B, title="Shared Role", company="Globex")
    # Same user, different job → independent trigger.
    a_job2 = matches.add(_QA_A, title="Other Role")

    assert await evaluate_match_trigger(
        a_job, _QA_A, _score(90.0), threshold=THRESHOLD, engine=matches.engine)
    assert await evaluate_match_trigger(
        b_job, _QA_B, _score(90.0), threshold=THRESHOLD, engine=matches.engine)
    assert await evaluate_match_trigger(
        a_job2, _QA_A, _score(90.0), threshold=THRESHOLD, engine=matches.engine)
    assert matches.triggered() == 3


# ── Async / non-blocking behaviour ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_schedule_returns_immediately_and_completes_in_background(matches):
    job = matches.add(_QA_A)
    task = schedule_match_trigger(
        job, _QA_A, _score(90.0),
        job_title="PM", company_name="Acme",
        threshold=THRESHOLD, engine=matches.engine,
    )
    # Fire-and-forget: the caller gets a Task, not a result — the scoring
    # pipeline does not await persistence.
    assert isinstance(task, asyncio.Task)
    assert await task is True
    assert matches.triggered() == 1


@pytest.mark.asyncio
async def test_schedule_swallows_persistence_failures(caplog):
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


def test_schedule_without_event_loop_is_a_safe_noop(matches):
    # Pure-sync callers (no running loop) skip trigger evaluation entirely.
    job = matches.add(_QA_A)
    assert schedule_match_trigger(
        job, _QA_A, _score(90.0), threshold=THRESHOLD, engine=matches.engine,
    ) is None
    assert matches.triggered() == 0


# ── Consumer API ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_pending_fetch_and_consume_roundtrip(matches):
    job1 = matches.add(_QA_A, title="Senior PM", company="Acme")
    job2 = matches.add(_QA_A, title="Product Lead", company="Globex")

    await evaluate_match_trigger(
        job1, _QA_A, _score(91.0),
        job_title="Senior PM", company_name="Acme",
        threshold=THRESHOLD, engine=matches.engine,
    )
    await evaluate_match_trigger(
        job2, _QA_A, _score(88.0),
        job_title="Product Lead", company_name="Globex",
        threshold=THRESHOLD, engine=matches.engine,
    )

    pending = [p for p in fetch_pending_triggers(_QA_A, engine=matches.engine)
               if p["job_id"] in matches.job_ids]
    assert len(pending) == 2
    assert pending[0]["job_id"] == job2                    # newest first
    # title/company now come from the joined posting rather than a frozen
    # payload blob, which is the point of the fold — they cannot go stale.
    assert pending[0]["title"].startswith("Product Lead")
    assert pending[0]["company"] == "Globex"
    assert pending[0]["score"] == 88.0

    consumed = mark_triggers_consumed([p["id"] for p in pending], engine=matches.engine)
    assert consumed == 2
    assert [p for p in fetch_pending_triggers(_QA_A, engine=matches.engine)
            if p["job_id"] in matches.job_ids] == []

    # Consuming must not clear the state — it IS the dedup record, so the same
    # job still cannot re-fire afterwards.
    assert matches.triggered() == 2
    refire = await evaluate_match_trigger(
        job1, _QA_A, _score(95.0), threshold=THRESHOLD, engine=matches.engine,
    )
    assert refire is False


@pytest.mark.asyncio
async def test_pending_fetch_is_scoped_to_user(matches):
    a_job = matches.add(_QA_A)
    b_job = matches.add(_QA_B)
    await evaluate_match_trigger(
        a_job, _QA_A, _score(91.0), threshold=THRESHOLD, engine=matches.engine)
    await evaluate_match_trigger(
        b_job, _QA_B, _score(91.0), threshold=THRESHOLD, engine=matches.engine)

    mine = lambda uid: [p for p in fetch_pending_triggers(uid, engine=matches.engine)
                        if p["job_id"] in matches.job_ids]
    assert [p["job_id"] for p in mine(_QA_A)] == [a_job]
    assert [p["job_id"] for p in mine(_QA_B)] == [b_job]


@pytest.mark.asyncio
async def test_trigger_without_a_match_row_is_a_noop(matches):
    """
    Behaviour introduced by the fold into user_job_matches (3542b0021d6b):
    trigger state lives ON the match, so there is nothing to attach to when the
    user has never matched that job. The old standalone table would have
    accepted the row and orphaned it.
    """
    fired = await evaluate_match_trigger(
        f"never-matched-{uuid.uuid4()}", _QA_A, _score(95.0),
        threshold=THRESHOLD, engine=matches.engine,
    )
    assert fired is False
