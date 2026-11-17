"""Part C counts that need no model, from results/cvs.jsonl. Prints markdown.

Per CV, against the invented person's own YAML (what they actually wrote):
  - employers and degrees in the CV that the person never listed (hard failure)
  - job titles that differ from the person's title at that employer
  - job-ad terms in the CV that appear nowhere in the person's text
  - numbers in the CV that appear nowhere in the person's text (years ignored)
  - banned words and long dashes
  - share of bullets opening with the same word, share of bullets with a number

Usage: python count_cv.py
"""
from __future__ import annotations

import json
import re
import statistics
from collections import Counter, defaultdict
from pathlib import Path

import yaml

HERE = Path(__file__).parent
PEOPLE = {p["id"]: p for p in (yaml.safe_load(f.read_text(encoding="utf-8"))
                               for f in sorted((HERE / "people").glob("*.yaml")))}
JOBS = {j["id"]: j for p in PEOPLE.values() for j in p["jobs"]}

# From the self-audit list in backend/agents/tailor.py _SYSTEM_PROMPT, item (f).
BANNED = ("spearheaded", "orchestrated", "navigated", "harnessed", "delve", "testament",
          "paramount", "meticulous", "transformative", "synergy")
# Capitalised words an ad uses as ordinary English, not as a term.
AD_WORDS = {"we", "you", "our", "the", "a", "an", "and", "or", "in", "on", "for", "with", "what",
            "requirements", "advantages", "advantage", "hybrid", "remote", "full", "part", "time",
            "lead", "design", "own", "run", "take", "build", "work", "experience", "strong",
            "background", "years", "year", "is", "are", "to", "of", "at", "as", "be", "this"}


def _flat(obj) -> str:
    if isinstance(obj, dict):
        return "\n".join(_flat(v) for v in obj.values())
    if isinstance(obj, list):
        return "\n".join(_flat(v) for v in obj)
    return str(obj or "")


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip().casefold()


def _numbers(text: str) -> set[str]:
    out = set()
    for m in re.findall(r"\d[\d,.]*", text):
        n = m.replace(",", "").rstrip(".")
        if re.fullmatch(r"(19|20)\d\d", n):     # a year, not a claim
            continue
        out.add(n)
    return out


def _ad_terms(text: str) -> set[str]:
    """Latin-script terms in the ad that look like names: a capital, a digit or a symbol."""
    terms = set()
    for t in re.findall(r"[A-Za-z][A-Za-z0-9+#./-]*", text):
        t = t.rstrip(".-/")
        if t.casefold() in AD_WORDS or len(t) < 2:
            continue
        if re.search(r"[A-Z0-9+#]", t[1:]) or t[0].isupper():
            terms.add(t)
    return terms


def _has(text: str, term: str, exact_case: bool = False) -> bool:
    flags = 0 if exact_case else re.I
    return re.search(rf"(?<![A-Za-z0-9]){re.escape(term)}(?![A-Za-z0-9])", text, flags) is not None


def check(row: dict) -> dict:
    person, job, cv = PEOPLE[row["person"]]["profile"], JOBS[row["job"]], row["cv"]
    source = _flat(person)
    bullets = [b for e in cv.get("experience") or [] for b in e.get("bullets") or []]
    mil = cv.get("military_service") or {}
    bullets += list(mil.get("key_responsibilities") or [])
    written = "\n".join([cv.get("summary") or "", (cv.get("header") or {}).get("target_title") or "",
                         *bullets, *(i for c in (cv.get("skills") or {}).get("categories") or []
                                     for i in c.get("items") or [])])

    roles_by_company = defaultdict(set)
    for e in person.get("experience") or []:
        roles_by_company[_norm(e.get("company"))].add(_norm(e.get("role")))
    companies = set(roles_by_company)
    degrees = {_norm(e.get("degree")) for e in person.get("education") or []}

    invented_employers = [e.get("company") for e in cv.get("experience") or []
                          if _norm(e.get("company")) and _norm(e.get("company")) not in companies]
    invented_degrees = [e.get("degree") for e in cv.get("education") or []
                        if _norm(e.get("degree")) and _norm(e.get("degree")) not in degrees]
    changed_titles = [f"{e.get('company')}: {e.get('role')}" for e in cv.get("experience") or []
                      if _norm(e.get("company")) in companies
                      and _norm(e.get("role")) not in roles_by_company[_norm(e.get("company"))]]
    ad_terms = sorted(t for t in _ad_terms(job["text"]) if _has(written, t, exact_case=True) and not _has(source, t)
                      and not (t.endswith("s") and _has(source, t[:-1])))
    new_numbers = sorted(_numbers(written) - _numbers(source))
    firsts = Counter(b.split()[0].casefold() for b in bullets if b.split())
    return {
        "invented_employers": invented_employers,
        "invented_degrees": invented_degrees,
        "changed_titles": changed_titles,
        "ad_terms_not_in_profile": ad_terms,
        "numbers_not_in_profile": new_numbers,
        "banned_words": sum(len(re.findall(rf"\b{w}\b", written, re.I)) for w in BANNED),
        "long_dashes": written.count("—") + written.count("–"),
        "same_opening_share": round(firsts.most_common(1)[0][1] / len(bullets), 2) if bullets else 0.0,
        "bullets_with_number": round(sum(bool(re.search(r"\d", b)) for b in bullets) / len(bullets), 2)
                               if bullets else 0.0,
        "bullets": len(bullets),
    }


def main() -> None:
    path = HERE / "results" / "cvs.jsonl"
    rows = [json.loads(l) for l in path.read_text().splitlines() if l.strip()] if path.exists() else []
    rows = [r for r in rows if not r["dry_run"]]
    kinds = Counter((r["prompt"], r["type"]) for r in rows)
    print(f"rows: {len(rows)} | by prompt and outcome: {dict(sorted(kinds.items()))}\n")
    cvs = [(r, check(r)) for r in rows if r["type"] == "cv"]
    if not cvs:
        print("No CVs to count.")
        return

    print("| Prompt | CVs | Invented employer or degree | Changed titles | Ad terms not in profile "
          "(median, max) | Numbers not in profile (median, max) | Banned words | Long dashes | "
          "Same opening (median) | Bullets with a number (median) |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    for prompt in sorted({r["prompt"] for r, _ in cvs}):
        c = [x for r, x in cvs if r["prompt"] == prompt]
        terms = [len(x["ad_terms_not_in_profile"]) for x in c]
        nums = [len(x["numbers_not_in_profile"]) for x in c]
        print(f"| {prompt} | {len(c)} | {sum(bool(x['invented_employers'] or x['invented_degrees']) for x in c)} "
              f"| {sum(len(x['changed_titles']) for x in c)} | {statistics.median(terms):.1f}, {max(terms)} "
              f"| {statistics.median(nums):.1f}, {max(nums)} | {sum(x['banned_words'] for x in c)} "
              f"| {sum(x['long_dashes'] for x in c)} "
              f"| {statistics.median(x['same_opening_share'] for x in c):.2f} "
              f"| {statistics.median(x['bullets_with_number'] for x in c):.2f} |")

    print("\n## Hard failures (invented employer or degree)\n")
    hard = [(r, x) for r, x in cvs if x["invented_employers"] or x["invented_degrees"]]
    for r, x in hard:
        print(f"- {r['job']} {r['prompt']} #{r['run']} ({r['locale']}): "
              f"employers {x['invented_employers']}, degrees {x['invented_degrees']}")
    if not hard:
        print("None.")

    print("\n## Per CV\n")
    for r, x in cvs:
        print(f"- {r['job']} {r['prompt']} #{r['run']} ({r['locale']}): titles {x['changed_titles']}; "
              f"ad terms {x['ad_terms_not_in_profile']}; numbers {x['numbers_not_in_profile']}")


if __name__ == "__main__":
    main()
