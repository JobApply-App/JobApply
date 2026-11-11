# Research 00: what we know, how well, and what is still missing

Consolidation pass over stages 1-3 (2026-11-10), before stage 3 continues. For each finding: how solid it is, what the pass added or corrected, and what is still open.

**Evidence weighting:** 2026 carries the most weight; 2025 is valid but older; earlier is background.

**Solidity marks:**
- **A**: read in the primary source, or measured by us.
- **B**: primary source seen only in part, or a vendor's own study.
- **C**: secondary reports only.

---

## 1. Corrections to earlier notes

| What I wrote | What the source says | Effect |
|---|---|---|
| "Gemini 2.0 Flash picks the wrong candidate about 1 time in 4 (validity 0.73)" | 0.73 is one cell: the hardest pairs (one differing qualification), CVs written by Claude. On average Gemini 2.0 Flash is **above 0.90**; on real-world CVs **0.90 vs Claude Sonnet 4's 0.92**. And **84-93% of the errors are abstentions**, not wrong picks. (Castleman et al., Feb 2026, tables 1-3) | The gap between models is **real on close calls, small on clear ones**. The case for changing the scoring model is weaker than I implied. |
| "LLMs prefer CVs written by the same model" (read as applying to any model) | The study tested GPT-4o family, LLaMA, Mistral, Qwen and DeepSeek. **Claude and Gemini were not tested.** Preference between different LLMs is mixed; the consistent effect is **LLM-written over human-written**. (Xu et al., rev. Jun 2026) | No basis for choosing a CV-writing model from this study. |
| Kickresume 2026: "tailored AI CV 18% vs generic 10%" | The same test had **human-written CVs: 31% (single-column) and 12% (two-column)**. The single-column human CV went out first, to the best-matched jobs, so its lead is confounded. **30 of 36 positive responses came from well-matched roles.** (Kickresume, July 2026, 204 applications) | Fit decided most outcomes. Tailoring helped within AI CVs. "A person supplies the substance" is the vendor's own reading. |
| "Hebrew CVs uploaded to *us* may be read reversed" | Measured: our ingestion (pdfplumber + our RTL fixer) reads both our Hebrew PDF and the Word control **in correct word order**. Small defects only: punctuation next to mixed Hebrew/English runs ("ב.B2B SaaS-", "מ9%-"). | Worry closed. Minor defect logged. |

---

## 2. New findings from this pass (all 2026 unless marked)

### The CV is losing information value, and the market is moving to verified evidence
- **Ashlagi, Johari, Kleinberg & Murthy, Sept 2026** (theory, arXiv 2609.30058) [A]:
  - as AI makes application materials less informative, a rational firm "relies more heavily on coarse observables such as prior experience";
  - **the most harmed group is "inexperienced-compatible" applicants**: good fit, little experience;
  - firms respond with **multistage hiring**: a cheap intermediate assessment (skill test, work sample) before full screening.
- **Aka, Palikot et al., Stanford, v2 Aug 2026** (two field experiments, arXiv 2507.08029) [A]:
  - candidates shortlisted with a structured AI-interview report passed the final human interview **17.5-20 percentage points more often** than those shortlisted from CVs alone;
  - "the gains concentrate where resumes are least informative": adding the report raised predictive accuracy (AUC) by **0.18 for junior candidates vs 0.08 for others**;
  - 75% of invited candidates did not complete the AI interview.
- **Jabarian & Henkel, v2 Sept 2026** (70,000 applicants) [A]: +12% offers, +18% starts and one-month retention with structured AI interviews.
- **LinkedIn, Sept 29 2026** (primary press release; Censuswide survey of 500 US recruiters, Aug 2026) [A]:
  - "global hiring down 30% and applications per applicant up 30% compared to pre-pandemic levels";
  - **64% of US talent professionals say "it's becoming harder to know who to trust and what's real"**;
  - Hiring Assistant 2 combines verification status, ATS data, pre-screening answers and work experience; 20,000+ companies use LinkedIn's agentic hiring products;
  - "Applicants rated as top matches are 2.6x more likely to be interviewed than those rated as lower matches" [vendor claim];
  - **LinkedIn "Job Match"** tells Premium members their fit before applying; used 1M+ times a week; users "submit fewer applications to low-match roles and more to high-match roles".
- **Greenhouse 2026** [B/C]: recruiters handle **411% more applications than in 2022** (Benchmark Report, via secondary); 56% of recruiters say AI makes it easier to cheat or fake credentials; 46% of job seekers say their trust in hiring declined in the past year (Greenhouse blog, primary).

**Why this matters for JobApply**
- **The junior Customer Success user is exactly the "inexperienced-compatible" applicant** the theory says is hurt most, and the group for whom CVs carry the least information (Stanford). The founder's complaint about junior CS scores sits on the market's weakest spot.
- **The durable value is evidence, not prose.** Ariel's structured probing produces the kind of information the 2026 experiments show employers reward.
- **An honest fit signal has measured value** (LinkedIn Job Match; Kickresume: 5 of 6 responses from well-matched roles). Steering users toward jobs they fit is worth more than polishing CVs for jobs they don't.

### Manipulating AI screeners
- **Zhang et al. with hireEZ, May 2026** (about 200,000 real CVs, arXiv 2605.28999) [A]:
  - **about 1% of real CVs contain hidden prompt injections**, rising over the past one to two years;
  - 90%+ are hidden keywords or text (white text, 1-pt font), not explicit instructions;
  - detectors for this now exist.
- **Baxi, Xu et al., June 2026** (arXiv 2606.27287) [A]: "subtle self-promotional text that introduces no new qualifications" lifts rankings when few candidates do it, and **the effect collapses as more candidates do it**. It can let a weaker candidate outrank a stronger one near the threshold.
- **Mao et al., 2026** (arXiv 2604.09620) [B]: LLM screeners favour candidates who express positive attitudes toward AI.
- **For us:** never hidden text (we already guard it); self-promotional filler is both detectable and a wasting asset.

### How to build the judge (LLM-as-a-judge evidence)
- **The systematized review, Sept 2026** [A]: "Case judgment: each criterion is marked **supported, contradicted, or unknown with cited evidence**"; "recommend when evidence and separation are sufficient; otherwise **request a fact, show a tie, or defer**."
- **Binary questions:** BinEval, 2026 (arXiv 2606.27226) [B]: decomposing into atomic yes/no questions matches or beats holistic judges and "avoids the ceiling effects common in prior LLM judges". ResearchRubrics, 2025 [C]: moving from three levels to two raised agreement by about 20 points.
- **Numeric scales, mixed evidence:**
  - Vaugrante & Hagendorff, Oct 2026 (arXiv 2610.05094) [A]: on *simple* rating tasks, finer scales (0-1, 0-100) were slightly **better** than 1-7; changing the scale alone shifted measured bias by up to 0.93 points; **model identity is the largest source of variance**; they recommend aggregating several models.
  - Li et al., Jan 2026 (arXiv 2601.03444) [B]: human-LLM agreement was highest on a **0-5** scale.
  - "Rating Roulette", 2025 [B]: the same judge gives different scores across runs.
- **Honest reading:** the evidence does **not** say "0-100 is always worse". It says:
  1. per-criterion yes/no/unknown with evidence is the most defensible unit for *case judgment*;
  2. a holistic number depends heavily on the model and the scale;
  3. when a scale is shown, coarse (0-5 or bands) agrees best with people.

### Parsing
- **Root cause of our Hebrew word-order problem, now understood** [A, measured]:
  - Chromium's PDF writer (Skia) writes each line's words **left to right in visual order**, with each word's letters in logical order.
  - LibreOffice writes the line in logical order.
  - Extractors that follow the file's order (**PyMuPDF, pypdf**) therefore return our Hebrew lines with the words reversed.
  - Extractors that re-order by layout (**Poppler**) read it correctly.
  - pdfminer returns fully visual text for both files; a standard bidi step recovers it (this is what our own ingestion does).
- **Apache PDFBox/Tika** (the common Java extractor in enterprise systems) could not be tested: downloading and running it was blocked by the session's safety rules. **Open.**
- **Multilingual parsing remains hard for LLMs:** ResumeBench (2025) [C]; JobResQA (Avature, Jan 2026) [B]: LLM reading comprehension on CVs is best in English and Spanish, with "substantial degradation for other languages". Hebrew is in neither benchmark.

---

## 3. Status of every main finding

| # | Finding | Solidity | Still open |
|---|---|---|---|
| 1 | Our match score: structural 40% is broken (hard-skills = 0 for everyone) | A (logs + reproduction) | none |
| 2 | Two different formulas shown side by side | A | none |
| 3 | Local term hard-coded to one user's titles and seniority | A | none |
| 4 | Confidence barely reaches the match score | A | none |
| 5 | Real ATSs: per-requirement, coarse categories, human decides | A for Greenhouse, Workday (Aug 2026), Ashby, **SmartRecruiters and Eightfold (own pages, pass 2)**; B for iCIMS (marketing page only); **C for SAP, Oracle** | SAP and Oracle help sites return empty pages from here; iCIMS's knowledge base is unreachable |
| 6 | Automatic rejection = form answers | A (Workday manual via search, Greenhouse); C elsewhere | Comeet |
| 7 | Comeet behaviour | C (one vendor blog) | **the recruiter test (reminder set for Nov 11)**; Comeet's support site is unreachable from here |
| 8 | Holistic LLM scores unstable / per-criterion better | A, with the nuance in section 2 | size of the effect for *our* model and prompt: needs our own measurement (stage 7) |
| 9 | LLM-written CVs preferred by LLM screeners | A. **Now tested for Claude and Gemini** (Pagan et al., Oct 2026, section 5) | the test used cover letters, not CVs; no CV-only replication with current models |
| 10 | Tailoring: required, not differentiating | A (freelance, 2025) + B (Kickresume 2026) + A (theory 2026) | still no causal study of salaried hiring |
| 11 | Evidence beats prose; structured elicitation works | A (three 2026 field experiments) | none |
| 12 | Recruiters distrust AI-written and fabricated material; rising | A (LinkedIn Aug 2026 survey; Boyd-Swan & Reynolds Oct 2026 experiment; Greenhouse 2026 candidate report PDF) | Greenhouse *AI in Hiring* and *Benchmark* 2026 PDFs: pages return 404; Checkr page is a stub |
| 13 | Recruiter first-scan behaviour (titles, companies, dates) | **C; no measured study since 2018** | genuinely thin; no 2024+ eye-tracking exists that I can find |
| 14 | Israeli recruiters' habits | **C (guides only)** | no representative Israeli data found; candidate for our own small survey |
| 15 | Role titles not locked in our CVs | A (code) | how often it happens: needs generated CVs (stage 6) |
| 16 | Hebrew PDF word order | A (root cause measured) | PDFBox/Tika; real ATS |
| 17 | Skills-based hiring changes little in practice | A (PDF read, pass 2) | it is a 2024 report on 2014-2023 data: background weight only; no 2026 update found |
| 18 | Regulation (EU AI Act dates, NYC LL144, Mobley v. Workday) | B/C | verify against official texts before relying on dates |

---

## 4. What remains (updated after pass 2)
1. **Vendor docs still not read in the primary:** SAP SuccessFactors and Oracle (help sites load as empty shells from here), iCIMS's knowledge base, Workable's AI screening article, Comeet's support site.
2. **Primary PDFs still missing:** Greenhouse 2026 *AI in Hiring* and *Benchmark* reports (their pages return 404), LinkedIn *Future of Recruiting 2026* (only the 2025 edition is reachable), Checkr 2026, the UK ICO audit (403).
3. **Stage 3 topics not yet started:** hiring manager vs recruiter; CV length, photo and format evidence; referrals.
4. **Things only we can measure:** our scorer's run-to-run stability; how often our generated CVs change titles or add facts; Comeet and PDFBox on our PDFs.
5. **Genuinely absent from the literature (searched, not found):** a post-2018 measured study of where recruiters look; representative Israeli recruiter data; any Hebrew CV parsing benchmark; a causal study of CV tailoring in salaried hiring.

---

## 5. Pass 2 (2026-11-10): 23 more 2026 papers, three primary reports, vendor pages

Solidity here: **A** = read the relevant sections; **B** = abstract and key passages only.

### 5.1 Which model should write the CV? Now tested directly
**Pagan et al., 30 Oct 2026** (arXiv 2610.41866) [A]. 11 writer models × 9 evaluator models, cover letters for real job ads.
- **Most favoured writers:** Gemini 3.5 Flash (+0.45), GPT-4o-mini (+0.44), Gemini 3 Flash (+0.36). Locally hosted open models are disfavoured.
- **Self-preference is not the driver.** Claude Haiku 4.5 shows essentially none. The mechanism is style: how closely the text tracks the ad, and readability.
- **When the evaluator also sees the CV, the gaps shrink to about ±0.12.** The writing advantage lives mostly in free text judged alone.
- **Noise:** scoring the same writer twice displaces 7.6-9.5% of candidates.
- **As evaluator:** Claude Sonnet 4.6 identifies high-fit candidates best (93.6%), Gemini 3.5 Flash 89.6%.

**What this settles:** the founder's question "should CVs be written with Claude instead of Gemini?" has a direct 2026 answer: **no evidence for switching the writer; the current Gemini family is among the most favoured writers.** For *judging*, Claude is a few points better, in line with Castleman (Feb 2026). Limits: cover letters, not CVs; English.

### 5.2 Automated CV improvement fabricates, and prompts alone do not stop it
**arXiv 2608.26171, Aug 2026** [B]. Automated CV-improvement pipelines introduced fabricated content in **96.7% of outputs**. Prompt guardrails cut fabrication density by 86%, but **50% of outputs still contained at least one fabrication**. A human checkpoint closed most of the rest.
- **For us:** this is the strongest external support for two things we already suspected: (1) our tailor must be checked by code against the profile, not only instructed (titles, employers, dates, numbers); (2) the user's review step is a safety control, not a courtesy. Stage 6 must measure our own fabrication rate.

### 5.3 The score a job seeker should see
- **French public employment service, two field experiments** (arXiv 2603.21699) [A]. Recommendations that combine *what the person wants* with *the chance of being hired* beat either alone on clicks and applications. The model ranks jobs by expected value = preference × hiring probability.
  - **For us:** one number mixing "do I fit" and "do I want it" hides two different things. Our feed should rank on both; the *displayed* fit should be about hiring chance only.
- **Indeed, 2026** (single-token scoring) [B]. Indeed's own team states that zero-shot LLM scores "produce conflicting reasoning and different scores for identical candidate contexts", even at low temperature. Their fix: read the probability distribution over grades 1-5 in one decoding step, which is deterministic.
  - **For us:** a second production team confirming finding 8. Our 0-100 semantic and management numbers come from exactly the unstable setup.
- **Experience-level classification** (arXiv 2610.04304) [B]. Models confuse **Entry and Senior** levels, and title-only reading fails on ambiguous titles; reading the requirements section fixes much of it.
  - **For us:** direct support for finding 4 ("Junior Customer Success **Manager**" read as manager level). Seniority must come from the requirements text, not the title words.
- **Rubric judges: how to report agreement** (Rao & Callison-Burch, 2026) [B]. Protocol choices alone (scale, exclusions, pooling) moved reported accuracy from 0.551 to 0.899 on the same verdicts. **Consistency is not validity** (Tiwari, 2026) [B]: two judges were 92-97% self-consistent while correlating only 0.28-0.34 with people.
  - **For stage 7:** the benchmark must fix its protocol before measuring, and must measure agreement with human judgments, not only run-to-run stability.

### 5.4 Keyword vs semantic screening
- **Fofanah, 2026** (two papers) [B]. Simulations only: keyword screening rejects qualified candidates through wording differences; semantic matching reduces this. The author states it is "not a measurement of how much real-world friction is artificial".
  - **Weight:** low. Useful as a framing, not as evidence of how real systems behave.
- **ManpowerGroup, 2026** [B]: production matching uses **hybrid retrieval**: semantic vectors fused with full-text keyword relevance. **Malt, 2026** [B]: an LLM teacher distilled into a ranking model that outputs per-skill fit scores.
  - **For us:** real systems use both literal and semantic matching. Exact terms from the job still matter (recruiter search, hybrid retrieval); synonyms are increasingly understood. This agrees with stage 2.

### 5.5 What employers and candidates say in 2026
- **Boyd-Swan & Reynolds, Oct 2026** (EdWorkingPaper 26-1604; survey experiment on hiring professionals) [A]. *Earlier notes called this "Cowgill et al."; that attribution was wrong.*
  - Told that AI **substitutes** for a student's effort, employers were clearly less willing to interview and to negotiate salary, **most of all for high-GPA applicants**: strong paper credentials are discounted when they may be AI-earned.
  - Told that AI **assists**, no penalty.
  - The only reassurance both groups accepted: **in-person tests**.
- **Stephany et al., 2026** (1,725 recruiters, UK/US/Germany, conjoint) [B]. Stated AI skills raise interview invitations by **8-15 percentage points**, and partly offset age and lower education; certificates add only moderately over self-declared skills.
  - **For us:** a truthful "tools I use" line that includes AI tools is worth surfacing in Ariel's questions. Never invent it.
- **Greenhouse Candidate AI Interview Report 2026** (2,950 active job seekers, five countries; PDF read) [A, vendor survey].
  - 63% of US job seekers have been interviewed by AI (+12 points in six months); 38% have withdrawn from a process because of it.
  - **78% of US candidates still tailor applications; only 3% mass-apply with automation; 31% hear back from fewer than a quarter of employers.**
  - 57% believe their applications are often rejected automatically with no human review; only 21% think employers use AI responsibly.
- **Wang, 2026** (1,919 US job seekers, preregistered conjoint) [B]. Human involvement mattered more to applicants than any other feature, about as much as cutting wrongful rejections from 30% to 10%.
- **Surati, Bellini & Black, 2026** (22 recruiter interviews) [B]. Recruiters believe they hold final authority while AI shapes the material they judge from; adoption is often imposed from above; reported efficiency gains are marginal.
- **Reading:** candidates distrust opaque automation and tailor anyway; employers discount unverifiable polish and trust in-person or verified evidence. Both sides point at the same thing as section 2: **verified, specific evidence over prose**.

### 5.6 Systemic effects
- **Model monoculture, COLM 2026** [B]. When employers' screeners share correlated biases, the share of candidates rejected by *everyone* rises from 5.6% to 17.3%. Post-trained models were 3.6% less likely to call back older applicants.
- **Braun et al., 2026** (resume audit, 36,880 applications to 9,220 ads) [B]. Callback gaps are **narrower where screening relies on verifiable, structured criteria** and wider where judgment is subjective.
- **Barcelona Activa audit, 2026** (497,000 pipeline entries) [B]. Aggregate parity hid large disparities by salary band and age; candidates 55+ were absent from the pipeline.
- **Kaya et al., Jobindex 2026** [B]. Human plus AI produced fairer candidate lists than either alone.
- **For us:** structured, verifiable criteria help the candidate too. They are the part of screening least open to arbitrary judgment.

### 5.7 Vendors, read on their own pages
| Vendor | What their own page says | Mark |
|---|---|---|
| **SmartRecruiters Winston Match** (FAQ) | Four bands: **Very high / High / Medium / Low**. Each candidate scored independently on separate models for skills, work experience (titles, seniority, trajectory), education and certifications, career progression, and **job-title relevance**, then combined with weights "based on real-world hiring outcomes" for that job. | A. *Corrects stage 2, which said "1-5 stars" from a secondary source.* |
| **SmartRecruiters Winston Screen** (FAQ) | AI generates screening questions, scores answers against must-have and nice-to-have criteria, ranks a shortlist. Recruiters review and edit the questions first. | A |
| **Eightfold** (Responsible AI page) | "Match scores come with plain-language reasoning, candidates can see the skills behind their fit". "Purpose-built, deterministic models". "It does not autonomously reject a candidate or advance one". Bias audits published under NYC LL144. | A |
| **Ashby** (AI page) | "The AI never 'ranks' or gives numerical ratings to applicants, a human must always be involved"; citations for every AI output; PII redacted before the model. | A (re-confirmed) |
| **iCIMS** (AI page) | "Rank candidates based on skills and experience"; certified by TrustArc as "explainable and interpretable". No method detail on the public page. | B |
| **Textkernel** (parser FAQ) | CV parsing in 29 languages, **Hebrew named in the list**; "column layout auto-detection". Search results suggest Hebrew is marked beta in the developer docs; that page is unreachable from here. | A for "Hebrew supported"; C for "beta" |

**What changes:** nothing in the direction, more confidence in it. Five vendors now confirmed on their own pages: coarse bands or criteria, shown reasons, no autonomous rejection. **Title relevance is an explicit scored dimension at SmartRecruiters**, which raises the cost of our tailor changing role titles (finding 15) and the value of an honest, recognisable title.

### 5.8 Skills-based hiring (background, 2024)
Burning Glass Institute + HBS, PDF read [A]: where firms dropped degree requirements, hires without a degree rose 3.5 points, in 3.6% of roles: **about 97,000 workers a year out of 77 million hires, "not even 1 in 700"**. About 45% of firms changed "in name only". Old data (2014-2023); kept as background for "what the job ad says is not how the hiring manager decides".

### 5.9 What pass 2 changes in our working conclusions
1. **Writer model:** closed. No case for moving CV writing from Gemini to Claude.
2. **Judge model:** a small, consistent Claude advantage on judging fit (2 sources, 2026). Worth testing in stage 7 against cost; not a reason to act now.
3. **Fabrication control moves up the list.** External evidence says prompts cut it but do not remove it. Code-level checks and the user's review are required.
4. **The displayed score:** bands plus per-requirement reasons is what vendors ship and what the judge literature supports; a raw 0-100 from a zero-shot LLM is what Indeed's own team calls unstable.
5. **Seniority from requirements, not from title words.**
6. **Two signals, not one:** fit (chance of being hired) and preference (does the user want it) should be ranked together but shown separately.

---

## 6. Pass 3 (2026-11-10): closing the listed gaps without the founder's help

Each gap from section 4, what was tried, and where it ended.

### 6.1 Closed
| Gap | Result | Mark |
|---|---|---|
| **Oracle Recruiting** | Own docs read. Generative AI rates each application **0 to 5 on four separate categories: Education, Experience, Skills, Profile**, shown as rating bars; admins set the relative weight of education, experience and skills; recruiters can filter by rating; a generated summary sits behind each bar. Off by default. | A |
| **Workable** | Own help article read ("Using the Workable Agent"). Criteria in 14 categories, each markable **must-have** or **disqualifier**; the agent gives **a normalized score out of 100**, must-haves weighted more; it also weighs "completeness of the candidate profile" and "validity and consistency of provided information". **Auto-advance and auto-disqualify exist as optional settings**; a disqualifier only rejects "if this action is enabled". | A |
| **Greenhouse 2026 AI in Hiring Report** | The PDF link was behind the form page; found and read (1,200 job seekers, 219 recruiters, 446 hiring managers, US). See 6.3. | A (vendor survey) |
| **A fifth PDF engine on our Hebrew files** | PDFium (the engine inside Chrome, already installed here as `pypdfium2`) returns the Hebrew lines with the words in reversed order **for our PDFs and for the Word-made control alike**. | A (measured) |

### 6.2 What these change
- **"No vendor rejects automatically" was too strong.** Workable ships optional automatic disqualification on recruiter-defined disqualifying criteria, and a 0-100 score. The accurate statement: rejection is driven by **explicit criteria the recruiter marked as disqualifying**, and it is opt-in. Greenhouse, Ashby, Eightfold, SmartRecruiters and Workday state that the AI does not reject on its own.
- **The 0-100 scale is not absent from the market** (Workable). Bands and 0-5 remain the majority (Greenhouse, SmartRecruiters, Oracle, Eightfold, iCIMS tiers). The stronger shared pattern is not the scale but the structure: **named criteria, must-have vs nice-to-have, a reason per criterion**.
- **Workable scores profile completeness and consistency.** A complete, internally consistent application is itself a scored signal. This supports asking for missing data up front and checking dates and titles for consistency before export.
- **Hebrew PDF word order is not only our problem.** With PDFium the Word control is reversed too. Tally across engines: Poppler reads both correctly; PyMuPDF and pypdf reverse ours only; PDFium reverses both; pdfminer needs a bidi step for both. So a system's Hebrew handling depends on its own engine and whether it applies bidi reordering. Our file is worse than Word's in two of five engines and equal in three. PDFBox/Tika remain untested.

### 6.3 Greenhouse 2026 AI in Hiring Report (primary)
- **53% of recruiters review fewer than half of the applications they receive; 21% review fewer than a tenth per role.**
- Only **21% are "very confident"** their system is well tuned; **25% are not confident** it isn't filtering out qualified candidates; 8% do not know what their AI prioritises. *(Corrected 2026-11-11 after checking the page layout: an earlier version attached 25% to the wrong statement.)*
- 91% of recruiters and hiring managers have spotted or suspected candidate deception; most common: CV exaggeration (63%), fake references (48%).
- Hiring managers' top two problems: candidate authenticity (46%) and **telling qualified from unqualified (45%)**. 68% are more involved in hiring than a year ago; 39% run more in-person interviews.
- **41% of candidates say they have used prompt injections in applications.** This is self-reported in a survey; the measured rate in about 200,000 real CVs was about 1% (Zhang et al., section 2). The two numbers measure different things and the survey figure should not be read as prevalence.
- 74% of candidates use AI in the job search; 87% want employers to disclose AI use.
- **For us:** most applications are never read by a person, so being surfaced matters; and the people who do read are primed to distrust polish. Both push toward specific, checkable facts.

### 6.4 A conflict found: do AI skills on a CV help?
- Stephany et al. (recruiter conjoint, 2026): +8 to 15 points on stated interview intent.
- **Danilov et al., 2026** (field correspondence experiment, cited in Boyd-Swan & Reynolds): listing advanced AI skills had **no average effect on real callbacks**.
- **Reading:** a real-callback experiment outweighs stated intent. Section 5.5's note that an AI-tools line is "worth surfacing" is downgraded to **unproven**. I have not read Danilov et al. in full; mark B.

### 6.5 Still open, and why it cannot be closed from here
| Gap | What was tried | Status |
|---|---|---|
| SAP SuccessFactors, primary | sap.com, community.sap.com, learning.sap.com, help.sap.com all return empty from this environment | **C.** Secondary sources agree: skills sorted into exact, related and "easily acquirable"; stack ranking by overall fit; not available for jobs in Germany. |
| iCIMS method | knowledge base unreachable; public page has no method | **B.** Tiers by skills and experience, per job. |
| Comeet | support site unreachable; searches return only launch coverage | **C.** Needs the recruiter test. |
| LinkedIn Future of Recruiting 2026 | only the 2025 edition is published at the known address; 2026 figures appear only in secondary write-ups | **C** |
| Checkr 2026, UK ICO audit | stub page; 403 | not read |
| PDFBox / Tika | download, and install through the system package manager, both blocked by the session's safety rules; not worked around | needs the founder's permission |
| Our scorer's run-to-run stability; our CVs' fabrication and title-change rate | no model API key exists in this environment, and adding one needs the founder | stage 7, with a key |
| Recruiter eye-tracking after 2018 | searched again; only blogs recycling the 2018 study, one 2023 machine-learning paper on older gaze data | **does not exist** as far as can be found |
| Representative Israeli recruiter data | Hebrew search: press pieces only (TheMarker June 2026, Mako, Ynet), mostly quoting foreign surveys | **does not exist** publicly; own survey is the only route |
| Hebrew CV parsing benchmark | none; RChilli lists Hebrew under "basic parsing" only | **does not exist**; our test kit is the substitute |
| Causal study of CV tailoring in salaried hiring | none found beyond Kickresume's own test | **does not exist** yet |
