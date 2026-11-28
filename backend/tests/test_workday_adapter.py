"""Company-level Workday adapter: facets, Israel only, the per-run cap, retries."""
import json

import httpx
import pytest

import backend.scrapers.workday_adapter as mod
from backend.scrapers.scraper_manager import scraper_from_config
from backend.scrapers.workday_adapter import WorkdayBoardAdapter, parse_site

SITE = "https://acme.wd5.myworkdayjobs.com/en-US/AcmeCareers"
BASE = "https://acme.wd5.myworkdayjobs.com/wday/cxs/acme/AcmeCareers"

FACETS = [{
    "facetParameter": "locationMainGroup",
    "values": [
        {"facetParameter": "locationHierarchy1", "values": [
            {"descriptor": "Israel", "id": "IL", "count": 3},
            {"descriptor": "Germany", "id": "DE", "count": 9},
        ]},
        {"facetParameter": "locationHierarchy2", "values": [
            {"descriptor": "Remote", "id": "RM", "count": 2},
        ]},
        {"facetParameter": "locations", "values": [
            {"descriptor": "Israel, Tel Aviv", "id": "TLV", "count": 2},
            {"descriptor": "Germany, Remote", "id": "DER", "count": 1},
        ]},
    ],
}]

DETAILS = {
    "/job/Israel-Tel-Aviv/PM_1": {"title": "Product Manager", "location": "Israel, Tel Aviv",
                                  "externalUrl": "https://acme.example/job/1", "startDate": "2026-11-27",
                                  "jobDescription": "<p>Own the roadmap.</p>"},
    "/job/Israel-Haifa/QA_2": {"title": "QA Engineer", "location": "2 Locations",
                               "additionalLocations": ["Israel, Haifa"],
                               "externalUrl": "https://acme.example/job/2", "jobDescription": "<p>Test.</p>"},
    "/job/Germany-Remote/SE_3": {"title": "Software Engineer", "location": "Germany, Remote",
                                 "externalUrl": "https://acme.example/job/3", "jobDescription": "<p>Code.</p>"},
    "/job/Germany-Berlin/X_4": {"title": "Office Manager", "location": "Germany, Berlin",
                                "externalUrl": "https://acme.example/job/4", "jobDescription": "<p>Office.</p>"},
}
BY_FACET = {
    "IL": ["/job/Israel-Tel-Aviv/PM_1", "/job/Israel-Haifa/QA_2", "/job/Germany-Berlin/X_4"],  # last one mislabelled
    "RM": ["/job/Germany-Remote/SE_3", "/job/Israel-Tel-Aviv/PM_1"],                           # PM_1 again: deduped
}


def _handler(seen):
    def handle(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path, request.content))
        if request.method == "POST":
            body = json.loads(request.content)
            applied = body["appliedFacets"]
            if not applied:
                return httpx.Response(200, json={"total": 2000, "facets": FACETS, "jobPostings": [{}]})
            (ids,) = applied.values()
            paths = [p for fid in ids for p in BY_FACET.get(fid, [])]
            page = paths[body["offset"]: body["offset"] + body["limit"]]
            return httpx.Response(200, json={"total": len(paths), "jobPostings": [{"externalPath": p} for p in page]})
        path = request.url.path.removeprefix("/wday/cxs/acme/AcmeCareers")
        return httpx.Response(200, json={"jobPostingInfo": DETAILS[path]})
    return handle


def _mock(monkeypatch, handler):
    real = httpx.AsyncClient
    monkeypatch.setattr(mod.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    async def instant(_):
        return None
    monkeypatch.setattr(mod.asyncio, "sleep", instant)


async def test_fetches_israel_only_and_filters(monkeypatch):
    seen = []
    _mock(monkeypatch, _handler(seen))
    jobs = await WorkdayBoardAdapter("Acme", SITE, user_id="u1").fetch_jobs()

    assert sorted(j.apply_url for j in jobs) == [
        "https://acme.example/job/1", "https://acme.example/job/2",
    ]                                                   # Berlin dropped on the detail's own location
    posts = [json.loads(c)["appliedFacets"] for m, _, c in seen if m == "POST"]
    assert {"locationHierarchy1": ["IL"]} in posts      # the exact "Israel" group, not "Israel, Tel Aviv"
    assert all("locationHierarchy2" not in p for p in posts)   # no remote query (Ron's call)
    assert not any(p.endswith("SE_3") for m, p, _ in seen if m == "GET")

    pm = next(j for j in jobs if j.title == "Product Manager")
    assert pm.company == "Acme" and pm.user_id == "u1" and pm.job_id.startswith("workday-")
    assert pm.location == "Israel, Tel Aviv" and pm.posted_at
    assert "Own the roadmap." in pm.jd_text and "<p>" not in pm.jd_text


async def test_cap_limits_detail_calls(monkeypatch):
    seen = []
    _mock(monkeypatch, _handler(seen))
    monkeypatch.setattr(mod, "MAX_POSTINGS", 2)
    await WorkdayBoardAdapter("Acme", SITE).fetch_jobs()
    assert sum(1 for m, *_ in seen if m == "GET") == 2


async def test_retries_429_then_succeeds(monkeypatch):
    calls = {"n": 0}
    inner = _handler([])

    def flaky(request):
        calls["n"] += 1
        if calls["n"] <= 2:
            return httpx.Response(429, headers={"Retry-After": "1"})
        return inner(request)

    _mock(monkeypatch, flaky)
    assert len(await WorkdayBoardAdapter("Acme", SITE).fetch_jobs()) == 2


async def test_gives_up_after_retries(monkeypatch, caplog):
    calls = {"n": 0}

    def refuse(request):
        calls["n"] += 1
        return httpx.Response(429)

    _mock(monkeypatch, refuse)
    assert await WorkdayBoardAdapter("Acme", SITE).fetch_jobs() == []
    assert calls["n"] == mod._RETRIES + 1
    assert "list fetch failed" in caplog.text


@pytest.mark.parametrize("url,site", [
    (SITE, ("acme.wd5.myworkdayjobs.com", "acme", "AcmeCareers")),
    ("https://intel.wd1.myworkdayjobs.com/External", ("intel.wd1.myworkdayjobs.com", "intel", "External")),
    ("https://intel.wd1.myworkdayjobs.com/", None),
    ("https://example.com/External", None),
])
def test_parse_site(url, site):
    assert parse_site(url) == site


def test_registry_builds_workday():
    s = scraper_from_config({"company_name": "Acme", "company_url": SITE, "adapter": "workday"})
    assert isinstance(s, WorkdayBoardAdapter)


async def test_shows_the_israeli_office_when_listed_abroad_first(monkeypatch):
    DETAILS["/job/Israel-Haifa/QA_2"]["location"] = "US, CA, Santa Clara"
    try:
        _mock(monkeypatch, _handler([]))
        jobs = await WorkdayBoardAdapter("Acme", SITE).fetch_jobs()
        assert next(j for j in jobs if j.title == "QA Engineer").location == "Israel, Haifa"
    finally:
        DETAILS["/job/Israel-Haifa/QA_2"]["location"] = "2 Locations"


async def test_remote_abroad_is_dropped_even_if_listed_under_israel(monkeypatch):
    BY_FACET["IL"].append("/job/Germany-Remote/SE_3")
    try:
        _mock(monkeypatch, _handler([]))
        jobs = await WorkdayBoardAdapter("Acme", SITE).fetch_jobs()
        assert "Software Engineer" not in {j.title for j in jobs}
    finally:
        BY_FACET["IL"].remove("/job/Germany-Remote/SE_3")


@pytest.mark.parametrize("loc,keep", [
    ("Israel, Tel Aviv", True), ("Israel, Remote", True), ("Yokneam", True),
    ("Germany, Remote", False), ("US, CA, Santa Clara", False), ("Chicago, IL", False), ("", False),
])
def test_in_israel(loc, keep):
    from backend.scrapers.ats_board_adapters import in_israel
    assert in_israel(loc) is keep


def test_default_registry_has_workday_sites(monkeypatch):
    import backend.main as main_mod
    from backend.scrapers import scraper_manager as sm

    fresh = sm.ScraperManager()
    monkeypatch.setattr(sm, "SCRAPER_MANAGER", fresh)
    main_mod._seed_scraper_registry()

    sites = [s for s in fresh._scrapers if isinstance(s, WorkdayBoardAdapter)]
    assert len(sites) >= 8
    assert all(s._site for s in sites)                         # every URL parses
    assert fresh._scrapers[-len(sites):] == sites              # registered last
