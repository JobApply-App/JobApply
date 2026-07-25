# Backend (FastAPI) — dev image, mirrors the local `uvicorn --reload` workflow.
#
# Build context is the REPO ROOT (not backend/) — a holdover from when the
# app also imported a shared Pydantic models package at repo root. That
# package now lives at backend/schemas/ (see the repo restructure), so
# everything backend needs is under backend/ already; the context could be
# narrowed to backend/ itself, deferred to a later infra pass. Build with:
#   docker build -f backend/Dockerfile -t jobapply-backend .
# (docker-compose.yml at the repo root already sets this up.)
# Pinned to a specific Debian codename (not the floating `python:3.9-slim`
# tag) because Playwright 1.49.1's `--with-deps` installer below only knows
# how to map apt package names for specific Debian releases — a newer
# unpinned base (Debian "trixie") fails with missing/renamed font packages
# (ttf-ubuntu-font-family, ttf-unifont). bookworm = Debian 12, which
# Playwright 1.49.1 fully supports. Verified via a real `docker compose
# build` run — do not un-pin this without re-testing the playwright install
# step.
FROM python:3.9-slim-bookworm

# build-essential: some pinned wheels (pymupdf, lxml) fall back to a source
# build on platforms without a prebuilt wheel. curl: used by the compose
# healthcheck below.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps in their own layer so `docker build` doesn't reinstall
# everything on every source-code change.
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

# Playwright's own Chromium binary — the only browser backend/services/
# pdf_builder.py launches (resume PDF export). --with-deps installs the
# matching apt packages for this base image automatically.
RUN python -m playwright install --with-deps chromium

# Everything backend needs now lives under backend/ itself (schemas/ moved
# in from the former repo-root models/). Not the whole repo — no frontend/,
# no legacy app.py/orchestrator.py/root requirements.txt (those belong to
# the frozen Streamlit reference app, see CLAUDE.md).
COPY backend/ backend/

EXPOSE 8000

# --reload picks up bind-mounted source changes (see docker-compose.yml).
# backend/jobs.db is created on first startup if the bind-mounted backend/
# directory doesn't already have one — it persists on the host via that
# same mount, no separate volume needed.
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
