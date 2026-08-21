"""
Inbound email webhook — receives parsed recruiter emails and updates the
application pipeline automatically.

POST /api/webhooks/inbound-email
  Body: { "sender": str, "subject": str, "body_text": str }

Security (Phase 5)
------------------
• Rate limited per caller IP via webhook_rate_limit (api/deps.py) — blunts
  email-bombing / replay floods.
• Strict Pydantic max_length caps on every field (body_text ≤ 20 000 chars)
  so a hostile payload can't exhaust memory or the LLM context window.
• Shared-secret verification: when EMAIL_WEBHOOK_SECRET is set in the
  environment, the X-Webhook-Secret header must match (constant-time
  comparison) or the request is rejected with 401. When unset, a loud
  warning is logged so local dev keeps working — set the secret in production.
• sanitize_text() is applied to sender/subject/body BEFORE any regex or LLM
  processing, neutralizing control-character / invisible-text prompt
  injection hidden in the email body.

Flow
----
0. Check for Gmail forwarding verification email FIRST.
   If sender is forwarding-noreply@google.com or subject contains
   "Gmail Forwarding Confirmation", extract the 9-digit confirmation
   code and persist it in the kv_store table, then return early.
1. Validate the payload.
2. Call email_parser.parse_recruiter_email() to extract company + status.
3. If mapped_status == "Unknown", return early (no DB mutation).
4. Search THAT USER's ApplicationRows for a matching company that is
   still in a non-terminal stage. Match is case-insensitive and
   substring-based so "Wix Engineering" matches a stored company of "Wix".
5. If a match is found, update its status and last_update timestamp.
6. Return a structured response describing what happened.

Per-user scoping (2026-08-20)
------------------------------
Step 4 requires payload.user_id and always scopes the search to that one
user — find_updatable_by_company() takes user_id as a required parameter
and filters on it. Before this, the search ran across EVERY user's
applications with no tenant filter at all: any inbound email whose company
name substring-matched ANY user's most-recently-submitted application
would silently mutate that unrelated user's row.

This payload has no real per-user routing today. INBOUND_EMAIL in
frontend/src/components/EmailSetupModal.tsx is a single hardcoded ngrok
dev-tunnel address shown identically to every user ("This is your unique
forwarding address" is not true yet), and InboundEmailPayload carries no
recipient/alias field an inbound-mail provider could use to identify whose
mailbox a message arrived at. So when user_id is absent — which is every
request today, since nothing upstream can supply one yet — this handler
now returns action="no_user_context" and never touches the DB, rather than
guessing. Shipping a real per-user forwarding address (and an inbound-mail
provider that passes it through as the recipient) is a separate feature
build, tracked outside this fix.
"""
from __future__ import annotations

import hmac
import logging
import re
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.api.deps import webhook_rate_limit
from backend.config import EMAIL_WEBHOOK_SECRET, STRICT_CONFIG, MissingRequiredConfigError
from backend.core.database import ENGINE
from backend.repositories import application_repository
from backend.repositories import kv_repository
from backend.services.email_parser import parse_recruiter_email
from backend.services.llm_validation import sanitize_text

router = APIRouter(dependencies=[Depends(webhook_rate_limit)])
logger = logging.getLogger(__name__)

# ── Shared-secret verification ────────────────────────────────────────────────
# The email provider (forwarding worker / inbound-parse service) is configured
# to send this token in the X-Webhook-Secret header on every delivery.
# Value is read once, centrally, in backend/config.py.

_WEBHOOK_SECRET = EMAIL_WEBHOOK_SECRET

if not _WEBHOOK_SECRET:
    if STRICT_CONFIG:
        # Production posture: an unauthenticated inbound webhook is not an
        # acceptable degraded state — fail fast at import time instead of
        # silently accepting unauthenticated requests (mirrors backend/config.py's
        # own STRICT_CONFIG required-env pattern, scoped to this one feature
        # rather than the app-wide required list since EMAIL_WEBHOOK_SECRET is
        # optional/feature-specific everywhere else).
        raise MissingRequiredConfigError(
            "STRICT_CONFIG=true and EMAIL_WEBHOOK_SECRET is not set. The inbound "
            "email webhook would accept unauthenticated requests, which is not "
            "permitted in this mode. Set EMAIL_WEBHOOK_SECRET in backend/.env, "
            "or unset STRICT_CONFIG for local development."
        )
    logger.warning(
        "[email-webhook] EMAIL_WEBHOOK_SECRET is not set — the inbound email "
        "webhook will accept UNAUTHENTICATED requests. Set it in backend/.env "
        "and configure the email provider to send the X-Webhook-Secret header."
    )


def _verify_webhook_secret(x_webhook_secret: str = Header(default="")) -> None:
    """
    FastAPI dependency: constant-time check of the shared webhook secret.

    Enforced whenever EMAIL_WEBHOOK_SECRET is configured; otherwise the
    request is allowed through with a warning so local dev keeps working.
    """
    if not _WEBHOOK_SECRET:
        logger.warning(
            "[email-webhook] accepting request WITHOUT secret verification "
            "(EMAIL_WEBHOOK_SECRET not configured)"
        )
        return
    if not hmac.compare_digest(x_webhook_secret or "", _WEBHOOK_SECRET):
        logger.warning("[email-webhook] rejected request — bad or missing X-Webhook-Secret")
        raise HTTPException(status_code=401, detail="Invalid webhook secret.")

# ── Gmail verification intercept ──────────────────────────────────────────────
# Google sends a forwarding confirmation email whose subject is always
# "Gmail Forwarding Confirmation - Receive Mail from <address>"
# and whose sender is forwarding-noreply@google.com.
# The body contains a 9-digit confirmation code on its own line, e.g.:
#   "Confirmation code: 123456789"  or  just  "123456789" on an isolated line.

_GMAIL_SENDERS   = frozenset({"forwarding-noreply@google.com"})
_GMAIL_SUBJ_FRAG = "gmail forwarding confirmation"
_KV_CODE_KEY     = "gmail_verification_code"

# Two patterns — prefer the labelled one, fall back to any isolated 9-digit run.
_CODE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r'(?i)confirmation\s+code[:\s]+(\d{9})\b'),
    re.compile(r'\b(\d{9})\b'),
]


def _extract_gmail_code(body: str) -> Optional[str]:
    """Return the first 9-digit confirmation code found in the email body."""
    for pattern in _CODE_PATTERNS:
        m = pattern.search(body)
        if m:
            return m.group(1)
    return None


def _is_gmail_verification(sender: str, subject: str) -> bool:
    """True when the email is a Gmail forwarding confirmation."""
    return (
        sender.strip().lower() in _GMAIL_SENDERS
        or _GMAIL_SUBJ_FRAG in subject.strip().lower()
    )


def _store_gmail_code(code: str) -> None:
    """Upsert the verification code into the kv_store table."""
    kv_repository.upsert(_KV_CODE_KEY, code)
    logger.info("[email-webhook] Stored Gmail verification code=%r", code)


# ── Stages that a company can be moved OUT of via an inbound email ────────────
# We don't overwrite an already-final status (offer / rejected) with a new
# classification — that would be destructive and probably an error.
_UPDATABLE_STATUSES: frozenset[str] = frozenset({
    "submitted",
    "phone screen",
    "technical",
    "interview",
})


# ── Pydantic models ────────────────────────────────────────────────────────────

class InboundEmailPayload(BaseModel):
    # Strict caps (Phase 4 invariant): an email address tops out at 320 chars
    # per RFC 5321; subject and body ceilings prevent email-bombing payloads
    # from exhausting memory or the LLM context window.
    sender:    str = Field(..., max_length=320)
    subject:   str = Field(..., max_length=1_000)
    # Which user this email belongs to. No real inbound-mail provider is
    # wired up to supply this yet (see the module docstring's "Per-user
    # scoping" note) — it exists so the handler has somewhere to receive one
    # once real per-user forwarding addresses exist, and so its absence is
    # an explicit, typed condition rather than an assumption. Absent ==
    # every request today == the DB-mutation step is skipped entirely.
    user_id:   Optional[str] = Field(default=None, max_length=64)
    body_text: str = Field(..., max_length=20_000)


class EmailWebhookResponse(BaseModel):
    received:      bool
    company_name:    Optional[str]
    mapped_status:   str
    db_status:       Optional[str]
    match_found:     bool
    application_id:  Optional[str]
    previous_status: Optional[str]
    action:          str           # "updated" | "skipped" | "no_match" | "gmail_verification"
    verification_code: Optional[str] = None  # populated when action == "gmail_verification"


# ── Helpers ────────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


async def _draft_reply_task(user_id: str, job_id: str, email_text: str) -> None:
    """
    Background task (Phase 6): have the agent draft a follow-up reply to the
    recruiter email that just advanced this application.

    Lazy import — orchestrator pulls heavy deps (playwright, langgraph) that
    must not load at webhook module import time. Errors are logged, never
    raised: reply drafting is best-effort and must not affect webhook delivery.
    """
    try:
        from backend.services.orchestrator import draft_recruiter_reply
        await draft_recruiter_reply(user_id, job_id, email_text)
    except Exception:
        logger.exception(
            "[email-webhook] reply drafting failed user=%s job=%s", user_id, job_id
        )


# ── Webhook endpoint ───────────────────────────────────────────────────────────

@router.post(
    "/inbound-email",
    response_model=EmailWebhookResponse,
    dependencies=[Depends(_verify_webhook_secret)],
)
async def inbound_email_webhook(
    payload:    InboundEmailPayload,
    background: BackgroundTasks,
) -> EmailWebhookResponse:
    """
    Receive a recruiter email, classify it with AI, and update the
    application pipeline if a matching application is found.

    Protected by webhook_rate_limit (router-level) and the X-Webhook-Secret
    shared-secret check (route-level). All fields are sanitized before any
    regex or LLM processing.
    """
    # Neutralize control-character / invisible-text injection in every field
    # BEFORE anything (regex intercept or LLM parser) reads them.
    sender    = sanitize_text(payload.sender)
    subject   = sanitize_text(payload.subject)
    body_text = sanitize_text(payload.body_text)

    logger.info(
        "[email-webhook] received  sender=%r  subject=%r",
        sender, subject[:80],
    )

    # ── Step 0: Gmail forwarding verification intercept ───────────────────────
    # Must run BEFORE the AI parser — verification emails contain no job data.
    if _is_gmail_verification(sender, subject):
        code = _extract_gmail_code(body_text)
        if code:
            _store_gmail_code(code)
            return EmailWebhookResponse(
                received          = True,
                company_name      = None,
                mapped_status     = "gmail_verification",
                db_status         = None,
                match_found       = False,
                application_id    = None,
                previous_status   = None,
                action            = "gmail_verification",
                verification_code = code,
            )
        else:
            logger.warning(
                "[email-webhook] Gmail verification email received but no 9-digit code found"
            )
            return EmailWebhookResponse(
                received       = True,
                company_name   = None,
                mapped_status  = "gmail_verification",
                db_status      = None,
                match_found    = False,
                application_id = None,
                previous_status= None,
                action         = "skipped",
            )

    # ── Step 1: AI classification (sanitized inputs only) ────────────────────
    parsed = await parse_recruiter_email(
        subject=subject,
        body=body_text,
    )

    company_name  = parsed["company_name"]
    mapped_status = parsed["mapped_status"]
    db_status     = parsed["db_status"]

    # ── Step 2: Early-exit for Unknown or missing company ────────────────────
    if mapped_status == "Unknown" or not company_name or not db_status:
        logger.info(
            "[email-webhook] status=Unknown or unidentifiable company — no DB mutation",
        )
        return EmailWebhookResponse(
            received       = True,
            company_name   = company_name,
            mapped_status  = mapped_status,
            db_status      = db_status,
            match_found    = False,
            application_id = None,
            previous_status= None,
            action         = "skipped",
        )

    # ── Step 3: Find matching application and update ─────────────────────────
    # No caller supplies user_id yet (see module docstring) — refuse to guess
    # across tenants rather than matching whichever user's application the
    # company name happens to hit. See "Per-user scoping" above.
    if not payload.user_id:
        logger.info(
            "[email-webhook] no user_id in payload — skipping DB match for "
            "company=%r (no per-user routing wired up yet)", company_name,
        )
        return EmailWebhookResponse(
            received       = True,
            company_name   = company_name,
            mapped_status  = mapped_status,
            db_status      = db_status,
            match_found    = False,
            application_id = None,
            previous_status= None,
            action         = "no_user_context",
        )

    with Session(ENGINE) as session:
        row = application_repository.find_updatable_by_company(
            session, payload.user_id, company_name, _UPDATABLE_STATUSES,
        )

        if row is None:
            logger.info(
                "[email-webhook] no updatable application found for company=%r", company_name,
            )
            return EmailWebhookResponse(
                received       = True,
                company_name   = company_name,
                mapped_status  = mapped_status,
                db_status      = db_status,
                match_found    = False,
                application_id = None,
                previous_status= None,
                action         = "no_match",
            )

        previous_status  = row.status
        row.status       = db_status
        row.last_update  = _now_iso()
        application_id   = row.application_id
        owner_user_id    = row.user_id
        job_id           = row.job_id
        session.commit()

    logger.info(
        "[email-webhook] updated application_id=%r  company=%r  %r → %r",
        application_id, company_name, previous_status, db_status,
    )

    # ── Step 4 (Phase 6): agent drafts a follow-up reply in the background ────
    # Uses the SANITIZED body and the application's own user_id/job_id, so the
    # draft is tenant-isolated to the application owner.
    background.add_task(_draft_reply_task, owner_user_id, job_id, body_text)

    return EmailWebhookResponse(
        received        = True,
        company_name    = company_name,
        mapped_status   = mapped_status,
        db_status       = db_status,
        match_found     = True,
        application_id  = application_id,
        previous_status = previous_status,
        action          = "updated",
    )
