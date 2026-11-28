"""Company-level Greenhouse / Lever adapters — parsing, URL handling, failure paths."""
import httpx
import pytest

import backend.scrapers.ats_board_adapters as mod
from backend.scrapers.ats_board_adapters import GreenhouseBoardAdapter, LeverBoardAdapter
from backend.scrapers.scraper_manager import scraper_from_config

_GH = {"jobs": [
    {
        "id": 1, "title": "Senior Product Manager",
        "absolute_url": "https://job-boards.greenhouse.io/wizinc/jobs/1",
        "location": {"name": "Tel Aviv, Israel"},
        "departments": [{"name": "Product"}],
        "content": "&lt;p&gt;Own the roadmap.&lt;/p&gt;&lt;ul&gt;&lt;li&gt;5+ years&lt;/li&gt;&lt;/ul&gt;",
        "first_published": "2026-11-27T09:00:00-04:00",
    },
    {"id": 2, "title": "", "absolute_url": "https://job-boards.greenhouse.io/wizinc/jobs/2"},
]}

_LEVER = [
    {
        "id": "abc", "text": "Customer Success Lead",
        "hostedUrl": "https://jobs.lever.co/acme/abc",
        "categories": {"location": "Tel Aviv", "team": "CS", "commitment": "Full-time"},
        "workplaceType": "remote",
        "createdAt": 1764230400000,
        "descriptionPlain": "Lead the CS team.",
        "lists": [{"text": "Requirements", "content": "<li>3+ years in SaaS</li>"}],
        "additionalPlain": "Hybrid in TLV.",
    },
    {"id": "nourl", "text": "No URL"},
]


def _mock(monkeypatch, handler):
    real = httpx.AsyncClient
    seen = []

    def wrapped(request):
        seen.append(str(request.url))
        return handler(request)

    monkeypatch.setattr(
        mod.httpx, "AsyncClient",
        lambda **kw: real(transport=httpx.MockTransport(wrapped), **kw),
    )
    return seen


async def test_greenhouse_parses_all_postings(monkeypatch):
    seen = _mock(monkeypatch, lambda r: httpx.Response(200, json=_GH))
    jobs = await GreenhouseBoardAdapter("Wiz", "https://boards.greenhouse.io/wizinc", user_id="u1").fetch_jobs()

    assert seen == ["https://boards-api.greenhouse.io/v1/boards/wizinc/jobs?content=true"]
    assert len(jobs) == 1                       # untitled posting dropped
    j = jobs[0]
    assert j.title == "Senior Product Manager"
    assert j.company == "Wiz"
    assert j.location == "Tel Aviv, Israel"
    assert j.apply_url == "https://job-boards.greenhouse.io/wizinc/jobs/1"
    assert j.job_id.startswith("greenhouse-")
    assert j.user_id == "u1" and j.source_type == "company_site" and j.match_score == 0.0
    assert "Department: Product" in j.jd_text
    assert "Own the roadmap." in j.jd_text and "5+ years" in j.jd_text
    assert "&lt;" not in j.jd_text and "<p>" not in j.jd_text
    assert j.posted_at                          # a date label, not blank


async def test_lever_parses_all_postings(monkeypatch):
    seen = _mock(monkeypatch, lambda r: httpx.Response(200, json=_LEVER))
    jobs = await LeverBoardAdapter("Acme", "https://jobs.lever.co/acme/", user_id="u1").fetch_jobs()

    assert seen == ["https://api.lever.co/v0/postings/acme?mode=json"]
    assert len(jobs) == 1                       # posting without a URL dropped
    j = jobs[0]
    assert j.title == "Customer Success Lead"
    assert j.location == "Remote · Tel Aviv"
    assert j.job_id.startswith("lever-")
    for piece in ("Department: CS", "Employment: Full-time", "Lead the CS team.",
                  "Requirements", "3+ years in SaaS", "Hybrid in TLV."):
        assert piece in j.jd_text


@pytest.mark.parametrize("url,slug", [
    ("https://boards.greenhouse.io/wizinc", "wizinc"),
    ("https://job-boards.greenhouse.io/wizinc/jobs/123", "wizinc"),
    ("wizinc", "wizinc"),
    ("https://evil.example.com/wizinc", None),
    ("https://boards.greenhouse.io/", None),
])
def test_greenhouse_slug(url, slug):
    assert GreenhouseBoardAdapter("X", url)._slug == slug


async def test_bad_url_makes_no_request(monkeypatch):
    seen = _mock(monkeypatch, lambda r: httpx.Response(200, json=[]))
    assert await LeverBoardAdapter("X", "https://example.com/acme").fetch_jobs() == []
    assert seen == []


@pytest.mark.parametrize("response", [
    httpx.Response(404, json={"status": 404, "error": "Job not found"}),
    httpx.Response(200, json={"unexpected": True}),
    httpx.Response(200, text="<html>not json</html>"),
])
async def test_greenhouse_failures_return_empty(monkeypatch, response):
    _mock(monkeypatch, lambda r: response)
    assert await GreenhouseBoardAdapter("X", "wizinc").fetch_jobs() == []


def test_registry_builds_both():
    gh = scraper_from_config({"company_name": "Wiz", "company_url": "wizinc", "adapter": "greenhouse"})
    lv = scraper_from_config({"company_name": "Acme", "company_url": "acme", "adapter": "Lever"})
    assert isinstance(gh, GreenhouseBoardAdapter)
    assert isinstance(lv, LeverBoardAdapter)


# ── Israel-or-remote scope (founder's call, 2026-11-28) ──────────────────────

@pytest.mark.parametrize("locations,remote,keep", [
    (["Tel Aviv"], False, True),
    (["Herzliya, Israel"], False, True),
    (["Chicago, IL"], False, False),                   # IL is also Illinois
    (["Israel"], False, True),
    (["תל אביב"], False, True),
    (["Petach Tikva / New York"], False, True),
    (["New York City", "Tel Aviv"], False, True),      # one of several offices
    (["Remote, US"], False, True),                     # remote abroad is never dropped
    (["London"], True, True),                          # remote by workplace type
    (["Anywhere"], False, True),
    (["New York City"], False, False),
    (["Seoul"], False, False),
    (["Acre, Brazil"], False, False),
    ([""], False, False),
])
def test_israel_or_remote(locations, remote, keep):
    assert mod.israel_or_remote(locations, remote=remote) is keep


async def test_greenhouse_drops_jobs_abroad(monkeypatch):
    data = {"jobs": [
        {**_GH["jobs"][0], "id": 10, "absolute_url": "https://x/10", "location": {"name": "New York City"}},
        {**_GH["jobs"][0], "id": 11, "absolute_url": "https://x/11", "location": {"name": "New York City"},
         "offices": [{"name": "Tel Aviv", "location": "Tel Aviv, Israel"}]},
        {**_GH["jobs"][0], "id": 12, "absolute_url": "https://x/12", "location": {"name": "Remote - EMEA"}},
    ]}
    _mock(monkeypatch, lambda r: httpx.Response(200, json=data))
    jobs = await GreenhouseBoardAdapter("Wiz", "wizinc").fetch_jobs()
    assert sorted(j.apply_url for j in jobs) == ["https://x/11", "https://x/12"]


async def test_lever_drops_jobs_abroad(monkeypatch):
    base = {**_LEVER[0], "workplaceType": "hybrid"}
    data = [
        {**base, "id": "a", "hostedUrl": "https://l/a", "categories": {"location": "Singapore"}},
        {**base, "id": "b", "hostedUrl": "https://l/b", "categories": {"location": "Singapore",
                                                                     "allLocations": ["Singapore", "Tel Aviv"]}},
        {**base, "id": "c", "hostedUrl": "https://l/c", "categories": {"location": "London"},
         "workplaceType": "remote"},
        {**base, "id": "d", "hostedUrl": "https://l/d", "categories": {"location": "HQ"}, "country": "IL"},
    ]
    _mock(monkeypatch, lambda r: httpx.Response(200, json=data))
    jobs = await LeverBoardAdapter("Acme", "acme").fetch_jobs()
    assert sorted(j.apply_url for j in jobs) == ["https://l/b", "https://l/c", "https://l/d"]


def test_default_registry_has_israeli_greenhouse_boards(monkeypatch):
    import backend.main as main_mod
    from backend.scrapers import scraper_manager as sm

    fresh = sm.ScraperManager()
    monkeypatch.setattr(sm, "SCRAPER_MANAGER", fresh)
    main_mod._seed_scraper_registry()

    boards = [s for s in fresh._scrapers if isinstance(s, GreenhouseBoardAdapter)]
    assert len(boards) >= 20
    assert all(b._slug for b in boards)                       # every URL parses to a slug
    assert len({b._slug for b in boards}) == len(boards)      # no duplicates
