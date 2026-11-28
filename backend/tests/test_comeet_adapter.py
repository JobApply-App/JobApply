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
