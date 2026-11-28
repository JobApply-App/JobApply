"""ATS detection from a careers page (stage 0 of docs/research/10-company-page-watching-pilot.md).

The HTML snippets are trimmed from the real pages on 2026-11-28.
"""
import asyncio

import httpx
import pytest

import backend.scrapers.ats_detect as mod
from backend.scrapers.ats_detect import detect_ats, detect_from_html, detect_from_url
from backend.scrapers.scraper_manager import scraper_from_config


def _links(href: str, n: int) -> str:
    return "".join(f'<a href="{href}{i}">Job {i}</a>' for i in range(n))


# Mobileye: its own Lever EU board, plus a subsidiary's Comeet board less often.
MOBILEYE = (_links("https://jobs.eu.lever.co/mobileye/7aa00e13-3ae1-4dd7-a853-", 20)
            + _links("https://www.comeet.com/jobs/mentee_robotics/6A.002/ai-engineer/37.47", 3))
NICE = _links("https://boards.eu.greenhouse.io/nice/jobs/50010491", 3)
FIVERR = '<a href="https://www.comeet.com/jobs/fiverr/60.002/business-manager/38.168">x</a>'
CYBERARK = '<a href="https://paloaltonetworks.wd5.myworkdayjobs.com/en-US/panwexternalcareers/introduceYourself?client=x">Apply</a>'
EMBED = '<script src="https://boards.greenhouse.io/embed/job_board/js?for=acme"></script>'
PLAYTIKA = '<script src="/js/greenHouseMain.js"></script><script>getGreenHouseJobs();</script>'
VERINT = '<a href="https://jobs.ashbyhq.com/27cfd344-670f-4dcd-8b13-0e18005b0d65">Jobs</a>'


@pytest.mark.parametrize("html,expected", [
    (MOBILEYE, ("lever", "https://jobs.eu.lever.co/mobileye")),        # most links wins
    (NICE, ("greenhouse", "https://job-boards.eu.greenhouse.io/nice")),
    (FIVERR, ("comeet", "https://www.comeet.com/jobs/fiverr/60.002")),
    (CYBERARK, ("workday", "https://paloaltonetworks.wd5.myworkdayjobs.com/panwexternalcareers")),
    (EMBED, ("greenhouse", "https://job-boards.greenhouse.io/acme")),  # not "embed"
    (PLAYTIKA, None),                                                  # board loaded from a script
    (VERINT, None),                                                    # Ashby: no adapter
    ("", None),
])
def test_detect_from_html(html, expected):
    assert detect_from_html(html) == expected


@pytest.mark.parametrize("url,expected", [
    ("https://jobs.lever.co/palantir", ("lever", "https://jobs.lever.co/palantir")),
    ("https://boards.greenhouse.io/wizinc/jobs/123", ("greenhouse", "https://job-boards.greenhouse.io/wizinc")),
    ("https://intel.wd1.myworkdayjobs.com/en-US/External/job/Israel-Haifa/X_JR1",
     ("workday", "https://intel.wd1.myworkdayjobs.com/External")),
    ("https://www.comeet.com/jobs/comm-it/76.008", ("comeet", "https://www.comeet.com/jobs/comm-it/76.008")),
    ("https://www.monday.com/careers", None),
])
def test_detect_from_url(url, expected):
    assert detect_from_url(url) == expected


@pytest.mark.parametrize("html", [MOBILEYE, NICE, FIVERR, CYBERARK])
def test_every_detection_builds_an_adapter(html):
    adapter, url = detect_from_html(html)
    assert scraper_from_config({"company_name": "X", "company_url": url, "adapter": adapter}) is not None


def _mock(monkeypatch, handler):
    real = httpx.AsyncClient
    seen = []

    def wrapped(request):
        seen.append(str(request.url))
        return handler(request)

    monkeypatch.setattr(mod.httpx, "AsyncClient",
                        lambda **kw: real(transport=httpx.MockTransport(wrapped), **kw))
    return seen


def test_detect_ats_reads_the_page(monkeypatch):
    seen = _mock(monkeypatch, lambda r: httpx.Response(200, text=NICE))
    assert asyncio.run(detect_ats("https://www.nice.com/careers")) == ("greenhouse", "https://job-boards.eu.greenhouse.io/nice")
    assert seen == ["https://www.nice.com/careers"]


def test_detect_ats_skips_the_fetch_for_an_ats_url(monkeypatch):
    seen = _mock(monkeypatch, lambda r: httpx.Response(200, text=""))
    assert asyncio.run(detect_ats("https://jobs.lever.co/palantir"))[0] == "lever"
    assert seen == []


@pytest.mark.parametrize("response", [httpx.Response(403, text=FIVERR), httpx.Response(200, text=PLAYTIKA)])
def test_detect_ats_none_on_refusal_or_nothing_found(monkeypatch, response):
    _mock(monkeypatch, lambda r: response)
    assert asyncio.run(detect_ats("https://www.example.com/careers")) is None


def test_route_resolves_auto_and_skips_unknown(monkeypatch):
    from backend.api.routes import jobs

    async def fake_detect(url):
        return ("lever", "https://jobs.eu.lever.co/mobileye") if "mobileye" in url else None
    monkeypatch.setattr(mod, "detect_ats", fake_detect)

    resolved = asyncio.run(jobs._resolve_adapter(
        {"company_name": "Mobileye", "company_url": "https://careers.mobileye.com/jobs", "adapter": "auto"}))
    assert resolved["adapter"] == "lever" and resolved["company_url"] == "https://jobs.eu.lever.co/mobileye"

    assert asyncio.run(jobs._resolve_adapter(
        {"company_name": "monday", "company_url": "https://www.monday.com/careers", "adapter": "auto"})) is None

    explicit = {"company_name": "Wiz", "company_url": "wizinc", "adapter": "greenhouse"}
    assert asyncio.run(jobs._resolve_adapter(explicit)) is explicit
