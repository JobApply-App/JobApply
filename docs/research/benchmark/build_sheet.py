"""Validate the benchmark people files and build the founder's ranking sheet.

Run from this folder:  python3 build_sheet.py
Fails loudly on any structural problem; a quiet pass means every check ran.
"""
import json
import random
import re
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).parent
FIT_RANK = {"strong": 0, "partial": 1, "none": 2}
LETTERS = ["א", "ב", "ג"]


def load():
    files = sorted((HERE / "people").glob("*.yaml"))
    assert len(files) == 12, f"expected 12 people, found {len(files)}"
    return [yaml.safe_load(f.read_text(encoding="utf-8")) for f in files]


def validate(people):
    problems = []
    for p in people:
        pid, prof, jobs = p["id"], p["profile"], p["jobs"]
        if len(jobs) != 3:
            problems.append(f"{pid}: {len(jobs)} jobs")
        if sorted(j["fit"] for j in jobs) != ["none", "partial", "strong"]:
            problems.append(f"{pid}: fits are not one of each")
        by_fit = [j["id"] for j in sorted(jobs, key=lambda j: FIT_RANK[j["fit"]])]
        if by_fit != p["expected_order"]:
            problems.append(f"{pid}: expected_order disagrees with fit labels")
        for key in ("title", "summary", "experience", "education", "skills", "languages"):
            if not prof.get(key):
                problems.append(f"{pid}: profile missing {key}")
        for e in prof["experience"]:
            if not e.get("role") or not e.get("bullets"):
                problems.append(f"{pid}: experience entry without role or bullets")
        employers = [e["company"] for e in prof["experience"] if e.get("company")]
        for j in jobs:
            n = len(j["text"])
            if n < 500:  # well above the product's 300-char thin-JD cutoff
                problems.append(f"{j['id']}: job text only {n} chars")
            if "—" in j["text"] or "–" in j["text"]:
                problems.append(f"{j['id']}: long dash in job text")
            # no accidental prior-employer match (the product uses \bcompany\b)
            for emp in employers:
                if re.search(rf"\b{re.escape(j['company'])}\b", emp, re.I) or \
                   re.search(rf"\b{re.escape(emp)}\b", j["company"] + " " + j["text"], re.I):
                    problems.append(f"{j['id']}: employer '{emp}' appears in the job")
            met = [r["met"] for r in j["requirements"]]
            if j["fit"] == "strong" and not all(met):
                problems.append(f"{j['id']}: strong fit with an unmet requirement")
            if j["fit"] == "partial" and (all(met) or not any(met)):
                problems.append(f"{j['id']}: partial fit must mix met and unmet")
            if j["fit"] == "none" and sum(met) > 1:
                problems.append(f"{j['id']}: non-fit meets more than one requirement")
        lv = p.get("legacy_variant")
        if lv:
            job = next(j for j in jobs if j["id"] == lv["job"])
            if lv["replace"] not in job["text"] or lv["replace"] != job["company"]:
                problems.append(f"{pid}: legacy_variant token not in the job")
            if lv["with"] not in employers:
                problems.append(f"{pid}: legacy_variant target is not a past employer")
        for j in jobs:
            if "years_token" in j and j["years_token"] not in j["text"]:
                problems.append(f"{j['id']}: years_token not in the job text")
    return problems


def build(people):
    rng = random.Random(7)  # fixed seed: the sheet is reproducible
    key, out = {}, [
        "# דף דירוג למייסד (שלב 7, מדד B7)",
        "",
        "לכל אדם יש 3 משרות. דרג אותן מהמתאימה ביותר לפחות מתאימה, לפי שיקול דעתך.",
        "אין צורך לנמק. כתוב את הדירוג בשורה שבסוף כל אדם, למשל: ב > א > ג.",
        "האנשים והחברות מומצאים.",
        "",
    ]
    for n, p in enumerate(people, 1):
        prof = p["profile"]
        jobs = p["jobs"][:]
        rng.shuffle(jobs)
        key[p["id"]] = {LETTERS[i]: j["id"] for i, j in enumerate(jobs)}
        out += [f"## {n}. {prof['name']}: {prof['title']}", "", prof["summary"], "", "**Experience, newest first:**"]
        for e in reversed(prof["experience"]):
            where = f" at {e['company']}" if e.get("company") else ""
            out.append(f"- {e['period']}: {e['role']}{where}")
            out += [f"  - {b}" for b in e["bullets"]]
        out += ["", "**Education:** " + "; ".join(f"{e['degree']}, {e['institution']}" for e in prof["education"])]
        out += ["**Skills:** " + ", ".join(i for c in prof["skills"]["categories"] for i in c["items"])]
        out += ["**Languages:** " + ", ".join(f"{l['language']} ({l['level']})" for l in prof["languages"]), ""]
        for i, j in enumerate(jobs):
            out += [f"### משרה {LETTERS[i]}: {j['title']}, {j['company']} ({j['location']})", "", j["text"].strip(), ""]
        out += ["**הדירוג שלי:** ___ > ___ > ___", "", "---", ""]
    (HERE / "ranking-sheet.md").write_text("\n".join(out), encoding="utf-8")
    (HERE / "ranking-key.json").write_text(json.dumps(key, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    people = load()
    problems = validate(people)
    if problems:
        print("\n".join(problems))
        sys.exit(1)
    build(people)
    texts = [len(j["text"]) for p in people for j in p["jobs"]]
    he = sum(j["language"] == "he" for p in people for j in p["jobs"])
    print(f"ok: 12 people, {len(texts)} jobs ({he} Hebrew), job text {min(texts)}-{max(texts)} chars")
