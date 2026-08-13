"""
Operational configuration constants for the JobApply backend.

All flags that control cost, frequency, or external-API usage live here so
they can be found and changed in one place before launch.

This module is also the single place backend/.env is loaded from and the
single place environment-variable-backed secrets/settings are declared.
Import the named constants below instead of calling os.getenv() directly in
new code, so every reader agrees on the variable name, default, and
required/optional status.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# ── Environment loading ───────────────────────────────────────────────────────
# Importing backend.config from anywhere (main.py, a future worker
# entrypoint, a standalone script, a test) guarantees backend/.env is loaded
# before the values below are read, regardless of import order. Safe to call
# more than once — python-dotenv is idempotent and override=True just
# re-applies the same values if main.py has already loaded it.
load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env", override=True)


# ── App environment (dev/prod switch) ───────────────────────────────────────────
# Canonical flag for picking between Development and Production Supabase
# projects (DATABASE_URL/SUPABASE_URL/SUPABASE_JWT_SECRET below). Accepts
# APP_ENV, or PYTHON_ENV/ENVIRONMENT as fallbacks so existing deployments
# that already set ENVIRONMENT=production (see CORS section further down)
# don't need to add a second variable. "dev"/"develop" and "prod" are
# accepted as shorthand aliases; anything else passes through unchanged
# (e.g. a future "staging") and is treated as non-production everywhere
# below.
_RAW_APP_ENV = (
    os.getenv("APP_ENV") or os.getenv("PYTHON_ENV") or os.getenv("ENVIRONMENT") or "development"
).strip().lower()
_APP_ENV_ALIASES = {"dev": "development", "develop": "development", "prod": "production"}
APP_ENV: str = _APP_ENV_ALIASES.get(_RAW_APP_ENV, _RAW_APP_ENV)

# Backward-compatible alias — _compute_cors_origins() below (and any other
# existing reader of ENVIRONMENT) keeps working unchanged; APP_ENV is now
# the single source of truth both variables derive from.
ENVIRONMENT: str = APP_ENV


def _select_env_var(base_name: str) -> Optional[str]:
    """
    Multi-environment resolution shared by every Dev/Prod-Supabase-backed
    setting (DATABASE_URL, SUPABASE_URL, SUPABASE_JWT_SECRET):
      1. The bare var (e.g. DATABASE_URL), if set, always wins — every
         existing single-environment .env (one Supabase/Postgres project,
         no dev/prod split) keeps working with zero changes.
      2. Otherwise <base_name>_DEV / <base_name>_PROD, selected by APP_ENV —
         lets both a Dev and a Prod Supabase project's credentials live in
         the same backend/.env at once, with APP_ENV picking which one is
         actually used by this process.
    """
    explicit = os.getenv(base_name)
    if explicit:
        return explicit
    suffix = "PROD" if APP_ENV == "production" else "DEV"
    return os.getenv(f"{base_name}_{suffix}")


def _database_url_from_parts() -> Optional[str]:
    """
    Build a DSN from discrete DB_HOST/DB_PORT/DB_NAME/DB_USER/DB_PASSWORD
    (optionally _DEV/_PROD-suffixed, same precedence as _select_env_var) —
    mirrors the discrete connection-field view Supabase's dashboard shows
    alongside its ready-made connection string, for anyone who copies those
    fields instead of the single URL. Only consulted when neither
    DATABASE_URL nor DATABASE_URL_DEV/DATABASE_URL_PROD is set. Username/
    password are percent-encoded — Supabase-generated passwords routinely
    contain characters (e.g. '+', '/', '@') that aren't valid unescaped in a
    URL.
    """
    suffix = "PROD" if APP_ENV == "production" else "DEV"
    host = os.getenv(f"DB_HOST_{suffix}") or os.getenv("DB_HOST")
    if not host:
        return None
    port = os.getenv(f"DB_PORT_{suffix}") or os.getenv("DB_PORT", "5432")
    name = os.getenv(f"DB_NAME_{suffix}") or os.getenv("DB_NAME", "postgres")
    user = os.getenv(f"DB_USER_{suffix}") or os.getenv("DB_USER", "postgres")
    password = os.getenv(f"DB_PASSWORD_{suffix}") or os.getenv("DB_PASSWORD", "")
    return f"postgresql://{quote(user, safe='')}:{quote(password, safe='')}@{host}:{port}/{name}"


# ── Secrets & external-service settings ───────────────────────────────────────
#
# Required in production (see _validate_required_env below):
#   ANTHROPIC_API_KEY               — every LLM-driven feature depends on this
#   SUPABASE_URL or SUPABASE_JWT_SECRET — at least one enables authentication
#
# Optional / feature-specific:
#   TAVILY_API_KEY                  — enables live company research (agents/
#                                      matching_engine.py); labelled fallback
#                                      output when unset, nothing breaks
#   EMAIL_WEBHOOK_SECRET             — enables inbound-email webhook signature
#                                      verification; webhook still works
#                                      unauthenticated (with a loud warning)
#                                      when unset
#   GEMINI_API_KEY                  — enables llm_client.py's automatic Gemini
#                                      fallback for plain text/tool-free calls
#                                      when every Anthropic attempt fails
#                                      (missing/invalid key, outage, etc).
#                                      Without it: those calls just fail with
#                                      the same LLMCallError as before this
#                                      fallback existed — nothing regresses.
#
# NOTE: All live LLM call sites now go through backend/services/llm_client.py
# (call_llm() / stream_llm()), which builds its own client from this value.
# A handful of agent/service modules still read os.getenv("ANTHROPIC_API_KEY")
# directly, but only as a pre-flight "is the key configured" guard before
# calling call_llm() — not to construct their own provider client. The one
# deliberate exception is backend/agents/resume.py's PDF-vision path, which
# uses the SDK's beta.messages.create(betas=[...]) surface that call_llm()
# does not wrap. The canonical value is exposed here so new code has one
# place to import it from.

ANTHROPIC_API_KEY: Optional[str] = os.getenv("ANTHROPIC_API_KEY")
TAVILY_API_KEY:    Optional[str] = os.getenv("TAVILY_API_KEY")
GEMINI_API_KEY:    Optional[str] = os.getenv("GEMINI_API_KEY")

# Both resolved via _select_env_var() — SUPABASE_URL_DEV/_PROD and
# SUPABASE_JWT_SECRET_DEV/_PROD let a Dev and a Prod Supabase project's auth
# settings coexist in one backend/.env, with APP_ENV picking which is live.
SUPABASE_URL:        Optional[str] = _select_env_var("SUPABASE_URL")
SUPABASE_JWT_SECRET: Optional[str] = _select_env_var("SUPABASE_JWT_SECRET")

# Service-role key — bypasses RLS, required for the Admin Auth API (creating/
# deleting auth.users rows). Only ever read by test fixtures that need a
# disposable, isolated account (see backend/tests/conftest.py's
# disposable_qa_account); never used by the running app itself.
SUPABASE_SECRET_KEY: Optional[str] = _select_env_var("SUPABASE_SECRET_KEY")

# Real PostgreSQL connection — used ONLY by backend/core/postgres.py (a
# dedicated engine for the backend/models/linkedin_job.py table, schema
# `linkedin`). This is NOT the app's primary datastore: backend/core/
# database.py's SQLite ENGINE still is (see that module + CLAUDE.md) —
# migrating the primary app schema off SQLite onto shared Postgres is a
# separate, much larger effort (every repository module would need a new
# data-access path) and is not part of this dev/prod config layer.
#
# Resolution order (see _select_env_var/_database_url_from_parts above):
#   1. DATABASE_URL                    — explicit override, always wins
#   2. DATABASE_URL_DEV / _PROD        — picked by APP_ENV
#   3. DB_HOST_DEV/_PROD + friends     — built from discrete parts
# An async-only `postgresql+asyncpg://` scheme is normalized to plain
# `postgresql://` (psycopg2) by backend/core/postgres.py's _to_sync_dsn() —
# every other DB access in this codebase is sync, so this avoids introducing
# the project's first async DB path for one table. That same module also
# adds `sslmode=require` for non-localhost hosts (Supabase requires TLS) and
# switches to NullPool when the DSN's port is 6543 (Supabase's transaction
# pooler already pools connections server-side).
DATABASE_URL: Optional[str] = _select_env_var("DATABASE_URL") or _database_url_from_parts()

EMAIL_WEBHOOK_SECRET: str = os.getenv("EMAIL_WEBHOOK_SECRET", "")

# High-match trigger threshold (JOB-43). A newly-computed, LLM-validated
# composite match score at or above this value emits a one-time trigger event
# consumable by the notification channels (bell dropdown, push/SMS, WhatsApp).
# The UI bell (Header.tsx) independently filters at score >= 85 — keep the two
# aligned when tuning. See backend/services/match_trigger_service.py.
HIGH_MATCH_THRESHOLD: float = float(os.getenv("HIGH_MATCH_THRESHOLD", "85.0"))


def _env_bool(name: str, *, default: bool = False) -> bool:
    """Parse a boolean-ish env var: 'true'/'1'/'yes' (case-insensitive) → True."""
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


# Strict startup validation — opt-in, OFF by default.
#
#   STRICT_CONFIG=false (default) — safe for local development. Missing
#     required variables only log a loud warning; the server still boots
#     (see the non-strict branch in _validate_required_env below).
#   STRICT_CONFIG=true  — for production. Missing required variables raise
#     immediately at import time, crashing the process before it can accept
#     any traffic in a half-configured state.
#
# Production deployments SHOULD set STRICT_CONFIG=true.
STRICT_CONFIG: bool = _env_bool("STRICT_CONFIG", default=False)


class MissingRequiredConfigError(RuntimeError):
    """Raised at import time when STRICT_CONFIG=true and a required var is absent."""


def _validate_required_env() -> None:
    """
    Check required variables and either warn (default) or fail fast (strict).

    Non-strict (STRICT_CONFIG=false, the default):
      Log a loud, hard-to-miss error for each missing required variable, but
      do NOT raise or exit the process.
      • No backend/.env exists in a fresh checkout, CI, or this very dev
        environment — large parts of the app (CRM board, applications list,
        analytics) work fine with zero external services configured.
      • backend/api/deps.py already degrades gracefully per-request (HTTP 503)
        when auth isn't configured; a hard crash here would be a *stricter*
        and new failure mode than the one that exists today, which would
        break local development and the test suite rather than any real bug.

    Strict (STRICT_CONFIG=true, intended for production):
      Raise MissingRequiredConfigError immediately, crashing the process at
      startup/import instead of letting it serve traffic half-configured.
    """
    missing = []
    if not ANTHROPIC_API_KEY:
        missing.append("ANTHROPIC_API_KEY")
    if not (SUPABASE_URL or SUPABASE_JWT_SECRET):
        missing.append("SUPABASE_URL or SUPABASE_JWT_SECRET")

    if not missing:
        return

    if STRICT_CONFIG:
        raise MissingRequiredConfigError(
            "STRICT_CONFIG=true and the following required environment "
            f"variable(s) are missing: {', '.join(missing)}. "
            "Set them in backend/.env (see backend/.env.example), or unset "
            "STRICT_CONFIG for local development."
        )

    logger.error(
        "[config] MISSING REQUIRED ENVIRONMENT VARIABLE(S): %s — "
        "add them to backend/.env (see backend/.env.example). The server "
        "will still start, but dependent features will fail at request "
        "time instead of at startup. Set STRICT_CONFIG=true to make this "
        "a hard failure (recommended for production).",
        ", ".join(missing),
    )


_validate_required_env()


# ── CORS origins ───────────────────────────────────────────────────────────────
# ENVIRONMENT here is an alias of APP_ENV (see the "App environment" section
# near the top of this file) — kept as its own name only because this
# section already reads it that way; there is only one underlying value.
#
#   ENVIRONMENT=development (default) — permissive localhost allow-list,
#     identical to the hardcoded list main.py used before this was made
#     configurable. Nothing changes for local dev.
#   ENVIRONMENT=production — explicit origins only, read from
#     CORS_ALLOWED_ORIGINS (comma-separated). No implicit localhost access.
#     If unset in production, no origins are allowed (fail closed) and a
#     loud error is logged — safer than silently allowing everything.

_DEV_CORS_ORIGINS: list[str] = [
    "http://localhost:3000",
    "http://localhost:3001",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:3001",
    "http://127.0.0.1:5500",
    "http://localhost:5500",
    "https://job-apply-chi.vercel.app",
]

CORS_ALLOWED_ORIGINS_RAW: str = os.getenv("CORS_ALLOWED_ORIGINS", "")


def _compute_cors_origins() -> list[str]:
    if ENVIRONMENT == "production":
        origins = [o.strip() for o in CORS_ALLOWED_ORIGINS_RAW.split(",") if o.strip()]
        if not origins:
            logger.error(
                "[config] ENVIRONMENT=production but CORS_ALLOWED_ORIGINS is not "
                "set — no browser origin will be allowed to call this API. Set "
                "it in backend/.env, e.g. "
                "CORS_ALLOWED_ORIGINS=https://app.example.com"
            )
        return origins
    return _DEV_CORS_ORIGINS


CORS_ORIGINS: list[str] = _compute_cors_origins()


# ── Targeted search queries ───────────────────────────────────────────────────
# The canonical list of job-title search terms used by every scraper and the
# discovery pipeline.  Scrapers submit one search request per term; the
# relevancy gate in backend/scrapers/relevancy.py also derives its matching
# rules from this list.
#
# Guidelines:
#   • Use full role titles — the gate checks for substring presence.
#   • Include Hebrew variants for Israeli boards (Drushim, AllJobs, etc.).
#   • Keep the list focused: each extra entry multiplies HTTP requests across
#     all board scrapers.
TARGET_SEARCH_QUERIES: list[str] = [
    # ── Product Management (English) ──────────────────────────────────────────
    "Product Manager",
    "Product Owner",
    "Group Product Manager",
    "Senior Product Manager",
    "Head of Product",
    "VP Product",
    "Director of Product",
    "Product Operations Manager",
    "Product Lead",
    "Product Management",
    # ── Product Management (Hebrew) ───────────────────────────────────────────
    "מנהל מוצר",
    "מנהלת מוצר",
    # ── Customer Success & Account Management (English) ───────────────────────
    "Customer Success",
    "CSM",
    "Account Manager",
    "Key Account Manager",
    "Partnership Manager",
    # ── Customer Success & Account Management (Hebrew) ────────────────────────
    "מנהל הצלחת לקוחות",
    "מנהלת הצלחת לקוחות",
    "מנהל תיקי לקוחות",
    "מנהלת תיקי לקוחות",
]

# ── Per-run discovery cap ─────────────────────────────────────────────────────
# Maximum number of *new* relevant jobs to persist in a single discovery run
# (shared across all scrapers / queries).  Pagination halts immediately once
# this cap is reached so no further HTTP or LLM credits are spent.
MAX_RELEVANT_JOBS: int = 50

# ── Auto-discovery toggle ─────────────────────────────────────────────────────
# Master switch for the background discovery loop.
# Keep False until single-job manual analysis (POST /api/jobs/analyze) is
# confirmed flawless end-to-end.  Set True to re-enable batch discovery.
#
# When False the _discovery_loop() in main.py logs a warning and sleeps
# indefinitely — no LinkedIn searches, no DB writes, no LLM calls.
AUTO_DISCOVERY: bool = True

# ── Credit conservation ───────────────────────────────────────────────────────
# When True, all automatic JD-text scraping is suppressed.
# The discovery loop will still run and ingest job metadata (title, company,
# URL) but will NOT call fetch_descriptions=True on the LinkedIn scraper.
# Full JD content is only retrieved when the user explicitly clicks
# "Fetch Missing Details" or opens a card that triggers an inline fetch.
#
# TODO: RE-ENABLE HIGH-FREQUENCY POLLING BEFORE LAUNCH.
#       Set CREDIT_CONSERVATION_MODE = False and review DISCOVERY_INTERVAL_SECONDS.
CREDIT_CONSERVATION_MODE: bool = True

# ── Discovery loop interval ───────────────────────────────────────────────────
# How often (in seconds) the background discovery loop runs.
#
# Pre-launch value  : 300   (5 minutes)  — uncomment after credit budget is set
# Conservation value: 86400 (24 hours)   — active while CREDIT_CONSERVATION_MODE=True
#
# TODO: RE-ENABLE HIGH-FREQUENCY POLLING BEFORE LAUNCH.
#       Switch back to DISCOVERY_INTERVAL_SECONDS = 300.
DISCOVERY_INTERVAL_SECONDS: int = 86400  # 24 hours — credit-conservation mode

# ── All-jobs matching loop interval ───────────────────────────────────────────
# How often (in seconds) the background loop that bridges public.all_jobs
# (the global catalog) into each user's Matches feed runs. This loop only
# copies metadata + relevancy-filters (no LLM calls of its own — the existing
# enrichment loop scores whatever it inserts), so it can run far more often
# than DISCOVERY_INTERVAL_SECONDS without adding to the LLM credit budget.
ALL_JOBS_MATCHING_INTERVAL_SECONDS: int = 1800  # 30 minutes

# ── Development mode ──────────────────────────────────────────────────────────
# When DEV_MODE is True, each board scraper is capped at DEV_MAX_JOBS_PER_BOARD
# detail-page fetches per run.  This keeps the full s1 → s4 pipeline cycle
# under ~30 seconds locally instead of several minutes.
#
# !! SET DEV_MODE = False BEFORE DEPLOYING TO PRODUCTION !!
#
# Guidance:
#   DEV_MAX_JOBS_PER_BOARD = 3   → ultra-fast (~5 s); good for UI transition tests
#   DEV_MAX_JOBS_PER_BOARD = 5   → fast  (~10 s); enough real data to inspect scores
#   DEV_MAX_JOBS_PER_BOARD = 15  → moderate; good for scoring / backfill accuracy checks
DEV_MODE: bool = False
DEV_MAX_JOBS_PER_BOARD: int = 5

