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


async def test_queue_status_counts_renders_ahead_and_estimates_the_wait():
    from backend.services.chromium_slot import queue_status

    assert queue_status()["ahead"] == 0
    release = asyncio.Event()
    seen = {}

    async def render():
        async with chromium_slot():
            await release.wait()

    tasks = [asyncio.create_task(render()) for _ in range(3)]
    await asyncio.sleep(0.01)
    seen = queue_status()
    release.set()
    await asyncio.gather(*tasks)
    assert seen["ahead"] == 3 and seen["running"] == 1
    assert seen["eta_seconds"] > seen["avg_render_seconds"] * 3   # 3 ahead + this one


async def test_a_full_queue_refuses_at_once_instead_of_piling_up(monkeypatch):
    import backend.services.chromium_slot as slot
    monkeypatch.setattr(slot, "_MAX_QUEUE", 2)
    release = asyncio.Event()

    async def render():
        async with chromium_slot():
            await release.wait()

    tasks = [asyncio.create_task(render()) for _ in range(3)]   # 1 running + 2 waiting
    await asyncio.sleep(0.01)
    try:
        async with chromium_slot():
            pass
        raise AssertionError("a full queue must refuse")
    except slot.QueueFull as exc:
        assert exc.retry_after >= 1
    release.set()
    await asyncio.gather(*tasks)


def test_a_full_queue_answers_503_with_retry_after():
    from backend.api.routes.resumes import _pdf_http_error
    from backend.services.chromium_slot import QueueFull
    err = _pdf_http_error(QueueFull(7), context="test")
    assert err.status_code == 503 and err.headers["Retry-After"] == "7"
