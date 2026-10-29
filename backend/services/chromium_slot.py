"""
At most CHROMIUM_CONCURRENCY headless Chromium instances at once (default 1),
a bounded queue behind them, and a live estimate of the wait.

The service runs on a 512 MB instance. Each PDF render launches its own
Chromium (~100 MB+), and nothing limited how many ran together: on
2026-10-28 17:07 about a dozen /api/resumes/render-pdf requests in 25 seconds
(a user flipping between CV designs) took memory from ~250 MB to the limit,
and Render killed the instance (OOM) mid-request for everyone on it. Renders
now queue; each takes 2-5 s, so a short wait replaces a crash.

The queue is bounded (CHROMIUM_MAX_QUEUE, default 30). Past that, a new
render is refused at once with QueueFull — the route answers 503 with a
Retry-After — instead of holding one more connection open for a minute.
That is load shedding: under a flood the server keeps serving what it can.

queue_status() reports how many renders are ahead and roughly how long they
will take, from a moving average of recent render times. The frontend polls
it while a render is pending and shows a countdown instead of a frozen page.

Usage — wrap every chromium.launch():

    async with chromium_slot():
        browser = await pw.chromium.launch()
        ...
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)

_LIMIT     = max(1, int(os.getenv("CHROMIUM_CONCURRENCY", "1")))
_MAX_QUEUE = max(1, int(os.getenv("CHROMIUM_MAX_QUEUE", "30")))

# Seed for the average before any render has finished: a typical render
# measured in production (render-pdf, 2026-10-28) took 2-5 s.
_DEFAULT_RENDER_SECONDS = 3.5
_EMA_WEIGHT = 0.3   # weight of the newest render in the moving average


class QueueFull(RuntimeError):
    """The render queue is at CHROMIUM_MAX_QUEUE; retry after `retry_after` seconds."""

    def __init__(self, retry_after: int):
        super().__init__(f"render queue full, retry after {retry_after}s")
        self.retry_after = retry_after


class _State:
    def __init__(self) -> None:
        self.sem = asyncio.Semaphore(_LIMIT)
        self.waiting = 0
        self.running = 0
        self.avg_seconds = _DEFAULT_RENDER_SECONDS


# One state per event loop, created on first use inside it. A module-level
# asyncio.Semaphore binds to whatever loop exists at import time on Python 3.9
# (production) and then fails in uvicorn's loop.
_STATES: dict[int, _State] = {}


def _state() -> _State:
    loop = asyncio.get_running_loop()
    st = _STATES.get(id(loop))
    if st is None:
        st = _STATES[id(loop)] = _State()
    return st


def _eta(st: _State, ahead: int) -> float:
    """Seconds until a render with `ahead` renders in front of it finishes."""
    rounds = ahead // _LIMIT + 1
    return round(rounds * st.avg_seconds, 1)


def queue_status() -> dict:
    """
    {"ahead", "running", "eta_seconds", "avg_render_seconds"} for a render
    submitted now. `ahead` counts renders waiting or running.
    """
    st = _state()
    ahead = st.waiting + st.running
    return {
        "ahead": ahead,
        "running": st.running,
        "eta_seconds": _eta(st, ahead),
        "avg_render_seconds": round(st.avg_seconds, 1),
    }


@asynccontextmanager
async def chromium_slot():
    st = _state()
    if st.waiting >= _MAX_QUEUE:
        retry = max(1, int(_eta(st, st.waiting + st.running)))
        logger.warning("[chromium] queue full (%d waiting) — refusing render, retry in %ds", st.waiting, retry)
        raise QueueFull(retry)
    if st.sem.locked():
        logger.info("[chromium] waiting for a free browser slot (%d ahead, limit=%d)",
                    st.waiting + st.running, _LIMIT)
    st.waiting += 1
    try:
        await st.sem.acquire()
    finally:
        st.waiting -= 1
    st.running += 1
    started = time.monotonic()
    try:
        yield
    finally:
        st.running -= 1
        st.sem.release()
        took = time.monotonic() - started
        st.avg_seconds = (1 - _EMA_WEIGHT) * st.avg_seconds + _EMA_WEIGHT * took
