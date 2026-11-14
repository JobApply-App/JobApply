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
