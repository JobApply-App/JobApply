"""
pytest configuration for backend/tests/
========================================
Ensures the project root is on sys.path so the canonical `backend.*` package
path resolves when pytest is run from anywhere.

All intra-backend imports use the `backend.` prefix (see main.py). The bare
`api.*` / `services.*` / `config` forms are forbidden: they load the same
file as a second, independent module object, which breaks monkeypatching and
FastAPI dependency_overrides (the override keys on a different function
object than the one the app actually calls).
"""
import os
import sys
import pytest
from pathlib import Path
from sqlalchemy import text

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent   # .../JobApply_Venture

if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# Must run before backend.config is first imported (which happens the moment
# any test module imports backend.main/backend.api.deps) — backend/api/deps.py's
# get_current_user() raises 503 if NEITHER SUPABASE_URL nor SUPABASE_JWT_SECRET
# is configured, before it ever reaches the "no token supplied" branch a test
# like test_route_requires_authentication_without_override needs to hit to
# get its expected 401. CI has no backend/.env (gitignored, never checked
# out) so os.getenv returns None there. A dummy value is sufficient: no test
# in this suite verifies a real Supabase-issued JWT signature — every
# authenticated-path test overrides get_current_user via
# app.dependency_overrides instead (see e.g. test_linkedin_jobs_route.py's
# `client` fixture). setdefault() so a real secret — set via backend/.env
# locally, loaded further below by backend.config's load_dotenv(override=True)
# — is never clobbered.
os.environ.setdefault("SUPABASE_JWT_SECRET", "test-only-dummy-jwt-secret-not-a-real-secret")


# ── Refuse to run against a database that isn't disposable ───────────────────
#
# This suite writes. It creates and deletes auth users, inserts profiles, and
# truncates tables between tests. That is fine against a throwaway database and
# unacceptable against a real one.
#
# Nothing used to stop the second case. backend/.env carries two DATABASE_URL
# lines and the later one wins, so the value backend.config resolves locally is
# the production Supabase pooler — the same database the deployed app serves
# users from. `pytest backend/tests` therefore ran the full write-heavy suite
# against production, and the only reason no user data was lost is that the
# disposable-account fixture happens to clean up after itself. A fixture that
# raised before its `finally`, or one test with a DELETE whose WHERE clause was
# a little too broad, would have taken real rows with it.
#
# CI never hit this because it points DATABASE_URL at a localhost service
# container. Same command, different environment — which is exactly why the
# green CI run was not evidence that running the suite locally was safe.
#
# A database is considered disposable if it is on this machine or its name says
# it is a test database. Anything else has to be opted into explicitly, so the
# unsafe case requires a deliberate act rather than an unlucky default.

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "", None, "host.docker.internal"}
_ALLOW_REMOTE_ENV = "ALLOW_TESTS_ON_REMOTE_DB"


def _db_is_disposable(url_str: str) -> tuple[bool, str]:
    """Return (is_disposable, human_readable_reason)."""
    from sqlalchemy.engine.url import make_url
    try:
        url = make_url(url_str)
    except Exception as exc:                      # unparseable — refuse rather than guess
        return False, f"could not parse DATABASE_URL ({exc})"

    if url.drivername.startswith("sqlite"):
        return True, "sqlite"
    if url.host in _LOCAL_HOSTS:
        return True, f"local host ({url.host})"
    if "test" in (url.database or "").lower():
        return True, f"database name looks disposable ({url.database})"
    return False, f"remote host {url.host}, database {url.database!r}"


def pytest_configure(config):
    """
    Fail the run before collection rather than at the first write, so the
    message arrives before anything has touched the database.
    """
    if os.getenv(_ALLOW_REMOTE_ENV) == "1":
        return

    from backend.config import DATABASE_URL
    if not DATABASE_URL:
        return                                    # unset -> sqlite fallback, harmless

    ok, reason = _db_is_disposable(DATABASE_URL)
    if ok:
        return

    from sqlalchemy.engine.url import make_url
    safe = make_url(DATABASE_URL).render_as_string(hide_password=True)
    raise pytest.UsageError(
        "\n"
        "Refusing to run the test suite against a non-disposable database.\n"
        "\n"
        f"  resolved DATABASE_URL : {safe}\n"
        f"  why it was rejected   : {reason}\n"
        "\n"
        "These tests create and delete users, write profiles, and truncate\n"
        "tables. Against a real database that destroys real data.\n"
        "\n"
        "Two things make this easy to hit by accident:\n"
        "  * backend/.env may define DATABASE_URL more than once, and the\n"
        "    last definition wins;\n"
        "  * backend/config.py loads that file with override=True, so the\n"
        "    file beats your shell — `DATABASE_URL=... pytest` is silently\n"
        "    ignored locally.\n"
        "\n"
        "So to point this run somewhere safe, edit the effective DATABASE_URL\n"
        "in backend/.env. To run against this database on purpose, set\n"
        f"{_ALLOW_REMOTE_ENV}=1 — that one is read from the environment and\n"
        "does work as a prefix.\n"
    )

@pytest.fixture(autouse=True)
def mock_env_vars():
    """Mock environment variables for tests."""
    os.environ["ANTHROPIC_API_KEY"] = "test-key-for-ci"


# ── Shared linkedin.jobs Postgres fixtures ───────────────────────────────────
# Used by test_linkedin_job_pipeline.py and test_linkedin_jobs_route.py — this
# table lives on the dedicated Postgres engine in backend/core/postgres.py,
# not the app's primary SQLite ENGINE, so it needs its own reachability
# check/cleanup rather than reusing any SQLite-based test fixture.

@pytest.fixture()
def db_available():
    from backend.core.postgres import PG_ENGINE
    try:
        with PG_ENGINE.connect():
            pass
    except Exception as exc:
        pytest.skip(f"PostgreSQL not reachable for local tests: {exc}")


@pytest.fixture()
def llm_available():
    """
    Skip a test that makes a real Anthropic call when no usable key is set.

    The sibling of db_available, and added for the same reason: CI has no
    ANTHROPIC_API_KEY, so a live-LLM test fails there with a 401 that looks
    like a product bug rather than a missing secret. These tests exist to check
    behaviour against the real model — mocking them would only assert that the
    mock was called — so skipping is the honest option.

    Reads the key through backend.config rather than os.environ directly. The
    key lives in backend/.env and only reaches the process via config's
    load_dotenv, so an os.environ check passes locally at import time but is
    empty here — which would skip the tests everywhere, silently disabling them
    instead of just in CI. That is the worse failure of the two, since a green
    run would then mean nothing was checked.
    """
    from backend.config import ANTHROPIC_API_KEY

    if not ANTHROPIC_API_KEY or not ANTHROPIC_API_KEY.startswith("sk-ant-"):
        pytest.skip("ANTHROPIC_API_KEY not configured — skipping live-LLM test")


@pytest.fixture()
def clean_jobs_table(db_available):
    from backend.core.postgres import get_pg_session
    with get_pg_session() as session:
        session.execute(text("TRUNCATE linkedin.jobs"))
        session.commit()
    yield
    with get_pg_session() as session:
        session.execute(text("TRUNCATE linkedin.jobs"))
        session.commit()


@pytest.fixture()
def disposable_qa_account(db_available):
    """
    A brand-new, real Supabase auth.users row, created via the Admin Auth API
    and hard-deleted on teardown — true per-test isolation for anything that
    reads a user's *entire* history (e.g. feedback_service.
    apply_preference_learning(), which sums every rated job on the account).
    A shared, reused QA account can't give that: leftover rows from an
    earlier test or a previous interrupted run silently pollute the mean.

    Deleting the auth.users row cascades through the whole graph on its own
    (profiles.id -> auth.users.id ON DELETE CASCADE, and every tenant table
    FK's to profiles.id the same way — see 00eab53e0f00's docstring), so
    teardown here needs nothing beyond the one DELETE call.

    Skips — not fails — when SUPABASE_URL/SUPABASE_SECRET_KEY aren't
    configured (e.g. CI, which has no service-role secret), same pattern as
    llm_available: a green run should mean "checked and passed", not
    "silently skipped everywhere".
    """
    import uuid as _uuid

    from backend.config import SUPABASE_SECRET_KEY, SUPABASE_URL

    if not SUPABASE_URL or not SUPABASE_SECRET_KEY:
        pytest.skip("SUPABASE_URL/SUPABASE_SECRET_KEY not configured — skipping disposable-account test")

    import httpx

    base = SUPABASE_URL.rstrip("/")
    headers = {
        "apikey": SUPABASE_SECRET_KEY,
        "Authorization": f"Bearer {SUPABASE_SECRET_KEY}",
        "Content-Type": "application/json",
    }
    email = f"qa-disposable-{_uuid.uuid4().hex[:12]}@example.com"

    with httpx.Client(timeout=10.0) as client:
        resp = client.post(f"{base}/auth/v1/admin/users", headers=headers, json={
            "email": email,
            "password": _uuid.uuid4().hex,
            "email_confirm": True,
        })
    if resp.status_code >= 400:
        pytest.skip(f"Could not create disposable Supabase test account: {resp.status_code} {resp.text}")
    user_id = resp.json()["id"]

    # auth.users alone isn't enough — every tenant table's FK targets
    # profiles.id, not auth.users.id directly, so writing anything (a job
    # match, a feedback row) would fail with a ForeignKeyViolation until a
    # profiles row exists for this user too. The real app creates it on
    # first login via /api/profile/init; tests must do the same explicitly.
    from sqlalchemy.orm import Session

    from backend.core.database import ENGINE
    from backend.repositories import profile_repository as pr

    with Session(ENGINE) as s:
        pr.get_or_create(s, user_id, now="2026-01-01T00:00:00")
        s.commit()

    try:
        yield user_id
    finally:
        with httpx.Client(timeout=10.0) as client:
            del_resp = client.delete(f"{base}/auth/v1/admin/users/{user_id}", headers=headers)
        if del_resp.status_code >= 400:
            print(f"[disposable_qa_account] WARNING: failed to delete {user_id}: "
                  f"{del_resp.status_code} {del_resp.text}")
