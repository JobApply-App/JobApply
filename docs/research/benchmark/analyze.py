"""Turn results/scores.jsonl into the pass/fail table of plan section 5 (parts A and B).

Reads only the live rows. Prints markdown. No model, no database.
Usage: python analyze.py
"""
from __future__ import annotations

import json
import statistics
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).parent
rows = [json.loads(l) for l in (HERE / "results" / "scores.jsonl").read_text().splitlines() if l.strip()]
rows = [r for r in rows if not r["dry_run"]]
failed = [r for r in rows if r["failed"]]
rows = [r for r in rows if not r["failed"]]

by = defaultdict(list)  # (job, profile_variant, variant) -> rows
fit, person = {}, {}
for r in rows:
    by[(r["job"], r["profile_variant"], r["variant"])].append(r)
    fit[r["job"]] = r["fit"]
    person[r["job"]] = r["person"]

jobs = sorted(fit)
people = sorted(set(person.values()))


def med(job, pv="base", v="base", field="total"):
    vals = [r[field] for r in by.get((job, pv, v), [])]
    return round(statistics.median(vals), 1) if vals else None


def verdict(ok):
    return "PASS" if ok else "FAIL"


print(f"rows: {len(rows)} live, {len(failed)} failed calls, {len(jobs)} jobs, {len(people)} people")
no_llm = [r for r in rows if r["variant"] != "thin" and not r["llm_validated"]]
print(f"non-thin rows without the LLM part: {len(no_llm)}")
models = sorted({m for r in rows for m in r["models"]})
print(f"models that answered: {models}\n")

# A1
print("## A1 run-to-run spread (5 runs per pair)\n")
print("| Job | Fit | Runs | Min | Max | Spread | Semantic min-max | Management min-max |")
print("|---|---|---|---|---|---|---|---|")
spreads = {}
for j in jobs:
    rs = by[(j, "base", "base")]
    t = [r["total"] for r in rs]
    s = [r["semantic"] for r in rs]
    m = [r["management"] for r in rs]
    spreads[j] = round(max(t) - min(t), 1)
    print(f"| {j} | {fit[j]} | {len(t)} | {min(t):.1f} | {max(t):.1f} | {spreads[j]:.1f} | "
          f"{min(s):.1f}-{max(s):.1f} | {min(m):.1f}-{max(m):.1f} |")
within = sum(1 for v in spreads.values() if v <= 3.0)
worst = max(spreads.values())
a1 = within / len(spreads) >= 0.9 and worst <= 8.0
print(f"\nA1: {within} of {len(spreads)} pairs with spread <= 3.0, largest spread {worst:.1f}. {verdict(a1)}\n")


def move_table(name, variant, limit, need, pv="base"):
    print(f"## {name}\n")
    print("| Job | Base (median of 5) | Variant | Move | Local base | Local variant | Semantic base | Semantic variant |")
    print("|---|---|---|---|---|---|---|---|")
    ok = n = 0
    for j in jobs:
        v = med(j, pv, variant)
        if v is None:
            continue
        b = med(j)
        move = round(abs(v - b), 1)
        n += 1
        ok += move <= limit
        print(f"| {j} | {b:.1f} | {v:.1f} | {move:.1f} | {med(j, field='local'):.1f} | "
              f"{med(j, pv, variant, 'local'):.1f} | {med(j, field='semantic'):.1f} | "
              f"{med(j, pv, variant, 'semantic'):.1f} |")
    passed = ok >= need(n)
    print(f"\n{name.split()[0]}: {ok} of {n} within {limit:.1f}. {verdict(passed)}\n")


move_table("A2 paraphrase", "paraphrase", 5.0, lambda n: n - 1)
move_table("A3 language", "translation", 5.0, lambda n: n - 1)
# A4 uses the skill-reordered profile against the base job text.
print("## A4 skill order\n")
ok = n = 0
big = []
for j in jobs:
    v = med(j, "skillorder", "base")
    if v is None:
        continue
    n += 1
    move = round(abs(v - med(j)), 1)
    ok += move <= 3.0
    if move > 3.0:
        big.append(f"{j} {move:.1f}")
print(f"A4: {ok} of {n} within 3.0. {verdict(n and ok / n >= 0.9)}" + (f" Above the line: {', '.join(big)}." if big else "") + "\n")

# B1, B2
print("## B1 and B2 order by construction\n")
print("| Person | Strong | Partial | None | Order right | Strong above none | Gap strong-none |")
print("|---|---|---|---|---|---|---|")
order_ok = above_ok = gap_ok = 0
strong_of = {}
for p in people:
    s = {fit[j]: med(j) for j in jobs if person[j] == p}
    strong_of[p] = s["strong"]
    o = s["strong"] > s["partial"] > s["none"]
    a = s["strong"] > s["none"]
    g = round(s["strong"] - s["none"], 1)
    order_ok += o
    above_ok += a
    gap_ok += g >= 20.0
    print(f"| {p} | {s['strong']:.1f} | {s['partial']:.1f} | {s['none']:.1f} | {'yes' if o else 'NO'} | "
          f"{'yes' if a else 'NO'} | {g:.1f} |")
print(f"\nB1: full order right for {order_ok} of {len(people)}, strong above none for {above_ok} of {len(people)}. "
      f"{verdict(order_ok >= 10 and above_ok == len(people))}")
print(f"B2: gap >= 20.0 for {gap_ok} of {len(people)}. {verdict(gap_ok >= 10)}\n")

# B3
print("## B3 thin job description\n")
thin = [r for r in rows if r["variant"] == "thin"]
b3 = bool(thin) and all(r["total"] <= 30.0 and r["semantic"] == 0.0 and r["management"] == 0.0 for r in thin)
for r in thin:
    print(f"- {r['job']}: total {r['total']:.1f}, semantic {r['semantic']:.1f}, management {r['management']:.1f}")
print(f"\nB3: {len(thin)} thin variants. {verdict(b3)}\n")

# B4
print("## B4 prior employer\n")
for (j, pv, v), rs in by.items():
    if v == "legacy":
        r = rs[0]
        bs, bm = med(j, field="semantic"), med(j, field="management")
        ok = r["semantic"] >= 85.0 and r["management"] >= 80.0 and r["semantic"] >= bs and r["management"] >= bm
        print(f"{j}: base semantic {bs:.1f}, management {bm:.1f}, total {med(j):.1f}; with the past employer's name "
              f"semantic {r['semantic']:.1f}, management {r['management']:.1f}, total {r['total']:.1f}. {verdict(ok)}\n")

# B5
print("## B5 overqualified\n")
for (j, pv, v), rs in by.items():
    if v == "years5":
        low, high = rs[0]["total"], med(j)
        print(f"{j}: 15-year ad {high:.1f}, 5-year ad {low:.1f}, difference {low - high:+.1f}. "
              f"{verdict(low >= high - 3.0)}\n")

# B6
print("## B6 pivot\n")
if "p01" in strong_of and "p03" in strong_of:
    d = round(abs(strong_of["p03"] - strong_of["p01"]), 1)
    print(f"p03 strong {strong_of['p03']:.1f}, p01 strong {strong_of['p01']:.1f}, difference {d:.1f}. {verdict(d <= 10.0)}\n")

# Range actually used
tot = [med(j) for j in jobs]
print("## Range of the composite\n")
for f in ("strong", "partial", "none"):
    v = [med(j) for j in jobs if fit[j] == f]
    print(f"- {f}: {min(v):.1f} to {max(v):.1f}, median {statistics.median(v):.1f}")
print(f"- all 36: {min(tot):.1f} to {max(tot):.1f}")
