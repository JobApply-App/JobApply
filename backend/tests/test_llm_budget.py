"""
Background LLM work is capped per user per day and stops during an outage.

On the first day ten real users were in the matching pipeline, the bridge
added ~2,400 matches and the enrichment loop sent every one of them to the
LLM (~4 calls each, every 30s sweep). That exhausted the Gemini quota and the
Anthropic credit balance; from then on Ariel, CV upload and scoring failed for
everyone. While providers were down, each sweep also counted the failure
against every pending job, retiring them permanently after three sweeps.

These tests pin the brake: a daily per-user budget, a per-sweep cap, best
jobs first, no LLM calls at all while providers are down, and no job
penalised for an outage.
"""
import uuid
from types import SimpleNamespace

import pytest

from backend.services import feed_service, llm_budget, llm_client


@pytest.fixture(autouse=True)
def _providers_up():
    llm_client._PROVIDERS_DOWN_UNTIL = 0.0
    yield
    llm_client._PROVIDERS_DOWN_UNTIL = 0.0


@pytest.fixture()
def uid(db_available):
    from sqlalchemy import text
    from backend.core.database import ENGINE
    u = str(uuid.uuid4())
    yield u
    with ENGINE.begin() as c:
        c.execute(text("DELETE FROM kv_store WHERE key LIKE :k"), {"k": f"llm_enrich_budget:{u}:%"})


# ── Budget ───────────────────────────────────────────────────────────────────

def test_budget_is_consumed_then_refused(uid, monkeypatch):
    monkeypatch.setattr("backend.config.ENRICH_DAILY_BUDGET_PER_USER", 3)
    assert llm_budget.remaining(uid) == 3
    assert [llm_budget.consume(uid) for _ in range(4)] == [True, True, True, False]
    assert llm_budget.remaining(uid) == 0


def test_budget_is_per_user(uid, monkeypatch):
    monkeypatch.setattr("backend.config.ENRICH_DAILY_BUDGET_PER_USER", 1)
    other = str(uuid.uuid4())
    assert llm_budget.consume(uid)
    assert llm_budget.remaining(other) == 1


# ── Outage detection ─────────────────────────────────────────────────────────

class _FakeExc(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status_code = status


def test_exhausted_credit_opens_the_outage_gate():
    assert not llm_client.providers_unavailable()
    llm_client._classify_anthropic_failure(
        _FakeExc(400, "Your credit balance is too low to access the Anthropic API.")
    )
    assert llm_client.providers_unavailable()


def test_an_ordinary_bad_request_does_not():
    llm_client._classify_anthropic_failure(_FakeExc(400, "messages: field required"))
    assert not llm_client.providers_unavailable()


# ── The enrichment sweep ─────────────────────────────────────────────────────

def _job(job_id, score):
    return SimpleNamespace(
        job_id=job_id, title="Analyst", company="Acme", apply_url="https://example.com/j",
        jd_text="x" * 2000, jd_structured="{}", fit_brief=None, score_is_proxy=True,
        enrichment_failures=0, match_score=score, score=score, posted_at="", reasons=[],
    )


@pytest.fixture()
def sweep(uid, monkeypatch):
    """refresh_user_scores with the feed, profile and LLM scoring stubbed out."""
    jobs = [_job(f"j{i}", float(i)) for i in range(10)]
    calls, failures = [], []

    monkeypatch.setattr(feed_service.job_store, "get_feed", lambda user_id: jobs)
    monkeypatch.setattr(feed_service, "_needs_enrichment", lambda j: True)
    monkeypatch.setattr(feed_service, "_build_profile_cv_proxy", lambda *a, **k: {})
    monkeypatch.setattr("backend.services.user_profile.get_profile", lambda user_id: {})
    monkeypatch.setattr("backend.services.master_profile_service.get_skill_proficiencies", lambda user_id: {})
    monkeypatch.setattr(
        "backend.services.confidence_matrix_service.get_entity_breakdown", lambda *a, **k: []
    )
    monkeypatch.setattr(
        feed_service.job_store, "increment_enrichment_failures",
        lambda job_id: failures.append(job_id) or 1,
    )

    async def _score(**kw):
        calls.append(kw["job_id"])
        raise llm_client.LLMCallError("down")
    monkeypatch.setattr(feed_service, "compute_match_score_async", _score)
    return SimpleNamespace(uid=uid, calls=calls, failures=failures)


async def test_sweep_sends_at_most_a_few_jobs_best_first(sweep, monkeypatch):
    monkeypatch.setattr("backend.config.ENRICH_DAILY_BUDGET_PER_USER", 10)
    await feed_service.refresh_user_scores(sweep.uid)
    assert sorted(sweep.calls) == ["j7", "j8", "j9"]   # _ENRICH_PER_SWEEP, highest scores


async def test_sweep_stops_at_the_daily_budget(sweep, monkeypatch):
    monkeypatch.setattr("backend.config.ENRICH_DAILY_BUDGET_PER_USER", 4)
    for _ in range(5):
        await feed_service.refresh_user_scores(sweep.uid)
    assert len(sweep.calls) == 4
    assert llm_budget.remaining(sweep.uid) == 0


async def test_no_llm_calls_while_providers_are_down(sweep):
    llm_client._mark_outage(60, "test")
    assert await feed_service.refresh_user_scores(sweep.uid) == 0
    assert sweep.calls == []


async def test_an_outage_mid_sweep_does_not_retire_jobs(sweep, monkeypatch):
    async def _score_and_go_down(**kw):
        sweep.calls.append(kw["job_id"])
        llm_client._mark_outage(60, "credit exhausted mid-sweep")
        raise llm_client.LLMCallError("down")
    monkeypatch.setattr(feed_service, "compute_match_score_async", _score_and_go_down)
    await feed_service.refresh_user_scores(sweep.uid)
    assert sweep.calls, "the sweep never reached the LLM"
    assert sweep.failures == []


async def test_a_user_opened_job_is_not_charged_to_the_budget(sweep, monkeypatch):
    monkeypatch.setattr("backend.config.ENRICH_DAILY_BUDGET_PER_USER", 2)
    await feed_service.refresh_user_scores(sweep.uid, only_job_id="j0")
    assert sweep.calls == ["j0"]
    assert llm_budget.remaining(sweep.uid) == 2
