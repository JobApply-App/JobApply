import asyncio
from typing import Optional
import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv

# Load backend/.env before any module that reads env vars is imported.
# Using an absolute path guarantees the correct file regardless of CWD.
# backend/config.py performs this same load (so it's self-sufficient for any
# other entrypoint that imports it directly); this call is kept as the
# earliest possible guard for this specific process. Both calls are
# idempotent — see backend/config.py for the full env-var inventory.
load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env", override=True)

# When uvicorn is launched from the backend/ directory, the project root
# (one level up) is not automatically on sys.path.  Add it so the canonical
# `backend.*` package path (e.g. backend.schemas.agent) is importable.
# ALL intra-backend imports use the `backend.` prefix — the bare
# `api.*` / `services.*` / `config` forms are forbidden because they load
# the same file as a second, independent module object (duplicated
# rate-limit buckets, JWKS caches, DB engines).
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from backend.api.routes import agents, analytics, applications, ariel, auth, chat, crm, history, jobs, outreach, profile, resumes, scraper, settings, webhooks
from backend.config import (
    AUTO_DISCOVERY,
    CORS_ORIGINS,
    CREDIT_CONSERVATION_MODE,
    DEV_MAX_JOBS_PER_BOARD,
    DEV_MODE,
    DISCOVERY_INTERVAL_SECONDS,
    TARGET_SEARCH_QUERIES,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    force=True,
)

logger = logging.getLogger(__name__)


async def _enrichment_loop() -> None:
    """
    Automatic enrichment worker — runs every 30 seconds.

    On transient failures the loop sleeps its normal interval and retries.
    After _CONSEC_FAIL_THRESHOLD consecutive failures the loop enters a
    long-backoff pause (_LONG_BACKOFF) and resets the counter, preventing
    log spam when the Anthropic API is rate-limiting or unreachable.
    """
    from backend.services.feed_service import refresh_user_scores
    from backend.services.tenant_registry import list_pipeline_user_ids

    _INTERVAL              = 30      # seconds between enrichment sweeps
    _LONG_BACKOFF          = 1800    # 30-min pause after repeated failures
    _CONSEC_FAIL_THRESHOLD = 5       # failures before entering long-backoff

    logger.info("[enrichment-loop] Automatic enrichment worker started — interval=%ds", _INTERVAL)

    consecutive_failures = 0

    while True:
        await asyncio.sleep(_INTERVAL)
        try:
            # Multi-tenant fan-out: one strictly-isolated sweep per user,
            # sequential by design (Phase 2 — no cross-tenant concurrency).
            for user_id in list_pipeline_user_ids():
                count = await refresh_user_scores(user_id)
                if count:
                    logger.info(
                        "[enrichment-loop] Enriched %d job(s) for user=%s", count, user_id,
                    )
            consecutive_failures = 0   # reset on success
        except Exception:
            consecutive_failures += 1
            if consecutive_failures >= _CONSEC_FAIL_THRESHOLD:
                logger.warning(
                    "[enrichment-loop] %d consecutive failures — entering long-backoff "
                    "(%ds) to avoid log spam. Will retry after pause.",
                    consecutive_failures, _LONG_BACKOFF,
                )
                await asyncio.sleep(_LONG_BACKOFF)
                consecutive_failures = 0
            else:
                logger.exception("[enrichment-loop] Unhandled error in enrichment sweep")


async def _discovery_loop() -> None:
    """
    Background job-discovery worker.

    Failure resilience
    ------------------
    Transient errors (network blips, a single 429 from the Anthropic enrichment
    step) are logged once and the loop sleeps its normal interval before retrying.

    After _CONSEC_FAIL_THRESHOLD consecutive failures the loop enters a long-
    backoff pause (_LONG_BACKOFF_SECONDS) and resets the counter, preventing
    log spam during an extended outage (e.g. Google rate-limiting all queries
    for a cycle, or the Anthropic API being temporarily unreachable).

    429-specific backoff at the Google-query level is handled inside
    GoogleDorkScraper._run_queries — this loop-level backoff is a second
    safety net for any other persistent failure mode that reaches here.
    """
    from backend.services.discovery import run_discovery_cycle
    from backend.services.tenant_registry import list_pipeline_user_ids

    _LONG_BACKOFF_SECONDS  = 1800    # 30-min pause after repeated failures
    _CONSEC_FAIL_THRESHOLD = 3       # failures before entering long-backoff

    if not AUTO_DISCOVERY:
        logger.warning(
            "[discovery-loop] AUTO_DISCOVERY=False — background discovery is DISABLED. "
            "Set AUTO_DISCOVERY=True in backend/config.py to re-enable. "
            "Manual single-job analysis via POST /api/jobs/analyze remains fully operational."
        )
        while True:
            await asyncio.sleep(3600)

    logger.info(
        "[discovery-loop] Background task started — interval=%ds  credit_conservation=%s",
        DISCOVERY_INTERVAL_SECONDS, CREDIT_CONSERVATION_MODE,
    )

    consecutive_failures = 0

    while True:
        try:
            # Multi-tenant fan-out: one discovery cycle per user, each cycle
            # scoped to that user's feed, profile, and dedup space.
            for uid in list_pipeline_user_ids():
                await run_discovery_cycle(user_id=uid)
            consecutive_failures = 0   # reset on success
        except Exception as exc:
            consecutive_failures += 1
            is_rate_limit = "429" in str(exc) or "too many requests" in str(exc).lower()
            if consecutive_failures >= _CONSEC_FAIL_THRESHOLD or is_rate_limit:
                backoff = _LONG_BACKOFF_SECONDS
                logger.warning(
                    "[discovery-loop] %d consecutive failure(s)%s — entering long-backoff "
                    "(%ds). Will retry after pause. Last error: %s",
                    consecutive_failures,
                    " (rate-limit)" if is_rate_limit else "",
                    backoff, exc,
                )
                await asyncio.sleep(backoff)
                consecutive_failures = 0
            else:
                logger.error("[discovery-loop] Error (attempt %d/%d): %s",
                             consecutive_failures, _CONSEC_FAIL_THRESHOLD, exc)
        await asyncio.sleep(DISCOVERY_INTERVAL_SECONDS)


def _seed_scraper_registry() -> None:
    """
    Register default company scrapers into the global SCRAPER_MANAGER.

    The user_id baked into each scraper at construction time is used as a
    fallback only.  The discovery loop and run_all() pass the active user_id
    at call time (read from data/active_user.json), which overrides this value
    so new jobs land in the correct user's feed.  We keep user_id="default"
    here so scrapers remain functional before any user logs in.
    """
    from backend.scrapers.scraper_manager import SCRAPER_MANAGER, scraper_from_config
    from backend.scrapers.drushim_scraper      import DrushimScraper
    from backend.scrapers.alljobs_scraper      import AllJobsScraper
    from backend.scrapers.gotfriends_scraper   import GotfriendsScraper
    from backend.scrapers.dialog_scraper       import DialogScraper
    from backend.scrapers.nisha_scraper        import NishaScraper
    from backend.scrapers.google_dork_scraper  import GoogleDorkScraper

    # ── Company-site adapters (Comeet) ────────────────────────────────────────
    # These scrape specific employer career pages — relevancy gate is applied
    # inside ScraperManager._save_new() since Comeet doesn't do keyword search.
    default_companies = [
        {
            "company_name": "Spark Hire",
            "company_url":  "https://www.comeet.co/jobs/spark-hire/30.005/all",
            "adapter":      "comeet",
            "user_id":      "default",
        },
        {
            "company_name": "Wix",
            "company_url":  "https://www.comeet.co/jobs/wix/ED.30A/all",
            "adapter":      "comeet",
            "user_id":      "default",
        },
    ]

    for cfg in default_companies:
        scraper = scraper_from_config(cfg)
        if scraper:
            SCRAPER_MANAGER.register(scraper)

    # ── Israeli board scrapers — targeted multi-keyword search ────────────────
    # Each board scraper runs one search request per entry in TARGET_SEARCH_QUERIES
    # and discards non-matching titles before any detail-page fetch.
    #
    # Dev-mode cap: when DEV_MODE=True (config.py), each scraper is limited to
    # DEV_MAX_JOBS_PER_BOARD detail-page fetches so the full s1→s4 pipeline
    # completes in seconds rather than minutes during local development.
    # Set DEV_MODE=False in config.py before deploying to production.
    _board_kw: dict = {"max_jobs": DEV_MAX_JOBS_PER_BOARD} if DEV_MODE else {}
    if DEV_MODE:
        logger.info(
            "[startup] DEV_MODE active — board scrapers capped at %d jobs each.",
            DEV_MAX_JOBS_PER_BOARD,
        )

    board_scrapers = [
        DrushimScraper(keywords=TARGET_SEARCH_QUERIES, user_id="default", **_board_kw),
        AllJobsScraper(keywords=TARGET_SEARCH_QUERIES, user_id="default", **_board_kw),
        GotfriendsScraper(keywords=TARGET_SEARCH_QUERIES, user_id="default", **_board_kw),
        DialogScraper(keywords=TARGET_SEARCH_QUERIES, user_id="default", **_board_kw),
        NishaScraper(keywords=TARGET_SEARCH_QUERIES, user_id="default", **_board_kw),
        # "Under the radar" — surfaces roles directly from ATS platforms via Google Dorks
        # before aggregators re-index them (lower competition, earlier pipeline entry).
        # GoogleDorkScraper has no max_jobs param — it is not a paginated board scraper.
        GoogleDorkScraper(keywords=TARGET_SEARCH_QUERIES, user_id="default"),
    ]

    for scraper in board_scrapers:
        SCRAPER_MANAGER.register(scraper)

    logger.info(
        "[startup] ScraperManager seeded with %d scraper(s) (%d board scrapers with %d keywords each).",
        SCRAPER_MANAGER.scraper_count,
        len(board_scrapers),
        len(TARGET_SEARCH_QUERIES),
    )


def purge_irrelevant_jobs(min_score: float = 30.0, dry_run: bool = False, user_id: Optional[str] = None) -> dict:
    """
    One-time cleanup utility: remove job rows that fall below quality threshold.

    A row is deleted when EITHER condition is true:
      • match_score < min_score  (default 30.0) — low AI fit, not worth showing
      • title does not match TARGET_SEARCH_QUERIES — not a PM-related role

    Parameters
    ----------
    min_score : float
        Rows with match_score strictly below this value are deleted.
    dry_run   : bool
        When True, counts rows that *would* be deleted but makes no changes.

    Returns
    -------
    dict with keys:
        total       — total rows examined
        deleted     — rows actually removed (0 if dry_run=True)
        dry_run_preview — rows that would be removed (only set when dry_run=True)
    """
    from backend.core.database import ENGINE
    from backend.models.job import JobRow
    from backend.scrapers.relevancy import is_title_relevant
    from sqlalchemy.orm import Session

    with Session(ENGINE) as session:
        query = session.query(JobRow)
        if user_id is not None:
            query = query.filter(JobRow.user_id == user_id)   # tenant-scoped purge
        all_rows = query.all()
        to_delete = [
            r for r in all_rows
            if (r.match_score or 0.0) < min_score or not is_title_relevant(r.title or "")
        ]

        result: dict = {"total": len(all_rows), "deleted": 0}

        if dry_run:
            result["dry_run_preview"] = len(to_delete)
            logger.info(
                "[purge] DRY RUN — would delete %d/%d rows (min_score=%.1f)",
                len(to_delete), len(all_rows), min_score,
            )
            return result

        for row in to_delete:
            session.delete(row)
        session.commit()

        result["deleted"] = len(to_delete)
        logger.info(
            "[purge] Deleted %d/%d job rows (min_score=%.1f)",
            len(to_delete), len(all_rows), min_score,
        )
        return result


@asynccontextmanager
async def lifespan(app: FastAPI):
    from backend.core.migrations import init_db
    init_db()
    logger.info("Database initialised.")

    try:
        from backend.services.master_profile_service import bootstrap_from_supplemental
        n = bootstrap_from_supplemental("default")   # legacy single-user seed
        if n:
            logger.info("[startup] Bootstrapped %d answer(s) from supplemental store into master profile", n)
    except Exception as exc:
        logger.warning("[startup] master_profile bootstrap failed (non-fatal): %s", exc)

    try:
        _seed_scraper_registry()
    except Exception as exc:
        logger.warning("[startup] Scraper registry seed failed (non-fatal): %s", exc)

    enrich_task    = asyncio.create_task(_enrichment_loop())
    discovery_task = asyncio.create_task(_discovery_loop())
    try:
        yield
    finally:
        for t in (enrich_task, discovery_task):
            t.cancel()
            try:
                await t
            except asyncio.CancelledError:
                pass
        logger.info("[startup] Background tasks stopped.")


app = FastAPI(title="Job Apply API", version="0.1.0", lifespan=lifespan)


# ── Global exception safety net ───────────────────────────────────────────────
# Last-resort handler for any exception a route/service did not itself convert
# to an HTTPException. FastAPI's built-in handlers for HTTPException and
# RequestValidationError are more specific and always win over this one, so
# existing intentional error responses (422 validation errors, deliberate
# HTTPException(status_code=..., detail=...) calls) are completely unaffected.
# This only catches what would otherwise be an unhandled exception — it
# ensures the raw exception text (which can contain library internals, DB
# details, or LLM provider error bodies) never reaches the client.

@app.exception_handler(Exception)
async def _unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception(
        "[unhandled] %s %s -> %s", request.method, request.url.path, type(exc).__name__,
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error. Please try again shortly."},
    )


# ── Security headers ──────────────────────────────────────────────────────────
# Inject hardening headers on every response. Native Starlette middleware — no
# new dependency. Placed as a class so the header set lives in one auditable
# spot; values are static and cheap to apply per-request.

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    _HEADERS = {
        "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
        "X-Content-Type-Options":    "nosniff",
        "X-Frame-Options":           "DENY",
        "X-XSS-Protection":          "1; mode=block",
    }

    async def dispatch(self, request, call_next):
        response = await call_next(request)
        for key, value in self._HEADERS.items():
            response.headers.setdefault(key, value)
        return response


app.add_middleware(SecurityHeadersMiddleware)

# Origin list is environment-based (backend/config.py::CORS_ORIGINS):
#   ENVIRONMENT=development (default) → same localhost list as before.
#   ENVIRONMENT=production            → explicit CORS_ALLOWED_ORIGINS only.
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(ariel.router,        prefix="/api/ariel",        tags=["ariel"])
app.include_router(auth.router,         prefix="/api/auth",         tags=["auth"])
app.include_router(chat.router,         prefix="/api/chat",         tags=["chat"])
app.include_router(history.router,      prefix="/api/chat",         tags=["chat-history"])
app.include_router(jobs.router,         prefix="/api/jobs",         tags=["jobs"])
app.include_router(agents.router,       prefix="/api/agents",       tags=["agents"])
app.include_router(applications.router, prefix="/api/applications", tags=["applications"])
app.include_router(resumes.router,      prefix="/api/resumes",      tags=["resumes"])
app.include_router(settings.router,     prefix="/api/settings",     tags=["settings"])
app.include_router(profile.router,      prefix="/api/profile",      tags=["profile"])
app.include_router(outreach.router,     prefix="/api/outreach",     tags=["outreach"])
app.include_router(analytics.router,    prefix="/api/analytics",    tags=["analytics"])
app.include_router(webhooks.router,     prefix="/api/webhooks",     tags=["webhooks"])
app.include_router(crm.router,          prefix="/api/crm",          tags=["crm"])
app.include_router(scraper.router,      prefix="/api/v1/scraper",   tags=["scraper"])


@app.get("/health")
async def health():
    return {"status": "ok"}
