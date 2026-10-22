"""
Analysing a pasted link survives the proxy timeout, and Workday links work.

A tester pasted an Intel posting (intel.wd1.myworkdayjobs.com): the page is
rendered client-side, so the generic scraper saw an empty shell and the
analysis failed. Separately, /analyze runs scrape + three LLM calls in one
request, which the Vercel proxy cuts off — and leaving the screen lost the
result. These tests pin the Workday JSON fallback and the start/status task.
"""
import asyncio
from fastapi import HTTPException

from backend.scrapers import ats_api_scraper as ats


# ── Workday ──────────────────────────────────────────────────────────────────

class _Resp:
    def __init__(self, payload):
        self._p = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._p


def test_workday_url_maps_to_the_public_json_endpoint(monkeypatch):
    seen = {}

    def _get(url, **_k):
        seen["url"] = url
        return _Resp({"jobPostingInfo": {
            "title": "Formal Verification Engineer",
            "location": "Israel, Haifa",
            "jobDescription": "<p>" + "Verify RTL designs with formal tools. " * 5 + "</p>",
        }})
    monkeypatch.setattr(ats.requests, "get", _get)

    out = ats.try_workday_api(
        "https://intel.wd1.myworkdayjobs.com/en-US/External/job/Israel-Haifa/Formal-Verification-Engineer_JR0287702"
    )
    assert seen["url"] == (
        "https://intel.wd1.myworkdayjobs.com/wday/cxs/intel/External/job/"
        "Israel-Haifa/Formal-Verification-Engineer_JR0287702"
    )
    assert out["title"] == "Formal Verification Engineer"
    assert out["company"] == "Intel"
    assert out["raw_text"].startswith("Location: Israel, Haifa")
    assert "<p>" not in out["raw_text"]


def test_non_workday_urls_are_ignored(monkeypatch):
    monkeypatch.setattr(ats.requests, "get", lambda *a, **k: (_ for _ in ()).throw(AssertionError("called")))
    assert ats.try_workday_api("https://boards.greenhouse.io/acme/jobs/1") is None
    assert ats.try_workday_api("https://intel.wd1.myworkdayjobs.com/External") is None


def test_thin_workday_payload_returns_none(monkeypatch):
    monkeypatch.setattr(ats.requests, "get", lambda *a, **k: _Resp({"jobPostingInfo": {"title": "X"}}))
    assert ats.try_workday_api("https://acme.wd5.myworkdayjobs.com/Careers/job/TLV/X_1") is None


# ── /analyze/start + /analyze/status ─────────────────────────────────────────
# Called directly in one event loop: the task must outlive the start request,
# which a TestClient without lifespan (a fresh loop per request) cannot show.

from backend.api.deps import CurrentUser
from backend.api.routes import jobs

_USER = CurrentUser(user_id="u1", email="t@example.com")


async def _finish(task_id, user=_USER):
    for _ in range(100):
        body = await jobs.get_analyze_status(task_id, user)
        if body["status"] != "pending":
            return body
        await asyncio.sleep(0.01)
    raise AssertionError("task never finished")


async def test_start_returns_immediately_and_status_returns_the_job(monkeypatch):
    async def _pipeline(request, user):
        await asyncio.sleep(0.05)
        return {"job_id": "j1", "url": request.url}
    monkeypatch.setattr(jobs, "analyze_job", _pipeline)

    start = await jobs.start_analyze_job(jobs.AnalyzeRequest(url="https://example.com/job"), _USER)
    assert start["status"] == "pending"
    assert (await jobs.get_analyze_status(start["task_id"], _USER))["status"] == "pending"
    assert await _finish(start["task_id"]) == {
        "status": "done", "result": {"job_id": "j1", "url": "https://example.com/job"},
    }


async def test_pipeline_errors_keep_their_status_and_detail(monkeypatch):
    async def _pipeline(request, user):
        raise HTTPException(status_code=422, detail="Scrape Failed: page returned no job description text.")
    monkeypatch.setattr(jobs, "analyze_job", _pipeline)

    start = await jobs.start_analyze_job(jobs.AnalyzeRequest(url="https://example.com/job"), _USER)
    done = await _finish(start["task_id"])
    assert done["status"] == "error" and done["status_code"] == 422
    assert done["detail"].startswith("Scrape Failed")


async def test_another_user_cannot_read_the_task(monkeypatch):
    async def _pipeline(request, user):
        return {"job_id": "secret"}
    monkeypatch.setattr(jobs, "analyze_job", _pipeline)

    start = await jobs.start_analyze_job(jobs.AnalyzeRequest(url="https://example.com/job"), _USER)
    await _finish(start["task_id"])
    intruder = CurrentUser(user_id="intruder", email="x@example.com")
    try:
        await jobs.get_analyze_status(start["task_id"], intruder)
    except HTTPException as exc:
        assert exc.status_code == 404
    else:
        raise AssertionError("another user read the task")
