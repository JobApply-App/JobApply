# Research 05: showing a score when the data is uncertain, and explaining a drop

Stage 5 of the scoring/CV research (2026-11-12). The founder's model: the score should reflect how sure the system is of the user's data. When unverified information comes in (for example through Ariel), that should be visible, with its reason. Adopted earlier: label such data "stated, not yet verified" instead of penalising it.

## In plain words (added 2026-11-12, after the founder said the first version was unclear)

**The one question this stage answers:** when the system is not sure about something in the user's profile, what should the user see?

**A worked example.** Dana applies to a Customer Success role with five requirements:

| Requirement in the job | What we know about Dana |
|---|---|
| 2+ years in Customer Success | In her CV, with dates and employer. **Confirmed.** |
| Salesforce | She told Ariel yesterday she used it. Nothing else backs it yet. **Said, not confirmed.** |
| Onboarding new customers | Half a line in her CV. **Partly.** |
| SQL | She said she does not know it. **Missing.** |
| Fluent English | Nothing in the profile either way. **We don't know.** |

**How this looks today:** one number, for example "58". Dana cannot tell whether 58 is good, what pulled it down, or what to do. And when she told Ariel about Salesforce, the confidence number for that skill started low, so sharing more looked like a penalty.

**What the research points to instead:**
1. **A word, not a digit, for the overall result:** "Good match".
2. **The five lines above, shown as they are**, each with its state.
3. **A next step on the uncertain lines:** "Confirm Salesforce: one short question", "Tell us about your English".
4. **When something changes, one plain sentence saying why**, taken from what actually happened: "Salesforce was added from your chat with Ariel and is waiting for confirmation." Never a silent drop.

**Why each of those four, in one line each:**
1. People read a bare percentage in different ways (section 10), and the tools on the market cannot even agree on what "good" is (stage 4).
2. A few clear states work better for ordinary users than fine-grained numbers (section 3).
3. Telling Dana "we don't know" does not make her trust us less (section 2), and an AI model will not say "I don't know" unless it is built in (section 4).
4. A personal score shown with its main reasons improved real behaviour in a 400,000-person experiment (section 5), and reasons written freely by an AI model can be confidently wrong (section 5).

**What stays undecided:** the exact words, the number of states, and whether old confirmations should fade with time. Those are product decisions for after the research.

---

**Questions for this stage**
1. Does showing uncertainty cost trust?
2. In what form should uncertainty be shown: a number, a range, words, a state?
3. Can the model's own stated confidence be used?
4. How should a change in the score, especially a drop, be explained?
5. Does an honest low score discourage a job seeker?
6. What does "verified" buy in the market?

**Evidence weighting:** 2026 first; 2025 valid but older; earlier is background. Vendor material is for ideas only (founder, 2026-11-11).

**Marks:** **A** = relevant passages read in the primary source. **B** = abstract or a summary of the primary source. **C** = secondary.

**An honest limit up front:** almost none of this research was done on job seekers looking at a fit score. It comes from medicine, finance, general AI advice and public statistics. Applying it to our screen is inference. Section 8 says which parts I would rely on.

---

## 1. Where the product stands today (from the code)

- **Confidence per skill** is built from evidence rows: each has a source type, a base weight, a date, and an "AI-assisted" flag. The score is weight × source weight × AI penalty × **time decay** (a half-life per source type), capped per source. (`confidence_math.py`, `confidence_matrix_service.py`)
- **The UI already has states**, not only numbers: verified, orchestration-only, baseline, unverified; and a rule that unverified skills capped at 30 are shown as "Baseline Knowledge", "not a punishment score". (`TrustDashboard.tsx`)
- **An audit log per skill exists** (`confidence_audit_log_repository.py`).
- **What is missing** (stage 1, finding 8): this confidence barely reaches the match score, and the match score does not explain its own movements.
- **So the raw material for this stage's recommendations is mostly built.** The gap is in carrying it into the fit display.

---

## 2. Does showing uncertainty cost trust?

- **Meta-analysis, Royal Society Open Science, 2026** (28 studies) [B]: communicating uncertainty had **no effect on trust in the source** compared with not communicating it (Hedges' g = 0.00, 95% CI -0.05 to 0.06). Within it: **numeric uncertainty had no effect; verbal uncertainty slightly reduced trust** (two studies).
- van der Bles et al., PNAS 2020 [B, background]: a numeric range around a point estimate did not meaningfully reduce trust in the number or the source. Replicated during COVID-19.
- One dissenting study (Kreps & Kriner, 2020) found ranges can undermine trust in a policy context.
- **Reading:** showing that we are unsure does not, on average, make people trust us less. **Confidence: medium-high** for the general claim; the studies are about public statistics, not personal scores.

---

## 3. In what form?

### Words or numbers
- **Bodenberger et al., 2025, revised May 2026** (lab experiment) [A]: people valued an uncertain option **lower when its likelihood was given in words** ("likely") than as a number (75%), at medium and high likelihoods, **even when they translated the word correctly**. The vagueness itself changes behaviour.
- With the meta-analysis above: **vague hedging words are the worst form.** A stated category with a defined meaning, or a number, is better than "probably" or "seems".

### One overall uncertainty figure, or per item
- **Villavicencio et al., FAccT 2026** (N=192, medical questions with an LLM) [A]:
  - uncertainty shown **per word** *increased* agreement with the AI: more detail made people trust it more, not check it more;
  - uncertainty shown **per reasoning step** made people lean on the uncertainty cues and do less independent checking;
  - one figure for the whole answer, or per step, lowered people's confidence in their own answer;
  - "more detailed uncertainty information does not necessarily yield more cautious use".
- **Reyes et al., 2026** (N=37 lay, 10 experts; forecasts) [A]: a simple **present/absent** uncertainty marker was trusted more in the moment; a **continuous** shading "helped users recognize model limitations" and was judged more reliable overall. Some participants found the continuous version vague.
- **Reading:** finer is not automatically better. For a lay user, a small number of clearly named states beats a shaded scale. **Confidence: medium** (small studies, other domains).

### Ranges
- **arXiv 2604.09573, 2026** (within-subject user study) [A]: explanations of the form "if X were between a and b, the result would change" beat single-point "if X were a" explanations, feature-importance lists and no explanation, on both understanding and demonstrated trust. Only the interval form was significantly better than no explanation.
- **Reading:** when we tell a user what would change their fit, a range or a condition ("with verified experience in X this moves to a strong match") works better than a bare list of factors.

### What this means for a fit display
The evidence does not support a single percentage with a confidence percentage beside it. It supports:
1. **a small set of named states per requirement**: met and verified / stated, not yet verified / partly met / missing / unknown;
2. **an overall band**, not a digit;
3. where uncertainty is large, **say what it depends on** ("strong match if your Salesforce experience is confirmed").

This is the same shape stages 2 and 4 reached from the market side.

---

## 4. Can we use the model's own confidence?

- **Zhang et al., 2026** (30 models, 10 tasks) [A]: what a model *says* its confidence is often does not match its internal confidence; association is "weak on average"; instruction-tuned models report higher confidence with **worse calibration**; prompt wording mostly shifts the distribution. "A lossy channel": it can carry rank information, "but it does not make the scores calibrated".
- **Hsiao, 2026** (up to 18 models, three benchmarks) [A]: on **post-2025 top-tier proprietary models**, verbalized confidence is now a better soft signal for LLM judges than token probabilities, especially with an explicit overconfidence warning and a self-debate step. The author notes older advice was based on older models.
- **Demir, 2026** (legal citations) [B]: when **no option was correct, generative LLMs still picked one in 38-86% of cases**. Accepting an answer only when a second, calibrated model agreed halved wrong citations.
- **Di Scala et al., 2026** [B]: a system built to say "I don't know" when its sources are incomplete or irrelevant reduced over-agreement.
- **Reading:**
  - The two confidence papers do not contradict each other: newer top models give a usable *ranking* signal; none gives a *calibrated probability* one can print as "85% sure".
  - **Models do not abstain on their own.** "Unknown" has to be an explicit allowed answer per requirement, and the default when the profile has no evidence.
  - **Our stronger source of uncertainty is not the model at all.** It is the evidence record: who said it, when, verified or not. That is data we own and can show exactly.
- **Confidence: high** that we should not display model self-confidence as a number; **high** that "unknown" must be designed in.

---

## 5. Explaining a change in the score

### The closest real-world analogue: credit scores
- **Homonoff, O'Brien & Sussman** (NBER w26048, 2019; field experiment, 400,000+ student-loan borrowers) [A, background by date, strong by design]:
  - borrowers told that their personal FICO score was available, with **two reason codes** naming the main factors behind it;
  - late payments fell, scores rose (+0.7 points on average; **+8.2 points and 9 percentage points fewer late payments** among those induced to look), fewer became subprime;
  - effects "largely persist across the full two year study period";
  - people became **less likely to overestimate their own score**: the disclosure corrected overoptimism.
- **Reading:** a personal score with its top reasons changed real behaviour for the better and made self-assessment more accurate. This is the best evidence available for "show the score and the reason". It is not about hiring, and the authors could not separate the effect of the score from the reason codes.

### What makes an explanation work
- arXiv 2604.09573 (above): the **conditional, range-based** form was the only one that beat no explanation. A list of factor weights did not.
- **Aryal & Keane, 2026** [B]: people preferred "even if" explanations that also say *why* the outcome holds (what is carrying it).
- **Spillner et al., 2026** [A]: explanations' effect on trust depended on workflow and the user's domain knowledge; **stated trust and actual reliance are different things** and must be measured separately.
- **Van den Bulck et al., Nov 2026** (credit, education, employment datasets; five LLMs) [A]: when an LLM writes the explanation, it makes "plausible but false statements", and frames explanations more negatively for some groups once a protected attribute is known.
- **Reading for us:**
  1. A drop needs a **specific cause in the user's own data** ("you added 'Looker' through Ariel; it is not yet verified"), plus **what would reverse it**.
  2. The explanation of a score change should be **assembled from the audit log by code**, not written freely by the model. A model-written reason can be fluent and wrong.
  3. Keep to **one or two reasons**, as reason codes do.

### The founder's case: new unverified information lowers confidence
There are two different things here, and the evidence says to keep them apart:
- **The fit did not get worse.** The user told us more.
- **Our certainty about one item is low.**

Showing this as a lower number tells the user they were punished for sharing, which discourages the behaviour the product depends on. Showing it as a new item in the "stated, not yet verified" state, with a way to confirm it, is accurate and costs nothing. This is my inference from sections 3 and 6; no study tests this exact case.

---

## 6. Does an honest low score discourage people?

- **Job seekers are overoptimistic and do not correct themselves.** Mueller, Spinnewijn & Topa (NBER w25294) [A, background]: beliefs show "an optimistic bias that is larger for the long-term unemployed" and are "not revised downward when job seekers remain unemployed"; biased beliefs explain more than 10% of long-term unemployment in their model.
- **Feedback helps the underconfident and does not harm the overconfident.** Tekleselassie, Witte et al., IZA DP 17761, 2025 (field experiment, 2,537 job seekers, Addis Ababa) [B]: relative-ability feedback raised search effort by 0.2 SD among the initially **underconfident**; the **overconfident did not change behaviour**.
- **People steer away from crowded jobs when shown the crowd.** Fradkin, Bhole & Horton, Management Science 2026 (large field experiments on a job board) [B]: showing the number of prior applicants increased applications and directed them to postings with few applicants: "competition avoidance", not herding.
- **A fit signal redirects effort.** LinkedIn, Sept 2026 [A, vendor]: Job Match users "submit fewer applications to low-match roles and more to high-match roles".
- **Procedure matters to applicants for its own sake.** Wang, 2026 (1,919 US job seekers) [B]; Bhattacharya & Verbert, 2025 (20 job seekers, qualitative) [A]: explained recommendations were seen as more actionable, trustworthy and fair.
- **Reading:**
  - Honest information moves behaviour in sensible directions, and the evidence found shows no backfire among those told bad news; they mostly do not react.
  - The risk is not that a true low score harms. It is that a **wrong** low score does. Stage 1 showed ours is wrong and low for everyone. That is the damaging case, and it is a bug, not a presentation problem.
  - **Confidence: medium.** None of these studies shows a job seeker a personal fit score and tracks the outcome.

---

## 7. What "verified" buys

- LinkedIn states that verified members get about 60% more profile views [C: repeated from LinkedIn's help pages; no independent audit]. An independent January 2026 outreach test found acceptance tracked photo, headline and message quality more than the badge [C].
- Stage 3: 64% of US recruiters say it is getting harder to know what is real (LinkedIn, primary); hiring managers' top worry is authenticity (Greenhouse 2026, primary); two theory papers predict employers fall back on observable, checkable quality.
- **Reading:** demand for verified information is well supported. The size of the benefit of any one badge is not. For us "verified" is first an **internal** quality signal (what the CV may assert), and only possibly an external one.

---

## 8. Conclusions, with confidence

| # | Conclusion | Confidence | Rests on |
|---|---|---|---|
| 1 | Showing uncertainty does not reduce trust on average | Medium-high | 2026 meta-analysis (28 studies); PNAS 2020. Not tested on personal fit scores |
| 2 | Vague hedging words are the worst form; use defined states or numbers | Medium-high | Bodenberger 2026; meta-analysis subgroup |
| 3 | A few named states per requirement beat fine-grained uncertainty | Medium | Villavicencio 2026; Reyes 2026 (small, other domains) |
| 4 | Do not print the model's self-reported confidence as a number | High | Zhang 2026; Hsiao 2026 |
| 5 | "Unknown" must be an explicit state; models will not abstain unprompted | High | Demir 2026; Di Scala 2026; stage 2 judge-design review |
| 6 | Our best uncertainty signal is the evidence record, not the model | High (it is our own data) | Code review |
| 7 | A score with one or two specific reasons changes behaviour for the better and corrects overoptimism | Medium-high for the mechanism; low-medium for transfer to hiring | FICO field experiment |
| 8 | Explain change as a condition ("if X is confirmed, this becomes Y"), not as factor weights | Medium | One 2026 user study |
| 9 | Build the explanation from logged facts in code, not from free model text | Medium-high | Van den Bulck 2026; stage 3 fabrication evidence |
| 10 | New unverified information should appear as a new "stated, not yet verified" item, not as a lower score | Medium (inference; no direct study) | Sections 3, 5, 6 |
| 11 | Honest low signals do not backfire in the studies found; wrong low signals are the real harm | Medium | IZA 2025; Mueller et al.; Fradkin 2026 |

### What I could not find
- Any study that shows job seekers a personal fit score with uncertainty and measures what they do next.
- Any evidence on Hebrew-speaking or Israeli users' reading of bands or states.
- The full text of the 2026 meta-analysis and of the IZA and Management Science papers (hosts unreachable); those rest on abstracts.

### What only we can measure
Whether our users apply more to strong matches and less to weak ones after the display changes, and whether they verify more items when "stated, not yet verified" is shown with a one-step confirm. Both need outcome tracking in the product.

---

## 9. Inputs to the design decisions (not decisions)

1. **Fit shown as a band plus a per-requirement list** with five states: verified, stated (not yet verified), partly met, missing, unknown.
2. **Two separate things on screen:** how well you fit, and how much of that we could confirm. Never multiplied into one number.
3. **Unverified items count toward fit and are marked**, with a one-step way to confirm. They are not a deduction.
4. **Every change gets one or two reasons taken from the audit log**, each with what would reverse it. Written from templates, not by the model.
5. **"Unknown" is the default** when the profile holds no evidence for a requirement, and it is an invitation ("tell Ariel"), not a gap.
6. **Time decay already lowers confidence silently.** If it stays, it needs its own plain reason ("last confirmed 14 months ago"). Whether old evidence should decay at all is a product decision the founder has not yet made.
7. **Overoptimism is the norm among job seekers**, so an honest display will feel low to some users at first. The copy should state odds plainly and point to the lever (confirm, add evidence, or pick a better-matched role).

---

## 10. Second pass: more findings (2026-11-12)

### What does a percentage mean to the person reading it?
- **Gigerenzer et al., Risk Analysis 2005** (street survey in five cities) [B, background]: asked what "30% chance of rain tomorrow" means, most people outside New York gave a wrong reading: that it will rain 30% of the time, or over 30% of the area. The authors' conclusion: **always say what the percentage is a percentage of.** No recent replication found.
- **For us:** "65% match" has the same problem. 65% of what? Of the requirements? A 65% chance of an interview? Readers will each pick one. A band with the list of requirements underneath removes the question.

### Do explanations to job seekers work? Honest answer: they are liked, and their effect is small
- **Schellingerhout et al., 2023-2024** (job recommender explanations; co-design interviews, then 30 participants: candidates, recruiters, company representatives) [A, small samples]:
  - **candidates preferred brief, plain-text explanations** "that allow them to quickly judge potential matches"; hiring-side users were split between text and graphs;
  - **showing real explanations versus random, nonsensical ones barely changed participants' opinion of the system**; the upward trend with real explanations was not statistically significant;
  - participants "still largely rely on their knowledge and intuition, often disregarding the explanations".
- **Reading:** this tempers section 5. An explanation as decoration does little. What the FICO experiment and the range-explanation study support is narrower: **a reason the person can act on** ("confirm X", "this role asks for Y, which you do not have"). Keep explanations short, in text, and tied to a next step. **Confidence in "explanations raise trust" drops to low-medium; confidence in "one actionable reason helps" stays medium.**

### Feedback about the task helps; feedback about the person can hurt
- **Kluger & DeNisi, Psychological Bulletin 1996** (meta-analysis, 607 effect sizes) [B, background, still the standard reference; cited unchanged by a 2026 meta-analysis]: feedback improved performance on average, **but more than a third of feedback interventions made performance worse**. Their explanation: feedback works less well the more it directs attention to the self and away from the task.
- **For us:** "You are a weak candidate (42)" points at the person. "This role asks for SQL; your profile does not show it" points at the task. The same information, and the research predicts different effects. This supports per-requirement lines over a verdict on the person.

### Progress meters
- **Nunes & Dreze, Journal of Consumer Research 2006** [B, background]: people given a head start toward a goal (some progress already credited) were more likely to finish and finished faster. Later replications are mixed, and no published test of a profile-completeness meter was found.
- **For us:** weak support for showing "3 of 5 requirements confirmed" as progress the user can complete. Low confidence; an idea, not a finding.

### Letting the user correct the scorer
- **Chopra et al. (UC Berkeley), 2026**, "Attune" [B]: an interface where people steer an LLM scorer directly: correct a score, say "this should be between 4 and 6", add or remove a criterion. Built because users of LLM scorers need to adjust the logic, not only read the result.
- **For us:** Careerflow's "mark this requirement as irrelevant" (stage 4) is the crude version. A user who can say "this requirement does not apply to me" or "I do have this" gives us data and feels in control. Whether it should change the score is a separate decision.

### Updated confidence table
| Conclusion | Before | After this pass |
|---|---|---|
| Show a band and the list of requirements, not a bare percentage | Medium | **Medium-high** (reference-class problem added) |
| Explanations raise trust | Medium | **Low-medium** (real vs random explanations: no significant difference) |
| One short, actionable reason per change helps | Medium-high | **Medium** (kept, narrowed to actionable reasons) |
| Phrase feedback about the requirement, not the person | not stated | **Medium** (old but large meta-analysis) |
| A progress meter helps people confirm items | not stated | **Low** |
