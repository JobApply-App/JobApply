"""
Unbounded parallel Chromium launches OOM-killed the 512 MB instance
(2026-10-28 17:07, a burst of render-pdf requests). chromium_slot() lets one
run at a time; the rest wait.
"""
import asyncio

from backend.services.chromium_slot import chromium_slot


async def test_renders_run_one_at_a_time():
    running, peak = 0, 0

    async def render():
        nonlocal running, peak
        async with chromium_slot():
            running += 1
            peak = max(peak, running)
            await asyncio.sleep(0.01)
            running -= 1

    await asyncio.gather(*(render() for _ in range(12)))
    assert peak == 1


async def test_slot_is_released_when_a_render_fails():
    try:
        async with chromium_slot():
            raise RuntimeError("chromium crashed")
    except RuntimeError:
        pass
    await asyncio.wait_for(_take_slot(), timeout=1)


async def _take_slot():
    async with chromium_slot():
        pass
