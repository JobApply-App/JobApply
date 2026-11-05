"""
User-supplied links were fetched with no check, so a job link could point the
server at its own internal network (SSRF). Only public http(s) addresses are
fetched now, on every redirect hop.
"""
import socket
from types import SimpleNamespace

import pytest

from backend.utilities import safe_url
from backend.utilities.safe_url import UnsafeURL, assert_public_url, safe_requests_get

_DNS = {
    "jobs.example.com": "93.184.216.34",
    "internal.example.com": "10.0.0.5",
    "rebind.example.com": "169.254.169.254",
}


@pytest.fixture(autouse=True)
def fake_dns(monkeypatch):
    def getaddrinfo(host, port, *a, **k):
        ip = _DNS.get(host, host)
        try:
            socket.inet_pton(socket.AF_INET6 if ":" in ip else socket.AF_INET, ip)
        except OSError:
            raise socket.gaierror("no such host")
        fam = socket.AF_INET6 if ":" in ip else socket.AF_INET
        return [(fam, socket.SOCK_STREAM, 6, "", (ip, port))]
    monkeypatch.setattr(safe_url.socket, "getaddrinfo", getaddrinfo)


@pytest.mark.parametrize("url", [
    "http://localhost:8000/health",
    "http://127.0.0.1/",
    "http://10.24.158.133/",              # Render's private network
    "http://169.254.169.254/latest/meta-data/",
    "http://[::1]/",
    "http://[::ffff:127.0.0.1]/",
    "http://100.64.0.1/",                 # carrier-grade NAT
    "http://internal.example.com/",       # public name, private address
    "file:///etc/passwd",
    "gopher://jobs.example.com/",
    "http://no-such-host.invalid/",
])
def test_non_public_targets_are_refused(url):
    with pytest.raises(UnsafeURL):
        assert_public_url(url)


def test_a_public_job_link_is_allowed():
    assert assert_public_url("https://jobs.example.com/careers/123") == "https://jobs.example.com/careers/123"


def test_a_redirect_into_the_private_network_is_refused(monkeypatch):
    calls = []

    def fake_get(url, allow_redirects, **kw):
        calls.append(url)
        assert allow_redirects is False
        return SimpleNamespace(is_redirect=True, headers={"location": "http://rebind.example.com/x"},
                               close=lambda: None)

    import requests
    monkeypatch.setattr(requests, "get", fake_get)
    with pytest.raises(UnsafeURL):
        safe_requests_get("https://jobs.example.com/apply")
    assert calls == ["https://jobs.example.com/apply"]   # the private hop was never requested


def test_the_scrapers_refuse_private_links():
    from backend.scrapers.url_router import scrape_jd_text, scrape_linkedin_job
    from backend.url_scraper import scrape_job_post
    for fn in (scrape_job_post, scrape_jd_text, scrape_linkedin_job):
        with pytest.raises(UnsafeURL):
            fn("http://10.0.0.1/?linkedin.com/jobs/view/123")
