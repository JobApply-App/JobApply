# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project: JobApply_Venture (B2C Upgrade)

B2C, ATS-optimized job-application platform. Backend is FastAPI (Python); frontend is Next.js. Four core B2C features under active development: Master Profile (persistent supplemental-answer storage), Match Score (0-100% JD match algorithm + UI), Template Engine (3 ATS-safe HTML/CSS resume templates), Live Editor (manual CV text editing before PDF export).

## Commands

**Backend** (FastAPI, run from repo root):
```bash
uvicorn backend.main:app --reload
```
- All intra-backend imports must use the `backend.` prefix (e.g. `from backend.services import db`) — bare `api.*`/`services.*`/`config` imports load a second, independent module instance (duplicated rate-limit buckets, JWKS caches, DB engines). `backend/main.py` enforces this by inserting the project root onto `sys.path`.
- Env vars come from `backend/.env` (not root `.env`): `ANTHROPIC_API_KEY`, `DATABASE_URL`, `REDIS_URL`, `SUPABASE_URL`, `SUPABASE_JWT_SECRET`.
- Single test: `pytest backend/tests/test_profile_trust.py`. Test-only deps (`pytest`, `pytest-asyncio`) live in `backend/requirements-dev.txt`, not `backend/requirements.txt` — install with `pip install -r backend/requirements-dev.txt` (this also pulls in `requirements.txt` via `-r`). `backend/pytest.ini` sets `asyncio_mode = auto`; a venv missing `pytest-asyncio` will fail every `@pytest.mark.asyncio` test with "Unknown pytest.mark.asyncio" rather than skip cleanly, so this step is easy to silently miss — see `docs/environment-setup.md`.

**Frontend** (Next.js, run from `frontend/`):
```bash
npm run dev      # next dev
npm run build     # next build
npm run lint      # next lint
```
No test framework is configured for the frontend.

## Architecture

### Backend (`backend/`)
- `main.py` — FastAPI app entry point; wires all routers.
- `api/routes/` — one router per domain: `agents`, `analytics`, `applications`, `ariel` (AI assistant/copilot), `auth`, `chat`, `crm`, `history`, `jobs`, `outreach`, `profile`, `resumes`, `settings`, `webhooks`.
- `agents/` — LLM agent classes (applier, matcher, resume, scraper, tailor, copilot, gatekeeper, truth_check, ariel_tools).
- `engines/` — core scoring logic: master_profile, matching_engine, optimization_engine.
- `services/` — bulk of business logic: `db.py`, feed/job/match_score/confidence_matrix/master_profile/cv_assembly/pdf_builder/outreach/ats_match_engine services.
- `scrapers/` — per-site job scrapers (LinkedIn, AllJobs, Drushim, Comeet, Gotfriends, Nisha, etc.) plus `relevancy.py`, `scraper_manager.py`.
- `integrations/` — external service glue (`job_scraper.py`, `oauth_integrations.py`).
- `logic/` — legacy modules (`outreach_engine.py`, `verifier.py`) used only by the root Streamlit app, not the FastAPI app.
- `templates/` — resume HTML templates (`cv_template.html`, `cv/`).

**Database** (corrected 2026-08-16 — the previous description of this section was wrong in every particular, see below): Postgres on Supabase is the active primary datastore. `backend/core/database.py` builds `ENGINE` from `backend.config.DATABASE_URL` and only falls back to `sqlite:///backend/jobs.db` when that variable is unset. `backend/core/postgres.py` builds a second engine (`PG_ENGINE`) from the same URL for the `all_jobs`/LinkedIn tables. `backend/services/db.py` does not exist.

There is exactly **one** Supabase project (`ynirccgaxwcwmbhkfxnh`), reached via the bare `DATABASE_URL`, serving both local development and the deployed Render service (`render.yaml` declares the bare key too). `config.py`'s `_select_env_var()` still supports `DATABASE_URL_DEV`/`_PROD` for a future genuine two-project split, but they are unset — the bare key wins over both regardless of `APP_ENV`.

Two traps this section previously hid, both of which reached production:
- **An empty database is indistinguishable from a healthy one.** `core/migrations.py` runs `Base.metadata.create_all()` at startup, so pointing at a fresh/wrong project creates the schema on arrival and every query returns `200` with zero rows. No error anywhere. This is what a `_PROD` variable aimed at an unpopulated project looks like.
- **`/health` proves nothing about the database.** It returns `{"status": "ok"}` unconditionally and touches neither Postgres nor Chromium.

The stale text claimed SQLite was primary, `DATABASE_URL` was "aspirational/unused", and `backend/services/db.py` existed. Anyone trusting it would conclude the database configuration could not be the cause of a data problem — which is exactly the wrong place to stop looking. Root-level `jobs.db` remains a stray 0-byte artifact.

### Legacy standalone Streamlit app (not part of the FastAPI product)
Root `app.py` is a separate Streamlit dashboard that imports `orchestrator.py` and `backend/logic/*`. `orchestrator.py` defines `analyze_fit()` and a hardcoded `_TARGET_JOB`. Do not confuse this with the FastAPI backend — it's a parallel/older UI kept for reference. See `docs/architecture-boundaries.md` for the full dependency-direction audit and multi-tenant preparation notes.

### Frontend (`frontend/`)
App root is `frontend/`; the package name is `job-apply-web` (the two differ — don't infer the directory from the package name). Source lives in `frontend/src/{app,components,contexts,hooks,lib,locales}`. Next.js 14 (app router), Tailwind, Supabase JS client.

There is no `web_dashboard/` directory. Earlier revisions of this file said there was, which is worse than saying nothing: a `grep` scoped to a path that doesn't exist returns empty and reads exactly like "this symbol is unused." That misread once cost a full-stack rename being scoped as backend-only. When checking whether the frontend uses something, scope the search with `git ls-files` rather than a hardcoded directory.

### Shared Pydantic models (`models/`)
- `agent.py` — agent state/stats for UI agent cards.
- `application.py` — `ApplicationStatus` enum (submitted → offer/rejected).
- `job.py` — `RawJobPosting` and job source/status/locale literals.
- `matching.py` — `ScoringBreakdown`/`MatchAnalysis` for the matching engine.
- `optimization.py` — `CVImprovement`/`OptimizationReport` for CV rewrite suggestions.
- `profile.py` — deep profile including `ProfessionalRole`.
- `user.py` — `UserProfile` (skills, seniority, salary targets).

## Design system

See `DESIGN_SYSTEM.md` ("Editorial Intercom" system) for full detail. Key rules:
- Teal (`#0D9488`) primary — no corporate blue.
- Boxless UI: prefer whitespace/borders over nested cards.
- `rounded-2xl` for cards, `rounded-lg` for buttons; avoid `rounded-full` on nav.
- Custom multi-layer micro-shadows — never flat `shadow-md`/`shadow-lg`.
- AI chat (Ariel) is on-demand/overlay, never a persistent split-screen panel.

## Empty results are not evidence

An empty or zero result means one of two things — "the thing genuinely isn't
there" or "the check never actually ran" — and they look identical. Confirm
which before drawing a conclusion. This has produced wrong conclusions in this
repo repeatedly:

- A `grep` scoped to `web_dashboard/`, a directory that does not exist, returned
  empty and read as "this symbol is unused". Cost a full-stack rename being
  scoped as backend-only (see the frontend section above).
- `frontend/src/lib/cvParser.ts` contained a raw NUL byte, so `git` and
  `file(1)` classified it as binary and `grep` silently reported zero matches
  for symbols that were plainly in the file.
- A PDF's section headings are letter-spaced (`M I L I T A R Y  S E R V I C E`),
  so `grep -i military` on extracted text found nothing while the section was
  present.
- `build_full_text()` takes a `user_id`; passing it a profile dict made it
  resolve nothing, a broad `except` turned that into a warning, and the
  resulting corpus came back *smaller* than the one it was meant to widen. The
  "measurement" looked like a modest improvement rather than a check that had
  never run.

Practical habits that catch these:

- Before concluding "no matches", verify the search space is real —
  `git ls-files <path>`, or grep for a token you know is present.
- Treat a bare `except` around a measurement as suspect. If a step can fail
  silently and still return a plausible-looking value, log the failure loudly
  or let it raise.
- When a number moves the wrong way (a corpus shrinks, a count drops), assume a
  broken check before assuming a real finding.
- For a test suite, confirm the tests you care about actually ran rather than
  skipped — a green run with everything skipped is also green.

## Global rules (`.ai_rules`)

- All scores must use 1 decimal precision.
- User interactions must update the central User Profile.
- New features must not override existing source labeling (LinkedIn/Company Site).

## AI Persona: Senior Product Manager

For product-design work (not implementation), operate as a senior product manager responsible for end-to-end product development.

**Core Design Principles:**
1. Reality First: Solutions must be technically, temporally, and financially feasible. Avoid idealized assumptions.
2. Detail-Oriented: Capture nuanced user behaviors and psychological needs via user personas and scenarios.
3. Humanistic Care: Integrate inclusivity (accessibility), emotional support (friendly feedback), and moral responsibility (privacy).

**Workflow:**
1. Understand Context (business goals, constraints, target users).
2. User Research (build user personas detailing goals, pain points, behaviors).
3. Feature Design (output feature list with P0/P1/P2 priorities, core flows, edge cases, MVP scope).
4. Humanistic Design (accessibility, emotional design, privacy/ethics).
5. Document Output (save to `docs/prd-b2c.md`).

---

## Core AI Scoring & Logic Principles

These are **mandatory architectural rules** for all matching, scoring, and prompt-engineering work in this project. Every new feature, prompt change, or scoring adjustment must comply with all five principles. Non-compliant implementations must be rejected and corrected before merging.

### 1. Data Completeness — No Truncation
The LLM must receive the **full candidate experience timeline**, ordered most-recent-first, with brief context per role. Never slice or cap the experience array before passing it to the model (e.g., `[:5]` is forbidden). Older, less-relevant roles appear last so the model's attention naturally falls on the most recent positions.

- **Implementation reference:** `_llm_dual_score()` in `match_score_service.py` — uses `reversed(cv_data["experience"])` with no length cap.
- **Anti-pattern to avoid:** Any `experience[:][:N]` or fixed-count slice on the data sent to the LLM prompt.

### 2. Company Legacy — Prior Employer Boost
If the target job's company name appears in the candidate's experience history, this is the **strongest possible fit signal** and must produce a score override. The system must detect the match programmatically and inject a mandatory high-priority directive into the LLM prompt that floors `semantic_experience_score ≥ 85` and `management_trajectory_score ≥ 80` unless there is an explicit, disqualifying hard-skill gap stated in the JD.

- **Implementation reference:** `_find_prior_employer()` + `company_legacy_note` injection in `match_score_service.py`.
- **Matching rule:** Word-boundary regex (`\b{company}\b` with `re.escape`) — never bare substring containment, to prevent false positives (e.g., "River" must not match "Riverside").

### 3. Exploration Freedom & Seniority Scaling
The scoring system must **never penalize**:
- A career pivot or title mismatch between the candidate's current/recent role and the target JD. Evaluate transferable capabilities across the full history.
- Overqualification. If the candidate has more seniority or more years of experience than the JD requires, treat that as a neutral-to-positive signal, never as a deduction.

These constraints are enforced at the **prompt level** via the MANDATORY ARCHITECTURAL PRINCIPLES block in `_LLM_SCORER_TEMPLATE`. Any future prompt rewrite must preserve the Exploration Freedom and Seniority Scaling clauses verbatim or in equivalent force.

### 4. Strict Fallback for Thin JDs
When `jd_text` is below the minimum length threshold (currently **300 characters**), the LLM call is skipped. In this scenario:
- `semantic_score` **must be set to `0.0`**.
- `management_score` **must be set to `0.0`**.
- The composite is computed normally: `0.30 × local + 0.50 × 0 + 0.20 × 0 = 0.30 × local`.
- This caps un-hydrated jobs at ~28–30 points for an exact title match, keeping them near the **bottom** of the feed until the real JD is fetched and a full re-score runs.

**Anti-pattern:** Returning `_phase1().total` directly as the composite when the JD is thin. A Phase-1-only score of 94 for "Senior Product Manager" with an empty JD is a false positive that surfaces irrelevant jobs at the top of the feed.

- **Implementation reference:** The `_LLM_MIN_JD_CHARS` guard block in `compute_match_score_async()`, `match_score_service.py`.

### 5. Future Mandate
All newly developed matching or scoring features — including any new LLM dimensions, re-ranking logic, or supplemental scoring layers — must be reviewed against these four principles before implementation. If a proposed change would violate any principle (e.g., adding a "title-match bonus" that inflates thin-JD scores, or capping the experience list passed to a new model), the design must be revised to comply before work begins.
