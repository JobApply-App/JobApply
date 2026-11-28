"""
ComeetAdapter credential scraping — DB-free (`pytest --noconftest`).

On 2026-11-28 the Wix default (comeet.com/jobs/wix/ED.30A) 302'd to Comeet's
marketing homepage. The adapter then reported "Could not find Comeet API
token", which reads like a scraping bug; the real cause was that Wix no
longer has a Comeet board. These tests pin the clearer error, and that a
real board page still yields uid + token.
"""
import logging
from unittest.mock import AsyncMock, patch

import pytest

from backend.scrapers.comeet_adapter import ComeetAdapter

_HOMEPAGE = "<html><title>Spark Hire Recruit - The Applicant Tracking System</title></html>"
_BOARD = (
    '<script>COMPANY_DATA = {"name": "Acme", "company_uid": "30.005", '
    '"token": "359F1DD13E1DD1DD1A813E6A6A"}; POSITIONS_DATA = [];</script>'
)


def _patch_page(html: str):
    return patch.object(
        ComeetAdapter, "_fetch_html_with_fallback", new=AsyncMock(return_value=html)
    )


async def test_homepage_redirect_is_reported_as_no_board():
    adapter = ComeetAdapter("Wix", "https://www.comeet.co/jobs/wix/ED.30A/all")
    with _patch_page(_HOMEPAGE):
        with pytest.raises(ValueError, match="no Comeet board"):
            await adapter._scrape_credentials(adapter._page_url)


async def test_fetch_jobs_logs_the_reason_and_returns_empty(caplog):
    adapter = ComeetAdapter("Wix", "https://www.comeet.co/jobs/wix/ED.30A/all")
    with _patch_page(_HOMEPAGE), caplog.at_level(logging.WARNING):
        assert await adapter.fetch_jobs() == []
    assert "no Comeet board" in caplog.text


async def test_real_board_page_yields_uid_and_token():
    adapter = ComeetAdapter("Acme", "https://www.comeet.co/jobs/acme/30.005/all")
    with _patch_page(_BOARD):
        uid, token = await adapter._scrape_credentials(adapter._page_url)
    assert uid == "30.005"
    assert token == "359F1DD13E1DD1DD1A813E6A6A"


def test_no_comeet_defaults_are_seeded():
    """The two dead Comeet defaults must not come back unnoticed."""
    import inspect

    from backend import main

    src = inspect.getsource(main._seed_scraper_registry)
    assert '"adapter":      "comeet"' not in src


def test_positions_sharing_a_company_careers_page_stay_distinct():
    """Comm-IT, 2026-11-28: 113 of 124 positions had the same
    careers_page_active_url (the company's generic careers page), so a job_id
    built from it collapsed them into one job."""
    adapter = ComeetAdapter("Comm-IT", "https://www.comeet.com/jobs/comm-it/76.008")
    shared = "https://www.comm-it.com/commit-jobs#career-sec"
    positions = [
        {
            "name": "AI R&D Forward Deployment Engineer",
            "position_uid": uid,
            "careers_page_active_url": shared,
            "careers_page_url": f"https://www.comeet.com/jobs/comm-it/76.008/ai-rd/{uid}",
            "location_object": {"city": city, "country": "IL"},
        }
        for uid, city in (("17.574", "Tel Aviv-Yafo"), ("17.574-43.606", "Hod Hasharon"))
    ]
    jobs = [adapter._parse_position(p) for p in positions]
    assert all(j is not None for j in jobs)
    assert len({j.job_id for j in jobs}) == 2
    assert all(j.apply_url != shared for j in jobs)


def test_active_url_is_used_when_no_hosted_page():
    adapter = ComeetAdapter("Acme", "https://www.comeet.com/jobs/acme/30.005")
    job = adapter._parse_position({
        "name": "PM", "careers_page_active_url": "https://acme.com/jobs/pm",
    })
    assert job is not None and job.apply_url == "https://acme.com/jobs/pm"
