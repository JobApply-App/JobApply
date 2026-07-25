"""
Tests for backend.services.llm_client — Gemini primary, Anthropic fallback.

No real network calls. Anthropic: backend.services.llm_client._client.messages
.create/.stream is patched with an AsyncMock/MagicMock in every test. Gemini:
backend.services.llm_client._gemini_client is patched — either to None (to
isolate a test to pure-Anthropic behavior, since messages/tools eligible for
Gemini would otherwise hit whatever real GEMINI_API_KEY is configured
locally) or to a fake client object (to test the Gemini-primary / Anthropic-
fallback interplay itself).
"""
from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import anthropic
import httpx
import pytest

from unittest.mock import MagicMock

from backend.services.llm_client import LLMCallError, call_llm, stream_llm
import backend.services.llm_client as llm_client_module


# ── Fake exception / response builders ────────────────────────────────────────

def _fake_request() -> httpx.Request:
    return httpx.Request("POST", "https://api.anthropic.com/v1/messages")


def _fake_http_response(status_code: int) -> httpx.Response:
    return httpx.Response(status_code=status_code, request=_fake_request())


def _rate_limit_error() -> anthropic.RateLimitError:
    return anthropic.RateLimitError("rate limited", response=_fake_http_response(429), body=None)


def _internal_server_error() -> anthropic.InternalServerError:
    return anthropic.InternalServerError("server error", response=_fake_http_response(500), body=None)


def _bad_request_error() -> anthropic.BadRequestError:
    return anthropic.BadRequestError("bad request", response=_fake_http_response(400), body=None)


def _connection_error() -> anthropic.APIConnectionError:
    return anthropic.APIConnectionError(request=_fake_request())


def _fake_message(text: str = "hello from claude", input_tokens: int = 10, output_tokens: int = 5):
    return SimpleNamespace(
        content=[SimpleNamespace(text=text)],
        usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens),
    )


_CALL_KWARGS = dict(
    system="You are a helpful assistant.",
    messages=[{"role": "user", "content": "hi"}],
    model="claude-haiku-4-5",
    max_tokens=100,
    purpose="test_call",
    user_id="user-123",
    job_id="job-456",
)


# ── Success path ───────────────────────────────────────────────────────────────

def test_success_path_returns_text_and_usage():
    """
    Isolates the pure-Anthropic path: `_gemini_client` patched to None so
    this plain-string, tool-free call — which IS Gemini-eligible — doesn't
    reach whatever real Gemini client the local/CI environment happens to
    have configured. See _call_anthropic()-specific tests throughout this
    file for the same reasoning.
    """
    fake_response = _fake_message(text="the answer")

    async def run():
        with patch.object(llm_client_module, "_gemini_client", None):
            with patch.object(
                llm_client_module._client.messages, "create", new=AsyncMock(return_value=fake_response)
            ) as mock_create:
                result = await call_llm(**_CALL_KWARGS)
                assert result.text == "the answer"
                assert result.input_tokens == 10
                assert result.output_tokens == 5
                assert result.attempts == 1
                assert mock_create.call_count == 1

    asyncio.run(run())


def test_system_omitted_when_not_provided():
    """Some call sites (e.g. resume.py's vision helpers) never had a system
    prompt at all — call_llm must not force an empty one onto the request.
    `_gemini_client` disabled to isolate the Anthropic-specific kwargs
    assembly this test checks (see test_success_path... docstring)."""
    fake_response = _fake_message()
    kwargs_without_system = {k: v for k, v in _CALL_KWARGS.items() if k != "system"}

    async def run():
        with patch.object(llm_client_module, "_gemini_client", None):
            with patch.object(
                llm_client_module._client.messages, "create", new=AsyncMock(return_value=fake_response)
            ) as mock_create:
                await call_llm(**kwargs_without_system)
                assert "system" not in mock_create.call_args.kwargs

    asyncio.run(run())


def test_tools_param_passed_through_when_provided():
    """This server-side-style tool (no "input_schema") is never Gemini-
    eligible regardless of `_gemini_client` state — see _tools_eligible() —
    so this naturally isolates the Anthropic path already; `_gemini_client`
    is still disabled here for consistency/robustness with the rest of the
    file rather than relying on that eligibility gate implicitly."""
    fake_response = _fake_message()
    tools = [{"type": "web_search_20260209", "name": "web_search", "max_uses": 4}]

    async def run():
        with patch.object(llm_client_module, "_gemini_client", None):
            with patch.object(
                llm_client_module._client.messages, "create", new=AsyncMock(return_value=fake_response)
            ) as mock_create:
                await call_llm(**_CALL_KWARGS, tools=tools)
                assert mock_create.call_args.kwargs.get("tools") == tools

    asyncio.run(run())


def test_tools_param_omitted_when_not_provided():
    fake_response = _fake_message()

    async def run():
        with patch.object(llm_client_module, "_gemini_client", None):
            with patch.object(
                llm_client_module._client.messages, "create", new=AsyncMock(return_value=fake_response)
            ) as mock_create:
                await call_llm(**_CALL_KWARGS)
                assert "tools" not in mock_create.call_args.kwargs

    asyncio.run(run())


# ── Retry path ─────────────────────────────────────────────────────────────────

def test_retries_then_succeeds_on_transient_failure():
    """`_gemini_client` disabled — this tests _call_anthropic()'s retry loop
    specifically, which only runs at all once Gemini is ineligible/disabled."""
    fake_response = _fake_message(text="succeeded after retries")
    mock_create = AsyncMock(side_effect=[_rate_limit_error(), _internal_server_error(), fake_response])

    async def run():
        with patch.object(llm_client_module, "_gemini_client", None):
            with patch.object(llm_client_module._client.messages, "create", new=mock_create):
                with patch.object(llm_client_module, "_RETRY_BASE_DELAY_S", 0.001):
                    result = await call_llm(**_CALL_KWARGS, max_retries=2)
                    assert result.text == "succeeded after retries"
                    assert result.attempts == 3
                    assert mock_create.call_count == 3

    asyncio.run(run())


def test_retry_exhausted_raises_llm_call_error():
    mock_create = AsyncMock(side_effect=[_rate_limit_error(), _rate_limit_error()])

    async def run():
        # No Gemini fallback configured — isolates this test from whatever
        # GEMINI_API_KEY happens to be set in the local/CI environment, so it
        # always exercises the "Anthropic exhausted, no fallback available"
        # path regardless of machine-specific .env content.
        with patch.object(llm_client_module, "_gemini_client", None):
            with patch.object(llm_client_module._client.messages, "create", new=mock_create):
                with patch.object(llm_client_module, "_RETRY_BASE_DELAY_S", 0.001):
                    with pytest.raises(LLMCallError):
                        await call_llm(**_CALL_KWARGS, max_retries=1)
                    # max_retries=1 → 2 total attempts (1 initial + 1 retry), then raise
                    assert mock_create.call_count == 2

    asyncio.run(run())


# ── Non-retryable errors ────────────────────────────────────────────────────────

def test_non_retryable_error_raises_immediately_without_retry():
    mock_create = AsyncMock(side_effect=_bad_request_error())

    async def run():
        with patch.object(llm_client_module, "_gemini_client", None):
            with patch.object(llm_client_module._client.messages, "create", new=mock_create):
                with pytest.raises(LLMCallError):
                    await call_llm(**_CALL_KWARGS, max_retries=3)
                # A 4xx error must NOT be retried, regardless of max_retries.
                assert mock_create.call_count == 1

    asyncio.run(run())


def test_connection_error_is_retried():
    fake_response = _fake_message()
    mock_create = AsyncMock(side_effect=[_connection_error(), fake_response])

    async def run():
        with patch.object(llm_client_module, "_gemini_client", None):
            with patch.object(llm_client_module._client.messages, "create", new=mock_create):
                with patch.object(llm_client_module, "_RETRY_BASE_DELAY_S", 0.001):
                    result = await call_llm(**_CALL_KWARGS, max_retries=1)
                    assert result.attempts == 2
                    assert mock_create.call_count == 2

    asyncio.run(run())


# ── Gemini primary / Anthropic fallback ──────────────────────────────────────────
#
# call_llm() tries Gemini FIRST for any Gemini-eligible request (see
# _gemini_eligible() in llm_client.py — plain text, or block content of type
# text/tool_use/tool_result/image/document, plus tools that all carry
# "input_schema"), falling back to Anthropic only when Gemini is ineligible
# or the Gemini attempt itself fails. These tests build a fake Gemini client
# object (not the real google.genai.Client) and patch
# llm_client_module._gemini_client with it, so no real network call is ever
# made here regardless of whatever GEMINI_API_KEY is present in the
# local/CI environment.

def _fake_gemini_part(text: Optional[str] = None, function_call: Optional[SimpleNamespace] = None):
    return SimpleNamespace(text=text, function_call=function_call)


def _fake_gemini_response(
    text: str = "hello from gemini",
    prompt_tokens: int = 8,
    output_tokens: int = 4,
    parts: Optional[list] = None,
):
    """Mirrors the real google.genai response shape closely enough for
    _gemini_response_to_content_blocks(): .candidates[0].content.parts, each
    part exposing .text / .function_call, plus a top-level .text convenience
    property (real SDK responses have one too)."""
    if parts is None:
        parts = [_fake_gemini_part(text=text)]
    return SimpleNamespace(
        text=text,
        candidates=[SimpleNamespace(content=SimpleNamespace(parts=parts))],
        usage_metadata=SimpleNamespace(
            prompt_token_count=prompt_tokens, candidates_token_count=output_tokens,
        ),
    )


def _fake_gemini_client(generate_content: AsyncMock) -> SimpleNamespace:
    return SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(generate_content=generate_content)))


def test_gemini_used_as_primary_when_eligible():
    """Gemini is tried first and succeeds -> Anthropic is never touched at
    all, not even attempted as a fallback."""
    mock_anthropic_create = AsyncMock(side_effect=_bad_request_error())
    mock_gemini_generate = AsyncMock(return_value=_fake_gemini_response(text="primary answer"))
    fake_gemini = _fake_gemini_client(mock_gemini_generate)

    async def run():
        with patch.object(llm_client_module, "_gemini_client", fake_gemini):
            with patch.object(llm_client_module._client.messages, "create", new=mock_anthropic_create):
                result = await call_llm(**_CALL_KWARGS)
                assert result.text == "primary answer"
                assert result.model == llm_client_module._GEMINI_MODEL
                assert result.input_tokens == 8
                assert result.output_tokens == 4
                mock_gemini_generate.assert_called_once()
                mock_anthropic_create.assert_not_called()

    asyncio.run(run())


def test_anthropic_used_as_fallback_when_gemini_fails():
    """Gemini is eligible and tried first, but fails -> call_llm falls back
    to Anthropic, which succeeds; the returned result comes from Anthropic."""
    fake_response = _fake_message(text="anthropic fallback answer")
    mock_anthropic_create = AsyncMock(return_value=fake_response)
    mock_gemini_generate = AsyncMock(side_effect=RuntimeError("gemini down"))
    fake_gemini = _fake_gemini_client(mock_gemini_generate)

    async def run():
        with patch.object(llm_client_module, "_gemini_client", fake_gemini):
            with patch.object(llm_client_module._client.messages, "create", new=mock_anthropic_create):
                result = await call_llm(**_CALL_KWARGS)
                assert result.text == "anthropic fallback answer"
                assert result.model == _CALL_KWARGS["model"]
                mock_gemini_generate.assert_called_once()
                mock_anthropic_create.assert_called_once()

    asyncio.run(run())


def test_gemini_not_eligible_when_tools_lack_input_schema():
    """A server-side-style tool (no "input_schema") is never Gemini-
    eligible, so Gemini is skipped entirely and Anthropic (mocked to fail
    here) is the only attempt made."""
    mock_anthropic_create = AsyncMock(side_effect=_bad_request_error())
    mock_gemini_generate = AsyncMock(return_value=_fake_gemini_response())
    fake_gemini = _fake_gemini_client(mock_gemini_generate)
    tools = [{"type": "web_search_20260209", "name": "web_search", "max_uses": 4}]

    async def run():
        with patch.object(llm_client_module, "_gemini_client", fake_gemini):
            with patch.object(llm_client_module._client.messages, "create", new=mock_anthropic_create):
                with pytest.raises(LLMCallError):
                    await call_llm(**_CALL_KWARGS, tools=tools)
                mock_gemini_generate.assert_not_called()
                mock_anthropic_create.assert_called_once()

    asyncio.run(run())


def test_gemini_primary_ok_for_text_block_content():
    """A block-list message made only of "text" blocks (no tool_use/
    tool_result) is still plain conversational content — eligible for the
    Gemini primary path just like a plain string, same as multi-turn
    Anthropic-shaped history that happens to use the block form instead of
    a bare string."""
    mock_anthropic_create = AsyncMock(side_effect=_bad_request_error())
    mock_gemini_generate = AsyncMock(return_value=_fake_gemini_response(text="ok"))
    fake_gemini = _fake_gemini_client(mock_gemini_generate)
    block_messages = [{"role": "user", "content": [{"type": "text", "text": "hi"}]}]

    async def run():
        with patch.object(llm_client_module, "_gemini_client", fake_gemini):
            with patch.object(llm_client_module._client.messages, "create", new=mock_anthropic_create):
                result = await call_llm(**{**_CALL_KWARGS, "messages": block_messages})
                assert result.text == "ok"
                mock_gemini_generate.assert_called_once()
                mock_anthropic_create.assert_not_called()

    asyncio.run(run())


def test_gemini_now_eligible_for_vision_message_content():
    """Vision/PDF calls (backend/agents/resume.py, document_verifier.py) pass
    an "image" block. _messages_to_gemini_contents() now translates
    image/document blocks via Part.from_bytes() (added alongside the
    Gemini-primary switch, to avoid silently pushing every attachment-
    bearing call straight to Anthropic) — so these ARE now Gemini-eligible
    and go through the primary path like anything else."""
    mock_anthropic_create = AsyncMock(side_effect=_bad_request_error())
    mock_gemini_generate = AsyncMock(return_value=_fake_gemini_response(text="i see a cat"))
    fake_gemini = _fake_gemini_client(mock_gemini_generate)
    block_messages = [{
        "role": "user",
        "content": [
            {"type": "text", "text": "what's in this image?"},
            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "aGVsbG8="}},
        ],
    }]

    async def run():
        with patch.object(llm_client_module, "_gemini_client", fake_gemini):
            with patch.object(llm_client_module._client.messages, "create", new=mock_anthropic_create):
                result = await call_llm(**{**_CALL_KWARGS, "messages": block_messages})
                assert result.text == "i see a cat"
                mock_gemini_generate.assert_called_once()
                mock_anthropic_create.assert_not_called()

    asyncio.run(run())


def test_gemini_primary_used_for_tool_use_call_with_custom_function_tools():
    """Custom function-tools (every tool dict has an "input_schema") DO
    translate to Gemini function declarations — only Anthropic server-side
    tools (no "input_schema") are excluded. See the sibling test using a
    web_search-style tool for that exclusion."""
    mock_anthropic_create = AsyncMock(side_effect=_bad_request_error())
    fake_function_call = SimpleNamespace(name="get_full_candidate_profile", args={"reason": "cv updated"})
    mock_gemini_generate = AsyncMock(
        return_value=_fake_gemini_response(parts=[_fake_gemini_part(function_call=fake_function_call)])
    )
    fake_gemini = _fake_gemini_client(mock_gemini_generate)
    custom_tool = [{
        "name": "get_full_candidate_profile",
        "description": "Fetch the candidate's full profile.",
        "input_schema": {"type": "object", "properties": {"reason": {"type": "string"}}, "required": ["reason"]},
    }]

    async def run():
        with patch.object(llm_client_module, "_gemini_client", fake_gemini):
            with patch.object(llm_client_module._client.messages, "create", new=mock_anthropic_create):
                result = await call_llm(**_CALL_KWARGS, tools=custom_tool)
                mock_gemini_generate.assert_called_once()
                mock_anthropic_create.assert_not_called()
                block = result.raw.content[0]
                assert block.type == "tool_use"
                assert block.name == "get_full_candidate_profile"
                assert block.input == {"reason": "cv updated"}
                assert block.model_dump()["type"] == "tool_use"

    asyncio.run(run())


def test_llm_call_error_when_both_providers_fail():
    """Gemini (primary) and Anthropic (fallback) both fail -> LLMCallError,
    with both actually having been attempted."""
    mock_anthropic_create = AsyncMock(side_effect=_bad_request_error())
    mock_gemini_generate = AsyncMock(side_effect=RuntimeError("gemini also down"))
    fake_gemini = _fake_gemini_client(mock_gemini_generate)

    async def run():
        with patch.object(llm_client_module, "_gemini_client", fake_gemini):
            with patch.object(llm_client_module._client.messages, "create", new=mock_anthropic_create):
                with pytest.raises(LLMCallError):
                    await call_llm(**_CALL_KWARGS)
                mock_gemini_generate.assert_called_once()
                mock_anthropic_create.assert_called_once()

    asyncio.run(run())


def test_gemini_not_attempted_when_no_gemini_client_configured():
    """With no Gemini client at all, call_llm goes straight to Anthropic —
    still the only provider attempted, same as before Gemini existed."""
    mock_anthropic_create = AsyncMock(side_effect=_bad_request_error())

    async def run():
        with patch.object(llm_client_module, "_gemini_client", None):
            with patch.object(llm_client_module._client.messages, "create", new=mock_anthropic_create):
                with pytest.raises(LLMCallError):
                    await call_llm(**_CALL_KWARGS)

    asyncio.run(run())


# ── Safe error wrapping ──────────────────────────────────────────────────────────

def test_llm_call_error_message_never_contains_raw_exception_text():
    secret_marker = "RAW_PROVIDER_INTERNAL_DETAIL_12345"
    mock_create = AsyncMock(side_effect=anthropic.BadRequestError(secret_marker, response=_fake_http_response(400), body=None))

    async def run():
        with patch.object(llm_client_module, "_gemini_client", None):
            with patch.object(llm_client_module._client.messages, "create", new=mock_create):
                with pytest.raises(LLMCallError) as exc_info:
                    await call_llm(**_CALL_KWARGS)
                assert secret_marker not in str(exc_info.value)

    asyncio.run(run())


# ── Safe logging ──────────────────────────────────────────────────────────────

def test_logging_never_includes_prompt_or_response_content(caplog):
    secret_system = "SECRET_SYSTEM_PROMPT_MARKER"
    secret_user_message = "SECRET_USER_MESSAGE_MARKER"
    secret_response_text = "SECRET_RESPONSE_TEXT_MARKER"

    fake_response = _fake_message(text=secret_response_text)

    async def run():
        with patch.object(llm_client_module, "_gemini_client", None):
            with patch.object(
                llm_client_module._client.messages, "create", new=AsyncMock(return_value=fake_response)
            ):
                with caplog.at_level(logging.DEBUG, logger="backend.services.llm_client"):
                    await call_llm(
                        system=secret_system,
                        messages=[{"role": "user", "content": secret_user_message}],
                        model="claude-haiku-4-5",
                        max_tokens=100,
                        purpose="test_no_leak",
                        user_id="user-123",
                        job_id="job-456",
                    )

    asyncio.run(run())

    all_log_text = "\n".join(record.getMessage() for record in caplog.records)
    assert secret_system not in all_log_text
    assert secret_user_message not in all_log_text
    assert secret_response_text not in all_log_text
    # Sanity check: logging DID actually happen (the assertions above aren't
    # vacuously true because nothing was logged at all).
    assert any("llm_client" in record.getMessage() for record in caplog.records)


def test_logging_on_retry_never_includes_prompt_or_error_body(caplog):
    secret_system = "SECRET_SYSTEM_PROMPT_MARKER_2"
    secret_error_body = "RAW_ERROR_BODY_SECRET_MARKER"
    fake_response = _fake_message()

    mock_create = AsyncMock(
        side_effect=[
            anthropic.RateLimitError(secret_error_body, response=_fake_http_response(429), body=None),
            fake_response,
        ]
    )

    async def run():
        with patch.object(llm_client_module, "_gemini_client", None):
            with patch.object(llm_client_module._client.messages, "create", new=mock_create):
                with patch.object(llm_client_module, "_RETRY_BASE_DELAY_S", 0.001):
                    with caplog.at_level(logging.DEBUG, logger="backend.services.llm_client"):
                        await call_llm(
                            system=secret_system,
                            messages=[{"role": "user", "content": "hi"}],
                            model="claude-haiku-4-5",
                            max_tokens=100,
                            purpose="test_retry_no_leak",
                            max_retries=1,
                        )

    asyncio.run(run())

    all_log_text = "\n".join(record.getMessage() for record in caplog.records)
    assert secret_system not in all_log_text
    assert secret_error_body not in all_log_text


# ── stream_llm() — async context manager, with a text-only Gemini fallback ────
#
# stream_llm() is now an @asynccontextmanager: calling it still returns
# immediately (no call site elsewhere in the codebase needed to change), but
# entering it (`async with stream_llm(...) as stream:`) is what actually
# calls _client.messages.stream(...) and awaits its __aenter__(). These tests
# build a fake Anthropic stream context manager (a MagicMock with async
# __aenter__/__aexit__) rather than a bare sentinel, to match.

def _fake_anthropic_stream_cm(entered_value: Any = None, aenter_exc: Optional[Exception] = None) -> MagicMock:
    cm = MagicMock()
    if aenter_exc is not None:
        cm.__aenter__ = AsyncMock(side_effect=aenter_exc)
    else:
        cm.__aenter__ = AsyncMock(return_value=entered_value)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


_STREAM_KWARGS = dict(
    system="You are a helpful assistant.",
    messages=[{"role": "user", "content": "hi"}],
    model="claude-sonnet-4-6",
    max_tokens=1024,
    purpose="test_stream",
    user_id="user-123",
    job_id="job-456",
)


def test_stream_llm_returns_client_stream_manager_with_assembled_kwargs():
    """`_gemini_client` disabled — this tests the Anthropic kwargs assembly
    specifically; `_STREAM_KWARGS`'s plain-string message is otherwise
    Gemini-eligible and would try the real client."""
    sentinel = MagicMock(name="stream_manager")
    fake_cm = _fake_anthropic_stream_cm(entered_value=sentinel)

    async def run():
        with patch.object(llm_client_module, "_gemini_client", None):
            with patch.object(llm_client_module._client.messages, "stream", new=MagicMock(return_value=fake_cm)) as mock_stream:
                async with stream_llm(**_STREAM_KWARGS) as stream:
                    assert stream is sentinel
                assert mock_stream.call_args.kwargs["model"] == "claude-sonnet-4-6"
                assert mock_stream.call_args.kwargs["max_tokens"] == 1024
                assert mock_stream.call_args.kwargs["system"] == _STREAM_KWARGS["system"]
                assert mock_stream.call_args.kwargs["messages"] == _STREAM_KWARGS["messages"]

    asyncio.run(run())


def test_stream_llm_system_omitted_when_not_provided():
    kwargs_without_system = {k: v for k, v in _STREAM_KWARGS.items() if k != "system"}
    fake_cm = _fake_anthropic_stream_cm(entered_value=MagicMock())

    async def run():
        with patch.object(llm_client_module, "_gemini_client", None):
            with patch.object(llm_client_module._client.messages, "stream", new=MagicMock(return_value=fake_cm)) as mock_stream:
                async with stream_llm(**kwargs_without_system):
                    pass
                assert "system" not in mock_stream.call_args.kwargs

    asyncio.run(run())


def test_stream_llm_tools_and_tool_choice_passed_through_when_provided():
    """`_gemini_client` disabled — `tool_choice` is an Anthropic-only concept
    this test checks reaches _client.messages.stream() unchanged; these
    tools also carry "input_schema" so would otherwise be Gemini-eligible
    and never reach the mocked Anthropic call at all."""
    tools = [{"name": "tailor_resume_for_job", "input_schema": {"type": "object"}}]
    tool_choice = {"type": "none"}
    fake_cm = _fake_anthropic_stream_cm(entered_value=MagicMock())

    async def run():
        with patch.object(llm_client_module, "_gemini_client", None):
            with patch.object(llm_client_module._client.messages, "stream", new=MagicMock(return_value=fake_cm)) as mock_stream:
                async with stream_llm(**_STREAM_KWARGS, tools=tools, tool_choice=tool_choice):
                    pass
                assert mock_stream.call_args.kwargs.get("tools") == tools
                assert mock_stream.call_args.kwargs.get("tool_choice") == tool_choice

    asyncio.run(run())


def test_stream_llm_tools_and_tool_choice_omitted_when_not_provided():
    fake_cm = _fake_anthropic_stream_cm(entered_value=MagicMock())

    async def run():
        with patch.object(llm_client_module, "_gemini_client", None):
            with patch.object(llm_client_module._client.messages, "stream", new=MagicMock(return_value=fake_cm)) as mock_stream:
                async with stream_llm(**_STREAM_KWARGS):
                    pass
                assert "tools" not in mock_stream.call_args.kwargs
                assert "tool_choice" not in mock_stream.call_args.kwargs

    asyncio.run(run())


def test_stream_llm_logging_never_includes_prompt_or_tool_content(caplog):
    secret_system = "SECRET_STREAM_SYSTEM_MARKER"
    secret_user_message = "SECRET_STREAM_USER_MARKER"
    secret_tool_content = "SECRET_STREAM_TOOL_MARKER"
    tools = [{"name": secret_tool_content, "input_schema": {"type": "object"}}]
    fake_cm = _fake_anthropic_stream_cm(entered_value=MagicMock())

    async def run():
        with patch.object(llm_client_module, "_gemini_client", None):
            with patch.object(llm_client_module._client.messages, "stream", new=MagicMock(return_value=fake_cm)):
                with caplog.at_level(logging.DEBUG, logger="backend.services.llm_client"):
                    async with stream_llm(
                        system=secret_system,
                        messages=[{"role": "user", "content": secret_user_message}],
                        model="claude-sonnet-4-6",
                        max_tokens=1024,
                        purpose="test_stream_no_leak",
                        tools=tools,
                    ):
                        pass

    asyncio.run(run())

    all_log_text = "\n".join(record.getMessage() for record in caplog.records)
    assert secret_system not in all_log_text
    assert secret_user_message not in all_log_text
    assert secret_tool_content not in all_log_text
    assert any("STREAM START" in record.getMessage() for record in caplog.records)


# ── stream_llm() — Gemini primary streaming, Anthropic fallback ─────────────────
#
# stream_llm() tries Gemini first for any eligible call — including
# tool-using ones now (see _gemini_chunk_to_events()/_gemini_stream_events()
# in llm_client.py, which adapt Gemini's per-chunk candidates/content/parts
# shape, text or function_call, into the same content_block_start/delta/stop
# event shape chat.py's consumers already read off a raw Anthropic stream).
# Falls back to Anthropic only if Gemini is ineligible or fails to open.

def _fake_gemini_stream_part(text: Optional[str] = None, function_call: Optional[SimpleNamespace] = None):
    return SimpleNamespace(text=text, function_call=function_call)


def _fake_gemini_stream_chunk(parts: list):
    """Mirrors the real per-chunk shape _gemini_chunk_to_events() reads:
    .candidates[0].content.parts, each part exposing .text/.function_call —
    the same shape as a non-streaming response (see _fake_gemini_response
    above), NOT a bare `.text` shorthand."""
    return SimpleNamespace(candidates=[SimpleNamespace(content=SimpleNamespace(parts=parts))])


def _fake_gemini_stream_client(text_chunks: list[str], generate_stream: Optional[AsyncMock] = None) -> SimpleNamespace:
    async def _agen():
        for c in text_chunks:
            yield _fake_gemini_stream_chunk([_fake_gemini_stream_part(text=c)])

    mock = generate_stream or AsyncMock(return_value=_agen())
    return SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(generate_content_stream=mock)))


def _fake_anthropic_stream_events(events: list) -> Any:
    return _agen_of(events)


async def _agen_of(items: list):
    for item in items:
        yield item


def test_stream_llm_uses_gemini_as_primary_stream():
    """Gemini is eligible and succeeds -> Anthropic's stream() is never
    even called."""
    fake_cm = _fake_anthropic_stream_cm(aenter_exc=_bad_request_error())
    fake_gemini = _fake_gemini_stream_client(["hel", "lo"])

    async def run():
        with patch.object(llm_client_module, "_gemini_client", fake_gemini):
            with patch.object(
                llm_client_module._client.messages, "stream", new=MagicMock(return_value=fake_cm)
            ) as mock_stream:
                collected = ""
                async with stream_llm(**_STREAM_KWARGS) as stream:
                    async for event in stream:
                        if event.type == "content_block_delta" and event.delta.type == "text_delta":
                            collected += event.delta.text
                assert collected == "hello"
                mock_stream.assert_not_called()

    asyncio.run(run())


def test_stream_llm_falls_back_to_anthropic_when_gemini_stream_fails_to_open():
    """Gemini is eligible but fails to open (before any chunk arrives) ->
    stream_llm falls back to the Anthropic stream, which succeeds."""
    anthropic_events = [SimpleNamespace(
        type="content_block_delta",
        delta=SimpleNamespace(type="text_delta", text="anthropic fallback text"),
    )]
    fake_cm = _fake_anthropic_stream_cm(entered_value=_fake_anthropic_stream_events(anthropic_events))
    fake_gemini = SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(
        generate_content_stream=AsyncMock(side_effect=RuntimeError("gemini stream down"))
    )))

    async def run():
        with patch.object(llm_client_module, "_gemini_client", fake_gemini):
            with patch.object(llm_client_module._client.messages, "stream", new=MagicMock(return_value=fake_cm)) as mock_stream:
                collected = ""
                async with stream_llm(**_STREAM_KWARGS) as stream:
                    async for event in stream:
                        if event.type == "content_block_delta" and event.delta.type == "text_delta":
                            collected += event.delta.text
                assert collected == "anthropic fallback text"
                mock_stream.assert_called_once()

    asyncio.run(run())


def test_stream_llm_uses_gemini_primary_for_tool_streaming_when_eligible():
    """Tools carrying "input_schema" ARE Gemini-eligible for streaming (this
    is what _gemini_chunk_to_events()/_gemini_stream_events() exist for) —
    a function_call chunk translates into the same content_block_start
    (tool_use) / content_block_delta (input_json_delta) / content_block_stop
    sequence chat.py already expects from a raw Anthropic stream."""
    fake_cm = _fake_anthropic_stream_cm(aenter_exc=_bad_request_error())
    fake_function_call = SimpleNamespace(name="tailor_resume_for_job", args={"job_title": "PM"})
    fake_gemini = _fake_gemini_stream_client(
        [], generate_stream=AsyncMock(return_value=_agen_of([
            _fake_gemini_stream_chunk([_fake_gemini_stream_part(function_call=fake_function_call)]),
        ]))
    )
    tools = [{"name": "tailor_resume_for_job", "input_schema": {"type": "object"}}]

    async def run():
        with patch.object(llm_client_module, "_gemini_client", fake_gemini):
            with patch.object(llm_client_module._client.messages, "stream", new=MagicMock(return_value=fake_cm)) as mock_stream:
                events = []
                async with stream_llm(**_STREAM_KWARGS, tools=tools) as stream:
                    async for event in stream:
                        events.append(event)
                mock_stream.assert_not_called()
                assert events[0].type == "content_block_start"
                assert events[0].content_block.type == "tool_use"
                assert events[0].content_block.name == "tailor_resume_for_job"
                assert events[1].type == "content_block_delta"
                assert events[1].delta.type == "input_json_delta"
                assert '"job_title"' in events[1].delta.partial_json
                assert events[2].type == "content_block_stop"

    asyncio.run(run())


def test_stream_llm_no_gemini_attempt_when_tools_not_translatable():
    """A server-side-style tool (no "input_schema") is never Gemini-eligible
    for streaming either — Gemini is skipped entirely and Anthropic (mocked
    to fail here) is the only attempt made, so its exception surfaces
    directly with no fallback possible."""
    fake_cm = _fake_anthropic_stream_cm(aenter_exc=_bad_request_error())
    fake_gemini = _fake_gemini_stream_client(["should not be reached"])
    tools = [{"type": "web_search_20260209", "name": "web_search", "max_uses": 4}]

    async def run():
        with patch.object(llm_client_module, "_gemini_client", fake_gemini):
            with patch.object(llm_client_module._client.messages, "stream", new=MagicMock(return_value=fake_cm)):
                with pytest.raises(anthropic.BadRequestError):
                    async with stream_llm(**_STREAM_KWARGS, tools=tools) as stream:
                        async for _ in stream:
                            pass

    asyncio.run(run())


def test_stream_llm_no_fallback_when_no_gemini_client_configured():
    fake_cm = _fake_anthropic_stream_cm(aenter_exc=_bad_request_error())

    async def run():
        with patch.object(llm_client_module, "_gemini_client", None):
            with patch.object(llm_client_module._client.messages, "stream", new=MagicMock(return_value=fake_cm)):
                with pytest.raises(anthropic.BadRequestError):
                    async with stream_llm(**_STREAM_KWARGS) as stream:
                        async for _ in stream:
                            pass

    asyncio.run(run())
