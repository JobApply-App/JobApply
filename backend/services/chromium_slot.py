"""
At most CHROMIUM_CONCURRENCY headless Chromium instances at once (default 1).

The service runs on a 512 MB instance. Each PDF render launches its own
Chromium (~100 MB+), and nothing limited how many ran together: on
2026-10-28 17:07 about a dozen /api/resumes/render-pdf requests in 25 seconds
(a user flipping between CV designs) took memory from ~250 MB to the limit,
and Render killed the instance (OOM) mid-request for everyone on it. Renders
now queue; each takes 2-5 s, so a short wait replaces a crash.

Usage — wrap every chromium.launch():

    async with chromium_slot():
        browser = await pw.chromium.launch()
        ...
"""
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)

_LIMIT = max(1, int(os.getenv("CHROMIUM_CONCURRENCY", "1")))

# One semaphore per event loop, created on first use inside it. A
# module-level asyncio.Semaphore binds to whatever loop exists at import time
# on Python 3.9 (production) and then fails in uvicorn's loop.
_SEMAPHORES: dict[int, asyncio.Semaphore] = {}


def _semaphore() -> asyncio.Semaphore:
    loop = asyncio.get_running_loop()
    sem = _SEMAPHORES.get(id(loop))
    if sem is None:
        sem = _SEMAPHORES[id(loop)] = asyncio.Semaphore(_LIMIT)
    return sem


@asynccontextmanager
async def chromium_slot():
    sem = _semaphore()
    if sem.locked():
        logger.info("[chromium] waiting for a free browser slot (limit=%d)", _LIMIT)
    async with sem:
        yield
