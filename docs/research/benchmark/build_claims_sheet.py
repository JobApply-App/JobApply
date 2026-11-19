"""Build the founder's spot-check sheet for part C's reading check.

The checker model flagged claims in each CV (results/claims.jsonl). The
founder marks a fixed sample of them, so the counts in
07-benchmark-results.md say how often the checker is right.

Run from this folder:  python3 build_claims_sheet.py
Writes claims-sheet.md (for the founder) and claims-key.json (which CV each
item came from). The sample is fixed by the seed, so a re-run gives the same.
"""
import json
import random
from pathlib import Path

HERE = Path(__file__).parent
PER_KIND = 10
KIND_HE = {"unsupported": "אין לזה בסיס בפרופיל", "strengthened": "חוזק מעבר למה שבפרופיל"}

rows: dict = {}
for line in (HERE / "results" / "claims.jsonl").read_text(encoding="utf-8").splitlines():
    r = json.loads(line)
    if not r["error"]:
        rows[(r["job"], r["prompt"], r["run"])] = r      # last good check per CV
assert rows, "no checked CVs in results/claims.jsonl"

rng = random.Random(7)
items = []
for kind in ("unsupported", "strengthened"):
    pool = [(r, x) for r in rows.values() for x in r[kind]]
    assert len(pool) >= PER_KIND, f"only {len(pool)} {kind} claims"
    items += [(kind, r, x) for r, x in rng.sample(pool, PER_KIND)]
rng.shuffle(items)

out = ["# דף בדיקה למייסד: טענות בקורות החיים (שלב 7, חלק C)", "",
       "מודל הבדיקה קרא כל קורות חיים מול הפרופיל וסימן טענות. אלה 20 מהן, שנבחרו באקראי.",
       "לכל אחת כתוב בשורה **הכרעה** אחת מהשלוש: **נכון** (באמת אין בסיס / באמת חוזק), "
       "**שגוי** (הפרופיל כן תומך), או **חלקית**. האנשים והחברות מומצאים.", ""]
key = []
for i, (kind, r, x) in enumerate(items, 1):
    out += [f"## {i}. {KIND_HE[kind]}", "",
            f"- **בקורות החיים:** {x.get('cv_text', '').strip()}"]
    if kind == "strengthened" and x.get("profile_text"):
        out.append(f"- **בפרופיל:** {x['profile_text'].strip()}")
    out += [f"- **נימוק המודל:** {x.get('why', '').strip()}", "- **הכרעה:** ", ""]
    key.append({"item": i, "kind": kind, "person": r["person"], "job": r["job"],
                "prompt": r["prompt"], "run": r["run"], "locale": r["locale"]})

(HERE / "claims-sheet.md").write_text("\n".join(out), encoding="utf-8")
(HERE / "claims-key.json").write_text(json.dumps(key, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
print(f"{len(rows)} CVs, {len(items)} items -> claims-sheet.md, claims-key.json")
