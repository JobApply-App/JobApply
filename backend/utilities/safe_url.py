"""
Fetch only addresses on the public internet.

Several endpoints fetch a URL the user typed (analyze a job link, scrape a
company careers page). Nothing checked where that URL pointed, so a user
could make the server request its own internal network: http://localhost,
the 10.x addresses of Render's private network, or a cloud metadata service
at 169.254.169.254. The page text is then stored on a job the user can read
back, which turns the fetch into a way to read internal pages (SSRF).

assert_public_url() allows http(s) only and resolves the host, refusing it
when ANY address it resolves to is not a public one (private, loopback,
link-local, carrier-grade NAT, multicast, reserved). Redirects are the
other way around a check at the door, so the fetch helpers here follow
redirects themselves and check every hop.

Known limit: a hostname can resolve to a public address when checked and a
private one when connected (DNS rebinding). Closing that needs pinning the
resolved IP into the connection; the check here stops every plain attempt.
"""
from __future__ import annotations

import asyncio
import ipaddress
import socket
from typing import Any
from urllib.parse import urljoin, urlparse

_MAX_REDIRECTS = 5


class UnsafeURL(ValueError):
    """The URL is not an http(s) address on the public internet."""


def _is_public(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    mapped = getattr(ip, "ipv4_mapped", None)
    if mapped is not None:
        ip = mapped
    return ip.is_global and not ip.is_multicast


def assert_public_url(url: str) -> str:
    """Return url unchanged, or raise UnsafeURL."""
    parsed = urlparse(str(url or "").strip())
    if parsed.scheme not in ("http", "https"):
        raise UnsafeURL("only http and https links are allowed")
    host = parsed.hostname
    if not host:
        raise UnsafeURL("the link has no host")
    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError as exc:
        raise UnsafeURL("the link has an invalid port") from exc
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except (socket.gaierror, UnicodeError) as exc:
        raise UnsafeURL("the host does not resolve") from exc
    for info in infos:
        ip = ipaddress.ip_address(str(info[4][0]).split("%", 1)[0])
        if not _is_public(ip):
            raise UnsafeURL("the link points to a private or reserved address")
    return url


async def assert_public_url_async(url: str) -> str:
    """assert_public_url without blocking the event loop on DNS."""
    return await asyncio.to_thread(assert_public_url, url)


def safe_requests_get(url: str, **kwargs: Any):
    """requests.get that refuses non-public targets, on every redirect hop."""
    import requests

    kwargs.pop("allow_redirects", None)
    for _ in range(_MAX_REDIRECTS + 1):
        assert_public_url(url)
        resp = requests.get(url, allow_redirects=False, **kwargs)
        if resp.is_redirect and resp.headers.get("location"):
            url = urljoin(url, resp.headers["location"])
            resp.close()
            continue
        return resp
    raise UnsafeURL("too many redirects")


async def _check_request(request) -> None:
    await assert_public_url_async(str(request.url))


def httpx_guard_hooks() -> dict:
    """event_hooks for an httpx.AsyncClient: every request, redirects
    included, must target a public address."""
    return {"request": [_check_request]}
