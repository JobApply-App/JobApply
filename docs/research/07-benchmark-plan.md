# Stage 7: the benchmark (plan, not yet run)

Written 2026-11-13. Status: **plan approved by the founder on 2026-11-13. The test set is written (`benchmark/`). No model call has been made.**

## 1. What this stage is for

Stages 1-6 produced claims we could not test without running our own model. Stage 7 builds one fixed set of profiles and jobs and measures three things on it, so that every later change to scoring or CV writing is measured before and after.

| Question | Where it came from |
|---|---|
| A. Does the same profile and job get the same score every time, and does the score move for reasons that should not matter? | Stage 0 finding 8; Indeed 2026; gap map 6.5 |
| B. Does the score put jobs in the right order? | Stage 0 section 5.3: consistency is not validity |
| C. Do our generated CVs invent or change facts, and does the prompt without quotas do better? | Stage 6 section "Proposed measurement for stage 7" |

## 2. Founder decisions already made (2026-11-13)

- **Profiles are invented.** No real user data. Each profile is a full, realistic person written for this benchmark.
- **No recruiter is available.** The founder will judge if needed, and prefers an automated judge if that is more correct.
- **Cost must be estimated before anything runs.** See section 7.

## 3. Who decides what the right answer is

The founder asked whether a bot would judge fit better than he would. The research says no, for two reasons:

- An LLM judge can agree with itself 92-97% of the time and still agree with people only at 0.28-0.34 (Tiwari 2026, stage 0 section 5.3).
- Our scorer is an LLM. Checking it with another LLM measures whether two models agree, not whether either is right. Models also prefer text from their own family (stage 2, self-preference).

So the plan uses three sources of truth, in this order:

1. **Truth by construction (most of the benchmark, no judge needed).** Each job is written from a checklist of hard requirements, and each profile either meets every item, meets some, or misses a named hard requirement. The expected order (strong > partial > no fit) follows from the checklist, which is saved next to the pair so anyone can check it.
2. **Rules that have one right answer (no judge needed).** CLAUDE.md already fixes several outcomes: a thin job description must score at most about 30; a prior employer must floor two sub-scores; overqualification and a career pivot must not lower the score. These are pass or fail.
3. **The founder, once, for about 75 minutes.** He confirms or corrects the expected order for the 12 profiles (3 jobs each, about 45 minutes), and checks 30 verdicts of the fact checker in part C (about 30 minutes). This is the only human judgment in the plan. It is one person, so it is a sanity check on the construction, not a recruiter study.

A model is used as a checker only in part C, and only for a factual question: "is this CV claim supported by this profile text?" That is reading against a source, not a judgment of quality. Its accuracy is measured against the founder's 30 checks before its numbers are trusted.

## 4. The test set

**12 invented people**, each a complete profile in the shape the product stores (experience timeline, skills, education, military service where relevant, summary):

| # | Profile | Why it is in the set |
|---|---|---|
| 1 | Senior backend engineer, 9 years | plain hi-tech baseline |
| 2 | Junior data analyst, 1 year | entry level; stage 0 found Entry and Senior get confused |
| 3 | Product manager, ex-QA, 6 years | career pivot (principle 3) |
| 4 | VP operations, 18 years | overqualified for most jobs (principle 3) |
| 5 | Customer success manager, 5 years | "Manager" in a non-management title (stage 0 finding 4) |
| 6 | Call-centre team lead, 7 years | service work, few keywords |
| 7 | Graphic designer, 8 years | creative, portfolio-led |
| 8 | Postdoc in biology moving to industry | academia, long CV, few "business" words |
| 9 | Combat officer released a year ago, first civilian job | military service as the main experience |
| 10 | Marketing manager who worked at the target company 4 years ago | prior employer (principle 2) |
| 11 | Bookkeeper returning after a 5-year gap | gap, older experience |
| 12 | Full-stack developer, 4 years, English profile against Hebrew job ads | cross-language input |

Profiles 3, 6, 9 and 12 also get Hebrew CVs in part C.

**3 jobs per person = 36 pairs:** one strong fit, one partial fit, one clear non-fit (a named hard requirement is missing). Job texts are 550-1,600 characters (Hebrew ads are the shorter ones), all well above the product's 300-character thin-JD cutoff. 18 are Hebrew and 18 English, with invented companies.

**Variants made from those pairs.** The first, third, fourth and fifth are mechanical. The second needs writing and is done after the founder's ranking, since it does not affect it:
- thin job description (cut below 300 characters) for 6 pairs;
- the same job paraphrased, and the same job translated to the other language, for the 12 partial-fit jobs (one per person), where a score has the most room to move;
- the profile's skills list in a different order, for all 36;
- for profile 10: the partial-fit job with its company name changed to her past employer. The base job names a company she never worked at, so the prior-employer boost cannot disturb the base order;
- for profile 4: the same job asking for 5 years and for 15 years.

## 5. What is measured, and the pass line fixed in advance

Stage 0 showed that protocol choices alone moved a reported accuracy from 0.55 to 0.90. So the measures and pass lines are fixed here, before any run. All scores are reported to 1 decimal.

### Part A: stability of the score
| Measure | How | Pass line |
|---|---|---|
| A1. Run-to-run spread | each of the 36 pairs scored 5 times; spread = max minus min of the composite | spread ≤ 3.0 points on at least 90% of pairs; no pair above 8.0 |
| A2. Paraphrase | same job reworded, 12 jobs | composite moves ≤ 5.0 on 11 of 12 |
| A3. Language | same job in Hebrew and in English, 12 jobs | composite moves ≤ 5.0 on 11 of 12 |
| A4. Skill order | same profile, skills reordered | composite moves ≤ 3.0 on 90% of pairs |

### Part B: is the order right
| Measure | How | Pass line |
|---|---|---|
| B1. Order by construction | for each person: strong > partial > non-fit | all 3 in order for at least 10 of 12 people; strong above non-fit for all 12 |
| B2. Gap size | strong minus non-fit | at least 20.0 points on 10 of 12 |
| B3. Thin job description | 6 thin variants | every one ≤ 30.0, with both LLM sub-scores exactly 0.0 |
| B4. Prior employer | profile 10's partial-fit job | with the past employer's name: semantic ≥ 85.0 and management ≥ 80.0, and neither lower than with the base name |
| B5. Overqualified | profile 4 | score for the 5-year job is not lower than for the 15-year job by more than 3.0 |
| B6. Pivot | profile 3's strong-fit job | scores within 10.0 of profile 1's strong-fit score |
| B7. Founder's order | founder ranks the 3 jobs for each person without seeing scores | reported as agreement out of 12; no pass line, because it is one judge |

### Part C: honesty of the generated CV
Each of the 36 pairs gets a CV from today's prompt and from the same prompt with the quotas removed. 12 pairs are generated twice per prompt to see run-to-run change. Total 96 CVs, 32 of them in Hebrew.

Counted by code, no model:
- job-description terms that appear in the CV and nowhere in the profile;
- job titles that differ from the profile's titles;
- numbers in the CV that are not in the profile;
- banned-style words and long dashes;
- repeated sentence openings, line-length spread, share of lines with a number (the stage 6 parser, so our output is compared with the 1,291 real CVs).

Counted by the checker model, then spot-checked by the founder:
- claims with no support in the profile;
- qualifiers that were strengthened ("helped with" became "led").

There is no pass line for part C. It is a comparison of the two prompts and a baseline for later changes. The one hard rule: a CV with an invented employer, degree or title counts as a failure and is listed by name.

## 6. How it runs

1. **Write the set**: 12 profiles, 36 jobs, the requirement checklist for each pair, the variants. Saved under `docs/research/benchmark/`. No model call.
2. **Founder review** of the 12 expected orders (B7), before any score exists, so the scores cannot influence him.
3. **Pilot on 2 people** (about $3): confirms the runner works end to end and measures the real token use, so the cost in section 7 is corrected before the full run.
4. **Full run** of parts A and B, then part C.
5. **Checker run** on the 96 CVs; founder spot-checks 30 verdicts.
6. **Write-up** as `docs/research/07-benchmark-results.md`, with every failing pair listed.

Technical points that shape the runner:
- **Corrected 2026-11-13:** scoring is not database-free. It reads the person's Confidence Matrix, knockout preferences, skill depth and location from the database, and most of those reads fall back silently when the rows are missing. So every invented person is ingested through the product's own CV-upload path (`_ingest_cv_full`) before anything is scored. See section 10.
- The tailor reads the profile by `user_id` from the database (`TailorAgent`, `GroundingGate.for_user`). **We have one Supabase project and it is production.** The benchmark must not write invented users into it. The runner uses a local Postgres database, `jobapply_bench`, built with the same recipe CI uses (`benchmark/setup_local_db.sh`), and refuses to start on any database that is not on localhost. SQLite does not work: the profile code uses Postgres-only SQL.
- The runner calls the product's own code path (`call_llm` with the product's models and temperature), not a copy of the prompt. A copy would drift from what users get.
- Every model call logs its token use to a file, and the runner stops if spending passes the cap.
- Per CLAUDE.md "empty results are not evidence": the runner fails loudly if a CV comes back empty, a score call is skipped, or the grounding step raises. A missing value is never recorded as 0.

## 7. Cost estimate

Prices per million tokens, from the pricing table dated 2026-11-03: Claude Haiku 4.5 $1 in / $5 out (our scorer); Claude Sonnet 4.6 $3 / $15 (our tailor, grounding and Hebrew step); Claude Sonnet 5.5 $2 / $10 (proposed checker).

Sizes are estimated from the code, not measured: the scorer template is 5,681 characters and its reply is capped at 600 tokens; the tailor's system prompt is 44,463 characters (about 11,000-12,000 tokens) and its reply is capped at 6,000.

| Part | Calls | Per call | Estimate |
|---|---|---|---|
| Ingest | 24 uploads (12 people, twice: normal and skills reordered), each with a background title-terms call | about $0.06 | **$1-2** |
| A + B scoring | about 285 scores (36 x 5 repeats, 36 with skills reordered, about 32 variants). Each score is 2 model calls (JD parser on Sonnet, then the scorer on Haiku), plus one structuring call per ad and one culture call per company | about $0.025 | **$8-12** |
| C, English CVs | 64 | tailor + grounding + occasional refine = about $0.15 | **$8-12** |
| C, Hebrew CVs | 32 | the above plus the Hebrew step = about $0.23 | **$6-9** |
| C, checker | 96 | about 7,000 in, 2,500 out = $0.04 | **$3-5** |
| Pilot and re-runs after fixes | | | **$3-6** |
| **Total** | | | **about $29-46** |

- **Hard cap: $50**, approved by the founder. The runner stops there. The revised estimate leaves little room under it, so the pilot's measured numbers decide whether the full run fits.
- **These are Anthropic prices.** Production answers with Gemini first (section 10). A run that mirrors production needs Gemini's price entered before it starts; the runner refuses to guess it.
- The pilot replaces these estimates with measured numbers before the full run.
- After the first run, repeating **parts A and B only** after a scoring change costs about $10. Repeating everything costs about $40.
- Not included: the tokens Claude Code uses to write the profiles and the runner. That is part of the normal subscription, not the API key.
- The Batch API would halve the price, but it bypasses `call_llm`, so it would test a copy of the pipeline. Not used.

## 8. What this benchmark cannot show

- **It is not a study of recruiters.** Truth by construction shows the scorer orders clear cases correctly. It says nothing about close calls between two good candidates.
- **Invented profiles are tidier than real ones.** Real CVs have gaps, typos and odd formats. Results here are an upper bound on how the scorer behaves on real uploads.
- **12 people is a small set.** A pass line "10 of 12" cannot detect a problem that affects one profile type in ten.
- **One checker model, same vendor.** The founder's 30 spot-checks measure its error rate. A checker from another vendor would be more independent but needs a second API key.

## 9. Open questions for the founder

1. Approve the $50 cap and the pilot?
2. Approve the 12 profile types, or swap any for a type closer to the users we expect first?
3. The pass lines in section 5 are proposals. Any that should be stricter or looser before we see results?
4. **Which model should the benchmark measure?** (a) What production uses: Gemini first, Claude as fallback. This needs the Gemini key enabled locally and Gemini's price. (b) Claude only, which is what the local key file gives today but is not what users get. (c) Both, at roughly double the scoring cost. Recommendation: (a), because the point of the benchmark is what users see.

## 10. What building the runner showed (2026-11-13)

The runner (`benchmark/run_benchmark.py`) was run end to end in dry mode, where the model is replaced by a stub and nothing is spent. Getting it to run showed five things the plan had wrong or had not seen. None has been measured yet with a real model.

1. **Production does not answer with Claude first.** `llm_client.call_llm` sends every eligible call to `gemini-flash-latest` when `GEMINI_API_KEY` is set, and falls back to Anthropic only on failure. Production has that key. The local `backend/.env` has it commented out. So a local run with only the Anthropic key measures Claude Haiku and Sonnet, which is not what users get. **This needs a founder decision: see section 9, question 4.** The runner records which model answered every call, so the results always say which case was measured.
2. **Scoring depends on database state** (corrected in section 6). People are ingested through the real upload path into a local Postgres.
3. **Every score is at least two model calls, and the first one rewrites the job ad.** `compute_match_score_async` first sends the ad to `JDParserAgent` (Sonnet 4.6, on every call, not cached). The scorer then sees the parser's condensed text, not the ad. Two consequences to measure in the pilot:
   - Run-to-run change in the score can come from the parser as well as from the scorer.
   - The 300-character thin-JD cutoff is applied to the condensed text. A real but short ad could be condensed below 300 characters and then be scored as if it were empty (both LLM sub-scores 0.0, composite at most about 30). Our Hebrew ads are 550-800 characters, so they will show whether this happens. The runner marks every such case `NO-LLM-PART` and never averages it in.
4. **An upload also starts a background model call** (`title_search_terms`) that expands the person's titles for job search. It is part of the real cost of an upload.
5. **The stored profile is thinner than the CV.** The upload step keeps one or two sentences per role, not the bullets. For part C this means the fact check must compare the generated CV against what the product stored, and separately against the original CV text, because a detail can be lost at upload and then "invented" back.

**Not built yet:** the part C runner (CV generation and the fact checker), the 12 reworded and 12 translated job ads, and the script that turns `scores.jsonl` into the pass or fail table of section 5.
