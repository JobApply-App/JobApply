# Stage 7 benchmark

Plan and findings: `../07-benchmark-plan.md`. Everything here is invented: the people, the companies and the job ads.

| Path | What it is |
|---|---|
| `people/*.yaml` | 12 people. Each has a full profile, 3 job ads (strong, partial and no fit) and the requirement checklist that fixes the expected order. |
| `build_sheet.py` | Validates the people files and builds `ranking-sheet.md` for the founder's blind ranking. `ranking-key.json` maps the sheet's letters back to job ids. |
| `setup_local_db.sh` | Creates the local Postgres database `jobapply_bench` with the recipe CI uses. |
| `variants.yaml` | A reworded and a translated version of each of the 12 partial-fit job ads. |
| `run_benchmark.py` | Ingests the people through the product's CV-upload path and scores their jobs the way the feed does. Writes `results/`. |

## Running

From the repo root, with the project's virtualenv active:

```bash
sh docs/research/benchmark/setup_local_db.sh
export DATABASE_URL=postgresql://$(whoami)@localhost:5432/jobapply_bench
python docs/research/benchmark/run_benchmark.py ingest --dry-run --people p01,p05
python docs/research/benchmark/run_benchmark.py score  --dry-run --people p01,p05
```

`--dry-run` replaces the model with a stub and spends nothing. A real run drops `--dry-run` and adds `--env-file <path to backend/.env>`, from which only the model API keys are read.

The runner refuses to start unless `DATABASE_URL` is a localhost database whose name contains `bench`. Run it from a checkout that has no `backend/.env`, or one whose `backend/.env` points at that local database: where the file exists it overrides the shell.

## Part C: the generated CVs
```bash
python docs/research/benchmark/run_benchmark.py cv --env-file <path to backend/.env>
python docs/research/benchmark/count_cv.py
```
- `cv` writes one CV per pair with today's prompt and one with the quotas removed (`cv_prompts.py`), and the strong-fit pair of each person twice per prompt: 96 CVs, the 32 of p03, p06, p09 and p12 in Hebrew. It goes through `TailorAgent.tailor`, the call the CV route makes. The route's refine pass and PDF building are not run.
- `cv_prompts.py` stops if the product prompt no longer contains a passage it replaces, so an edited prompt can't be tested by mistake.
- Before writing, each invented user's LinkedIn question is skipped the way a user skips it in the app. Without that, every CV stops at that question before any model call.
- Results go to `results/cvs.jsonl`. A row that ended in an error is tried again on the next run.
- `count_cv.py` does the counts that need no model, against each person's YAML: invented employers and degrees (listed by name), changed titles, ad terms and numbers not in the profile, banned words, long dashes, repeated openings.
- The claims check (is each CV line supported by the profile?) is done by reading, inside the Claude Code session, per plan section 11. It is not scripted.
- Measured on 2026-11-17: about $0.0125 per CV on `gemini-flash-latest`, so roughly $1.5 for all 96.

## After a run
- `analyze.py` turns `results/scores.jsonl` into the pass/fail table of plan section 5 (parts A and B).
- `skills_dimension_check.py` runs the product's hard-skills dimension on the 36 base pairs, with no model. Needs `DATABASE_URL` pointing at the local benchmark database and a finished score step.
