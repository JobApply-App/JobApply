"""Model-free check of the structural "hard skills" dimension on the 36 base pairs.

Uses the requirement lists the product's own structuring pass returned during the
run (results/structured.json) and the profiles ingested into the local benchmark
database. Calls the product's score_hard_skills unchanged. No model call.
Run after the score step, with DATABASE_URL pointing at the local benchmark database.
"""
from __future__ import annotations

import hashlib
import json
import logging
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[2]))
logging.disable(logging.CRITICAL)

import run_benchmark as rb  # noqa: E402

rb.check_database_is_local()
from backend.core.database import ENGINE  # noqa: E402

assert ENGINE.url.host in rb.LOCAL_HOSTS and "bench" in (ENGINE.url.database or "")
from backend.services.feed_service import _build_profile_cv_proxy  # noqa: E402
from backend.services.match_dimensions import build_equivalence_map, score_hard_skills  # noqa: E402
from backend.services.match_score_service import _extract_cv_skills, _jd_requirements  # noqa: E402
from backend.services.user_profile import get_profile  # noqa: E402

structured = json.loads(rb.STRUCTURED.read_text())
print("| Job | Fit | Must-haves in the ad | Matched | Hard-skills score | Profile skills |")
print("|---|---|---|---|---|---|")
by_fit: dict[str, list[float]] = {}
missing_cache = 0
for p in rb.load_people(None):
    uid = rb.user_id_for(p["id"], "base")
    skills = _extract_cv_skills(_build_profile_cv_proxy(get_profile(uid), user_id=uid))
    for job in p["jobs"]:
        text = job["text"].strip()
        js = structured.get(hashlib.sha256(text.encode()).hexdigest())
        if not js:
            missing_cache += 1
            continue
        must, nice = _jd_requirements(text, js)
        eq = build_equivalence_map(list({*must, *nice, *skills}))
        score, matched, _missing, _eqv = score_hard_skills(must, nice, skills, eq)
        by_fit.setdefault(job["fit"], []).append(score)
        print(f"| {job['id']} | {job['fit']} | {len(must)} | {len(matched)} | {score:.1f} | {len(skills)} |")
print(f"\njobs with no cached structure (not checked): {missing_cache}")
for fit, vals in by_fit.items():
    print(f"- {fit}: {sum(v > 0 for v in vals)} of {len(vals)} above 0.0, highest {max(vals):.1f}")
