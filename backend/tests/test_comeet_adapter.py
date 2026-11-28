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

from backend.scrapers.comeet_adapter import ComeetAdapter, _in_israel

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


def test_dead_comeet_defaults_stay_gone_and_comm_it_is_seeded():
    """Wix and Spark Hire returned 0 jobs on 2026-11-28; Comm-IT is live."""
    import inspect

    from backend import main

    src = inspect.getsource(main._seed_scraper_registry)
    assert "comeet.co/jobs/wix" not in src
    assert "spark-hire/30.005" not in src
    assert "comeet.com/jobs/comm-it/76.008" in src


def _pos(uid, country, city="", remote=""):
    return {
        "name": f"Engineer {uid}", "position_uid": uid, "Remote": remote,
        "careers_page_url": f"https://www.comeet.com/jobs/acme/30.005/x/{uid}",
        "location_object": {"country": country, "city": city, "name": city},
    }


def test_in_israel_trusts_comeet_country_code():
    assert _in_israel(_pos("a", "IL", "Petah Tikva"))
    assert _in_israel(_pos("b", "IL", "Tel Aviv-Yafo", remote="Hybrid"))
    assert not _in_israel(_pos("c", "PL", "Warsaw", remote="Remote"))
    assert not _in_israel(_pos("d", "US", "Springfield"))


def test_in_israel_falls_back_to_city_without_country():
    assert _in_israel(_pos("e", "", "Haifa"))
    assert _in_israel({"name": "x", "location": "Tel Aviv, Israel"})
    assert not _in_israel(_pos("f", "", "Buenos Aires", remote="Remote"))
    assert not _in_israel({"name": "x"})


async def test_fetch_jobs_keeps_only_israel_by_default():
    positions = [_pos("1", "IL", "Haifa"), _pos("2", "UA", "Kyiv", "Remote")]
    adapter = ComeetAdapter("Acme", "https://www.comeet.com/jobs/acme/30.005",
                            token="T" * 26, fetch_details=False)
    with patch.object(ComeetAdapter, "_fetch_positions_list",
                      new=AsyncMock(return_value=positions)):
        jobs = await adapter.fetch_jobs()
    assert [j.location for j in jobs] == ["Haifa, IL"]

    everywhere = ComeetAdapter("Acme", "https://www.comeet.com/jobs/acme/30.005",
                               token="T" * 26, fetch_details=False, israel_only=False)
    with patch.object(ComeetAdapter, "_fetch_positions_list",
                      new=AsyncMock(return_value=positions)):
        assert len(await everywhere.fetch_jobs()) == 2


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


async def test_city_variant_keeps_its_own_url_and_city_after_detail_merge():
    """Comeet's detail call for 17.574-43.606 returns the parent 17.574."""
    adapter = ComeetAdapter("Comm-IT", "https://www.comeet.com/jobs/comm-it/76.008",
                            token="T" * 26)
    parent = _pos("17.574", "IL", "Tel Aviv-Yafo")
    variant = _pos("17.574-43.606", "IL", "Hod Hasharon")
    parent_detail = {**parent, "description": "<p>Build things</p>"}
    with patch.object(ComeetAdapter, "_fetch_positions_list",
                      new=AsyncMock(return_value=[parent, variant])), \
         patch.object(ComeetAdapter, "_fetch_one_detail",
                      new=AsyncMock(return_value=parent_detail)):
        jobs = await adapter.fetch_jobs()
    assert len({j.job_id for j in jobs}) == 2
    assert sorted(j.location for j in jobs) == ["Hod Hasharon, IL", "Tel Aviv-Yafo, IL"]
    assert all("Build things" in (j.jd_text or "") for j in jobs)
