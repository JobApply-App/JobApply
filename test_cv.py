"""
test_cv.py — end-to-end smoke test for the CV tailoring + PDF generation pipeline.

Steps:
  1. Fetch a specific job from the database (Bright Data CS or Sensos PM).
  2. Run TailorAgent.tailor() to produce structured CV content.
  3. Pass the result to pdf_builder.build_pdf() to render test_cv.pdf.

Run with the project venv:
    venv/bin/python test_cv.py
"""
import asyncio
import sys
import textwrap
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

# Load .env before importing any agent module so ANTHROPIC_API_KEY is available.
# We write directly to os.environ before any dotenv call inside imported modules
# can run, ensuring the key is present regardless of working directory.
import os as _os
_env_file = ROOT / ".env"
if _env_file.exists():
    for _line in _env_file.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            _k, _v = _k.strip(), _v.strip()
            if _k not in _os.environ:
                _os.environ[_k] = _v

from backend.repositories.job_repository import get_by_url, get_all  # noqa: E402
from backend.agents.tailor import TailorAgent               # noqa: E402
from backend.services.pdf_builder import build_pdf          # noqa: E402

OUTPUT_PATH = ROOT / "test_cv.pdf"

# ── Job selectors (tried in order, first hit wins) ───────────────────────────
_PREFERRED_COMPANIES = ["Bright Data", "Sensos", "Wix", "TITAN", "altshare"]

DIVIDER  = "─" * 66
DIVIDER2 = "═" * 66


def _pick_job():
    """Return the best candidate job from the database."""
    all_jobs = get_all()
    if not all_jobs:
        return None

    # Try preferred companies first
    for company in _PREFERRED_COMPANIES:
        for j in all_jobs:
            if company.lower() in j.company.lower():
                return j

    # Fall back to highest-scoring job
    return all_jobs[0]


async def main() -> None:
    print(f"\n{DIVIDER2}")
    print("  test_cv.py — CV tailoring + PDF generation smoke test")
    print(DIVIDER2)

    # ── Step 1: fetch job ────────────────────────────────────────────────────
    print("\n[1/3] Fetching job from database…")
    job = _pick_job()
    if job is None:
        print("  ERROR: No jobs found in the database. Aborting.")
        sys.exit(1)

    print(f"  Found  : {job.title}")
    print(f"  Company: {job.company}")
    print(f"  Score  : {job.score:.1f}   Category: {job.category or 'N/A'}")
    print(f"  Job ID : {job.job_id}")
    if job.apply_url:
        print(f"  URL    : {job.apply_url}")

    # ── Step 2: run TailorAgent ──────────────────────────────────────────────
    print(f"\n{DIVIDER}")
    print("[2/3] Running TailorAgent…")
    t0 = time.perf_counter()

    agent  = TailorAgent()
    result = await agent.tailor(job)

    elapsed = time.perf_counter() - t0
    print(f"  Done in {elapsed:.1f}s")

    # Handle circuit-breaker response shape
    if result.get("type") == "missing_data":
        reqs = result.get("requests", [])
        print(f"\n  ⚠  Agent requested {len(reqs)} piece(s) of missing data:")
        for r in reqs:
            print(f"     [{r.get('id','?')}] {r.get('question','')}")
        print("\n  Aborting — re-run with supplemental_answers to continue.")
        sys.exit(0)

    cv_data = result.get("cv_data", result)   # unwrap discriminated envelope

    print(f"\n  Title      : {cv_data.get('title', '—')}")
    summary = cv_data.get("summary", "")
    print(f"  Summary    : {textwrap.shorten(summary, width=72, placeholder='…')}")
    print(f"  Experiences: {len(cv_data.get('experience', []))}")
    for i, exp in enumerate(cv_data.get("experience", []), 1):
        bullets = exp.get("bullets", [])
        print(f"    {i}. {exp.get('role','?')} @ {exp.get('company','?')} ({exp.get('dates','?')}) — {len(bullets)} bullet(s)")
    cats = (cv_data.get("skills") or {}).get("categories", [])
    skill_labels = [f"{c['label']}: {', '.join(c.get('items',[]))}" for c in cats]
    print(f"  Skills     : {' | '.join(skill_labels) or '—'}")
    langs = cv_data.get("languages", [])
    if langs:
        print(f"  Languages  : {', '.join(l['language'] for l in langs)}")
    mil = cv_data.get("military") or {}
    if mil.get("role"):
        print(f"  Military   : {mil['role']} — {mil['unit']} ({mil['dates']})")
    vol = cv_data.get("volunteering", "")
    if vol:
        print(f"  Volunteering: {textwrap.shorten(vol, width=72, placeholder='…')}")

    # ── Step 3: build PDF ────────────────────────────────────────────────────
    print(f"\n{DIVIDER}")
    print("[3/3] Building PDF…")
    t1 = time.perf_counter()

    pdf_bytes = await build_pdf(cv_data, output_path=OUTPUT_PATH)

    elapsed_pdf = time.perf_counter() - t1
    size_kb = len(pdf_bytes) / 1024

    print(f"  Done in {elapsed_pdf:.1f}s")
    print(f"  Output : {OUTPUT_PATH}")
    print(f"  Size   : {size_kb:.1f} KB")

    print(f"\n{DIVIDER2}")
    print("  PASS — test_cv.pdf generated successfully.")
    print(DIVIDER2 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
