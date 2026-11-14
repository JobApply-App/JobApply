"""Checks that need no model call and no database: the parts of the score that
are plain code. Run from the repo root:  python docs/research/benchmark/free_checks.py

Uses the product's own functions, so the numbers are what the product computes.
"""
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2]))
os.chdir(HERE.parents[2])
sys.path.insert(0, str(HERE))

from run_benchmark import job_variants, load_people  # noqa: E402

from backend.services.match_score_service import (  # noqa: E402
    _find_prior_employer, compute_local_proxy_score, finalize_composite,
)

people = load_people(None)
rows = []
for p in people:
    cv = {"experience": [{"role": e["role"], "company": e.get("company", ""), "bullets": e["bullets"]}
                         for e in p["profile"]["experience"]]}
    for job in p["jobs"]:
        for variant, title, company, text in job_variants(p, job):
            local = compute_local_proxy_score(title, text)
            rows.append({"person": p["id"], "who": p["profile"]["title"], "job": job["id"], "fit": job["fit"],
                         "lang": job["language"], "variant": variant, "title": title, "local": local,
                         "thin_composite": finalize_composite(local, 0.0, 0.0),
                         "prior_employer": _find_prior_employer(cv, company)})

base = [r for r in rows if r["variant"] == "base"]
print("| Person | Their job title | Strong | Partial | No fit | Order right? |\n|---|---|---|---|---|---|")
right = 0
for p in people:
    s = {r["fit"]: r["local"] for r in base if r["person"] == p["id"]}
    ok = s["strong"] > s["partial"] > s["none"]
    right += ok
    print(f"| {p['id']} | {p['profile']['title']} | {s['strong']:.1f} | {s['partial']:.1f} | {s['none']:.1f} | {'yes' if ok else 'no'} |")
print(f"\nlocal score orders strong > partial > none for {right} of 12 people")
top = sum(1 for p in people if (lambda s: s["strong"] > max(s["partial"], s["none"]))({r["fit"]: r["local"] for r in base if r["person"] == p["id"]}))
print(f"strong fit has the single highest local score for {top} of 12 people")
vals = sorted({r["local"] for r in base})
print(f"distinct local scores over the 36 jobs: {vals}")
he = [r["local"] for r in base if r["lang"] == "he"]
print(f"Hebrew-titled jobs: {len(he)}, distinct local scores: {sorted(set(he))}")

print("\ntranslation pairs (same job, title in the other language):")
for r in rows:
    if r["variant"] == "translation":
        b = next(x for x in base if x["job"] == r["job"])
        print(f"  {r['job']}: {b['lang']} title {b['local']:.1f} -> translated title {r['local']:.1f}  ({r['title']})")

print("\nthin job description (composite = 0.30 x local, both LLM sub-scores 0.0):")
for r in rows:
    if r["variant"] == "thin":
        print(f"  {r['job']} ({r['title']}): local {r['local']:.1f} -> composite {r['thin_composite']:.1f}")

print("\nprior employer detection:")
for r in rows:
    if r["person"] == "p10" and r["job"] == "p10-j2":
        print(f"  {r['variant']}: detected = {r['prior_employer']!r}")
others = [r for r in rows if r["prior_employer"] and not (r["job"] == "p10-j2" and r["variant"] == "legacy")]
print(f"  false detections elsewhere: {len(others)} of {len(rows) - 1}")
