"""
Behind Render's load balancer every anonymous request arrived from one of a
few internal 10.x addresses, so all visitors shared a handful of rate-limit
buckets. The client is the last X-Forwarded-For entry, which the balancer
appends; earlier entries are client-supplied and ignored.
"""
from types import SimpleNamespace

from backend.api.deps import _client_ip


def _req(peer, xff=None):
    headers = {"x-forwarded-for": xff} if xff is not None else {}
    return SimpleNamespace(client=SimpleNamespace(host=peer), headers=headers)


def test_behind_render_the_real_client_is_used():
    assert _client_ip(_req("10.24.158.133", "203.0.113.7")) == "203.0.113.7"


def test_a_forged_forwarded_for_cannot_pick_the_bucket():
    assert _client_ip(_req("10.24.158.133", "1.2.3.4, 203.0.113.7")) == "203.0.113.7"


def test_a_direct_public_caller_cannot_spoof():
    assert _client_ip(_req("8.8.8.8", "1.2.3.4")) == "8.8.8.8"


def test_the_local_nextjs_proxy_still_forwards_the_visitor():
    assert _client_ip(_req("127.0.0.1", "203.0.113.7")) == "203.0.113.7"
