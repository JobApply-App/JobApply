"""
A user must sign in again 2 hours after signing in (Ron, 2026-11-23).

The limit is counted from the token's `amr` claim (when the person last
authenticated), not `iat`: Supabase refreshes the access token every hour and
each refresh gets a new `iat`, so `iat` would let a session live forever.
The browser enforces the same limit (frontend/src/lib/sessionLimit.ts); these
tests cover the backend, which is the check that holds when the browser's
timer did not run.
"""
from __future__ import annotations

import time

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from jose import JWTError, jwt

from backend.api import deps
from backend.core.errors import AppError, install_error_handlers
from backend.services import auth_utils
from backend.services.auth_utils import (
    SESSION_MAX_AGE_SECONDS,
    authenticated_at,
    enforce_session_age,
    verify_hs256,
)

NOW = 1_800_000_000


def _token(signed_in_ago: float | None, *, iat_ago: float = 0, now: float | None = None) -> str:
    now = time.time() if now is None else now
    claims = {"sub": "user-1", "email": "a@b.c", "iat": int(now - iat_ago), "exp": int(now + 3600)}
    if signed_in_ago is not None:
        claims["amr"] = [{"method": "password", "timestamp": int(now - signed_in_ago)}]
    return jwt.encode(claims, auth_utils.JWT_SECRET, algorithm="HS256")


def test_the_limit_is_two_hours():
    assert SESSION_MAX_AGE_SECONDS == 7200


def test_sign_in_time_is_the_newest_amr_entry():
    payload = {"amr": [{"method": "password", "timestamp": NOW - 500}, {"method": "totp", "timestamp": NOW - 10}]}
    assert authenticated_at(payload) == NOW - 10


@pytest.mark.parametrize("payload", [{}, {"amr": []}, {"amr": [{"method": "password"}]},
                                     {"amr": [{"timestamp": True}]}, {"amr": "password"}])
def test_no_usable_sign_in_time(payload):
    assert authenticated_at(payload) is None


def test_inside_the_limit_passes():
    enforce_session_age({"amr": [{"timestamp": NOW - SESSION_MAX_AGE_SECONDS + 1}]}, now=NOW)


@pytest.mark.parametrize("age", [SESSION_MAX_AGE_SECONDS, SESSION_MAX_AGE_SECONDS + 1, 3 * 86400])
def test_at_or_past_the_limit_is_rejected(age):
    with pytest.raises(AppError) as exc:
        enforce_session_age({"amr": [{"timestamp": NOW - age}]}, now=NOW)
    assert exc.value.code == "session_time_limit"
    assert exc.value.status_code == 401


def test_a_token_without_a_sign_in_time_is_rejected():
    # Otherwise dropping the claim would switch the limit off.
    with pytest.raises(AppError) as exc:
        enforce_session_age({"sub": "user-1"}, now=NOW)
    assert exc.value.code == "session_time_limit"


def test_a_fresh_sign_in_verifies():
    identity = verify_hs256(_token(signed_in_ago=600), jwt, JWTError)
    assert identity.user_id == "user-1"


def test_a_refreshed_token_does_not_reset_the_clock():
    # Issued a minute ago by a refresh, but the person signed in 3 hours ago.
    token = _token(signed_in_ago=3 * 3600, iat_ago=60)
    with pytest.raises(AppError) as exc:
        verify_hs256(token, jwt, JWTError)
    assert exc.value.code == "session_time_limit"


@pytest.fixture
def client(monkeypatch):
    # HS256 path with the test secret; is_admin would otherwise query the DB.
    monkeypatch.setattr(deps, "_SUPABASE_URL", "")
    monkeypatch.setattr(deps, "_load_is_admin", lambda user_id: False)
    app = FastAPI()
    install_error_handlers(app)

    @app.get("/me")
    async def me(user: deps.CurrentUser = Depends(deps.get_current_user)):
        return {"user_id": user.user_id}

    return TestClient(app)


def test_api_accepts_a_recent_sign_in(client):
    r = client.get("/me", headers={"Authorization": f"Bearer {_token(signed_in_ago=60)}"})
    assert r.status_code == 200
    assert r.json() == {"user_id": "user-1"}


def test_api_answers_session_time_limit_after_two_hours(client):
    # The browser reads this code to sign the user out with a friendly message
    # (frontend/src/contexts/AuthContext.tsx), instead of retrying forever.
    r = client.get("/me", headers={"Authorization": f"Bearer {_token(signed_in_ago=2 * 3600 + 5)}"})
    assert r.status_code == 401
    assert r.json()["code"] == "session_time_limit"
    assert r.headers.get("www-authenticate") == "Bearer"
