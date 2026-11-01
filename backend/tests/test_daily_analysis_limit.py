"""The daily limit of AI job analyses (deps.consume_daily_analysis): ten a
day per user, counted in the kv table, and a cached analysis never counts."""
from types import SimpleNamespace

import pytest

from backend.api import deps
from backend.core.errors import AppError


@pytest.fixture()
def kv(monkeypatch):
    store: dict[str, str] = {}
    from backend.repositories import kv_repository
    monkeypatch.setattr(kv_repository, "get", lambda key, session=None: SimpleNamespace(value=store[key]) if key in store else None)
    monkeypatch.setattr(kv_repository, "upsert", lambda key, value, *a, **k: store.__setitem__(key, value))
    return store


def test_ten_analyses_pass_and_the_eleventh_is_refused(kv):
    for _ in range(deps.DAILY_ANALYSIS_CAP):
        deps.consume_daily_analysis("user-a")
    with pytest.raises(AppError) as exc:
        deps.consume_daily_analysis("user-a")
    assert exc.value.status_code == 429
    assert exc.value.code == "daily_analysis_limit"


def test_each_user_has_their_own_count(kv):
    for _ in range(deps.DAILY_ANALYSIS_CAP):
        deps.consume_daily_analysis("user-a")
    deps.consume_daily_analysis("user-b")   # does not raise


def test_the_cap_is_ten():
    assert deps.DAILY_ANALYSIS_CAP == 10


def test_opening_an_analysed_job_does_not_count(kv, monkeypatch):
    import asyncio

    from backend.api.routes import jobs

    analysed = SimpleNamespace(job_id="j1", fit_brief="Strong fit.", score_is_proxy=False, enrichment_failures=0)
    monkeypatch.setattr(jobs.job_store, "get_by_id", lambda job_id, user_id: analysed)
    user = SimpleNamespace(user_id="user-a")
    asyncio.run(jobs.analyze_job_now("j1", user=user))
    assert kv == {}
