"""
Every route that spends LLM calls (or re-reads a whole feed) is rate limited.

A sweep found eleven /api/jobs routes and both Ariel probe routes calling
the LLM with no limit at all — including /analyze/start, three LLM calls per
request — and the feed 'sync' actions, each of which re-reads and re-scores
the user's whole feed (database egress, the Supabase free plan's binding
limit). One script could run up the bill or the quota.
"""
from fastapi.routing import APIRoute

from backend.api.deps import llm_rate_limit, sync_rate_limit
from backend.main import app

LLM_ROUTES = {
    ("POST", "/api/jobs/feed/refresh"), ("POST", "/api/jobs/{job_id}/fetch-jd"),
    ("POST", "/api/jobs/{job_id}/tailor-cv"), ("POST", "/api/jobs/{job_id}/tailor-cv/edit"),
    ("POST", "/api/jobs/analyze-job"), ("POST", "/api/jobs/analyze"), ("POST", "/api/jobs/analyze/start"),
    ("POST", "/api/jobs/scrape"), ("POST", "/api/jobs/{job_id}/verify/chat"),
    ("POST", "/api/jobs/{job_id}/ats-keywords"), ("POST", "/api/jobs/{job_id}/skills-gap"),
    ("POST", "/api/jobs/{job_id}/analyze-now"),
    ("POST", "/api/ariel/probe/start"), ("POST", "/api/ariel/probe/respond"),
}
SYNC_ROUTES = {("POST", "/api/jobs/feed/refresh-all"), ("POST", "/api/jobs/feed/backfill-jd")}


def _deps(method, path):
    for r in app.routes:
        if isinstance(r, APIRoute) and r.path == path and method in r.methods:
            return [d.call for d in r.dependant.dependencies]
    raise AssertionError(f"route not found: {method} {path}")


def test_llm_routes_have_the_llm_limit():
    missing = [f"{m} {p}" for m, p in sorted(LLM_ROUTES) if llm_rate_limit not in _deps(m, p)]
    assert not missing, f"LLM routes without llm_rate_limit: {missing}"


def test_feed_sync_routes_have_the_sync_limit():
    missing = [f"{m} {p}" for m, p in sorted(SYNC_ROUTES) if sync_rate_limit not in _deps(m, p)]
    assert not missing, f"sync routes without sync_rate_limit: {missing}"
