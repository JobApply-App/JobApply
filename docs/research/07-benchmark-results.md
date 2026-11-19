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

## Parts A and B: the model run (2026-11-14)

The first attempt stopped at the first call with nothing spent: the local Gemini key was rejected (HTTP 401) and the Anthropic account had no credit. The founder replaced the key and added credit, and the run then completed.

- 12 people ingested twice each (base and skills reordered) through the product's own upload path, into the local benchmark database. Nothing was written to production.
- 248 scores: 36 pairs x 5 runs, 36 with reordered skills, 12 paraphrases, 12 translations, 6 thin, 1 prior employer, 1 with the years lowered.
- 0 failed calls. 0 non-thin scores came back without the LLM part. Every one of the 668 model calls was answered by `gemini-flash-latest`; the Anthropic fallback was never used.
- Cost by the runner's ledger: **$1.17**, against the $15 cap. That figure uses the assumed list price for `gemini-flash-latest` ($0.75 / $3.75 per million tokens) and does not count thinking tokens, so the bill may differ somewhat.
- Tables below come from `benchmark/analyze.py`. Where a pair has 5 runs, its score is the median.

### Verdict by measure

| Measure | Result | Verdict |
|---|---|---|
| A1 run-to-run spread | 30 of 36 pairs within 3.0 (83%, line is 90%); largest 5.4 (line is 8.0) | FAIL |
| A2 paraphrase | 11 of 12 within 5.0 | PASS |
| A3 language | 11 of 12 within 5.0 | PASS |
| A4 skill order | 34 of 36 within 3.0 | PASS |
| B1 order | strong > partial > none for 12 of 12 people | PASS |
| B2 gap | strong minus none at least 20.0 for 12 of 12 (23.5 to 38.3) | PASS |
| B3 thin description | 6 of 6 at most 30.0 with both LLM sub-scores 0.0 | PASS |
| B4 prior employer | semantic 62.0 -> 87.0, management 75.0 -> 84.0, total 38.7 -> 50.1 | PASS |
| B5 overqualified | 58.4 for both the 15-year and the 5-year ad | PASS |
| B6 pivot | 62.4 against 58.9, difference 3.5 | PASS |
| B7 founder's order | not done yet | - |

The order is right for every person, on a set where the local score alone got 1 of 12. The model part of the score is doing the work.

### B1 and B2: order and gap

| Person | Strong | Partial | None | Order right | Strong above none | Gap strong-none |
|---|---|---|---|---|---|---|
| p01 | 58.9 | 41.1 | 33.4 | yes | yes | 25.5 |
| p02 | 53.5 | 42.9 | 15.2 | yes | yes | 38.3 |
| p03 | 62.4 | 47.8 | 29.9 | yes | yes | 32.5 |
| p04 | 58.4 | 31.6 | 29.8 | yes | yes | 28.6 |
| p05 | 58.4 | 48.7 | 25.4 | yes | yes | 33.0 |
| p06 | 56.2 | 42.4 | 25.0 | yes | yes | 31.2 |
| p07 | 55.1 | 31.9 | 20.2 | yes | yes | 34.9 |
| p08 | 53.0 | 34.3 | 22.9 | yes | yes | 30.1 |
| p09 | 55.4 | 39.2 | 28.1 | yes | yes | 27.3 |
| p10 | 49.8 | 38.7 | 26.3 | yes | yes | 23.5 |
| p11 | 54.8 | 32.3 | 20.0 | yes | yes | 34.8 |
| p12 | 53.5 | 31.9 | 17.2 | yes | yes | 36.3 |

B1: full order right for 12 of 12, strong above none for 12 of 12. PASS
B2: gap >= 20.0 for 12 of 12. PASS

### A1: where the score is not steady

The 6 pairs above the 3.0 line: p03-j3 (5.1), p07-j1 (5.4), p04-j2 (3.4), p11-j2 (3.3), p12-j3 (3.3), p11-j3 (3.6). Five of the six are partial fits. Strong fits are steady: all 12 have a spread of 1.8 or less. The movement comes from the semantic sub-score, which on a partial fit ranges by up to 14 points between runs of the same input (p07-j1: 28.0 to 42.0).

Full table: `benchmark/results/analysis.md` is not committed (the `results/` folder is ignored); rerun `analyze.py` to rebuild it.

### A3: a correction to part 0.2

Part 0.2 said measure A3 "already fails on the local score alone". In the live path it passes, 11 of 12. Part 0 computed the local score on the raw ad; the product computes it after its JD parser has rewritten the ad into condensed English, and there the Hebrew ads get a local score of 56.8, not 44.8. The title still matters (p03-j3 falls from 94.0 to 56.8 local when its title is in Hebrew, and that is the one job that fails, moving 8.8), but the damage is smaller than part 0 predicted. Part 0.1 stands: the local score still does not track fit.

### Finding 1: the hard-skills dimension scores 0.0 for every job

No strong fit scores above 62.4, although the model gives those same pairs a semantic score of 84.0 to 96.0. The range of the composite over all 36 jobs is 15.2 to 62.4:

- strong: 49.8 to 62.4, median 55.2
- partial: 31.6 to 48.7, median 39.0
- none: 15.2 to 33.4, median 25.2
- all 36: 15.2 to 62.4

The cause is in the deterministic 40% of the score. For p01's strong fit the product logged `skills=0.0 depth=15.0 domain=50.0 impact=44.0 -> structural=21.1`, and the final blend was `0.60 x 84.0 + 0.40 x 24.0 = 58.9`.

`score_hard_skills` in `backend/services/match_dimensions.py` compares each JD requirement with the profile's skill names: equal after normalising, equal through the taxonomy, or every word of the requirement contained in one skill name. The requirements it is given are whole sentences from the structuring pass ("Production experience in Python or Go"). The profile skills are single terms ("python", "go"). A sentence never equals a term and its words are never all inside one term, so nothing matches. The same happens when the structure is missing and the heuristic splitter is used, because it also returns the requirement lines.

`benchmark/skills_dimension_check.py` runs the product's own function, unchanged and with no model, on all 36 pairs, with the requirement lists the product produced during the run:

- strong: 0 of 12 above 0.0
- partial: 0 of 12 above 0.0
- none: 0 of 12 above 0.0

Each row had 4 to 7 must-haves and 10 to 20 profile skills, so the check did run; it matched 0 of them every time. p01 has Python, Go, PostgreSQL, Kafka and AWS in the profile and all five are named in the ad's requirements.

What it means for a user: 35% of the structural score is a constant 0.0, so a perfect candidate is shown a match of about 50 to 62 out of 100. The order survives because the constant is the same for every job. The number the user sees does not.

This was measured on invented profiles in a local database. It has not been checked against a real production profile. The mechanism does not depend on the profile, so the same result is expected there, but that is an expectation.

### Finding 2: the management sub-score follows the person, not the job

For a senior candidate the management score is high even for a job they do not fit: p01 gets 75.0 to 85.0 against a non-fit job, p03 75.0 to 82.0, p04 75.0 to 90.0, p09 75.0 to 85.0. For p02, p05, p07, p08, p11 and p12 it is 5.0 to 35.0 against a non-fit, and for the two team leads without a senior title (p06, p10) 60.0 to 75.0. It carries 0.20 of the LLM bucket, so it lifts every job of a senior person by a similar amount and is why p01's non-fit job (33.4) scores above p04's and p11's partial fits (31.6, 32.3). Within one person's feed this changes little. It would matter if scores were ever compared across people or against a fixed threshold.

### Finding 3: the local score has 5 values

After the parser, 28 of the 36 base jobs have a local score of exactly 56.8, whatever the job or the person. Part 0.1 stands in the live path.

## Parts A and B again, after #164 and #165 (2026-11-17)

Same 248 scores, with the skills fix (#164), years lines no longer counted as skills, and the local title score dropped from the full formula (#165). All on `gemini-flash-latest`, no failed calls, no 60/60 fallbacks.

| Measure | Before | After |
|---|---|---|
| A1 run-to-run spread within 3.0 | FAIL 30/36, largest 5.4 | FAIL 24/36, largest 11.1 |
| A2 paraphrase | PASS 11/12 | PASS 12/12 |
| A3 language | PASS 11/12 | FAIL 8/12 |
| A4 skill order | PASS 34/36 | FAIL 29/36 |
| B1 order strong > partial > none | PASS 12/12 | PASS 12/12 |
| B2 gap strong to none, at least 20 | PASS 12/12, gaps 23.5-38.3 | PASS 12/12, gaps 42.2-67.7 |
| B6 pivot (p03 vs p01, within 10) | PASS 3.5 | FAIL 14.9 |
| Composite range | 15.2-62.4 | 7.5-86.3 (strong 70.1-86.3, none 7.5-29.4) |

**Order got much better, stability got worse.** Both have one cause. The local score was a near-constant (56.8 for 28 of 36 jobs) carrying 18% of the total. It hid the order and it also damped the model's noise. Without it, the management sub-score carries 17% instead of 12%, and that sub-score swings between runs: 35-75 on p10-j3, 45-75 on p12-j2, 55-80 on p06-j1. Those are the pairs that fail A1.

**B6 shows the structural half is tool-literal.** p03 (product manager) and p01 (backend) get the same model scores on their strong jobs (95/92 and 96/95), but structural 34 against 66 before impact. p03's requirements are written as abilities ("owning a product area with an engineering squad", "product analytics, including funnels, cohorts, and A/B tests"); the profile says "a/b testing", and no line names a single tool. Matching by skill name works for jobs that list tools and fails for jobs that describe work. The local score used to give product-manager titles 94 and hid this.

**What would fix each:**
- Stability: the management sub-score's spread, measured here for the first time on its own. Options: score it twice and average, or give it less weight.
- Structural for ability-worded jobs: judge each requirement line as met, partly met or not met, with the model reading the profile, and let code compute coverage from those verdicts. The same verdicts would carry the years check (which roles count toward "8+ years of X").

## Part C: the generated CVs (2026-11-17, counts only)

96 CV requests: 48 with today's prompt, 48 with the quotas removed (`benchmark/cv_prompts.py`). All on `gemini-flash-latest`, about $1.6 by the ledger. Counts from `benchmark/count_cv.py`; the reading check of each claim is not done yet.

| | Today's prompt | Without quotas |
|---|---|---|
| CVs produced | 43 | 42 |
| Writer asked the user questions instead | 5 | 6 |
| Invalid JSON the product could not repair (all succeeded on retry) | 9 | 2 |
| CVs with an invented employer or degree (English CVs) | 5 | 4 |
| Job titles changed (English CVs) | 11 | 6 |
| Ad terms in the CV that are nowhere in the profile (median, max) | 0, 2 | 0, 2 |
| Numbers in the CV that are nowhere in the profile (median, max) | 0, 2 | 0, 2 |
| Banned words, long dashes | 0, 0 | 0, 0 |

**The hard-rule failures, by name.** Both happen with either prompt, so they are not caused by the quotas:
- **p11, a 5-year career break became a job.** The profile says "Career break (raising children), 2019-2024" and that she kept the family business's books voluntarily. Three CVs list "Bookkeeper, Family Small Business, 2019-2024" as employment.
- **p08, a role listed as a degree.** Six CVs add "Ph.D. Researcher" as a fourth education entry beside the real Ph.D. Immunology.

**Title changes.** Most are shortenings ("Teaching Assistant, Introduction to Statistics" to "Teaching Assistant, Statistics"; "(in-house)" dropped). Two kinds change the claim: "(part time)" removed from p11's current job (5 CVs, both prompts), and once, with today's prompt only, all three of p11's titles inflated ("Senior Bookkeeper & Team Mentor", "Bookkeeper & Client Account Manager", "Bookkeeper & Administrative Coordinator") for a job she does not fit.

**What the counts show.** On this set, the quotas do not make the model add job terms or numbers that the profile lacks: median 0 for both. They go with more changed titles (11 against 6) and more broken JSON (9 against 2). The two hard failures come from somewhere other than the quotas.

**Not covered yet.** Unsupported claims and strengthened wording ("helped with" becoming "led") need the reading check. Hebrew CVs are skipped by the string checks because names and degrees are translated.

## B7: the founder's blind ranking (2026-11-17)

The founder ranked each person's 3 jobs from `benchmark/ranking-sheet.md` without seeing scores. Letters mapped back with `ranking-key.json`.

| | Agreement |
|---|---|
| Founder and the designed order | 10/12 (same top job 10/12) |
| Founder and the system, after #164/#165 | 10/12 |
| Founder and the system, before | 10/12 |

The system agrees with the designed order for all 12, so the two disagreements are between the founder and the design, not the scorer:
- **p04** (VP Operations): founder puts the partial-fit COO job above the strong-fit site Operations Manager job. The COO job is a step up; the site job is a step down for her.
- **p07** (senior graphic designer): founder puts the partial-fit product designer job above the strong-fit senior graphic designer job, a move into a new field.

In both, the founder picked the job the person would likely want, not the one they fit best. The scorer measures fit and must not penalise overqualification or a pivot (CLAUDE.md principle 3), so it should not copy this order. Whether the feed should also show "a step up" or "a move" next to fit is a product question, not a scoring fix.

## Parts A and B after #167 to #170 (2026-11-18)

Same 248 scores after the four fixes the run above pointed to:
- #167, per-requirement verdicts: the scorer marks each requirement line met, partly met or not met, and hard skills count coverage from those verdicts.
- #168, domain from the profile.
- #169, roles read newest first.
- #170, depth from the verdicts with per-skill years capped at 3, and impact judged per job.

All on `gemini-flash-latest`, 0 failed calls.

| Measure | After #164/#165 | After #167-#170 |
|---|---|---|
| A1 run-to-run spread within 3.0 | FAIL 24/36, largest 11.1 | FAIL 21/36, largest 10.2 |
| A2 paraphrase | PASS 12/12 | PASS 11/12 |
| A3 language | FAIL 8/12 | FAIL 10/12 |
| A4 skill order | FAIL 29/36 | FAIL 27/36 |
| B1 order | PASS 12/12 | PASS 12/12 |
| B2 gap strong to none | PASS, 42.2-67.7 | PASS, 63.0-78.6 |
| B4 prior employer | not reported | PASS, total 58.7 -> 83.2 |
| B5 overqualified | not reported | PASS, 95.7 for both ads |
| B6 pivot (p03 vs p01) | FAIL 14.9 | PASS 3.7 |
| Strong fits | 70.1-86.3 | 89.1-96.8, median 92.9 |
| Partial fits | not reported | 40.1-65.5, median 52.8 |
| No fit | 7.5-29.4 | 15.1-33.3, median 23.8 |

**Measures that now pass:**
- **B6 passes.** The product manager whose requirements are written as abilities now gets a structural score close to the backend engineer's, whose requirements name tools. The verdicts closed the gap that was described above as "tool-literal".
- **Strong fits score like strong fits.** They show about 90 or more, against 50 to 62 in the first run.

**What still fails is stability, and it has three sources.** Where a pair moves between runs of the same input:

| Source | Example (5 runs) | Points of total it moves |
|---|---|---|
| Semantic sub-score (about 43% of the total) | p01-j1 45-58, p02-j3 45-58 | up to about 5.6 |
| Management sub-score (about 17%) | p10-j3 40-75, p04-j3 75-90 | up to about 6 |
| Verdicts flipping between "partly" and "not met", through the structural half | p08-j3: semantic fixed at 45.0, total still moves 4.9 | about 3 |

- **Which fits move.** Strong fits are steady: 11 of 12 within 3.0. Nearly all the movement is in partial and no-fit pairs, which is where a single judgement call can go either way.
- **What a user sees.** A score is computed once and stored, so the spread shows only when a job is scored again, for example after a profile change. A user does not see the score move between page loads.

**Options for stability, not yet chosen:**
1. Score twice and average the two answers. This roughly halves the spread, at twice the scoring cost.
2. Give the management sub-score less weight.
3. Leave it as it is.

The spread is estimated to drop with each option as follows. These are estimates from the five recorded runs, not measured:
- Two calls averaged would bring A1 to about 26 of 36.
- Three calls averaged would bring it to about 31 of 36.

**Research stages, where they stand:**
- **Stages 1 to 6 (desk research):** done.
- **Stage 7 (benchmark):**
  - Part 0, A, B and B7 are measured.
  - Part C: counts and the model's reading check are done (2026-11-19, below). The founder's spot check is open.
- **Open:**
  - the stability choice above (chosen 2026-11-19, see the next section)
  - the two CV hard-rule failures in part C: fixed 2026-11-19, below

## Stability: a fourth source, and the choice (2026-11-19)

**A fourth source was found.** The JD parser (`JDParserAgent.parse_and_format_jd`) is a model call that rewrites the ad before the scorer sees it. It ran on every scoring with no cache and no temperature set. So each repeat sent the scorer a differently worded ad.

**What was done (#171):**
- The parser now runs at temperature 0, and the first valid parse of an ad is kept.
- The runner now sets `MATCH_SCORE_REUSE=0`, so every repeat still reaches the scorer.

**Same 248 scores, run again:**

| Measure | After #167-#170 | Parser cached |
|---|---|---|
| A1 run-to-run spread within 3.0 | FAIL 21/36, largest 10.2 | FAIL 18/36, largest 8.2 |
| A2 paraphrase | PASS 11/12 | FAIL 10/12 |
| A3 language | FAIL 10/12 | FAIL 8/12 |
| A4 skill order | FAIL 27/36 | FAIL 30/36 |
| B1, B2, B4, B5, B6 | PASS | PASS |
| Partial fits | 40.1-65.5, median 52.8 | 35.5-65.5, median 53.0 |
| No fit | 15.1-33.3, median 23.8 | 13.6-34.7, median 23.6 |

Cost: $1.07, all on `gemini-flash-latest`, 0 failed calls.

**What it shows:**
- **The parse is now steady.** The 5 repeats of a pair send the scorer the same prompt: 242 recorded scorings fall on 98 prompt hashes.
- **The scorer itself is not steady.** On that identical prompt, the semantic and management sub-scores still move by up to 10 points. The parser was only a small part of A1's spread, and the A1 count moved within noise.

**The choice (the founder's call, 2026-11-18): keep the first score, record every scoring.**
- **Same input, same score.** The scorer's first valid answer is reused, per user, for an identical prompt. A changed CV, profile or ad makes a new prompt, and so a new score. This costs no extra model calls; it saves them.
- **Every scoring is history.** Each scoring is a row in `shadow_match_scores`. A row records:
  - the job
  - the sub-scores and dimensions
  - the prompt hash and the full answer
  - the model
  - whether the answer was reused

  This history is how score movement is measured from now on.
- **What this does not fix.** It does not make the model's first judgement more accurate. It only stops that judgement changing when nothing changed. A2, A3 and A4 change the input, so they still measure how much the wording moves the score.

Not measured: a full run with reuse on. Its repeat spread is 0 by construction. The reuse path is covered by unit tests (`backend/tests/test_same_input_same_score.py`).

## Part C: the hard rules fixed, and the reading check (2026-11-19)

### The two hard-rule failures had three causes, two of them in our code

| Failure | Where it really came from | Fix |
|---|---|---|
| p08: "Ph.D. Researcher" listed as a degree | `cv_entry_kind.DEGREE` read any title starting "Ph.D." as a degree, so the job was moved to education when the CV was read in, losing its bullets | A degree word followed by a job noun (researcher, student, assistant, ...) is a job |
| p08: the same job also missing from experience | `user_profile._overlaps` counted two roles at one employer as duplicates when they shared only a boundary year (Ph.D. 2015-2021, Postdoc 2021-present). The earlier role never reached the profile or the scorer, against principle 1 | Sharing only the boundary year is the next role, not the same role. This is applied when the profile is read, so stored profiles are repaired too |
| p11: a career break became "Bookkeeper, Family Small Business" | The CV extraction prompt asks for an "exact company name" for every role and said nothing about breaks. The stored profile already read "Bookkeeper (voluntary), Family's small business", and the writer repeated it | Rules in both prompts (extraction and writer). A mechanical guard after writing drops a CV entry that gives an employer to the years of a profile break, matched by years so it also works on Hebrew CVs |

After the fix, p08 and p11 were ingested again and their CVs regenerated (same inputs as on 2026-11-17):
- **p08:** 4 of 4 CVs list Ph.D. Researcher under experience. Education holds only the 3 real degrees.
- **p11:** the stored profile keeps "Career break (raising children)" with no employer. None of the 7 CVs gives the break an employer.
- **Still open for p11:** 3 of the 7 drop "(part time)" from her current title. The reading check below counts this as strengthening.

Tests: `backend/tests/test_cv_hard_rules.py`.

### The reading check

The checker model read 84 CVs against the person's profile and listed every unsupported and every strengthened claim. These are 82 CVs from the 2026-11-17 run, with p08's and p11's replaced by the regenerated ones; the checker's JSON broke twice, so 82 are counted. The run used `run_benchmark.py check` on `gemini-flash-latest` and cost $0.25 by the ledger.

| | Today's prompt | Without quotas |
|---|---|---|
| CVs checked | 41 | 41 |
| Unsupported claims per CV (median, max) | 5, 9 | 4, 7 |
| CVs with no unsupported claim | 0 | 2 |
| Strengthened claims per CV (median, max) | 1, 4 | 1, 4 |
| CVs with no strengthened claim | 11 | 10 |

**What kind of claims.** Of the 334 unsupported claims:
- about 260 are added detail on a real activity, such as a frequency ("weekly"), an adjective ("strategic customers"), a context ("under tight deadlines"), or an ad's term attached to work the profile describes in other words;
- about 30 attach a tool from the skills list to a job the profile does not tie it to;
- about 20 are numbers;
- about 25 are titles or headline claims, such as "Contact Centre Manager" for a team lead, or "Marketplace" in a target title.

Of the 93 strengthened claims, about a third are job titles ("Company Clerk" became "HR coordinator", "(part time)" dropped).

**What it shows, with one caveat.** Almost every CV says more than the profile does, with either prompt. The quotas add about one unsupported claim per CV. Partial fits get the most (median 6), where the writer stretches furthest toward the ad. These are the checker's judgements, and part of them is the checker being strict. They are not yet confirmed.

**The founder's spot check.** `benchmark/claims-sheet.md` holds 20 claims sampled at random, 10 of each kind; `claims-key.json` maps each to its CV. The founder's verdicts give the checker's precision, and the counts above should be read through it.

**Open:**
- the founder's spot check
- job titles: the writer still edits titles, and a third of strengthened claims are titles. Taking titles, employers and dates from the profile as they are, and leaving only bullets and the summary to the writer, would close this class mechanically
- the stored profiles of users whose CV was read in under the old degree rule: a role that starts with a degree word may sit in their education. The read-time fix above does not move it back
