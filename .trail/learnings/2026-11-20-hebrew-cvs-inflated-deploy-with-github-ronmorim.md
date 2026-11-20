---
title: "Hebrew CVs inflated 'deploy with GitHub Actions' to 'built CI/CD' in both the writer and the localiser"
author: RonMorim
date: 2026-11-20
branch: claude/he-cicd-inflation
cost: { minutes: 8, tokens: 114522 }
id: l-5d17d4c3
scope: repo
status: active
src: agent
---

## Decided
Stage 7 benchmark, p12 (Hebrew CVs): "Deploy with Docker and GitHub Actions to AWS" became "הקמת/הטמעת תהליכי CI/CD". A spy on `backend/services/cv_localize.localize_cv_to_hebrew` (record its input and output) showed both steps add it. The writer, writing Hebrew directly via `_output_language_directive`, wrote "בניתי תהליכי פריסה... CI/CD" in 1 of 4 rows. The localiser raised plain lines ("ניהול והפצת...", "תכננתי ופרסתי...") to "הקמת תהליכי CI/CD" in 2 of 3 accepted rows. Fix in both places: a "SAME CLAIM, SAME SIZE" rule in the localiser `_SYSTEM`, the summary rule no longer says "packed with the job's key terms", and the Hebrew directive in tailor.py says the HONESTY LINE holds in Hebrew, with the CI/CD example in Hebrew.
## Watch out
The localiser gets KEY_TERMS from JD keywords already present in the CV, so once the writer writes "CI/CD", "ci"/"cd" become keep-in-English terms and the localiser spreads them to the summary. The stored benchmark CVs hold only the post-localiser CV, so you need the spy to tell the two steps apart. The benchmark `--cap` is cumulative over results/ledger.jsonl, not per run.
