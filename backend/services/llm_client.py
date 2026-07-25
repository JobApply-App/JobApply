"""
Centralized LLM client wrapper — Gemini primary, Anthropic fallback.

This module is the single place a call site should get an LLM call from. It
does not change any prompt or business logic — it only owns: client
construction, timeout, retry-on-transient-failure, safe error wrapping, and
metadata-only logging (never prompt/response content).

Every call site builds and reads messages in Anthropic's wire shape (the
`messages`/`tools` dict shapes chat.py's tool loops construct and
round-trip via `.model_dump()`) — that hasn't changed. What changed is which
provider actually answers first:

Primary provider — both call_llm() and stream_llm():
  Every call attempts Gemini (`_GEMINI_MODEL`, via GEMINI_API_KEY) first,
  translating the Anthropic-shaped `messages`/`tools` into Gemini's shape
  and translating the response back into Anthropic-shaped objects, so
  callers never need to know which provider actually ran. This only happens
  when _gemini_eligible() says the request translates safely:

    - `tools`, if passed, must be plain custom function-tools (every tool
      dict has an "input_schema" key) — Anthropic *server-side* tools (e.g.
      `web_search_20260209`) have no Gemini equivalent this module builds,
      so a call using one is never eligible.
    - Every message's `content` must be either a plain string, or a list of
      blocks whose `type` is one of "text" / "tool_use" / "tool_result" /
      "image" / "document".

  When Gemini is ineligible for the call, or the Gemini attempt itself
  fails, the call falls back to Anthropic (`model=` as passed by the
  caller) — see call_llm()/stream_llm() docstrings for exactly when a
  streaming fallback can happen (only "failed/refused to open", never
  mid-stream, to avoid duplicating or garbling text already shown to the
  user).

  Doubly-failing calls raise LLMCallError, same safe-wrapping contract as
  before this Gemini-primary switch.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, AsyncIterator, Optional

import anthropic
from google import genai
from google.genai import errors as genai_errors
from google.genai import types as genai_types

from backend.config import ANTHROPIC_API_KEY, GEMINI_API_KEY

logger = logging.getLogger(__name__)

# ── Anthropic client (fallback provider) ────────────────────────────────────────
# One client for the whole process, built from the centrally-validated
# ANTHROPIC_API_KEY (backend/config.py) instead of each call site reading
# os.getenv("ANTHROPIC_API_KEY") itself.
#
# max_retries=0: the SDK has its own built-in retry, but retry is handled
# explicitly in _call_anthropic() below instead, so the policy is visible in
# one place, doesn't silently compound with the SDK's own retry, and is easy
# to unit test by mocking messages.create() directly.
_client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY, max_retries=0)

# ── Gemini client (primary provider) ────────────────────────────────────────────
# None when GEMINI_API_KEY is unset — every call checks this first, so "no
# Gemini key configured" degrades straight to the Anthropic fallback, never
# a second error about the primary provider itself being unconfigured.
_gemini_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

# Single fixed primary model — this is a project-wide default, not a tuned
# per-call-site choice, so one reasonably fast/capable model is used for
# every call regardless of which Claude model the caller's `model=` param
# names (that param only takes effect on the Anthropic fallback path).
#
# Use the "-latest" alias rather than pinning a dated snapshot (e.g.
# "gemini-2.5-flash") — Google periodically retires dated model IDs for new
# API keys/projects ("no longer available to new users"), which would
# silently kill the primary provider for anyone provisioning a key after
# that cutoff.
_GEMINI_MODEL = "gemini-flash-latest"

_DEFAULT_TIMEOUT_S = 60.0
_DEFAULT_MAX_RETRIES = 2
_RETRY_BASE_DELAY_S = 1.0

# Transient/infrastructure failures — safe to retry:
#   RateLimitError      — HTTP 429
#   APIConnectionError   — network failure (APITimeoutError is a subclass of
#                          this, so request timeouts are covered too)
#   InternalServerError  — HTTP 5xx
# Deliberately NOT included: BadRequestError (400), AuthenticationError (401),
# PermissionDeniedError (403), NotFoundError (404), ConflictError (409),
# UnprocessableEntityError (422) — these are client/request errors that will
# not resolve themselves on retry.
_RETRYABLE_EXCEPTIONS = (
    anthropic.RateLimitError,
    anthropic.APIConnectionError,
    anthropic.InternalServerError,
)


class LLMCallError(RuntimeError):
    """
    Safe, generic error raised for any LLM call failure (after retries are
    exhausted for transient errors, or immediately for non-retryable ones).

    The message is always a short, generic, user-safe string — never the
    raw provider exception text, which can echo back request/response
    internals. The real exception is logged server-side (by type and status
    code only, not by message body) before this is raised; use `from exc`
    at the raise site if you need the original traceback for debugging.
    """


@dataclass
class LLMResult:
    text: str                      # convenience: response.content[0].text
    model: str
    input_tokens: Optional[int]
    output_tokens: Optional[int]
    latency_ms: float
    attempts: int
    raw: Any                       # full anthropic.types.Message (or a duck-typed
                                    # equivalent — see _GeminiRaw — for a Gemini
                                    # fallback response)


# ── Gemini eligibility + translation ─────────────────────────────────────────────
#
# Anthropic's wire format is the one true shape every call site and every
# multi-turn tool loop (chat.py's _ariel_tool_loop_then_stream) builds and
# reads. These helpers translate FROM that shape TO Gemini's, and translate
# Gemini's response BACK INTO Anthropic-shaped objects — so a tool loop that
# uses Gemini for one turn, then Anthropic (fallback) for the next, never
# needs its own bookkeeping to change: it always reads and writes Anthropic
# shapes, and each call_llm()/stream_llm() invocation re-translates fresh,
# statelessly, in whichever direction is needed for that one call.

_ELIGIBLE_BLOCK_TYPES = {"text", "tool_use", "tool_result", "image", "document"}


def _content_eligible(content: Any) -> bool:
    if isinstance(content, str):
        return True
    if isinstance(content, list):
        return all(isinstance(b, dict) and b.get("type") in _ELIGIBLE_BLOCK_TYPES for b in content)
    return False


def _tools_eligible(tools: Optional[list]) -> bool:
    """Only plain custom function-tools translate — Anthropic server-side
    tools (web_search, etc.) have no "input_schema" and no Gemini equivalent
    built here."""
    if tools is None:
        return True
    return all(isinstance(t, dict) and "input_schema" in t for t in tools)


def _tool_use_blocks_gemini_safe(content: Any) -> bool:
    """
    A tool_use block can only be replayed to Gemini if it carries the
    `thought_signature` Gemini itself attached when it originally produced
    that call (see _FakeContentBlock's docstring) — an Anthropic-produced
    tool_use block (no such field) would make Gemini reject the whole
    request. Non-list / non-tool_use content is trivially safe.
    """
    if not isinstance(content, list):
        return True
    return all(
        b.get("thought_signature") is not None
        for b in content
        if isinstance(b, dict) and b.get("type") == "tool_use"
    )


def _gemini_eligible(messages: list[dict], tools: Optional[list]) -> bool:
    """Whether this call can be attempted against Gemini at all — the
    primary-provider gate. False means go straight to the Anthropic
    fallback (no Gemini attempt is made)."""
    if _gemini_client is None or not _tools_eligible(tools):
        return False
    return all(
        _content_eligible(m.get("content")) and _tool_use_blocks_gemini_safe(m.get("content"))
        for m in messages
    )


class _FakeContentBlock:
    """
    Duck-types an Anthropic content block closely enough for
    chat.py's _ariel_tool_loop_then_stream(): `.type` plus whichever of
    `.text` / `.id` / `.name` / `.input` apply, and `.model_dump()` returning
    the same plain-dict shape Anthropic's own pydantic blocks produce (the
    loop round-trips prior-turn blocks into the next turn's `messages` via
    `.model_dump()`).

    A Gemini-produced tool_use block also carries `.thought_signature` (raw
    bytes) — Gemini's API rejects a function_call part replayed in a later
    turn without the exact signature it originally returned for that call
    ("Function call is missing a thought_signature" / "Corrupted thought
    signature" if a placeholder is substituted). Anthropic has no
    equivalent concept, so an Anthropic-produced tool_use block simply omits
    this field; see _gemini_eligible()'s use of _tool_use_blocks_gemini_safe()
    below for why that makes a later Gemini attempt in the same tool loop
    ineligible until a fresh, Gemini-signed call restarts the chain.
    """

    def __init__(self, **kwargs: Any) -> None:
        self._data = kwargs
        for k, v in kwargs.items():
            setattr(self, k, v)

    def model_dump(self) -> dict:
        return dict(self._data)


def _messages_to_gemini_contents(messages: list[dict]) -> list[genai_types.Content]:
    """
    Anthropic messages (str content, or block-list content with text/
    tool_use/tool_result blocks) -> Gemini `contents`. Tool correlation:
    Anthropic's tool_result blocks reference the producing tool_use's `id`;
    Gemini's function_response correlates by `name` instead, so this walks
    messages in order building an id->name map from tool_use blocks seen so
    far, exactly the order they'd have been appended in a real conversation.
    """
    contents: list[genai_types.Content] = []
    tool_id_to_name: dict[str, str] = {}

    for m in messages:
        role = "model" if m["role"] == "assistant" else "user"
        content = m["content"]

        if isinstance(content, str):
            contents.append(genai_types.Content(role=role, parts=[genai_types.Part(text=content)]))
            continue

        parts: list[genai_types.Part] = []
        for block in content:
            btype = block["type"]
            if btype == "text":
                parts.append(genai_types.Part(text=block["text"]))
            elif btype == "tool_use":
                tool_id_to_name[block["id"]] = block["name"]
                fc_part = genai_types.Part.from_function_call(
                    name=block["name"], args=block.get("input") or {},
                )
                # Required by Gemini when this block is replayed in a later
                # turn — see _FakeContentBlock's docstring. Only a Gemini-
                # produced block carries this; _gemini_eligible() keeps a
                # signature-less block (Anthropic-produced) from ever
                # reaching here.
                sig = block.get("thought_signature")
                if sig is not None:
                    fc_part.thought_signature = sig
                parts.append(fc_part)
            elif btype == "tool_result":
                name = tool_id_to_name.get(block["tool_use_id"], "unknown_tool")
                parts.append(genai_types.Part.from_function_response(
                    name=name, response={"result": block.get("content")},
                ))
            elif btype in ("image", "document"):
                source = block["source"]
                raw_bytes = base64.b64decode(source["data"])
                parts.append(genai_types.Part.from_bytes(
                    data=raw_bytes, mime_type=source["media_type"],
                ))
        contents.append(genai_types.Content(role=role, parts=parts))

    return contents


def _anthropic_tools_to_gemini(tools: Optional[list]) -> Optional[genai_types.Tool]:
    if not tools:
        return None
    declarations = [
        genai_types.FunctionDeclaration(
            name=t["name"],
            description=t.get("description", ""),
            parameters_json_schema=t.get("input_schema"),
        )
        for t in tools
    ]
    return genai_types.Tool(function_declarations=declarations)


def _gemini_response_to_content_blocks(response: genai_types.GenerateContentResponse) -> list[_FakeContentBlock]:
    """Gemini's response parts -> Anthropic-shaped content blocks (text /
    tool_use), so callers reading `.raw.content` see the same block shapes
    regardless of which provider actually answered."""
    blocks: list[_FakeContentBlock] = []
    candidates = getattr(response, "candidates", None) or []
    parts = candidates[0].content.parts if candidates and candidates[0].content else []
    for part in parts or []:
        if getattr(part, "function_call", None) is not None:
            fc = part.function_call
            blocks.append(_FakeContentBlock(
                type="tool_use",
                id=f"gemini_{uuid.uuid4().hex[:12]}",
                name=fc.name,
                input=dict(fc.args) if fc.args else {},
                thought_signature=getattr(part, "thought_signature", None),
            ))
        elif getattr(part, "text", None):
            blocks.append(_FakeContentBlock(type="text", text=part.text))
    return blocks


# gemini-flash-latest defaults to an internal "thinking" pass whose tokens
# count against max_output_tokens — confirmed experimentally: a plain chat
# reply at max_tokens=100 spent 92 tokens on invisible thinking, truncating
# the visible reply to two words. thinking_budget=0 is rejected outright by
# this model ("invalid argument"); budget=1 is the smallest value the API
# accepts, and keeps the thinking pass token-cheap enough that the full
# reply fits inside the max_tokens budgets this app already uses (256–1024,
# sized for Anthropic, which has no equivalent hidden token cost).
_GEMINI_THINKING_BUDGET = 1


def _gemini_generation_config(
    *, max_tokens: int, system: Optional[str], temperature: Optional[float], tools: Optional[list],
) -> genai_types.GenerateContentConfig:
    kwargs: dict = {
        "max_output_tokens": max_tokens,
        "thinking_config": genai_types.ThinkingConfig(thinking_budget=_GEMINI_THINKING_BUDGET),
    }
    if system is not None:
        kwargs["system_instruction"] = system
    if temperature is not None:
        kwargs["temperature"] = temperature
    gemini_tool = _anthropic_tools_to_gemini(tools)
    if gemini_tool is not None:
        kwargs["tools"] = [gemini_tool]
    return genai_types.GenerateContentConfig(**kwargs)


async def _call_gemini(
    *,
    system: Optional[str],
    messages: list[dict],
    max_tokens: int,
    purpose: str,
    user_id: Optional[str],
    job_id: Optional[str],
    temperature: Optional[float],
    tools: Optional[list],
    timeout: float,
) -> LLMResult:
    """
    Single-attempt Gemini call — the primary-provider path from call_llm(),
    reached whenever _gemini_eligible() passes. Raises LLMCallError on
    failure — same safe-wrapping contract as the Anthropic path, never
    leaks raw provider exception text.
    """
    contents = _messages_to_gemini_contents(messages)
    config = _gemini_generation_config(
        max_tokens=max_tokens, system=system, temperature=temperature, tools=tools,
    )

    start = time.monotonic()
    try:
        response = await _gemini_client.aio.models.generate_content(
            model=_GEMINI_MODEL, contents=contents, config=config,
        )
    except genai_errors.APIError as exc:
        logger.error(
            "[llm_client] purpose=%s GEMINI CALL FAILED %s (status=%s)",
            purpose, type(exc).__name__, getattr(exc, "code", None),
        )
        raise LLMCallError(
            "The AI service is temporarily unavailable. Please try again shortly."
        ) from exc
    except Exception as exc:
        logger.exception(
            "[llm_client] purpose=%s GEMINI UNEXPECTED %s", purpose, type(exc).__name__,
        )
        raise LLMCallError(
            "An unexpected error occurred while contacting the AI service."
        ) from exc

    latency_ms = (time.monotonic() - start) * 1000
    usage = response.usage_metadata
    input_tokens = getattr(usage, "prompt_token_count", None) if usage is not None else None
    output_tokens = getattr(usage, "candidates_token_count", None) if usage is not None else None

    logger.info(
        "[llm_client] purpose=%s model=%s (GEMINI) user_id=%s job_id=%s "
        "input_tokens=%s output_tokens=%s latency_ms=%.0f",
        purpose, _GEMINI_MODEL, user_id, job_id, input_tokens, output_tokens, latency_ms,
    )

    blocks = _gemini_response_to_content_blocks(response)
    text = blocks[0].text if blocks and blocks[0].type == "text" else ""

    return LLMResult(
        text=text,
        model=_GEMINI_MODEL,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        latency_ms=latency_ms,
        attempts=1,
        raw=SimpleNamespace(content=blocks),
    )


async def call_llm(
    *,
    system: Optional[str] = None,
    messages: list[dict],
    model: str,
    max_tokens: int,
    purpose: str,
    user_id: Optional[str] = None,
    job_id: Optional[str] = None,
    temperature: Optional[float] = None,
    tools: Optional[list] = None,
    timeout: float = _DEFAULT_TIMEOUT_S,
    max_retries: int = _DEFAULT_MAX_RETRIES,
) -> LLMResult:
    """
    Make one non-streaming LLM call with timeout, transient-failure retry,
    safe metadata-only logging. Gemini (`_GEMINI_MODEL`) is the primary
    provider — see the module docstring — and this falls back to Anthropic
    (`model=` as passed by the caller) only when Gemini is ineligible for
    the call or the Gemini attempt itself fails.

    `purpose` / `user_id` / `job_id` are for server-side log correlation
    ONLY. They are never sent to the provider and never appear in `system`
    or `messages` — callers must not fold them into the prompt themselves
    expecting this function to do it; it doesn't.

    `tools` is passed straight through unchanged to whichever provider ends
    up handling the call — callers driving a multi-turn tool/pause_turn
    loop should call call_llm() once per turn and inspect
    `.raw.stop_reason` / `.raw.content` themselves; this function always
    makes exactly one primary-provider call per invocation (plus, on
    failure or ineligibility, at most one Anthropic fallback call). See
    _gemini_eligible() for exactly which `tools` values are translatable.

    Never logs: system, messages, prompt content, or any field of the
    response other than token counts. Raises LLMCallError on failure —
    never re-raises the raw provider exception to the caller.
    """
    if _gemini_eligible(messages, tools):
        try:
            return await _call_gemini(
                system=system, messages=messages, max_tokens=max_tokens, purpose=purpose,
                user_id=user_id, job_id=job_id, temperature=temperature, tools=tools, timeout=timeout,
            )
        except LLMCallError:
            logger.warning(
                "[llm_client] purpose=%s model=%s user_id=%s job_id=%s "
                "Gemini failed — falling back to Anthropic",
                purpose, model, user_id, job_id,
            )
    return await _call_anthropic(
        system=system, messages=messages, model=model, max_tokens=max_tokens,
        purpose=purpose, user_id=user_id, job_id=job_id, temperature=temperature,
        tools=tools, timeout=timeout, max_retries=max_retries,
    )


async def _call_anthropic(
    *,
    system: Optional[str],
    messages: list[dict],
    model: str,
    max_tokens: int,
    purpose: str,
    user_id: Optional[str],
    job_id: Optional[str],
    temperature: Optional[float],
    tools: Optional[list],
    timeout: float,
    max_retries: int,
) -> LLMResult:
    kwargs: dict = dict(model=model, max_tokens=max_tokens, messages=messages)
    if system is not None:
        kwargs["system"] = system
    if temperature is not None:
        kwargs["temperature"] = temperature
    if tools is not None:
        kwargs["tools"] = tools

    attempt = 0
    start = time.monotonic()

    while True:
        attempt += 1
        try:
            response = await _client.messages.create(timeout=timeout, **kwargs)
            break
        except _RETRYABLE_EXCEPTIONS as exc:
            status_code = getattr(exc, "status_code", None)
            if attempt > max_retries:
                logger.error(
                    "[llm_client] purpose=%s model=%s user_id=%s job_id=%s "
                    "FAILED after %d attempt(s): %s (status=%s)",
                    purpose, model, user_id, job_id, attempt, type(exc).__name__, status_code,
                )
                raise LLMCallError(
                    "The AI service is temporarily unavailable. Please try again shortly."
                ) from exc
            logger.warning(
                "[llm_client] purpose=%s model=%s user_id=%s job_id=%s "
                "attempt=%d/%d retrying after %s (status=%s)",
                purpose, model, user_id, job_id, attempt, max_retries + 1,
                type(exc).__name__, status_code,
            )
            await asyncio.sleep(_RETRY_BASE_DELAY_S * attempt)
        except anthropic.APIError as exc:
            # Non-retryable: bad request, auth, permission, not found,
            # conflict, unprocessable entity, or any other API error.
            logger.error(
                "[llm_client] purpose=%s model=%s user_id=%s job_id=%s "
                "NON-RETRYABLE %s (status=%s)",
                purpose, model, user_id, job_id, type(exc).__name__,
                getattr(exc, "status_code", None),
            )
            raise LLMCallError(
                "The AI request could not be completed. Please try again or contact support."
            ) from exc
        except Exception as exc:
            # Anything else unexpected — still safe-wrap, never leak str(exc).
            logger.exception(
                "[llm_client] purpose=%s model=%s user_id=%s job_id=%s UNEXPECTED %s",
                purpose, model, user_id, job_id, type(exc).__name__,
            )
            raise LLMCallError(
                "An unexpected error occurred while contacting the AI service."
            ) from exc

    latency_ms = (time.monotonic() - start) * 1000

    usage = getattr(response, "usage", None)
    input_tokens = getattr(usage, "input_tokens", None) if usage is not None else None
    output_tokens = getattr(usage, "output_tokens", None) if usage is not None else None

    logger.info(
        "[llm_client] purpose=%s model=%s user_id=%s job_id=%s "
        "input_tokens=%s output_tokens=%s latency_ms=%.0f attempts=%d",
        purpose, model, user_id, job_id, input_tokens, output_tokens, latency_ms, attempt,
    )

    text = ""
    if response.content:
        text = getattr(response.content[0], "text", "") or ""

    return LLMResult(
        text=text,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        latency_ms=latency_ms,
        attempts=attempt,
        raw=response,
    )


def _gemini_chunk_to_events(
    chunk: genai_types.GenerateContentResponse,
) -> list[SimpleNamespace]:
    """
    One Gemini stream chunk -> zero or more Anthropic-shaped stream events.

    Gemini doesn't stream a function call incrementally the way Anthropic's
    `input_json_delta` does — the arguments arrive complete in a single
    chunk — so a tool_use block is emitted as one immediate
    start -> delta (whole JSON) -> stop, which chat.py's existing
    accumulate-then-json.loads() consumers handle correctly either way (they
    just concatenate whatever deltas arrive).
    """
    events: list[SimpleNamespace] = []
    candidates = getattr(chunk, "candidates", None) or []
    parts = candidates[0].content.parts if candidates and candidates[0].content else []
    for part in parts or []:
        fc = getattr(part, "function_call", None)
        if fc is not None:
            events.append(SimpleNamespace(
                type="content_block_start",
                content_block=SimpleNamespace(type="tool_use", name=fc.name),
            ))
            events.append(SimpleNamespace(
                type="content_block_delta",
                delta=SimpleNamespace(
                    type="input_json_delta",
                    partial_json=json.dumps(dict(fc.args) if fc.args else {}),
                ),
            ))
            events.append(SimpleNamespace(type="content_block_stop"))
        elif getattr(part, "text", None):
            events.append(SimpleNamespace(
                type="content_block_start", content_block=SimpleNamespace(type="text"),
            ))
            events.append(SimpleNamespace(
                type="content_block_delta",
                delta=SimpleNamespace(type="text_delta", text=part.text),
            ))
            events.append(SimpleNamespace(type="content_block_stop"))
    return events


async def _gemini_stream_events(
    gemini_stream: AsyncIterator[genai_types.GenerateContentResponse],
) -> AsyncIterator[SimpleNamespace]:
    """
    Adapts a Gemini streaming iterator into the same event shape chat.py's
    stream consumers already read off a raw Anthropic stream:
    content_block_start -> content_block_delta* -> content_block_stop,
    for both text and tool_use blocks (see _gemini_chunk_to_events).
    """
    async for chunk in gemini_stream:
        for event in _gemini_chunk_to_events(chunk):
            yield event


async def _open_gemini_stream(
    *,
    system: Optional[str],
    messages: list[dict],
    max_tokens: int,
    temperature: Optional[float],
    tools: Optional[list],
) -> AsyncIterator[genai_types.GenerateContentResponse]:
    contents = _messages_to_gemini_contents(messages)
    config = _gemini_generation_config(
        max_tokens=max_tokens, system=system, temperature=temperature, tools=tools,
    )
    return await _gemini_client.aio.models.generate_content_stream(
        model=_GEMINI_MODEL, contents=contents, config=config,
    )


async def _prepend(first: Any, rest: AsyncIterator[Any]) -> AsyncIterator[Any]:
    yield first
    async for item in rest:
        yield item


@asynccontextmanager
async def stream_llm(
    *,
    system: Optional[str] = None,
    messages: list[dict],
    model: str,
    max_tokens: int,
    purpose: str,
    user_id: Optional[str] = None,
    job_id: Optional[str] = None,
    temperature: Optional[float] = None,
    tools: Optional[list] = None,
    tool_choice: Optional[dict] = None,
    timeout: float = _DEFAULT_TIMEOUT_S,
):
    """
    Async context manager wrapping one streamed turn. Gemini (`_GEMINI_MODEL`)
    is the primary provider — see the module docstring — with a fallback to
    the shared Anthropic client (`model=` as passed by the caller) if Gemini
    is ineligible for the call, or the Gemini stream fails to even open
    (auth error, missing key, connection refused before any bytes/chunks
    arrive).

    Usage is unchanged from the version this replaced:
    `async with stream_llm(...) as stream: async for event in stream: ...`
    — `stream_llm(...)` still returns immediately (no coroutine runs until
    entered), so no call site needed to change.

    Why only "failed to open", not mid-stream failures: once a provider has
    already started sending bytes/chunks to the client, silently switching
    provider mid-response could duplicate or garble text already shown to
    the user. The caller's own try/except around its `async for` loop still
    handles a genuine mid-stream drop exactly as before — this function does
    not catch or translate those. For Gemini specifically, "failed to open"
    is detected by eagerly pulling the first chunk (see `_prepend`) before
    handing the stream to the caller, since `generate_content_stream()`
    itself can return without the request having actually been sent yet.

    Never logs system, messages, tools, or response content — only a single
    metadata-only "stream start" line (purpose/model/user_id/job_id).
    """
    logger.info(
        "[llm_client] STREAM START purpose=%s model=%s user_id=%s job_id=%s",
        purpose, model, user_id, job_id,
    )

    if _gemini_eligible(messages, tools):
        try:
            gemini_stream = await _open_gemini_stream(
                system=system, messages=messages, max_tokens=max_tokens,
                temperature=temperature, tools=tools,
            )
            gemini_agen = gemini_stream.__aiter__()
            first_chunk = await gemini_agen.__anext__()
        except StopAsyncIteration:
            # Gemini opened the stream but produced zero chunks (empty
            # reply) — a valid (if unusual) outcome, not a failure to open.
            # `gemini_agen` is already exhausted, so this just yields
            # nothing rather than falling back to Anthropic.
            yield _gemini_stream_events(gemini_agen)
            return
        except Exception:
            logger.warning(
                "[llm_client] purpose=%s model=%s user_id=%s job_id=%s "
                "Gemini stream failed to open — falling back to Anthropic streaming",
                purpose, model, user_id, job_id,
            )
        else:
            yield _gemini_stream_events(_prepend(first_chunk, gemini_agen))
            return

    kwargs: dict = dict(model=model, max_tokens=max_tokens, messages=messages)
    if system is not None:
        kwargs["system"] = system
    if temperature is not None:
        kwargs["temperature"] = temperature
    if tools is not None:
        kwargs["tools"] = tools
    if tool_choice is not None:
        kwargs["tool_choice"] = tool_choice

    anthropic_cm = _client.messages.stream(timeout=timeout, **kwargs)
    anthropic_stream = await anthropic_cm.__aenter__()
    try:
        yield anthropic_stream
    finally:
        await anthropic_cm.__aexit__(None, None, None)
