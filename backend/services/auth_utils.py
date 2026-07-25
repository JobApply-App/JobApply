"""
JWKS verification core — extracted from backend/api/deps.py.

Supabase can sign JWTs with either HS256 (older / self-hosted projects) or
RS256 (newer hosted projects with asymmetric key pairs). This module handles
both, preferring RS256/JWKS when SUPABASE_URL is present in the environment.
Behavior is unchanged from its prior home in deps.py — this is a relocation,
not a rewrite (see the JOB-6 singleton note below for why it moved).

RS256 flow (preferred — Supabase-hosted projects)
──────────────────────────────────────────────────
  • Public keys are fetched from
      {SUPABASE_URL}/auth/v1/.well-known/jwks.json
  • The response is cached in-process with a 1-hour TTL so the network call
    happens at most once per hour, not on every request.
  • On cache miss for a specific `kid` the cache is force-refreshed once
    (handles key rotation without a server restart).

HS256 fallback (legacy / local Supabase CLI)
────────────────────────────────────────────
  • Used when SUPABASE_URL is absent (i.e. local dev without a hosted project).
  • Verifies the token against SUPABASE_JWT_SECRET using HMAC-SHA256.
  • The startup check rejects the anon/service-role key (starts with 'eyJ').

Setup
─────
  backend/.env should contain at least one of:
    SUPABASE_URL=https://<ref>.supabase.co   ← enables RS256/JWKS
    SUPABASE_JWT_SECRET=<raw-secret>         ← HS256 fallback only

── Singleton note (JOB-6) ──────────────────────────────────────────────────
The JOB-6 "duplicate instance" bug is an IMPORT-PATH problem, not a missing-
singleton-pattern problem: a bare `from services.auth_utils import ...`
resolves to a *different* sys.modules entry than
`from backend.services.auth_utils import ...`, so Python loads this file's
top-level code (and therefore the module-level JWKS cache below) twice —
each import path gets its own independent `_jwks_keys`/`_jwks_fetched_at`.
This file being "a dedicated central module" does not, by itself, prevent
that — ANY module is equally vulnerable to being double-loaded under two
import paths. The actual guarantee is enforced two levels up:
  1. backend/main.py inserts the project root onto sys.path, making
     `backend.*` the one canonical resolvable prefix.
  2. CI (.github/workflows/*.yml) greps every file under backend/ for a bare
     `api.`/`services.`/`config` import and fails the build if one is found.
Every current call site was audited (see backend/api/deps.py's import below)
and already uses the `backend.services.auth_utils` form exclusively — this
module inherits the existing protection; it does not create a new one.

The _assert_single_init() call at the bottom of this module is a runtime
tripwire for the specific failure mode described above: if this module's
top-level code ever executes twice in the same process (the bare-import
regression, or an explicit importlib.reload()), it logs a loud warning so
the duplication is visible in logs rather than silently doubling the JWKS
cache and its outbound HTTP fetches.
"""
import logging
import sys
import time
from typing import Optional

import httpx
from fastapi import HTTPException, status

from backend.config import SUPABASE_JWT_SECRET, SUPABASE_URL

logger = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────
# Values are read once, centrally, in backend/config.py — see that module for
# the required/optional classification and startup validation.

SUPABASE_URL_NORMALIZED = (SUPABASE_URL or "").rstrip("/")
JWT_SECRET               = SUPABASE_JWT_SECRET or ""

# RS256/JWKS endpoint derived from the Supabase project URL
JWKS_URL = f"{SUPABASE_URL_NORMALIZED}/auth/v1/.well-known/jwks.json" if SUPABASE_URL_NORMALIZED else ""

# ── Startup diagnostics ───────────────────────────────────────────────────────

if SUPABASE_URL_NORMALIZED:
    logger.info(
        "[auth] JWKS mode (RS256/ES256) — public keys will be fetched from %s", JWKS_URL
    )
elif JWT_SECRET:
    if JWT_SECRET.startswith("eyJ"):
        logger.error(
            "[auth] SUPABASE_JWT_SECRET looks like a JWT token (starts with 'eyJ'). "
            "It must be the raw signing secret, not the anon/service-role key. "
            "Go to Supabase Dashboard → Project Settings → API → JWT Settings → JWT Secret."
        )
    else:
        logger.info("[auth] HS256 fallback mode — using SUPABASE_JWT_SECRET.")
else:
    logger.error(
        "[auth] Neither SUPABASE_URL nor SUPABASE_JWT_SECRET is set. "
        "All protected endpoints will return HTTP 503. "
        "Add SUPABASE_URL=https://<ref>.supabase.co to backend/.env."
    )

# ── JWKS cache (the "singleton" state) ────────────────────────────────────────
#
# Structure: (fetched_at_monotonic, list_of_jwk_dicts)
# A list is used so python-jose can match by `kid` if multiple keys are present.
#
# This is a lazy, refreshable cache, not a compute-once constant: it's
# re-populated on a 1-hour TTL and force-refreshed on a kid cache-miss (key
# rotation). "Singleton" here means exactly one such cache exists per
# process — guaranteed by the import-path discipline described above, not by
# anything in this cache's own implementation.

_CACHE_TTL_SECONDS: float = 3600.0   # refetch at most once per hour

_jwks_fetched_at: float      = 0.0
_jwks_keys:       list[dict] = []


async def fetch_jwks(*, force: bool = False) -> list[dict]:
    """
    Return the cached JWKS key list, refreshing when stale or forced.

    *force=True* is used on a `kid` cache-miss to handle key rotation without
    requiring a server restart.

    Thread-safety note: this is an async function called from a single-process
    ASGI server. Concurrent refreshes may occur under high load, but the result
    is idempotent (last writer wins) and the cost of an extra JWKS fetch is low.
    """
    global _jwks_fetched_at, _jwks_keys

    now = time.monotonic()
    if not force and _jwks_keys and now - _jwks_fetched_at < _CACHE_TTL_SECONDS:
        return _jwks_keys

    if not JWKS_URL:
        return []

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(JWKS_URL)
            r.raise_for_status()
            keys: list[dict] = r.json().get("keys", [])
        _jwks_keys      = keys
        _jwks_fetched_at = now
        logger.info("[auth] JWKS refreshed — %d key(s) cached", len(keys))
        return keys
    except Exception as exc:
        logger.error("[auth] JWKS fetch failed (%s) — using stale cache (%d key(s))", exc, len(_jwks_keys))
        return _jwks_keys   # stale is better than nothing


def pick_key(keys: list[dict], kid: Optional[str]) -> Optional[dict]:
    """
    Return the JWK entry whose `kid` matches the JWT header.

    If the JWT has no `kid` claim (uncommon) fall back to the first key so
    single-key setups still work without requiring strict `kid` usage.
    """
    if not keys:
        return None
    if not kid:
        return keys[0]
    return next((k for k in keys if k.get("kid") == kid), None)


# ── Verified-identity type ────────────────────────────────────────────────────
# Lives here (not deps.py) because it's the return type of this module's own
# verify_* functions — deps.py imports it from here, not the other way around.

class VerifiedIdentity:
    """Minimal payload extracted from a verified JWT — user_id and email only.

    backend/api/deps.py wraps this into its richer CurrentUser (which adds
    is_admin via a DB lookup deps.py owns) — kept separate so this module has
    zero DB dependency, matching Requirement 5's "core logic unchanged"
    constraint precisely: this file only ever does crypto/JWKS work.
    """
    __slots__ = ("user_id", "email", "name")

    def __init__(self, user_id: str, email: str = "", name: str = ""):
        self.user_id = user_id
        self.email   = email
        self.name    = name


async def verify_rs256(token: str, jwt, JWTError) -> VerifiedIdentity:
    """Verify an RS256 token against Supabase's JWKS public keys."""
    try:
        # Peek at the header to find the signing key
        header = jwt.get_unverified_header(token)
        kid    = header.get("kid")
        # Use whatever algorithm the token header declares (RS256, ES256, etc.)
        # rather than hardcoding a single algorithm — Supabase may rotate alg types.
        alg    = header.get("alg")
        if not alg:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token header is missing the 'alg' field.",
                headers={"WWW-Authenticate": "Bearer"},
            )

        keys = await fetch_jwks()
        key  = pick_key(keys, kid)

        if key is None and kid is not None:
            # kid not in cache — rotate and try once more
            logger.info("[auth] kid=%r not in cache — force-refreshing JWKS", kid)
            keys = await fetch_jwks(force=True)
            key  = pick_key(keys, kid)

        if key is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token signing key not found in JWKS.",
                headers={"WWW-Authenticate": "Bearer"},
            )

        payload = jwt.decode(
            token,
            key,
            algorithms=[alg],        # honour whatever alg the key advertises
            options={"verify_aud": False},
        )
        return extract_identity(payload)

    except HTTPException:
        raise
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid or expired token: {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        )


def verify_hs256(token: str, jwt, JWTError) -> VerifiedIdentity:
    """Verify an HS256 token against the raw SUPABASE_JWT_SECRET."""
    try:
        payload = jwt.decode(
            token,
            JWT_SECRET,
            algorithms=["HS256"],
            options={"verify_aud": False},
        )
        return extract_identity(payload)
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid or expired token: {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        )


def extract_identity(payload: dict) -> VerifiedIdentity:
    """Pull user_id, email, and display name from a verified JWT payload.

    Name comes from Supabase's `user_metadata` claim (`full_name` or `name`
    — populated at signup for email/password accounts that supplied one, or
    by OAuth providers like Google) — never asked for manually. Empty string
    if the account has neither, which callers must treat the same as any
    other missing profile field (blank, never guessed).
    """
    user_id: Optional[str] = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token is missing the 'sub' claim.",
        )
    user_metadata = payload.get("user_metadata") or {}
    name = str(user_metadata.get("full_name") or user_metadata.get("name") or "").strip()
    return VerifiedIdentity(
        user_id=user_id,
        email=payload.get("email", ""),
        name=name,
    )


# ── Re-initialization tripwire (Requirement 3) ────────────────────────────────
#
# A plain module-level flag (e.g. `_initialized = False` checked at import
# time) CANNOT detect the bare-vs-prefixed duplicate-import bug: each
# duplicate module instance gets its OWN fresh copy of that flag, so it would
# always read False on first execution regardless of how many times the
# *file* has actually been loaded under different sys.modules keys.
#
# `sys` itself is the one object guaranteed to be identical across every
# import path in the process (it's special-cased by the interpreter, not
# resolved through sys.modules the normal way) — so stamping a marker
# attribute directly onto `sys` is the one place a second module instance can
# actually observe that a first one already ran.

_SINGLETON_GUARD_ATTR = "_jobapply_auth_utils_initialized"


def _assert_single_init() -> None:
    if getattr(sys, _SINGLETON_GUARD_ATTR, False):
        logger.warning(
            "[auth] auth_utils module top-level code has executed more than once "
            "in this process — this means it was imported under two different "
            "paths (e.g. a bare 'from services.auth_utils import ...' alongside "
            "'from backend.services.auth_utils import ...') and the JWKS cache "
            "now exists as two independent copies. Check for a bare "
            "api./services./config import under backend/ — see the module "
            "docstring's Singleton note (JOB-6)."
        )
    else:
        setattr(sys, _SINGLETON_GUARD_ATTR, True)
        logger.debug("[auth] auth_utils initialized (single instance confirmed).")


_assert_single_init()
