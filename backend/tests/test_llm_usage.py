"""
Phase 0 of docs/research/09-companies-and-costs.md: the llm_usage log, the
Gemini pause on a billing/quota refusal, and the two new daily ceilings.

No network and no database: provider clients, the usage writer and the
repositories are all patched.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from google.genai import errors as genai_errors

import backend.services.llm_client as llm
from backend.core.errors import AppError

# Captured at import, before conftest's autouse fixture swaps it for a no-op.
_REAL_WRITE_USAGE = llm._write_usage


@pytest.fixture(autouse=True)
def _reset_gemini_pause():
    llm._GEMINI_DOWN_UNTIL = 0.0
    yield
    llm._GEMINI_DOWN_UNTIL = 0.0


@pytest.fixture()
def written(monkeypatch):
    rows: list[dict] = []
    monkeypatch.setattr(llm, "_write_usage", lambda **row: rows.append(row))
    return rows


_KW = dict(
    system="s", messages=[{"role": "user", "content": "hi"}], model="claude-haiku-4-5",
    max_tokens=50, purpose="test_purpose", user_id="u-1", job_id="j-1",
)


def _anthropic_message(input_tokens=1000, output_tokens=1000, cache_read=None, cache_write=None):
    return SimpleNamespace(
        content=[SimpleNamespace(text="ok")],
        usage=SimpleNamespace(
            input_tokens=input_tokens, output_tokens=output_tokens,
            cache_read_input_tokens=cache_read, cache_creation_input_tokens=cache_write,
        ),
    )


# ── Price estimate ────────────────────────────────────────────────────────────

def test_cost_haiku_4_5():
    assert llm.estimate_cost_usd("claude-haiku-4-5", 1000, 1000) == pytest.approx(0.006)


def test_cost_dated_id_prices_like_its_alias():
    assert llm.estimate_cost_usd("claude-haiku-4-5-20251001", 1000, 1000) == pytest.approx(0.006)


def test_cost_cache_tokens():
    # Sonnet 4.6: read 1M at 0.1 x $3, write 1M at 1.25 x $3.
    assert llm.estimate_cost_usd("claude-sonnet-4-6", 0, 0, 1_000_000, 1_000_000) == pytest.approx(0.30 + 3.75)


def test_cost_unknown_model_is_none_not_guessed():
    assert llm.estimate_cost_usd("gemini-flash-latest", 1000, 1000) is None


# ── Recording ─────────────────────────────────────────────────────────────────

def test_anthropic_call_writes_one_row(written):
    async def run():
        with patch.object(llm, "_gemini_client", None), \
             patch.object(llm._client.messages, "create", new=AsyncMock(return_value=_anthropic_message())):
            await llm.call_llm(**_KW)
    asyncio.run(run())  # asyncio.run waits for the default executor, so the write has run

    assert len(written) == 1
    row = written[0]
    assert row["purpose"] == "test_purpose"
    assert row["provider"] == "anthropic"
    assert row["model"] == "claude-haiku-4-5"
    assert row["user_id"] == "u-1" and row["job_id"] == "j-1"
    assert row["input_tokens"] == 1000 and row["output_tokens"] == 1000
    assert row["cost_usd"] == pytest.approx(0.006)


def test_failed_call_writes_nothing(written):
    import anthropic, httpx
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    err = anthropic.BadRequestError("bad", response=httpx.Response(400, request=req), body=None)

    async def run():
        with patch.object(llm, "_gemini_client", None), \
             patch.object(llm._client.messages, "create", new=AsyncMock(side_effect=err)):
            with pytest.raises(llm.LLMCallError):
                await llm.call_llm(**_KW)
    asyncio.run(run())
    assert written == []


def test_usage_write_failure_does_not_fail_the_call(monkeypatch, caplog):
    def boom(**row):
        raise RuntimeError("db down")
    monkeypatch.setattr(llm, "_write_usage", _REAL_WRITE_USAGE)
    monkeypatch.setattr("backend.repositories.llm_usage_repository.record", boom)

    async def run():
        with patch.object(llm, "_gemini_client", None), \
             patch.object(llm._client.messages, "create", new=AsyncMock(return_value=_anthropic_message())):
            return await llm.call_llm(**_KW)
    result = asyncio.run(run())
    assert result.text == "ok"
    assert "USAGE LOG WRITE FAILED" in caplog.text


# ── Gemini pause ──────────────────────────────────────────────────────────────

def _gemini_raising(code: int) -> tuple[SimpleNamespace, AsyncMock]:
    gen = AsyncMock(side_effect=genai_errors.APIError(code, {"error": {"message": "x"}}))
    return SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(generate_content=gen))), gen


def test_gemini_402_pauses_gemini_for_later_calls(written):
    fake_gemini, gen = _gemini_raising(402)
    create = AsyncMock(return_value=_anthropic_message())

    async def run():
        with patch.object(llm, "_gemini_client", fake_gemini), \
             patch.object(llm._client.messages, "create", new=create):
            await llm.call_llm(**_KW)
            await llm.call_llm(**_KW)
    asyncio.run(run())

    assert gen.call_count == 1          # second call skipped Gemini entirely
    assert create.call_count == 2


def test_gemini_500_does_not_pause(written):
    fake_gemini, gen = _gemini_raising(500)

    async def run():
        with patch.object(llm, "_gemini_client", fake_gemini), \
             patch.object(llm._client.messages, "create", new=AsyncMock(return_value=_anthropic_message())):
            await llm.call_llm(**_KW)
            await llm.call_llm(**_KW)
    asyncio.run(run())
    assert gen.call_count == 2


# ── Daily ceilings ────────────────────────────────────────────────────────────

def _user():
    from backend.api.deps import CurrentUser
    return CurrentUser(user_id="u-1")


def test_spend_ceiling_blocks_at_cap(monkeypatch):
    from backend.api import deps
    monkeypatch.setattr("backend.repositories.llm_usage_repository.spend_today", lambda uid: deps.DAILY_AI_SPEND_CAP_USD)
    with pytest.raises(AppError) as exc:
        asyncio.run(deps.daily_ai_spend_limit(_user()))
    assert exc.value.status_code == 429


def test_spend_ceiling_allows_below_cap(monkeypatch):
    from backend.api import deps
    monkeypatch.setattr("backend.repositories.llm_usage_repository.spend_today", lambda uid: 0.5)
    asyncio.run(deps.daily_ai_spend_limit(_user()))


def test_public_chat_cap_counts_then_blocks(monkeypatch):
    from backend.api import deps
    store: dict[str, str] = {}
    monkeypatch.setattr("backend.repositories.kv_repository.get",
                        lambda k: SimpleNamespace(value=store[k]) if k in store else None)
    monkeypatch.setattr("backend.repositories.kv_repository.upsert", lambda k, v: store.__setitem__(k, v))

    for _ in range(deps.DAILY_PUBLIC_CHAT_CAP_PER_IP):
        deps.consume_daily_public_chat("1.2.3.4")
    with pytest.raises(AppError) as exc:
        deps.consume_daily_public_chat("1.2.3.4")
    assert exc.value.status_code == 429
    deps.consume_daily_public_chat("5.6.7.8")   # another address is unaffected


def test_spend_ceiling_lets_the_call_through_when_the_check_fails(monkeypatch, caplog):
    from backend.api import deps
    def boom(uid):
        raise RuntimeError("no table")
    monkeypatch.setattr("backend.repositories.llm_usage_repository.spend_today", boom)
    asyncio.run(deps.daily_ai_spend_limit(_user()))
    assert "DAILY AI SPEND CHECK DID NOT RUN" in caplog.text


# ── Gemini cost (2026-11-28: Gemini rows used to be logged with cost None) ───

def test_gemini_cost_by_served_model():
    # 1M fresh input + 1M output on gemini-3.8-flash before 2027.
    assert llm.gemini_cost_usd("gemini-3.8-flash", 1_000_000, 1_000_000, today="2026-11-28") == pytest.approx(0.75 + 3.75)


def test_gemini_cost_changes_on_the_published_date():
    assert llm.gemini_cost_usd("gemini-3.8-flash", 1_000_000, 0, today="2027-01-01") == pytest.approx(1.50)


def test_gemini_cached_tokens_are_part_of_the_prompt_not_extra():
    # 1M prompt of which 400k cached: 600k at 0.75 + 400k at 0.075.
    assert llm.gemini_cost_usd("gemini-3.8-flash", 1_000_000, 0, 400_000, today="2026-11-28") == pytest.approx(0.45 + 0.03)


def test_gemini_flash_lite_never_prices_as_flash():
    assert llm.gemini_cost_usd("gemini-3.5-flash-lite-001", 1_000_000, 0, today="2026-11-28") == pytest.approx(0.30)


def test_unknown_gemini_model_counts_at_the_dearest_rate_and_warns(caplog):
    llm._UNPRICED_GEMINI_WARNED.discard("gemini-9-flash")
    cost = llm.gemini_cost_usd("gemini-9-flash", 1_000_000, 0, today="2026-11-28")
    assert cost == pytest.approx(0.75)       # never 0, never None: it feeds the spend ceiling
    assert "NO PRICE for Gemini model" in caplog.text


def _gemini_ok(model_version="gemini-3.8-flash", candidates=1000, thoughts=3000):
    response = SimpleNamespace(
        model_version=model_version,
        usage_metadata=SimpleNamespace(
            prompt_token_count=2000, candidates_token_count=candidates,
            thoughts_token_count=thoughts, cached_content_token_count=None,
        ),
        candidates=[SimpleNamespace(content=SimpleNamespace(parts=[SimpleNamespace(text="ok", function_call=None)]))],
    )
    gen = AsyncMock(return_value=response)
    return SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(generate_content=gen)))


def test_gemini_call_logs_served_model_thinking_tokens_and_a_cost(written):
    async def run():
        with patch.object(llm, "_gemini_client", _gemini_ok()):
            await llm.call_llm(**_KW)
            await asyncio.sleep(0.05)       # the row is written off the event loop
    asyncio.run(run())

    row = written[0]
    assert row["provider"] == "gemini"
    assert row["model"] == "gemini-3.8-flash"          # what served it, not the alias
    assert row["output_tokens"] == 4000                # 1000 answer + 3000 thinking
    assert row["cost_usd"] is not None and row["cost_usd"] > 0


def test_gemini_row_counts_toward_spend_today(monkeypatch):
    """The ceiling sums cost_usd: a Gemini row with a cost now adds to it."""
    from backend.repositories import llm_usage_repository as repo
    from backend.api import deps

    rows: list[dict] = []
    monkeypatch.setattr(repo, "record", lambda **row: rows.append(row))
    monkeypatch.setattr(repo, "spend_today", lambda uid: sum(r["cost_usd"] or 0 for r in rows if r["user_id"] == uid))
    monkeypatch.setattr(llm, "_write_usage", _REAL_WRITE_USAGE)

    big = _gemini_ok(candidates=0, thoughts=0)
    big.aio.models.generate_content.return_value.usage_metadata.prompt_token_count = 3_000_000   # ~$2.25

    async def run():
        with patch.object(llm, "_gemini_client", big):
            await llm.call_llm(**_KW)
            await asyncio.sleep(0.05)
    asyncio.run(run())

    assert repo.spend_today("u-1") >= deps.DAILY_AI_SPEND_CAP_USD
    with pytest.raises(AppError) as exc:
        asyncio.run(deps.daily_ai_spend_limit(_user()))
    assert exc.value.status_code == 429


def test_gemini_stream_is_logged(written):
    chunks = [
        SimpleNamespace(candidates=[SimpleNamespace(content=SimpleNamespace(parts=[SimpleNamespace(text="he", function_call=None)]))],
                        usage_metadata=None, model_version="gemini-3.8-flash"),
        SimpleNamespace(candidates=[SimpleNamespace(content=SimpleNamespace(parts=[SimpleNamespace(text="llo", function_call=None)]))],
                        usage_metadata=SimpleNamespace(prompt_token_count=500, candidates_token_count=20,
                                                       thoughts_token_count=80, cached_content_token_count=None),
                        model_version="gemini-3.8-flash"),
    ]

    async def agen():
        for c in chunks:
            yield c

    stream = AsyncMock(return_value=agen())
    fake = SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(generate_content_stream=stream)))

    async def run():
        with patch.object(llm, "_gemini_client", fake):
            async with llm.stream_llm(**_KW) as events:
                text = "".join([e.delta.text async for e in events if e.type == "content_block_delta"])
            await asyncio.sleep(0.05)
        return text
    assert asyncio.run(run()) == "hello"

    assert len(written) == 1
    assert written[0]["model"] == "gemini-3.8-flash"
    assert written[0]["output_tokens"] == 100
    assert written[0]["cost_usd"] > 0
