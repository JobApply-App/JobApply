"""
The RS256/ES256 JWKS path, which is how production verifies every request.

Written when python-jose (unmaintained, with an unpatched algorithm-confusion
advisory) was replaced by PyJWT on 2026-11-23. PyJWT takes a key object, not
the JWK dict the cache holds, so these tests sign real tokens with real keys
and run them through `verify_rs256` exactly as `deps.get_current_user` does.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from jwt import PyJWTError as JWTError
from jwt.algorithms import ECAlgorithm, RSAAlgorithm

from backend.core.errors import AppError
from backend.services import auth_utils

_RSA = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_EC = ec.generate_private_key(ec.SECP256R1())


def _jwk(public_key, alg: str, kid: str) -> dict:
    to_jwk = RSAAlgorithm.to_jwk if alg.startswith("RS") else ECAlgorithm.to_jwk
    jwk = json.loads(to_jwk(public_key))
    jwk.update({"kid": kid, "alg": alg, "use": "sig"})
    return jwk


@pytest.fixture(autouse=True)
def jwks(monkeypatch):
    keys = [_jwk(_RSA.public_key(), "RS256", "rsa-1"), _jwk(_EC.public_key(), "ES256", "ec-1")]

    async def fake_fetch(*, force: bool = False):
        return keys

    monkeypatch.setattr(auth_utils, "fetch_jwks", fake_fetch)
    return keys


def _claims(**over) -> dict:
    now = int(time.time())
    claims = {"sub": "user-1", "email": "a@b.c", "iat": now, "exp": now + 3600,
              "amr": [{"method": "password", "timestamp": now - 60}]}
    claims.update(over)
    return claims


def _verify(token: str):
    return asyncio.run(auth_utils.verify_rs256(token, jwt, JWTError))


@pytest.mark.parametrize("key,alg,kid", [(_RSA, "RS256", "rsa-1"), (_EC, "ES256", "ec-1")])
def test_a_valid_token_verifies(key, alg, kid):
    token = jwt.encode(_claims(), key, algorithm=alg, headers={"kid": kid})
    assert _verify(token).user_id == "user-1"


def test_a_token_signed_by_another_key_is_rejected():
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    token = jwt.encode(_claims(), other, algorithm="RS256", headers={"kid": "rsa-1"})
    with pytest.raises(AppError) as exc:
        _verify(token)
    assert exc.value.code == "session_expired"


def test_an_expired_token_is_rejected():
    now = int(time.time())
    token = jwt.encode(_claims(iat=now - 7000, exp=now - 3600), _RSA, algorithm="RS256",
                       headers={"kid": "rsa-1"})
    with pytest.raises(AppError) as exc:
        _verify(token)
    assert exc.value.code == "session_expired"


def test_hs256_signed_with_the_public_key_is_rejected(jwks):
    # The algorithm-confusion forgery: an HMAC token keyed with the public key.
    # Built by hand, because PyJWT itself refuses to HMAC with a public key.
    def b64(raw: bytes) -> bytes:
        return base64.urlsafe_b64encode(raw).rstrip(b"=")

    header = b64(json.dumps({"alg": "HS256", "typ": "JWT", "kid": "rsa-1"}).encode())
    body = b64(json.dumps(_claims()).encode())
    secret = json.dumps(jwks[0]).encode()
    sig = b64(hmac.new(secret, header + b"." + body, hashlib.sha256).digest())
    token = (header + b"." + body + b"." + sig).decode()
    with pytest.raises(AppError) as exc:
        _verify(token)
    assert exc.value.code == "session_expired"


def test_a_few_seconds_of_clock_skew_is_tolerated():
    # Supabase's clock a little ahead of ours must not sign anyone out.
    token = jwt.encode(_claims(iat=int(time.time()) + 5), _RSA, algorithm="RS256",
                       headers={"kid": "rsa-1"})
    assert _verify(token).user_id == "user-1"


def test_the_two_hour_limit_still_applies():
    now = int(time.time())
    token = jwt.encode(_claims(amr=[{"method": "password", "timestamp": now - 3 * 3600}]),
                       _RSA, algorithm="RS256", headers={"kid": "rsa-1"})
    with pytest.raises(AppError) as exc:
        _verify(token)
    assert exc.value.code == "session_time_limit"
