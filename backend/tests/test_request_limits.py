"""
Request-level protection: an oversized body is refused before it is read, and
rate-limit counters can live in Redis so every instance shares them.
"""
import asyncio

import pytest
from fastapi.testclient import TestClient


def test_oversized_json_body_is_refused_with_413():
    from backend.main import app
    r = TestClient(app).post("/api/resumes/render-pdf", content=b"{}",
                             headers={"content-type": "application/json",
                                      "content-length": str(50 * 1024 * 1024)})
    assert r.status_code == 413 and r.json()["code"] == "payload_too_large"


class _FakePipe:
    def __init__(self, store, fail):
        self.store, self.fail, self.ops = store, fail, []

    def incr(self, k):
        self.ops.append(k)

    def expire(self, k, s):
        pass

    async def execute(self):
        if self.fail:
            raise ConnectionError("redis down")
        k = self.ops[0]
        self.store[k] = self.store.get(k, 0) + 1
        return [self.store[k], True]


class _FakeRedis:
    def __init__(self, fail=False):
        self.store, self.fail = {}, fail

    def pipeline(self):
        return _FakePipe(self.store, self.fail)


class _Req:
    headers = {"authorization": ""}
    client = type("C", (), {"host": "203.0.113.9"})()


def _limiter(monkeypatch, fake):
    import backend.api.deps as deps
    monkeypatch.setattr(deps, "_redis_client", lambda: fake)
    return deps.RateLimiter(max_requests=2, window_seconds=60, scope=f"t{id(fake)}")


async def test_counters_in_redis_enforce_the_limit(monkeypatch):
    from backend.core.errors import AppError
    fake = _FakeRedis()
    lim = _limiter(monkeypatch, fake)
    await lim(_Req())
    await lim(_Req())
    with pytest.raises(AppError) as e:
        await lim(_Req())
    assert e.value.status_code == 429 and fake.store, "the count must be kept in Redis"


async def test_a_redis_outage_falls_back_to_memory_limits(monkeypatch):
    from backend.core.errors import AppError
    lim = _limiter(monkeypatch, _FakeRedis(fail=True))
    await lim(_Req())
    await lim(_Req())
    with pytest.raises(AppError):
        await lim(_Req())


class _AuthReq:
    def __init__(self, token):
        self.headers = {"authorization": f"Bearer {token}"}
        self.client = type("C", (), {"host": "10.0.0.5"})()


def _fake_verifier(monkeypatch, valid: dict):
    """Only tokens in `valid` verify (token -> user id); everything else is forged."""
    import backend.api.deps as deps
    from types import SimpleNamespace

    def verify(token, jwt, err):
        if token not in valid:
            raise ValueError("bad signature")
        return SimpleNamespace(user_id=valid[token])

    monkeypatch.setattr(deps, "_SUPABASE_URL", None)
    monkeypatch.setattr(deps, "_verify_hs256_identity", verify)
    deps._RATE_SUB_CACHE.clear()


async def test_forged_tokens_share_one_bucket_instead_of_one_each(monkeypatch):
    import backend.api.deps as deps
    _fake_verifier(monkeypatch, {})
    a = await deps._rate_identity(_AuthReq("forged-sub-1"))
    b = await deps._rate_identity(_AuthReq("forged-sub-2"))
    assert a == b and a.startswith("unverified:")


async def test_a_valid_token_is_keyed_by_its_user(monkeypatch):
    import backend.api.deps as deps
    _fake_verifier(monkeypatch, {"good": "user-123"})
    assert await deps._rate_identity(_AuthReq("good")) == "user:user-123"


async def test_forging_tokens_cannot_escape_the_limit(monkeypatch):
    import backend.api.deps as deps
    from backend.core.errors import AppError
    _fake_verifier(monkeypatch, {})
    monkeypatch.setattr(deps, "_redis_client", lambda: None)
    lim = deps.RateLimiter(max_requests=3, window_seconds=60, scope="forge-test")
    for i in range(3):
        await lim(_AuthReq(f"forged-{i}"))
    with pytest.raises(AppError):
        await lim(_AuthReq("forged-new"))
