import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, patch
import httpx
from backend.main import app
from backend.api.deps import CurrentUser, get_current_user

client = TestClient(app)


@pytest.fixture
def mock_fetch():
    with patch("backend.scrapers.proxy_manager.ProxyManager.fetch_with_retry", new_callable=AsyncMock) as mock:
        yield mock


@pytest.fixture(autouse=True)
def _authenticated():
    """
    /preview requires auth as of 2026-08-20 (was reachable unauthenticated —
    SSRF surface, see backend/api/routes/scraper.py). Every test in this
    file exercises the route's own logic, not auth itself, so the override
    is autouse; test_preview_scraper_requires_auth below removes it for the
    one test that checks the auth boundary itself.
    """
    def _override():
        return CurrentUser(user_id="qa-user", email="qa@test.com", name="QA")

    app.dependency_overrides[get_current_user] = _override
    yield
    app.dependency_overrides.pop(get_current_user, None)


def test_preview_scraper_requires_auth(mock_fetch):
    app.dependency_overrides.pop(get_current_user, None)  # undo the autouse override
    response = client.post("/api/v1/scraper/preview", json={"url": "http://example.com/job/1"})
    assert response.status_code == 401
    assert mock_fetch.call_count == 0


def test_preview_scraper_with_url(mock_fetch):
    mock_response = httpx.Response(
        200, 
        request=httpx.Request("GET", "http://example.com/job/1"),
        content=b"<html><body><h1 class='title'>Senior Engineer</h1><p>Test description</p></body></html>"
    )
    mock_fetch.return_value = mock_response

    payload = {
        "url": "http://example.com/job/1"
    }

    response = client.post("/api/v1/scraper/preview", json=payload)
    
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == "preview-12345"
    assert data["title"] == "Senior Engineer"
    assert data["company"] == "Preview Company"
    assert data["source_url"] == "http://example.com/job/1"
    assert "Test description" in data["raw_text"]
    assert mock_fetch.call_count == 1

def test_preview_scraper_with_html_bypass(mock_fetch):
    # Should not call fetch_with_retry if html is provided
    payload = {
        "url": "http://example.com/job/2",
        "html": "<html><body><h1>Bypass Title</h1><p>Direct HTML content</p></body></html>"
    }

    response = client.post("/api/v1/scraper/preview", json=payload)
    
    assert response.status_code == 200
    data = response.json()
    assert data["title"] == "Bypass Title"
    assert "Direct HTML content" in data["raw_text"]
    assert mock_fetch.call_count == 0

def test_preview_scraper_timeout(mock_fetch):
    mock_fetch.side_effect = httpx.TimeoutException("Timeout")

    payload = {
        "url": "http://example.com/job/timeout"
    }

    response = client.post("/api/v1/scraper/preview", json=payload)
    
    assert response.status_code == 504
    assert "timed out" in response.json()["detail"]

def test_preview_scraper_fetch_failure(mock_fetch):
    mock_fetch.side_effect = Exception("Connection Refused")

    payload = {
        "url": "http://example.com/job/fail"
    }

    response = client.post("/api/v1/scraper/preview", json=payload)
    
    assert response.status_code == 500
    assert "Failed to fetch URL" in response.json()["detail"]
