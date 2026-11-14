"""Stage 7 benchmark runner: ingest the invented people, then score their jobs.

It drives the product's own code, not a copy of it:
  ingest -> backend.api.routes.profile._ingest_cv_full   (the CV-upload path)
  score  -> jd_structure_service.structure_jd, then
            match_score_service.compute_match_score_async, called the way
            feed_service does.

Run from the repo root with the project's virtualenv:

  python docs/research/benchmark/run_benchmark.py ingest --dry-run
  python docs/research/benchmark/run_benchmark.py score  --dry-run
  python docs/research/benchmark/run_benchmark.py ingest --people p01,p05 --env-file <path to backend/.env>
  python docs/research/benchmark/run_benchmark.py score  --people p01,p05 --env-file <path to backend/.env>

Safety rules built in:
  - Refuses to start unless DATABASE_URL is a localhost Postgres database
    whose name contains "bench". The product has one Supabase project and it
    is production. (SQLite does not work: the profile code uses Postgres SQL.)
  - --env-file copies ONLY the model API keys into the environment. It never
    reads DATABASE_URL or any Supabase setting.
  - Every model call is written to results/ledger.jsonl with its token use
    and cost. The run stops when total spend reaches --cap (default $15).
  - A model whose price is not in PRICES stops the run. Cost is never guessed.
  - --dry-run makes no network call: the provider functions are replaced by a
    stub, so the database and scoring plumbing can be checked for free.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
RESULTS = HERE / "results"
LEDGER = RESULTS / "ledger.jsonl"
SCORES = RESULTS / "scores.jsonl"
STRUCTURED = RESULTS / "structured.json"

# USD per million tokens (input, output). Add a row for any other model before
# running; see --price.
#   Anthropic rows: pricing table dated 2026-11-03.
#   gemini-flash-latest: Google's pricing page read 2026-11-14 does not say which
#   model the alias points to. Both stable Flash models listed there
#   (gemini-3.6-flash, gemini-3.8-flash) cost $0.75 / $3.75 until 2026-12-31
#   and $1.50 / $7.50 from 2027-01-01, so that price is used.
#   Gemini bills thinking tokens as output, and llm_client reports only the
#   visible reply, so Gemini cost here is a slight undercount. The product
#   sets thinking_budget=1, which keeps it small; check the pilot's ledger
#   against Google's billing page.
PRICES: dict[str, tuple[float, float]] = {
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "gemini-flash-latest": (0.75, 3.75),
}
_VARIANTS_FILE = HERE / "variants.yaml"
VARIANTS: dict = yaml.safe_load(_VARIANTS_FILE.read_text(encoding="utf-8")) if _VARIANTS_FILE.exists() else {}
THIN_PEOPLE = ("p01", "p03", "p05", "p07", "p09", "p11")
REPEATS = 5


# ── test set ──────────────────────────────────────────────────────────────────

def load_people(only: set[str] | None) -> list[dict]:
    people = [yaml.safe_load(f.read_text(encoding="utf-8")) for f in sorted((HERE / "people").glob("*.yaml"))]
    assert len(people) == 12, f"expected 12 people, found {len(people)}"
    if only:
        missing = only - {p["id"] for p in people}
        assert not missing, f"unknown people: {missing}"
        people = [p for p in people if p["id"] in only]
    return people


DRY_RUN = False   # set in main(); dry-run users get their own ids, so stub
                  # profiles can never be mistaken for really ingested ones


def user_id_for(pid: str, profile_variant: str) -> str:
    mode = "dry:" if DRY_RUN else ""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"jobapply-benchmark:{mode}{pid}:{profile_variant}"))


def cv_text(profile: dict, *, reverse_skills: bool = False) -> str:
    """The person's CV as plain text, the way an uploaded document would read."""
    out = [profile["name"], profile["title"],
           f"{profile['email']} | {profile['phone']} | {profile['location']}", "",
           "SUMMARY", profile["summary"], "", "EXPERIENCE"]
    for e in reversed(profile["experience"]):
        head = f"{e['role']}, {e['company']}" if e.get("company") else e["role"]
        out += [f"{head} ({e['period']})"] + [f"- {b}" for b in e["bullets"]] + [""]
    out.append("EDUCATION")
    for e in profile["education"]:
        line = f"{e['degree']}, {e['institution']} ({e['period']})"
        extras = [x for x in (e.get("honors"), e.get("coursework")) if x]
        out.append(line + (". " + ". ".join(extras) if extras else ""))
    cats = profile["skills"]["categories"]
    if reverse_skills:
        cats = [{"label": c["label"], "items": list(reversed(c["items"]))} for c in reversed(cats)]
    out += ["", "SKILLS"] + [f"{c['label']}: {', '.join(c['items'])}" for c in cats]
    out += ["", "LANGUAGES", ", ".join(f"{l['language']} ({l['level']})" for l in profile["languages"])]
    if profile.get("volunteering"):
        out += ["", "VOLUNTEERING", profile["volunteering"]]
    return "\n".join(out)


def job_variants(person: dict, job: dict) -> list[tuple[str, str, str, str]]:
    """(variant name, title, company, text) for every scoring variant of a job."""
    title, company, text = job["title"], job["company"], job["text"].strip()
    out = [("base", title, company, text)]
    if job["fit"] == "strong" and person["id"] in THIN_PEOPLE:
        out.append(("thin", title, company, f"{title}\n{text[:200]}"))
    lv = person.get("legacy_variant")
    if lv and lv["job"] == job["id"]:
        out.append(("legacy", title, lv["with"], text.replace(lv["replace"], lv["with"])))
    if "years_token" in job:
        low = job["years_token"].replace("15", "5")
        assert low != job["years_token"]
        out.append(("years5", title, company, text.replace(job["years_token"], low)))
    for kind, v in (VARIANTS.get(job["id"]) or {}).items():   # paraphrase, translation
        out.append((kind, v["title"], v.get("company", company), v["text"].strip()))
    for name, _t, _c, body in out:
        assert body.strip(), f"{job['id']} {name}: empty job text"
    return out


# ── model-call ledger, cap and dry-run stub ───────────────────────────────────

class Ledger:
    def __init__(self, cap: float, dry_run: bool):
        self.cap, self.dry_run = cap, dry_run
        self.calls: list[dict] = []          # calls made in the current step
        self.by_purpose: dict[str, int] = {}
        self.spent = 0.0
        if LEDGER.exists():
            self.spent = sum(json.loads(l)["cost_usd"] for l in LEDGER.read_text().splitlines() if l.strip())

    def record(self, purpose: str, result) -> None:
        model = result.model
        key = next((k for k in PRICES if model.startswith(k)), None)
        if self.dry_run:
            cost = 0.0
        else:
            if key is None:
                raise SystemExit(f"no price for model '{model}'. Add it with --price; cost is never guessed.")
            if result.input_tokens is None or result.output_tokens is None:
                raise SystemExit(f"model '{model}' returned no token counts; cannot track cost.")
            cost = (result.input_tokens * PRICES[key][0] + result.output_tokens * PRICES[key][1]) / 1_000_000
        row = {"at": datetime.now(timezone.utc).isoformat(), "purpose": purpose, "model": model,
               "input_tokens": result.input_tokens, "output_tokens": result.output_tokens,
               "cost_usd": round(cost, 6), "dry_run": self.dry_run}
        self.calls.append(row)
        self.by_purpose[purpose] = self.by_purpose.get(purpose, 0) + 1
        if not self.dry_run:
            self.spent += cost
            with LEDGER.open("a") as f:
                f.write(json.dumps(row) + "\n")
            if self.spent >= self.cap:
                raise SystemExit(f"spending cap reached: ${self.spent:.2f} of ${self.cap:.2f}. Stopped.")


def install_ledger(ledger: Ledger, stub_state: dict | None) -> None:
    """Wrap the two provider functions call_llm() resolves at call time."""
    from backend.services import llm_client

    if ledger.dry_run:
        async def stub(*, purpose, messages=(), **_kw):
            if purpose == "jd_parser_parse_and_format":
                # The product scores the parser's condensed text, not the raw
                # ad. Echo the ad's lines back so the dry run reaches the scorer.
                raw = str(messages[0]["content"]).splitlines()[1:-2]
                text = json.dumps({"must_haves": [l.strip("- ").strip() for l in raw if l.strip()]})
            elif purpose == "cv_aggregate_claims":
                text = json.dumps(_stub_claims(stub_state["profile"]))
            elif purpose == "match_score_dual_score":
                text = json.dumps({"semantic_score": 50, "management_score": 50,
                                   "fit_brief": "dry run", "missing_critical_capabilities": []})
            else:
                # Every other caller treats unusable output as "no result".
                # The purpose still lands in the ledger, so the dry run shows
                # every model call a live run would make.
                text = "{}"
            result = llm_client.LLMResult(text=text, model="dry-run", input_tokens=0, output_tokens=0,
                                          latency_ms=0.0, attempts=1, raw=None)
            ledger.record(purpose, result)
            return result
        llm_client._gemini_eligible = lambda *_a, **_k: False
        llm_client._call_anthropic = stub
        return

    for name in ("_call_anthropic", "_call_gemini"):
        real = getattr(llm_client, name)

        async def wrapped(*, purpose, _real=real, **kw):
            result = await _real(purpose=purpose, **kw)
            ledger.record(purpose, result)
            return result
        setattr(llm_client, name, wrapped)


def _stub_claims(profile: dict) -> dict:
    """Dry-run stand-in for the aggregator's output, in its schema."""
    skills = [i for c in profile["skills"]["categories"] for i in c["items"]]
    exps = []
    for e in profile["experience"]:
        start, _, end = e["period"].partition(" - ")
        exps.append({"company": e.get("company", ""), "role": e["role"], "start": start.strip(),
                     "end": (end.strip() or start.strip()).lower(), "summary": " ".join(e["bullets"][:2]),
                     "kind": "military" if e.get("company", "").startswith("IDF") else "job"})
    return {
        "personal": {"full_name": profile["name"], "phone": profile["phone"], "email": profile["email"],
                     "linkedin_url": "", "location": profile["location"]},
        "languages": [{"language": l["language"], "level": "Native" if l["level"] == "Native" else "Fluent"}
                      for l in profile["languages"]],
        "skills": skills, "skill_details": [], "domains": [profile["title"]],
        "experiences": exps,
        "education": [{"degree": e["degree"], "institution": e["institution"], "years": str(e["period"])}
                      for e in profile["education"]],
        "summary": profile["summary"],
    }


# ── steps ─────────────────────────────────────────────────────────────────────

async def step_ingest(people: list[dict], ledger: Ledger, stub_state: dict) -> int:
    from backend.api.routes.profile import _ingest_cv_full
    from backend.core.database import ENGINE
    from backend.services.confidence_matrix_service import get_entity_breakdown

    failures = 0
    for p in people:
        for variant, reverse in (("base", False), ("skillorder", True)):
            uid = user_id_for(p["id"], variant)
            if get_entity_breakdown(uid, ENGINE):
                print(f"{p['id']} {variant}: already ingested, skipped")
                continue
            stub_state["profile"] = p["profile"]
            ledger.calls.clear()
            text = cv_text(p["profile"], reverse_skills=reverse)
            resp = await _ingest_cv_full([text], ["cv.txt"], [], uid)
            n_exp = len(resp["cv_claims"].get("experiences", []))
            ok = resp["entities_ingested"] > 0 and n_exp > 0
            failures += not ok
            print(f"{p['id']} {variant}: entities={resp['entities_ingested']} experiences={n_exp} "
                  f"models={[c['model'] for c in ledger.calls]} {'ok' if ok else 'FAILED'}")
    return failures


async def step_score(people: list[dict], ledger: Ledger, repeats: int) -> int:
    from backend.core.database import ENGINE
    from backend.services.confidence_matrix_service import get_entity_breakdown
    from backend.services.feed_service import _build_profile_cv_proxy
    from backend.services.jd_structure_service import structure_jd
    from backend.services.master_profile_service import get_skill_proficiencies
    from backend.services.match_score_service import compute_match_score_async
    from backend.services.user_profile import get_profile

    structured: dict[str, str | None] = json.loads(STRUCTURED.read_text()) if STRUCTURED.exists() else {}
    failures = 0

    async def score_once(p, job, profile_variant, variant, title, company, text, repeat):
        nonlocal failures
        uid = user_id_for(p["id"], profile_variant)
        entities = list(get_entity_breakdown(uid, ENGINE))
        if not entities:
            raise SystemExit(f"{p['id']} {profile_variant}: not ingested. Run the ingest step first.")
        thin = len(text.strip()) < 300
        key = hashlib.sha256(text.encode()).hexdigest()
        ledger.calls.clear()
        if not thin and key not in structured:
            structured[key] = await structure_jd(text, user_id=uid, job_id=None)
            if not ledger.dry_run:
                STRUCTURED.write_text(json.dumps(structured, ensure_ascii=False))
        result = await compute_match_score_async(
            cv_data=_build_profile_cv_proxy(get_profile(uid), user_id=uid),
            jd_text=text,
            run_llm_validation=True,
            skill_proficiencies=get_skill_proficiencies(uid),
            user_id=uid,
            job_title=title,
            company_name=company,
            entity_scores=entities,
            job_id=None,                 # no high-match trigger, nothing is sent to anyone
            jd_structured=structured.get(key),
            job_location=job["location"],
        )
        # A job whose raw text is not thin but which comes back without the LLM
        # part: either a model call failed and the product fell back silently,
        # or the product's JD parser condensed the ad below its own 300-char
        # cutoff. Neither is a real score, so it is flagged, never averaged in.
        failed = (not thin) and (not result.llm_validated)
        failures += failed
        row = {"person": p["id"], "job": job["id"], "fit": job["fit"], "language": job["language"],
               "profile_variant": profile_variant, "variant": variant, "repeat": repeat,
               "total": round(float(result.total), 1), "local": round(float(result.local_score), 1),
               "semantic": round(float(result.semantic_score), 1),
               "management": round(float(result.management_score), 1),
               "llm_validated": bool(result.llm_validated), "jd_structured": bool(structured.get(key)),
               "models": [c["model"] for c in ledger.calls], "failed": failed, "dry_run": ledger.dry_run,
               "at": datetime.now(timezone.utc).isoformat()}
        if not ledger.dry_run:
            with SCORES.open("a") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(f"{row['person']} {row['job']} {profile_variant}/{variant} #{repeat}: total={row['total']} "
              f"sem={row['semantic']} mgmt={row['management']} local={row['local']}"
              f"{' NO-LLM-PART' if failed else ''}")

    for p in people:
        for job in p["jobs"]:
            for variant, title, company, text in job_variants(p, job):
                for r in range(1, (repeats if variant == "base" else 1) + 1):
                    await score_once(p, job, "base", variant, title, company, text, r)
            await score_once(p, job, "skillorder", "base", job["title"], job["company"], job["text"].strip(), 1)
    return failures


# ── entry point ───────────────────────────────────────────────────────────────

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def check_database_is_local() -> None:
    """The benchmark writes invented users. It must never reach Supabase."""
    from sqlalchemy.engine import make_url
    for var in ("DATABASE_URL_DEV", "DATABASE_URL_PROD"):
        if os.environ.get(var):
            raise SystemExit(f"{var} is set. Unset it before running the benchmark.")
    raw = os.environ.get("DATABASE_URL")
    if not raw:
        raise SystemExit("DATABASE_URL is not set. Point it at the local benchmark database, e.g. "
                         "postgresql://<you>@localhost:5432/jobapply_bench (see README.md).")
    url = make_url(raw)
    if url.host not in LOCAL_HOSTS or "bench" not in (url.database or ""):
        raise SystemExit(f"DATABASE_URL points at {url.host}/{url.database}. It must be a localhost "
                         "database whose name contains 'bench'.")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=["ingest", "score"])
    ap.add_argument("--people", default="", help="comma-separated ids, e.g. p01,p05 (default: all 12)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--env-file", help="file to read ANTHROPIC_API_KEY / GEMINI_API_KEY from, and nothing else")
    ap.add_argument("--cap", type=float, default=15.0, help="total spend in USD at which the run stops")
    ap.add_argument("--repeats", type=int, default=REPEATS)
    ap.add_argument("--price", action="append", default=[], metavar="MODEL=IN,OUT",
                    help="USD per million tokens for a model not in PRICES")
    args = ap.parse_args()

    for item in args.price:
        model, _, pair = item.partition("=")
        PRICES[model] = tuple(float(x) for x in pair.split(","))  # type: ignore[assignment]

    global DRY_RUN
    DRY_RUN = args.dry_run
    check_database_is_local()
    if args.dry_run:
        os.environ.pop("ANTHROPIC_API_KEY", None)
        os.environ.pop("GEMINI_API_KEY", None)
    elif args.env_file:
        for line in Path(args.env_file).read_text().splitlines():
            name, _, value = line.strip().partition("=")
            if name in ("ANTHROPIC_API_KEY", "GEMINI_API_KEY") and value:
                os.environ[name] = value.strip().strip('"').strip("'")

    sys.path.insert(0, str(ROOT))
    os.chdir(ROOT)
    from backend.core.database import ENGINE
    # Check again on the engine the product actually built: backend/.env, where
    # it exists, overrides the shell.
    if ENGINE.url.host not in LOCAL_HOSTS or "bench" not in (ENGINE.url.database or ""):
        raise SystemExit(f"the product resolved its database to {ENGINE.url!r}, which is not the local "
                         "benchmark database. Refusing to run.")

    from backend.config import ANTHROPIC_API_KEY, GEMINI_API_KEY
    if not args.dry_run and not ANTHROPIC_API_KEY:
        raise SystemExit("no ANTHROPIC_API_KEY. Pass --env-file, or use --dry-run.")
    print(f"database: {ENGINE.url}\nproviders: anthropic={'yes' if ANTHROPIC_API_KEY else 'no'} "
          f"gemini={'yes (answers first, as in production)' if GEMINI_API_KEY else 'no'}"
          f"{'  [dry run: no network calls]' if args.dry_run else ''}")

    RESULTS.mkdir(exist_ok=True)
    ledger = Ledger(args.cap, args.dry_run)
    stub_state: dict = {}
    install_ledger(ledger, stub_state)
    people = load_people(set(filter(None, args.people.split(","))) or None)

    if args.step == "ingest":
        failures = asyncio.run(step_ingest(people, ledger, stub_state))
    else:
        failures = asyncio.run(step_score(people, ledger, args.repeats))
    print(f"model calls by purpose: {ledger.by_purpose}")
    print(f"spent so far: ${ledger.spent:.2f} of ${args.cap:.2f}")
    if failures:
        raise SystemExit(f"{failures} step(s) need a look. See the lines marked FAILED or NO-LLM-PART.")


if __name__ == "__main__":
    main()
