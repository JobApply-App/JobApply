"""
FastAPI authentication dependencies.

JWKS/HS256 verification logic (the JWT crypto core) lives in
backend/services/auth_utils.py — see that module's docstring for the JOB-6
singleton note. This file only wires that verification into FastAPI:
extracting the Bearer header, calling into auth_utils, resolving is_admin via
a DB lookup, and rate limiting. No JWT verification logic is duplicated here.

Setup
─────
  backend/.env should contain at least one of:
    SUPABASE_URL=https://<ref>.supabase.co   ← enables RS256/JWKS
    SUPABASE_JWT_SECRET=<raw-secret>         ← HS256 fallback only

NOTE — no `from __future__ import annotations` in this module, on purpose.
With postponed annotations, FastAPI (on Python 3.9) cannot resolve the
`request: Request` annotation on RateLimiter.__call__ (a callable-instance
dependency) and silently degrades it to a REQUIRED QUERY PARAMETER named
`request`, making every rate-limited endpoint return 422 for all callers.
All annotations below are runtime-valid on 3.9 without the future import.
"""
import logging
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from backend.services.auth_utils import (
    SUPABASE_URL_NORMALIZED as _SUPABASE_URL,
    JWT_SECRET as _JWT_SECRET,
    verify_rs256 as _verify_rs256_identity,
    verify_hs256 as _verify_hs256_identity,
)

logger = logging.getLogger(__name__)

# ── FastAPI plumbing ──────────────────────────────────────────────────────────

# auto_error=False lets us return a descriptive 401 body ourselves
_bearer = HTTPBearer(auto_error=False)


@dataclass
class CurrentUser:
    user_id:  str
    email:    str  = field(default="")
    name:     str  = field(default="")
    is_admin: bool = field(default=False)


def _load_is_admin(user_id: str) -> bool:
    """Cheap profiles.is_admin lookup; absent row (or any DB error) → False."""
    from backend.repositories.profile_repository import is_admin_lookup
    return is_admin_lookup(user_id)


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> CurrentUser:
    """
    FastAPI dependency: verifies a Supabase Bearer JWT and returns the caller's
    identity.

    Raises HTTP 503 when neither SUPABASE_URL nor SUPABASE_JWT_SECRET is set.
    Raises HTTP 401 for a missing/expired/invalid token or absent `sub` claim.

    Inject with:
        user: CurrentUser = Depends(get_current_user)
    """
    # ── Server misconfiguration check ─────────────────────────────────────────
    if not _SUPABASE_URL and not _JWT_SECRET:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Authentication is not configured on this server. "
                "Add SUPABASE_URL=https://<ref>.supabase.co to backend/.env."
            ),
        )

    # ── Token presence check ──────────────────────────────────────────────────
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    from jose import JWTError, jwt

    token = credentials.credentials

    # ── RS256/JWKS path ───────────────────────────────────────────────────────
    # Verification itself runs entirely in auth_utils (the JWKS singleton) —
    # this file never touches the JWKS cache or decodes a token directly.
    if _SUPABASE_URL:
        identity = await _verify_rs256_identity(token, jwt, JWTError)
    else:
        # ── HS256 fallback ────────────────────────────────────────────────────
        identity = _verify_hs256_identity(token, jwt, JWTError)

    user = CurrentUser(user_id=identity.user_id, email=identity.email, name=identity.name)
    user.is_admin = _load_is_admin(user.user_id)
    return user


async def require_admin(
    user: CurrentUser = Depends(get_current_user),
) -> CurrentUser:
    """
    FastAPI dependency for admin-only routes (Phase 2 foundation — defined
    and exported, not yet mounted on any route).

        user: CurrentUser = Depends(require_admin)
    """
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required.",
        )
    return user


# ══════════════════════════════════════════════════════════════════════════════
# Rate limiting — lightweight, memory-backed, dependency-injectable
# ══════════════════════════════════════════════════════════════════════════════
#
# A sliding-window counter keyed per identity (authenticated user_id when a
# Bearer token is present, else the client IP). No external store (Redis, etc.)
# — a process-local dict of timestamp deques, guarded by a lock so it is safe
# under the threadpool that runs sync path operations.
#
# Buckets are namespaced by `scope` so an endpoint's strict LLM budget and the
# standard budget are counted independently for the same identity.
#
# NOTE: state is per-process. Behind multiple workers each has its own window,
# so effective limits scale with worker count — acceptable for abuse/overload
# protection at this stage; swap the backing store for Redis if global limits
# are later required.

_RATE_BUCKETS: dict[str, deque] = defaultdict(deque)
_RATE_LOCK = threading.Lock()
_RATE_MAX_KEYS = 50_000   # opportunistic-cleanup threshold to bound memory


def _rate_identity(request: Request) -> str:
    """
    Best-effort caller identity for rate keying.

    Prefers the JWT `sub` (unverified decode — keying only, never trusted for
    authz), falls back to a token prefix, then to the client IP. Unverified
    decode is safe here: a forged `sub` only changes which bucket the caller's
    own requests land in, so a caller can throttle only themselves — they can
    never lift another identity's limit.
    """
    auth = request.headers.get("authorization", "")
    if auth[:7].lower() == "bearer ":
        token = auth[7:].strip()
        if token:
            try:
                from jose import jwt as _jwt
                sub = _jwt.get_unverified_claims(token).get("sub")
                if sub:
                    return f"user:{sub}"
            except Exception:
                pass
            return f"token:{token[:24]}"
    client = request.client
    host   = client.host if client else "unknown"
    # Trusted-proxy hop: the Next.js server proxies public traffic from
    # 127.0.0.1, which would collapse every anonymous visitor into one bucket.
    # Honour X-Forwarded-For ONLY when the direct peer is loopback — a remote
    # caller can't spoof its way into a fresh bucket because their XFF header
    # is ignored unless they already own the local proxy.
    if host in ("127.0.0.1", "::1", "localhost"):
        forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        if forwarded:
            return f"ip:{forwarded}"
    return f"ip:{host}"


class RateLimiter:
    """
    FastAPI dependency enforcing `max_requests` per `window_seconds` per caller.

    Usage — router-level:   APIRouter(dependencies=[Depends(llm_rate_limit)])
            per-route:       @router.post(..., dependencies=[Depends(llm_rate_limit)])

    Raises 429 (with a Retry-After header) when the window is saturated.
    """

    def __init__(self, max_requests: int, window_seconds: int = 60, scope: str = "default"):
        self.max_requests   = max_requests
        self.window_seconds = window_seconds
        self.scope          = scope

    async def __call__(self, request: Request) -> None:
        key = f"{self.scope}:{_rate_identity(request)}"
        now = time.monotonic()
        cutoff = now - self.window_seconds
        with _RATE_LOCK:
            # Opportunistic memory bound: drain fully-expired buckets when the
            # key space grows large (cheap amortised cleanup, no timers).
            if len(_RATE_BUCKETS) > _RATE_MAX_KEYS:
                for k in [k for k, dq in _RATE_BUCKETS.items() if not dq or dq[-1] < cutoff]:
                    del _RATE_BUCKETS[k]

            bucket = _RATE_BUCKETS[key]
            while bucket and bucket[0] < cutoff:
                bucket.popleft()

            if len(bucket) >= self.max_requests:
                retry_after = max(1, int(self.window_seconds - (now - bucket[0])) + 1)
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Rate limit exceeded. Please slow down and try again shortly.",
                    headers={"Retry-After": str(retry_after)},
                )
            bucket.append(now)


# Shared limiter instances — import and attach as route/router dependencies.
#   llm_rate_limit      → strict budget for expensive LLM-generation endpoints
#   standard_rate_limit → generous budget for ordinary reads/writes
#   webhook_rate_limit  → strict budget for unauthenticated inbound webhooks
llm_rate_limit      = RateLimiter(max_requests=10, window_seconds=60, scope="llm")
standard_rate_limit = RateLimiter(max_requests=60, window_seconds=60, scope="std")
webhook_rate_limit  = RateLimiter(max_requests=30, window_seconds=60, scope="webhook")
