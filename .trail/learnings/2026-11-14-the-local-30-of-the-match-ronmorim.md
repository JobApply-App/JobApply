---
title: "The local 30% of the match score is fixed to product and customer-success titles and never reads the user's profile"
author: RonMorim
date: 2026-11-14
branch: claude/bugs-ui-improvements-31vblx
cost: { minutes: 4, tokens: 354395 }
id: l-ed98601d
scope: repo
status: active
src: agent
touches:
  - docs/research/07-benchmark-plan.md
  - docs/research/benchmark/README.md
  - docs/research/benchmark/run_benchmark.py
  - docs/research/benchmark/variants.yaml
  - backend/services/match_score_service.py
  - CLAUDE.md
---

## Decided
- Recorded as a finding in docs/research/07-benchmark-plan.md section 10, not fixed. The stage 7 baseline is to be measured first, so the fix can be measured before and after.

## Watch out
- backend/services/match_score_service.py `compute_local_proxy_score(job_title, jd_text)` takes no profile. It scores the job title against `_TITLE_TIER_1..3` (product manager 90, customer success and account manager 68, anything else 28) and compares seniority to `_CANDIDATE_SENIORITY_LEVEL = 4`. For any user who is not a product or customer-success manager it says nothing about fit.
- The tier lists are English only, so a Hebrew title always gets 28. The same job scored 44.8 with its Hebrew title and 80.8 translated to English, with the model stubbed out.
- CLAUDE.md's "thin JD caps at about 28-30 for an exact title match" holds only for product-manager titles, for the same reason.
