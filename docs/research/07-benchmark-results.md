# Stage 7: benchmark results

## Part 0: checks that need no model (2026-11-14)

Run with `python docs/research/benchmark/free_checks.py`. It calls the product's own functions on the 36 job ads and their variants. No model call, no database, no cost. Every number below is what the product computes today.

### 0.1 The local score does not track fit

`compute_local_proxy_score(job_title, jd_text)` is 30% of the LLM composite, which is 60% of the final score. It never reads the user's profile (plan, section 10, finding 6).

| Person | Their job title | Strong fit | Partial fit | No fit | Order right? |
|---|---|---|---|---|---|
| p01 | Senior Backend Engineer | 56.8 | 32.8 | 56.8 | no |
| p02 | Junior Data Analyst | 44.8 | 73.0 | 20.8 | no |
| p03 | Product Manager | 94.0 | 82.0 | 56.8 | yes |
| p04 | VP Operations | 56.8 | 44.8 | 44.8 | no |
| p05 | Customer Success Manager | 44.8 | 44.8 | 44.8 | no |
| p06 | Call Centre Team Lead | 44.8 | 44.8 | 44.8 | no |
| p07 | Senior Graphic Designer | 44.8 | 44.8 | 44.8 | no |
| p08 | Postdoctoral Researcher | 44.8 | 56.8 | 56.8 | no |
| p09 | Operations Coordinator | 44.8 | 44.8 | 44.8 | no |
| p10 | Marketing Manager | 20.8 | 20.8 | 44.8 | no |
| p11 | Bookkeeper | 44.8 | 44.8 | 44.8 | no |
| p12 | Full-Stack Developer | 44.8 | 44.8 | 44.8 | no |

- The local score puts the three jobs in the right order for **1 of 12** people: the product manager, the one profile the title list was written for.
- The strong-fit job has the single highest local score for 2 of 12 people.
- For the marketing manager (p10) the job she cannot do, DevOps Engineer, scores highest: 44.8, against 20.8 for both the marketing and the e-commerce jobs. For the junior analyst (p02) the partial fit beats the strong fit by 28.2 points because its title contains the word "Product".
- The 36 jobs produce only 7 distinct local scores.

### 0.2 Every Hebrew job title gets the same local score

All 18 Hebrew-titled jobs score exactly **44.8**, whatever the job is: registered nurse, backend developer, bookkeeper, lawyer. The title lists are English only, so a Hebrew title never matches a tier.

The same job with its title in the other language:

| Job | Original title | Local | Translated title | Local | Change |
|---|---|---|---|---|---|
| p05-j1 | מנהל/ת צוות הצלחת לקוחות | 44.8 | Customer Success Team Manager | 80.8 | +36.0 |
| p07-j1 | מעצב/ת מוצר UX/UI בכיר/ה | 44.8 | Senior Product Designer (UX/UI) | 73.0 | +28.2 |
| p06-j2 | מנהל/ת מוקד שירות לקוחות | 44.8 | Customer Service Centre Manager | 56.8 | +12.0 |
| p09-j2 | מנהל/ת תפעול אזורי | 44.8 | Regional Operations Manager | 56.8 | +12.0 |
| p03-j3 | Senior Product Manager, Marketplace Growth | 82.0 | מנהל/ת מוצר בכיר/ה, צמיחת המרקטפלייס | 44.8 | -37.2 |
| p02-j3 | Data Analyst, Product Analytics | 73.0 | אנליסט/ית נתונים, אנליטיקת מוצר | 44.8 | -28.2 |
| p08-j3 | Senior Bioinformatics Scientist | 56.8 | מדען/ית ביואינפורמטיקה בכיר/ה | 44.8 | -12.0 |

The other 5 of the 12 translated jobs do not change: their titles match no tier in either language.

A product manager looking at a Hebrew "מנהל/ת מוצר" ad loses 37.2 local points against the same ad in English. Through the weights (0.30 x 0.60) that is about 6.7 points of the final score before any other effect. **Measure A3 (language) already fails on the local score alone**: 7 of 12 jobs move by more than the 5.0 the pass line allows, with no model involved.

### 0.3 Thin job descriptions: the rule holds, the "28-30" figure does not

With a description under 300 characters both LLM sub-scores are 0.0 and the composite is 0.30 x local, as CLAUDE.md principle 4 requires. Measure B3 (at most 30.0) passes on all 6.

| Thin job | Local | Composite |
|---|---|---|
| Product Manager (p03) | 94.0 | 28.2 |
| Senior Backend Engineer (p01) | 56.8 | 17.0 |
| the 4 Hebrew titles | 44.8 | 13.4 |

CLAUDE.md says this "caps un-hydrated jobs at about 28-30 points for an exact title match". That is true only for product-manager titles. For everyone else, an exact title match with a thin description scores 13.4 to 17.0.

### 0.4 Prior-employer detection works

`_find_prior_employer` finds "Verdane Outdoor" for profile 10 when the job names that company, and nothing when it names another. Over the other 67 job variants there are 0 false detections. The word-boundary rule of principle 2 holds on this set. Whether the model then honours the score floors needs a model run.

## Parts A, B and C: not run

The pilot was started on 2026-11-14 and stopped at the first model call with nothing spent:
- The Gemini key in the local `backend/.env` was rejected (HTTP 401). It does not have the usual `AIza...` shape of a Gemini API key.
- The fallback then failed too: the Anthropic account behind the local key has no credit ("credit balance is too low").

See the plan, section 11, for what is needed to run them at no cost.
