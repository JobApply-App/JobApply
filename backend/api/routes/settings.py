from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.api.deps import CurrentUser, get_current_user, require_admin
from backend.repositories import kv_repository, profile_repository

router = APIRouter()

# ── LinkedIn scraper status endpoint ─────────────────────────────────────────

_KV_SCRAPER_STATUS = "linkedin_scraper_status"
_KV_BLOCKED_AT     = "linkedin_scraper_blocked_at"
_KV_COOKIE_STATUS  = "linkedin_cookie_status"
_KV_SCRAPER_PAUSED = "linkedin_scraper_paused"


class ScraperStatusResponse(BaseModel):
    status:        str            # 'ok' | 'suspicious' | 'BLOCKED' | 'PAUSED'
    blocked_at:    Optional[str]  # ISO-8601 UTC, set when status='BLOCKED'
    cookie_status: Optional[str]  # 'ok' | 'suspicious'


SCRAPER_STATUS_KEYS = [_KV_SCRAPER_STATUS, _KV_BLOCKED_AT, _KV_COOKIE_STATUS, _KV_SCRAPER_PAUSED]


def build_scraper_status(entries: dict) -> ScraperStatusResponse:
    """
    Turn the 4 raw KV entries into a ScraperStatusResponse.

    Priority: BLOCKED > PAUSED > suspicious > ok. Returns status='ok' when no
    errors have been recorded. Pulled out of get_scraper_status() so
    dashboard.py's aggregated endpoint can reuse the same priority logic
    against KV entries it loaded itself (shared session), instead of calling
    this HTTP route internally.
    """
    status_row  = entries.get(_KV_SCRAPER_STATUS)
    blocked_row = entries.get(_KV_BLOCKED_AT)
    cookie_row  = entries.get(_KV_COOKIE_STATUS)
    paused_row  = entries.get(_KV_SCRAPER_PAUSED)

    blocked_at    = blocked_row.value if blocked_row else None
    cookie_status = cookie_row.value  if cookie_row  else "ok"

    if status_row and status_row.value == "BLOCKED":
        status = "BLOCKED"
    elif paused_row and paused_row.value == "1":
        # Manually paused via reset_linkedin_scraper.py --pause while a fresh
        # cookie is being configured.  Distinct from BLOCKED so the UI can show
        # a maintenance message instead of an error banner.
        status = "PAUSED"
    else:
        status = "ok"

    return ScraperStatusResponse(
        status=status,
        blocked_at=blocked_at,
        cookie_status=cookie_status,
    )


@router.get("/scraper-status", response_model=ScraperStatusResponse)
def get_scraper_status(user: CurrentUser = Depends(get_current_user)) -> ScraperStatusResponse:
    """
    Return the current LinkedIn scraper health status.

    Reads four KV keys:
      • linkedin_scraper_status  — 'BLOCKED' when redirect-loop threshold hit
      • linkedin_scraper_blocked_at — ISO timestamp when BLOCKED was set
      • linkedin_cookie_status   — 'suspicious' after first redirect error
      • linkedin_scraper_paused  — '1' when manually paused via reset script

    Priority: BLOCKED > PAUSED > suspicious > ok.
    Returns status='ok' when no errors have been recorded.
    """
    entries = kv_repository.get_many(SCRAPER_STATUS_KEYS)
    return build_scraper_status(entries)

# ── Gmail verification code endpoint ─────────────────────────────────────────

_KV_CODE_KEY = "gmail_verification_code"
_CODE_TTL_MINUTES = 30  # discard codes older than this


class GmailVerificationCodeResponse(BaseModel):
    code:       Optional[str]   # None when no code available or TTL expired
    captured_at: Optional[str]  # ISO-8601 UTC timestamp when it was stored


@router.get("/gmail-verification-code", response_model=GmailVerificationCodeResponse)
async def get_gmail_verification_code(user: CurrentUser = Depends(require_admin)) -> GmailVerificationCodeResponse:
    """
    Return the most recently captured Gmail forwarding verification code.

    The webhook (POST /api/webhooks/inbound-email) stores the code when it
    detects a forwarding-noreply@google.com email.  The frontend modal polls
    this endpoint so the code can be displayed automatically.

    Returns code=None when:
      • No code has been captured yet, OR
      • The stored code is older than 30 minutes (stale/already used).
    """
    entry = kv_repository.get(_KV_CODE_KEY)

    if entry is None:
        return GmailVerificationCodeResponse(code=None, captured_at=None)

    # TTL check — codes older than _CODE_TTL_MINUTES are silently expired
    try:
        stored_at = datetime.fromisoformat(entry.updated_at)
        age = datetime.now(timezone.utc) - stored_at.astimezone(timezone.utc)
        if age > timedelta(minutes=_CODE_TTL_MINUTES):
            return GmailVerificationCodeResponse(code=None, captured_at=None)
    except (ValueError, TypeError):
        # Malformed timestamp — treat as expired
        return GmailVerificationCodeResponse(code=None, captured_at=None)

    return GmailVerificationCodeResponse(code=entry.value, captured_at=entry.updated_at)


# ── Language preferences ─────────────────────────────────────────────────────
#
# ui_locale and cv_locale are independent on purpose: browsing the product in
# Hebrew while generating an English CV is a normal Israeli job-search
# pattern. See migration c5a91b3e7d02 for the full rationale, including why
# neither setting changes the language the profile is stored in.


class LocalePreferences(BaseModel):
    # Null means "this account has no stored preference yet" — distinct from
    # a stored "en". The client only adopts a non-null value, so it can leave
    # a visitor's own choice alone until they set one deliberately.
    ui_locale: Optional[str] = None
    cv_locale: Optional[str] = None


class LocalePreferencesUpdate(BaseModel):
    # Both optional so a caller can change one without restating the other —
    # switching CV language must never silently change interface language.
    ui_locale: Optional[str] = None
    cv_locale: Optional[str] = None


@router.get("/locales", response_model=LocalePreferences)
async def get_locale_preferences(user: CurrentUser = Depends(get_current_user)) -> LocalePreferences:
    """
    The caller's own interface and CV languages. Either field is null when
    this account has no stored preference yet, which the client reads as
    "keep whatever language you are already showing".

    A database that cannot be read is a 503, not a defaulted 200. Returning
    a plausible-looking "en" here made an infrastructure failure
    indistinguishable from a real preference, and the client persists what
    it receives — so a failed read silently overwrote a language the
    visitor had chosen. The client already keeps its current locale when
    this call fails, so the honest status code is also the one that
    produces the right behaviour.
    """
    try:
        return LocalePreferences(**profile_repository.get_locales(user.user_id))
    except profile_repository.LocalesUnavailable:
        raise HTTPException(
            status_code=503,
            detail="Language preferences are temporarily unavailable.",
        )


@router.patch("/locales", response_model=LocalePreferences)
async def update_locale_preferences(
    payload: LocalePreferencesUpdate,
    user: CurrentUser = Depends(get_current_user),
) -> LocalePreferences:
    """
    Update the caller's own language preferences.

    Scoped to user.user_id from the verified token — the body carries no
    user id, so this cannot be pointed at another account.
    """
    try:
        updated = profile_repository.set_locales(
            user.user_id,
            ui_locale=payload.ui_locale,
            cv_locale=payload.cv_locale,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except profile_repository.LocalesUnavailable:
        raise HTTPException(
            status_code=503,
            detail="Language preferences are temporarily unavailable.",
        )
    return LocalePreferences(**updated)
