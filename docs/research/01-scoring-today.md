# Research 01: how the match score and the CV's ATS score work today

Stage 1 of the scoring/CV research (2026-11-06). Question from the founder: junior Customer Success jobs never pass about 65, building a CV for a job shows a *lower* ATS score, and scores in general feel low. This stage only maps what the code does and measures it on production logs and local reproductions. No fixes yet.

## The two numbers the user sees

| Number | Where | Computed by | Uses AI |
|---|---|---|---|
| Match score (job card, feed) | `compute_match_score_async(run_llm_validation=True)` | blend of 5 parts (below) | yes |
| "ATS score for this CV" (CV preview) | the same function with `run_llm_validation=False`, so it is `_phase1()` only | keywords 40 + skills 35 + seniority 25 | no |

**Finding 1: two different formulas on the same 0-100 scale.** They are shown next to each other as if one could be compared with the other. A CV almost always "scores lower" than its job because it is measured by a narrower, purely lexical formula, not because the CV is worse. The 46.7% vs 12 incident (#135) was one symptom of this.

## The match score formula

```
llm_composite = 0.30 × local + 0.70 × (5/7 × semantic + 2/7 × management)
final         = 0.60 × llm_composite + 0.40 × structural  (+ culture ±5, + proximity 0..3; cap 40 on knockout)
structural    = 0.35 × hard_skills + 0.30 × depth + 0.20 × domain + 0.15 × impact
```

### Finding 2 (critical): `hard_skills` is 0 for every job, so the 40% term is broken

Production logs (`[match-dimensions]`, 2026-11-06), every line:

```
skills=0.0 depth=0.0|15.0 domain=50.0 impact=0|22|48|82 → structural=10.0–22.3
```

Reproduced locally (`score_hard_skills`): a profile containing **every** skill the job asks for (customer success, account management, Salesforce, HubSpot, onboarding, Jira, SaaS, communication, CRM) scores **0.0**.

**Cause:** the job's requirements are whole sentences ("1+ years of experience in Customer Success or Account Management"), and `_equivalent()` only matches when *all words of the sentence* are contained in a profile skill name. That is never true. Depth is computed over the matched skills, so it collapses to its 0/15 floor too.

**Effect:** the structural term sits at 10–22 for everyone. With it, a perfect AI assessment (semantic 100, management 100, local 100) reaches at most about **0.6 × 100 + 0.4 × 22 ≈ 69**. Real examples from the same log:

| Job | local | semantic | mgmt | structural | Final |
|---|---|---|---|---|---|
| Client Success Manager | 80.8 | 82 | 88 | 22.3 | **58.6** |
| Key Account Manager | 80.8 | 86 | 88 | ~30 | **62.8** |
| Product Manager | 94.0 | 58 | 68 | ~14.6 | 51.3 |

This alone explains "nothing passes ~65".

### Finding 3: the `local` term (30% of the AI part) is hard-coded for one person

`compute_local_proxy_score()` was written when the system served the founder alone:
- **Title tiers:** tier 1 is Product Manager titles (90); Customer Success / Account Manager are tier 3, "adjacent" (68) for *every* user, including a user whose target is Customer Success. A software engineer's own target titles fall to "no signal" (28).
- **Candidate seniority** is the constant `_CANDIDATE_SENIORITY_LEVEL = 4` ("manager") for everyone. The gap is `abs(job − 4)`, so a junior job (level 2) gets 40% of the seniority part regardless of who the user is. Because it is `abs()`, it also penalises a senior candidate for a junior job, which contradicts CLAUDE.md principle 3 (overqualification is never a penalty).
- `_phase1` gives +5 to any job whose title contains "product".

### Finding 4: seniority detection picks the highest word anywhere in the title

`_detect_seniority` returns the highest band whose word appears. "Junior Customer Success **Manager**" is level 4 (manager), and "Junior CS Specialist" is level 2. The same kind of role lands in different bands depending on wording.

### Finding 5: the AI's "management" dimension ignores what the job asks

The prompt defines `management_score` as leadership, people management and stakeholder management "regardless of whether the JD" asks for it. It is 2/7 of the AI part (20% of it). A junior candidate applying to a junior role loses points for a capability the job never asked for. Overqualification is protected in the prompt; underqualification for things *not required* is not.

### Finding 6: a failed AI call becomes a silent, neutral-looking score

`_llm_dual_score` returns `(60, 60)` on any API, parse or validation error. The user sees a normal-looking number with nothing saying the assessment did not run.

## The CV's ATS score (`_phase1`)

Reproduced on a near-perfect junior CS CV against a junior CS job: **71.8** (keywords 24/40, skills 22.8/35, seniority 25/25).

### Finding 7: keyword and skill extraction is fragile

- **Keywords:** only 5 were extracted from a full job description (b2b, jira, onboarding, crm, cs).
- **Keyword matching:** keywords are matched only inside experience bullets. "CRM" in the summary and the skills section counted as **missing**. The abbreviation "cs" is never matched to "Customer Success".
- **Skills:** "skills" are word windows such as `customer success or`, `crm tools such`.
- **Unused code:** a confidence-weighted skills path exists (`_confidence_weighted_skill_score`), but no caller turns it on.

## Confidence (trust) and the score

The founder's model is that the score reflects how sure the system is of the user's data. It should go down, with the reason shown, when new unverified information comes in (for example through Ariel).

### Finding 8: confidence barely reaches the match score

- **ATS engine (`score_competencies`):** confidence enters as `coverage = confidence/100 × (1.0 verified | 0.85 | 0.6 unverified)`.
  - In production `C` is 0.0–3.4 for everyone, so confidence values are very low and multiplied down again.
  - Since the structural dimensions replaced it in the final formula, that term no longer enters the score. It only feeds the knockout cap and the gap list in the UI.
- **Structural dimensions:** they use skill presence and years, never confidence.
- **Net effect:** today the user's confidence level has close to no effect on the match score. When it does show (gap lists), it reads as "missing" for skills the user has but has not verified.

Confidence already explains its own drops (the trust score, task from October). The match score does not, because it does not depend on confidence.

## What is sound

- `_seniority_fit` in the structural dimensions is correctly asymmetric (overqualification = 1.0).
- The prior-employer floor, the thin-JD rule (CLAUDE.md §4) and the knockout cap all behave as designed.
- The ATS engine's competency matcher (`_match_entity`) finds skills inside requirement sentences correctly. It is the confidence values it multiplies by that are low.

## Questions for the next stages

1. **Stage 2, the market:** what do real ATSs (Greenhouse, Lever, Workday, Comeet, iCIMS, Taleo) actually do? Keyword match, semantic, knock-out questions, ranking, or no score at all?
2. **Stage 3, recruiters:** what makes a recruiter shortlist a CV? Measured evidence only (eye-tracking, field studies), separated from vendor claims.
3. **Stage 4, competitors:** how do Jobscan, Teal, Rezi, Kickresume, Huntr and LinkedIn present and calculate "match", and what do users trust?
4. **Stage 5, confidence:** how a score should reflect uncertain data (score ranges and confidence bands instead of one number; how to explain a drop).
5. **Stage 6, CV generation:** what the best CVs do, from evidence, compared against our tailor prompt and our outputs.
6. **Stage 7, benchmark:** a fixed set of real jobs and profiles with expected judgments, so every change is measured before and after.
