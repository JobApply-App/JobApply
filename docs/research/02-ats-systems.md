# Research 02: how real applicant tracking systems read, filter and rank a CV

Stage 2 of the scoring/CV research. Working notes, built up over several rounds. Each round asks narrower questions than the last.


**Source access.** The research session's network cannot open vendor or academic sites directly (`support.greenhouse.io`, `doc.workday.com`, `arxiv.org` and others refuse to resolve). Approving a research environment that adds them needs claude.ai on a computer or a newer app. Until then, each finding is marked:
- **[primary]**: the vendor's own documentation, or the paper itself, as quoted in search results;
- **[secondary]**: a blog or guide describing it;
- **[vendor claim]**: a number or promise only the vendor states.

---

**Evidence weighting (founder, 2026-11-07):**
- **2026 findings carry the most weight.**
- **2025 is valid but already older.**
- **Anything earlier is background.**
- Everything is still researched, and the notes record where newer work changes older work.

## Round 1: what the big systems do

### Greenhouse (most common ATS in tech, including Israeli tech)
- **Talent Matching (AI)** sorts applicants into *match categories*, not a single number. [primary: support.greenhouse.io, "Talent Matching"; "Operational readiness guide: Talent Matching policy"]
- **No automatic decisions:** "Talent Matching does not auto-reject or auto-advance any candidate, including candidates in lower match categories". [primary]
- **Criteria come from the employer.** Admins "calibrate" them, and a permission controls who can view match scores. [primary]
- **Scope:** it runs only in the first stage, Application Review. A candidate can opt out of AI review and is then labelled "Needs manual review". [primary]
- **Automatic rejection exists only through employer-written application rules**, based on form answers (work authorisation, location, salary, years), never on the CV text. [secondary, consistent across several guides]
- **Scorecards** are filled in by people. [secondary]
- A bias audit statement is published (greenhouse.com/bias-audit-statement), as NYC Local Law 144 requires for automated employment decision tools. [primary, title only so far]

### Workday Recruiting + HiredScore (large enterprises)
- **Spotlight grades applicants A/B/C/D.** [secondary for the letter scale]
- **Basic qualifications decide the tier:** A/B vs C/D. Preferred qualifications rank within the tier. [primary: HiredScore release notes, August 2026, via search]
- **Each qualification is assessed directly**, no longer translated through a fixed framework. [primary, same]
- **"Fit & Gap" view:** each requirement is marked met or not met, with an explanation and a pointer to the part of the parsed profile that supports it. [primary, same]
- **Knockout questions are filtered programmatically** in Workday. [secondary]
- "70% more recruiter capacity" [vendor claim]

### Lever
- **The parser** pulls name, organisation and contact details into the profile, and recruiters fix failures by hand. It cannot read text inside images. Tables and columns are parsed, but the format can suffer. [primary per a quoted help article; page not reachable from here]
- **No auto-reject on a score.** Stages are moved by recruiters. [secondary]
- **Ranking:** no Lever help page describing one was found. AI ranking is attributed to an integration. [secondary, unconfirmed]

### Comeet (Israeli ATS)
- No public documentation of a match score was found in round 1. To check in a later round.

### Patterns already visible
1. **The leading systems do not give a CV a "percentage".** They give a **category or grade**, built from **requirements the employer marked as must-have vs preferred**, and show **met / not met per requirement with evidence**.
2. **A person decides.** Automatic rejection comes from **form answers** (knockout questions), not from the CV's wording.
3. **Requirements are evaluated one at a time, as whole requirements.** This is exactly where our structural matcher fails: it compares whole requirement sentences to short skill names and gets 0 (Research 01, finding 2).
4. **Explanations are a product feature,** partly because of regulation (NYC LL144 bias audits, the EU AI Act classing hiring AI as high-risk). To verify in the regulation round.

### Open questions for the next rounds
- iCIMS, Oracle (Taleo / Oracle Recruiting), SAP SuccessFactors, SmartRecruiters, Ashby, Eightfold: does each score, and how?
- **Parsers** (Textkernel, Sovren, Daxtra, Affinda, RChilli): what breaks a parse, and how is Hebrew/RTL handled?
- **Evidence on automatic rejection:** the Harvard Business School / Accenture "Hidden Workers" report, and the origin of the "75% rejected by ATS" claim.
- **Recruiter search behaviour:** Boolean search, filters, how keywords matter when a person searches the database.
- **Regulation:** NYC LL144, the EU AI Act, and Israeli privacy law, as constraints on how we score and explain.

---

## Round 2: iCIMS, Oracle, SAP, SmartRecruiters, Ashby, Eightfold

| System | Output to the recruiter | Built from | Auto-decides? |
|---|---|---|---|
| **iCIMS** (Candidate Ranking, "Role Fit") | **tiers** of similarly scored candidates; the number of tiers varies with the applicant pool | skills and experience vs the job's requirements, **per job** | no, recommendations [secondary, quoting iCIMS docs]; registered as an AEDT under NYC law, bias audits 2022 and 2023 [secondary] |
| **Oracle Recruiting Cloud** | **prescreening score** from weighted answers and competencies; **disqualification questions**; "Best Candidates" recommendation list | administrator-set weights on questions/competencies; Oracle AI matching for recommendations | disqualification questions filter; ranking is advisory [primary: docs.oracle.com 17.6 "Candidate Prescreening", 23D "Set Up Matching Features"] |
| **SAP SuccessFactors** (AI-Assisted Skills Matching) | **"Skill Compatibility"**: matched (green), unmatched (grey), "other applicant skills" AI judged useful (blue); classes: direct match, related skill, skill the applicant could readily acquire | AI-extracted skills from the CV vs the requisition's skills (also AI-extracted from the JD) | no numeric score found [primary: help.sap.com, via search]; a community tester saw only exact matched/unmatched, not the related tiers [secondary] |
| **SmartRecruiters** (SmartAssistant / Winston Match) | **1-5 stars**: 4-5 = "high confidence in a good match", 1-2 = low | skills extracted from the CV vs the job's title, description and qualifications, normalised to a ~14,000-skill taxonomy; separate models ensembled into one weighted score; trained on customer history | "does not make any hiring decisions" [vendor whitepaper]; candidates never see the score |
| **Ashby** (AI-Assisted Application Review) | **a verdict per criterion: Meets / Does not meet / Undecided (unknown when the CV does not say)**, with reasoning **and a citation from the CV**; optional sortable "% of criteria met" | up to 50 criteria the employer writes per role | no; "it is up to the reviewer to advance or reject" [Ashby blog, via search] |
| **Eightfold** | **0-5 in half steps**, per candidate-role pair, with reasons | skills (stated **and inferred** from similar careers, marked as inferred), past titles, experience; LLM semantic similarity per the plaintiffs | advisory; under an FCRA class action (Kistler v. Eightfold) arguing the score is a consumer report |

### What round 2 adds
1. **Nobody shows a precise percentage as truth.** Outputs are coarse: tiers, A-D, 1-5 stars, 0-5 in half steps, or per-criterion verdicts. Coarse scales are an honest expression of how uncertain these judgments are. Our "53.8% match" with one decimal implies precision we don't have.
   - The one-decimal rule in CLAUDE.md is a formatting rule; whether to show the number at all is a product decision for the synthesis.
2. **The unit of evaluation is the requirement.** Every system, from rule-based (Oracle) to LLM-based (Ashby, Workday Fit & Gap), checks requirements one by one and shows met / not met. The best ones show the evidence: a CV citation (Ashby) or a pointer into the parsed profile (Workday).
3. **"Unknown" is its own state, separate from "not met".** Ashby's "Undecided" means the CV doesn't say.
   - Our system turns "we have no evidence" into a low number (unverified skill × 0.6, missing entity = 0).
   - This bears directly on the founder's confidence question: missing information should read as *unknown, here's how to show it*, not as a penalty.
4. **Inferred skills are labelled as inferred** (Eightfold), and related or adjacent skills are their own tier (SAP).
   - This is a model for "the user told Ariel something not yet verified": count it, label it, keep it distinct from verified evidence.
5. **Must-have vs preferred is the first split everywhere.**
   - Workday: basic qualifications decide A/B vs C/D.
   - Oracle: disqualification questions.
   - Greenhouse: employer-calibrated criteria.
6. **Explainability and audits are now legal exposure, not just UX.** NYC LL144 bias audits (iCIMS, Greenhouse), and an FCRA suit against a numeric hiring score (Eightfold). Relevant to how we present a score to job seekers, since we're on the other side of the table.

---

## Round 3: how much do systems actually reject? And the myths

### "75% of CVs are rejected by the ATS" [historical, 2012]
- Traced by several independent write-ups to **2012 sales material from Preptel**, a CV-optimisation company that closed in 2013. No methodology was ever published. [secondary, consistent across sources]
- The figure drifts (70%, 75%, 88%) as it is repeated. The honest label is **unsupported**, not proven false.
- **Implication for us:** a product promising to "beat the ATS robot" is selling against a fear with no evidence behind it. What we should optimise is **a person's reading and a recruiter's search**, and what ATSs really automate: knockout answers and requirement matching.

### What recruiters report
- **Enhancv survey, 2025, 25 US recruiters:**
  - 92% say their ATS does not auto-reject for formatting, content or design;
  - 44% have an AI fit score, and 8% use it as a hard filter.
  - Small sample, and the author sells CV tools. [secondary]
- **Jobscan survey, 2025, 384 recruiters:** 99.7% use keyword filters/search. They filter by:
  - skills 76%;
  - education 60%;
  - previous job titles 55%;
  - certifications 51%;
  - years of experience 44%;
  - location 43%.
  - Seen only second-hand so far; the author also sells ATS optimisation. [secondary]
- **Reading the two together:** rejection is rarely automatic, but **search is everywhere**. A recruiter types skills and titles into the database and filters. A CV that doesn't contain the skill or title in a searchable form is **not rejected; it's never found**. That is the real reason keywords matter.

### Where automation does filter people out: "Hidden Workers" (Harvard Business School + Accenture, 2021) [historical]
- Fuller et al.: the efficiency drive "is creating a significant amount of the shortage that they complain about". [primary quote, via search; PDF on hbs.edu]
- **Mechanism:** systems use rigid proxies, such as a degree as a proxy for work ethic, or **an employment gap as an automatic rejection**. Heavily automated firms "regularly eliminate all but those candidates who most closely match the job requirements specified".
- **Survey:** about 8,700 workers and 2,250-2,275 executives. About 27 million "hidden workers" in the US.
- The often-quoted "88% of employers say their ATS filters out qualified candidates" is a survey *belief*, reported in two different framings. To verify against the PDF before citing.
- **Implication:** the rigid filters are **requirement-level and literal**: degree, years, titles, gaps. Our scoring should tell the user exactly which literal requirement might filter them out ("the job asks for 3+ years; your CV shows 1.5"), rather than fold it into a blended number.

### Parsers (the layer under most ATSs)
- **Textkernel** (which absorbed Sovren) lists CV parsing in **29 languages**. **DaXtra** lists 40+ (41, 11 of them "limited"), and its language page names **Hebrew**. [vendor pages via search]
- **No independent accuracy benchmark exists**; every accuracy claim is the vendor's own.
- **No source found on Hebrew RTL extraction quality** for any parser. This confirms the open item from research #135: we have to **test our own Hebrew PDFs** through a real parser.

### What round 3 adds
1. **Keywords matter for search more than for scoring.** The literal term must be present and searchable (title, skills, requirement wording), and that part is deterministic.
2. **Literal knockouts are the real filter.** Years, degree, location, work authorisation, language. Treat them separately and explicitly, not as points.
3. **Gaps and rigid proxies are where qualified people get lost.** Telling the user about them is more useful than a lower number.

---

## Round 4 (part 1): Israel, regulation, AI screening studies

### Which systems Israeli employers use
- **No market-share data exists**; the claims below are anecdotal. [secondary, mostly CV-tool vendors]
- **Comeet:** Israeli-built, described as the default at Israeli tech companies (Wix, Monday, Lightricks, ironSource, AppsFlyer named), and "Hebrew-aware". [Comeet's own LinkedIn + a CV-vendor blog]
- **Greenhouse:** larger, global-facing R&D sites (NVIDIA Israel, Intel and Mobileye named). A Hebrew CV there is described as "rolling dice". [same blog]
- **Others:** Workable at startups/SMBs, Workday at some large employers (Teva and Check Point named), Lever rare. A public GitHub survey of Israeli company job boards finds many larger companies on Ashby and Workday.
- **Comeet's screening and auto-rejection behaviour is not publicly documented.** Nothing found beyond the generic "knockout questions are the main automatic path".
- **Implication:** our users meet Comeet (Hebrew OK) and Greenhouse/Workday/Ashby (English-first, criteria-based). The language and format advice we give should depend on the employer's likely ATS, which we can often infer from the job's apply URL (comeet.co, boards.greenhouse.io, myworkdayjobs.com, jobs.ashbyhq.com). Our scrapers already route by these hosts.

### Regulation (constrains how a score may be built and explained)
- **EU AI Act:** recruitment and candidate selection are **Annex III high-risk**. The Article 6(3) exemption never applies to systems that profile people. Obligations: risk management, data quality, logging, documentation, human oversight. Timing differs across sources (high-risk employment duties reported as moved to 2 December 2027 by the "AI Omnibus"). [secondary + an arXiv review; verify against the Official Journal]
- **NYC Local Law 144** (enforced since 5 July 2023): an **independent** annual bias audit (selection rates and impact ratios by sex, race and ethnicity), a public summary, and notice to candidates. [secondary, consistent]
- **Our position:** a job seeker's tool scoring the *job* for the *candidate* is not the employer's AEDT. But the same principles (explainable, auditable, human decides) are what users and partners will expect, and what employer-side products are now built around.

### Studies of AI CV screening (leads for stage 5)
- **Wilson & Caliskan, AIES 2024:** embedding-based retrieval models disadvantaged Black male names in up to 100% of tested cases. [arXiv 2407.20371]
- **Chaturvedi et al., NAACL Industry 2025:** 32,000 paired comparisons varying names and institutions. Bias in job-resume matching LLMs.
- **"Can LLMs Hire Fairly?" (2026 preprint):** 14 LLMs; post-2024 models show null or reversed racial gaps.
- **"Beyond the Name" (2026 preprint):** forced-choice audit protocols manufacture spurious bias through **format and position artifacts**. LLM judgments are sensitive to presentation, not just content.
- **"Measuring Validity in LLM-based Resume Screening" (arXiv 2602.18550):** to read in full in stage 5. Directly relevant to whether our 70% AI component measures anything stable.
- **Implication for us:** an LLM's 0-100 number is sensitive to wording, order and format. **Per-requirement judgments with evidence are more stable and auditable than one holistic number.** This matches what Ashby and Workday ship.

## Round 4 (part 2): how Israeli ATSs read a CV; how reliable AI scores are; recruiter search

### Comeet / Greenhouse / Workable in practice [secondary: korotchaim.com, a CV-tool vendor; the indexed text was partly garbled]
- **Comeet**
  - Its text extractor reads **single-column by default**, so **a two-column CV can come out with scrambled sections**.
  - The recruiter sees the parsed candidate card **plus an AI summary: three bullets from the most recent role**.
  - So the most recent role's top bullets carry extra weight in Comeet. That supports the bullet-order rule we added in #135.
- **Greenhouse:** clear English section headings (Experience, Education, Skills) parse cleanly. Recruiters usually also open **the original file**, so design still matters once a person looks.
- **Advice in the same source:** keep two versions, a clean English CV for Greenhouse roles and a Hebrew or bilingual one for Comeet-based Israeli companies. This matches our per-language CVs (#134).
- **Two of our templates are two-column (to check: t3/t5).** If Comeet reads single-column, those layouts may parse out of order. This needs a real Comeet upload test (already an open item).

### Reliability of AI scoring
- **"Measuring Validity in LLM-based Resume Screening"** (arXiv 2602.18550, via summaries)
  - Uses synthetic CV pairs with known ground truth.
  - **Most models fail to abstain on equally qualified pairs**: discriminant validity is below 0.90, so they pick a "winner" in more than 10% of ties.
  - Validity is higher when CVs differ in education than when they differ in soft skills.
  - Rephrasing the prompt changes little.
- **"Competence-Preserving Resume Perturbations Expose Presentation Sensitivity in LLM Screening"** (arXiv 2609.16517): title only so far. Changing a CV's presentation without changing its competence moves LLM scores.
- **LLM-as-a-judge practice** (practitioner sources plus the Autorubric paper, arXiv 2603.00077):
  - LLMs "aren't calibrated to consistent scores on arbitrary scales". A near-identical input scored 7 in one run and 9 in another.
  - Unbounded numeric scores show "high variance across runs and systematic distributional biases".
  - **Per-criterion binary or coarse judgments are more reliable**, and pairwise comparison beats absolute scoring.
  - Agreement with people is measured per criterion; Cohen's kappa above 0.6 is acceptable, above 0.8 strong.
- **What this means for our design:**
  - 70% of our score is two holistic 0-100 numbers from an LLM (semantic, management).
  - Production logs show them landing on round values (0, 5, 10, 25, 38, 42, 58, 60, 68, 75, 85, 88).
  - The same job type for different users swings between 5 and 85.
  - The evidence favours **asking the model a yes/no/unknown question per requirement, with a quote**, and computing the number deterministically from those answers. That is the Ashby/Workday design.

### Recruiter search (why literal terms still matter)
- **LinkedIn Recruiter's own example:** `(Job Title: "developer" OR "programmer" OR "engineer") AND Skills: ("java" OR "C++") AND NOT Job Title: ("intern" OR "junior")`. Boolean operators work in the job-title, company and keyword filters. [LinkedIn help, via search]
- **Recruiters search on title variants plus must-have skills, and exclude seniority words.** A CV is found when its **titles** and **skills** contain the literal terms a recruiter would type.
  - Title wording is a search key, not just decoration.
  - The tailor's rule of using the posting's exact title wording where truthful is grounded here.

---

## Round 5: stability of AI judgments; automatic dispositions in Workday

### Presentation changes flip AI decisions
**Chen & Xiao, arXiv 2609.16517 (preprint under review).**
- **Design:** five versions of each CV. The original, plus verbosity, prose structure, AI polish, and **layout/extraction noise**, all keeping the job-relevant evidence fixed. 505 of 510 variants passed a deterministic fact-preservation gate.
- **Result:** the most valid setting (Llama-3.1-8B, validity 0.781) still **reversed 29.6% of pairwise decisions** when only presentation changed. Mistral-7B: validity 0.644, 41.4% flips.
- **For us, the scorer:** the AI half of our score can move when only wording, order or extraction noise changes. A user re-generating the same CV may see the number jump with no real change.
- **For us, the CV writer:** presentation does move AI screeners. Clear, evidence-first bullets are not cosmetic when the reader is an LLM.

### Humans vs GPT-4 on the same CVs
**Vaishampayan et al., Findings of NAACL 2025, 736 CVs.**
- Human raters agreed with each other at **κ ≈ 0.79** (substantial).
- GPT-4 reached only **"moderate"** agreement with them, and only with its best prompting (task-based chain of thought with examples).
- GPT ratings varied more than human ratings across rating constructs.
- The authors recommend an **LLM-guided human-in-the-loop** approach over fully automated rating.

### Workday automatic dispositions
- **Workday's administrator manual** (doc.workday.com, "The Job Application Business Process", via search):
  - conditional logic on a recruiting step can **route or disposition a candidate automatically** from an answer (their example: answering "No" to an age question);
  - decline reasons are defined per stage.
- **The rule acts on questionnaire answers, not on CV text.**
- **The same pattern holds across every system examined:** Greenhouse application rules, Oracle disqualification questions, Workday conditional dispositioning. **Automatic rejection = form answers. CV text = ranking and human reading.**

---

## Interim synthesis (after 5 rounds)

### What real ATSs do
1. **They parse the CV into fields.** Failures come from layout: multi-column, text in images, headers/footers, unusual headings. Comeet reportedly reads single-column. Hebrew support exists in some parsers (DaXtra lists it; Comeet is described as Hebrew-aware), but no independent quality data exists.
2. **Automatic rejection happens on form answers** (knockout/prescreening/disqualification questions). It does not happen on CV wording. The "75% rejected" figure is a 2012 sales claim without methodology.
3. **Ranking, where it exists, is advisory and coarse:**
   - categories (Greenhouse);
   - A-D (Workday);
   - tiers (iCIMS);
   - 1-5 stars (SmartRecruiters);
   - 0-5 (Eightfold);
   - or **per-requirement verdicts with evidence and no overall score** (Ashby).
4. **The unit is the requirement**, split into must-have vs preferred (or basic vs preferred), with **met / not met / unknown**. The best systems also give evidence: a CV citation (Ashby) or a pointer to the parsed profile (Workday Fit & Gap).
5. **Inferred or related skills are labelled** (Eightfold "inferred", SAP "related / could readily acquire"), never silently counted as proven.
6. **Recruiters search literally:** title variants OR'd together, plus must-have skills, minus unwanted seniority words. Being found depends on literal titles and skills in the CV.
7. **Holistic LLM scores are unstable.**
   - Presentation-only changes flip 30-41% of decisions.
   - LLM-to-human agreement is "moderate" at best.
   - Per-criterion yes/no judgments are more reliable than one 0-100 number.

### How our system compares (from Research 01)
| Industry practice | JobApply today |
|---|---|
| per-requirement met / not met / unknown, with evidence | requirement matching exists but **scores 0 for everyone** (sentence-vs-skill bug); no per-requirement evidence shown |
| must-have vs preferred split first | exists in the structural layer (0.80 / 0.20) but sits on the broken matcher |
| knockouts kept separate and explicit | exists (Layer-0 knockout, 40 cap); good |
| coarse grades | a one-decimal percentage, presented as precise |
| inferred/unverified evidence labelled, not punished | unverified × 0.6 and low confidence make skills read as missing; no "unknown" state |
| holistic LLM scores avoided or used as one input | **70% of the AI part** is two holistic 0-100 numbers |
| literal title/skill presence for search | a hard-coded title list (Product Manager first) for every user |

### Still open for stage 2 (next pass)
- **Read the primary documents in full** once the research environment is approved:
  - Greenhouse Talent Matching and its bias audit;
  - Workday HiredScore Fit & Gap;
  - Ashby AI review;
  - the HBS "Hidden Workers" PDF;
  - arXiv 2602.18550 and 2609.16517;
  - NAACL 2025.
- **Comeet in practice:** what its AI summary takes from the CV, and how it handles Hebrew and two-column PDFs. Best answered by a real upload test.
- **The data a parser needs** (section names, date formats, contact block) and **how a Hebrew PDF from our templates extracts.** Partly measurable locally with the same text extraction our tests use.
- **What Jobscan-style "match rate" tools compute**, and whether it relates to anything an ATS does. This is the bridge to stage 4.

---

## Round 6: primary sources, read in full (research environment approved, 2026-11-06)

### Greenhouse Talent Matching: the help article [primary, current]
- **Five categories:**
  - **Strong match**;
  - **Good match**;
  - **Partial match**;
  - **Limited match**;
  - **Needs manual review** (the CV could not be processed by AI, AI is off for the job, or the candidate opted out).
  - Candidates are grouped by category and **ordered by application date within each group**, not by a finer number.
- **"Calibration"** is the employer's list of **skills, each rated for importance**. Greenhouse's own advice: *"Since the match score is spread across the selected skills, for clearer matches, we recommend focusing on 4–6 key skills."* The score is spread over a handful of weighted requirements, not over every word in the posting.
- **What the recruiter sees per candidate:**
  - "An explanation of why the candidate received their match score, shown as a breakdown of matched experience, industries, and skills based on your calibration";
  - industry matches ("Media Production at SceneCloud");
  - **the CV with matched and *similar* keywords highlighted**;
  - "Calibrated skills matched: 2 of 4" and "Matched terms on this resume: 4".
- **Similar terms count, and are shown as such.** Exact and similar keyword matches are highlighted separately.
- **A person can override the match score.** Changing the calibration re-scores everyone, and calibration history is kept.
- **"Talent Matching is assistive AI, not automated-decision-making. It does not automatically advance or reject candidates."**
- **Bias audits** [greenhouse.com, 2025-2026]: monthly, by an independent auditor (Warden AI); disparate impact plus demographic-variable testing across 10 protected classes; published publicly; **a new version cannot ship until it passes**.
  - Real Talent's stated principles: "Transparency, Accountability, Human control". Recruiters "can see which criteria contributed to each match label and can adjust weightings at any time".

### Workday HiredScore Spotlight, release notes 5 August 2026 [primary, current]
- **The fixed preset framework was replaced by an LLM that "evaluates each screenable qualification individually against the candidate's parsed resume."**
- **Fit & Gap view:**
  - met / not met per basic and preferred qualification;
  - "how they influenced the candidate's grade";
  - "an explanation for each evaluation conclusion and pointers to relevant sections in the candidate's parsed profile, such as professional experience, education, skills, languages, certifications, and the resume summary."
- **Grade rule:** "Candidates who meet all scoped basic qualifications receive an A or B." A vs B (and C vs D) come from preferred qualifications and basic-qualification scores.
- **Stated rationale:** "By evaluating requirements individually, it improves accuracy and supports more fair hiring, including nuanced or non-numeric requirements."
- **Rollout:** opt-in, pilot first; old requisitions keep the old algorithm; can revert.
- **Note:** the largest enterprise vendor moved **from a fixed framework to per-requirement LLM evaluation with evidence** in August 2026. This is the current direction of the industry.

### Ashby (VP of Talent, September 2024) [primary, vendor]
- "No decisions are made for me. **No scoring or ranking is involved.** The AI analyzes the resume and produces a 'Meets' or 'Does not Meet' for each criterion I've set."
- **Reviewers work in batches of candidates who meet the same criteria.** The AI's explanation is "a helpful starting point" that the person verifies.
- **The example of a hard-to-verify criterion:** "2 years B2B SaaS experience".
- **Advice to candidates:** "clearly communicate, through your resume and application, how you meet the minimum requirements in the job description."

### How valid are LLM screeners?
**Castleman et al., Princeton, IASEAI'26, arXiv 2602.18550, February 2026 [primary].**
- **Method:** a synthetic CV dataset tailored to jobs with known ground truth.
- **Criterion validity** (does it pick the more qualified candidate?) rises with model size. *(Corrected 2026-11-10 after reading the paper's tables; the earlier note misread one cell as the average.)*
  - Averaged over pairs differing by 1-3 qualifications: Claude Sonnet 4 0.96; GPT-5, Gemini 2.5 Pro and **Gemini 2.0 Flash all above 0.90**.
  - On the hardest pairs (one differing qualification): Claude Sonnet 4 0.87-0.93, GPT-5 0.83-0.90, Gemini 2.5 Pro 0.82-0.88, **Gemini 2.0 Flash 0.73-0.84**, GPT-4o-mini 0.50-0.59.
  - On real-world CVs: Claude Sonnet 4 0.92, Gemini 2.0 Flash 0.90, Gemini 2.5 Pro 0.90, GPT-5 0.87.
  - **Most errors are abstentions, not wrong picks** (median 93% of errors; Gemini 2.0 Flash 84%). The earlier "picks wrong about 1 in 4" was an overstatement: the model mostly *declines to choose* on close pairs.
  - **Our scorer runs on Gemini Flash.** The gap to the best model is real on close calls and small on clear ones.
- **Discriminant validity** (abstaining on equally qualified pairs) is poor. When models wrongly pick a winner, they give **"untrue rationale ... such as 'better formatting' when resumes are formatted similarly."**
- **Validity is higher when CVs differ in credentials (education) than in soft skills.**
- **Validity drops for non-tech roles.** Nurse practitioner is lower than software engineer.

### Presentation sensitivity
**Chen & Xiao, arXiv 2609.16517, September 2026 [primary].**
- **Design:** 102 synthetic O*NET-based profiles across 17 occupations; five presentations each (original bullets, verbosity, prose, **AI polish**, **layout/extraction noise**).
- **Result:** even the most valid setting reverses **29.6%** of decisions on presentation alone (Mistral: 41.4%).
- **Limit:** small open models (7-8B), not the large commercial ones. The direction holds; the size for Gemini Flash is unmeasured.

### LLMs prefer CVs written by LLMs
**Xu, Li & Jiang, arXiv 2509.00462, Aug 2025, revised Jun 2026, AIES/EAAMO 2025 [primary].**
- **Models tested:** GPT-4o, GPT-4o-mini, GPT-4-turbo, LLaMA 3.3-70B, Mistral-7B, Qwen 2.5-72B, DeepSeek-V3. **Neither Claude nor Gemini was tested.** *(Added 2026-11-10.)*
- **Cross-model preference is mixed:** DeepSeek-V3 prefers its own output over other models'; GPT-4o and LLaMA 3.3 show no consistent preference between models. The strong, consistent effect is **LLM-written over human-written**.
- **Effect:** LLM screeners "consistently prefer resumes generated by themselves over those written by humans or produced by alternative models, even when content quality is controlled". Self-preference is **67-82%** across commercial and open models.
- **Simulated pipelines, 24 occupations:** candidates whose CV came from the same LLM as the screener are **23-60% more likely to be shortlisted**. The largest gaps are in **business roles such as sales and accounting**, the roles many of our users target.
- **Mitigation:** simple interventions targeting the model's self-recognition cut the bias by 17-63%.
- **Cuts both ways for us:**
  - (a) An AI-written CV may do better at an AI screener. But which model the employer uses is unknown, and cross-model preference is weaker.
  - (b) **Our scorer is an LLM grading CVs our own LLM wrote.** Part of any "the CV scores higher after tailoring" effect may be self-preference, not quality. **We must not use our own LLM score as proof that our CVs improved.** The benchmark (stage 7) needs judgments that don't come from our models.

### People follow the AI
**Wilson et al., FAccT 2026, arXiv 2606.22213 [primary].**
- People spend **up to 55.6% longer** on a CV when no AI recommendation is shown.
- Time spent on a non-recommended candidate raises their chance of selection by 3-4%.
- **AI recommendations reduce the careful review that would catch AI bias.**
- **For us:** our number shapes where the user spends attention (which jobs they open, which CVs they trust). A confident wrong number steers them away from good jobs. That's another reason to show *why* and *what's unknown*, not just a percentage.

### Humans vs GPT-4 on real CVs
**Vaishampayan et al., Findings of NAACL 2025 [primary].**
- **Data:** 736 real CVs to real jobs, rated by trained raters who were checked against experts.
- **Human raters agreed with each other:** Fleiss κ = **0.79**.
- **Zero-shot GPT-4 vs humans:** "LLM scores correlate minorly with humans, suggesting they are not interchangeable"; Fleiss' kappa showed **no agreement on any construct**. Chain-of-thought prompting improved it.
- **Where GPT-4 diverged:** skills (98 rating differences, **23 hallucinated skills**), education (126), certifications (170).
- **Conclusion:** LLM scores are not a substitute for a recruiter's judgment. Use them in a human-in-the-loop design.

---

## Round 7: what a parser extracts from *our* PDFs (measured locally, 2026-11-06)

- **Layout:** all five templates (t1-t5) are **single-column**. No grid, columns or floats; flex is used only for header and skills lines. The concern that Comeet's single-column reader scrambles two-column CVs **does not apply to us**.
- **English:** all five templates extract cleanly and in reading order with PyMuPDF and pdfplumber: contact block, then summary, experience, education, skills, languages and military service.
- **Hebrew:** compared against a control, the same Hebrew text in a Word document converted to PDF by LibreOffice.

| Extractor | Word/LibreOffice Hebrew PDF | Our Chromium Hebrew PDF |
|---|---|---|
| pdftotext (Poppler) | logical order, correct | **logical order, correct**; only date ranges come out reversed ("2026 - 2023") |
| PyMuPDF | logical order, correct | **word order reversed within each line** ("לקוחות הצלחת מנהל") |
| pdfplumber | letters reversed | letters reversed |

- **pdfplumber reverses Hebrew letters for any PDF.** That's a limit of the tool, not of our file.
- **PyMuPDF reads Word's Hebrew PDF correctly but ours word-reversed.** That's specific to how Chromium writes RTL text runs.
  - PyMuPDF and similar extractors feed many LLM-based screening pipelines.
  - **Our own backend parses uploaded CVs with PyMuPDF and pdfplumber** (agents/resume.py, profile_analyzer.py, cv_aggregator_service.py). Hebrew CVs uploaded by users may already be read reversed by us. To verify in the CV-ingestion stage.
- **Still unknown:** which extractor Comeet, Greenhouse and Workday use. Only a real upload answers this. The fix options (writing logical-order text into the PDF, or a different render path for Hebrew) are a decision for after the research.

---

## Round 8: what job-seeker "match rate" tools compute (the bridge to stage 4)

- **jobscan.co refuses automated access** (403 from its own server), so these points come from search results quoting its tutorial and reviews from 2026. [secondary]
- **Jobscan's match rate:**
  - hard skills (weighted most), job title, education (only when the posting asks for an advanced degree), soft skills, other keywords;
  - **word count and measurable results do not count**, though the report comments on them;
  - "predicted skills" (suggestions) don't affect the rate;
  - the target in its current tutorial is **75%** (older pages said 80%).
- **Reviewers' critique (2026):**
  - the rate is Jobscan's own keyword comparison, **not a score any employer or ATS produces**;
  - "stakeholder management" pasted into a skills list scores the same as the same skill shown in a measured bullet;
  - "a 65–75% match with honest, specific bullets beats a keyword-stuffed 95%".
- **Rezi:** its score is a *quality* grade (active verbs, quantification, formatting, word count, keyword targeting), separate from a match percentage. **Teal:** a skills-based match score. **Kickresume:** no published method. [secondary]
- **Our "ATS score for this CV" (`_phase1`) is this genre** (keywords, skills, seniority): a lexical proxy. The founder sees it as "the ATS score" and compares it to the job score, which is a different formula (Research 01, finding 1).

---

## Stage 2: conclusions (pending the Comeet upload test)

1. **There is no single "ATS score" to optimise for.**
   - Real systems either rank coarsely or judge requirement by requirement, and leave the decision to a person.
   - Automatic rejection comes from form answers.
   - Consumer "ATS scores" (Jobscan, ours) are keyword proxies of their own making.
2. **The 2025-2026 industry standard is per-requirement evaluation with evidence:**
   - must-have vs preferred;
   - met / not met / unknown;
   - a pointer to where in the CV.
   - Workday (August 2026), Ashby and Greenhouse all ship this. Greenhouse shows "Calibrated skills matched: 2 of 4" and highlights exact vs *similar* terms.
3. **Holistic LLM numbers are the weak point**, and recent research measures it:
   - on close pairs (one differing qualification) mid-size models fail to pick the better candidate 16-27% of the time, mostly by abstaining (Gemini 2.0 Flash 0.73-0.84; above 0.90 on average);
   - presentation-only changes flip 30-41% of decisions (small open models);
   - GPT-4 does not agree with trained recruiters;
   - LLMs prefer CVs written by LLMs (67-82%).
4. **Being *found* still depends on literal terms.** Recruiters search titles and must-have skills, and similar terms are matched only by some systems.
5. **Our PDFs:**
   - single-column, so no two-column risk;
   - English extracts cleanly;
   - **Hebrew extracts in reversed word order with PyMuPDF** (not with Poppler, and Word's PDF is fine). Real-ATS impact pending the Comeet test.

### Implications for the design decisions (to finalise after all stages)
- **The score:**
  - built from per-requirement verdicts (met / partly / not met / **unknown**) with a CV quote each;
  - must-haves separated from nice-to-haves;
  - knockouts shown explicitly;
  - the number computed deterministically from the verdicts, and possibly shown as a band, not a one-decimal percentage.
- **Unverified information** the user gave Ariel: counted as **"stated, not yet verified"**, shown as such, and not silently turned into a lower score. *(The founder has adopted this.)*
- **Never use our own LLM's judgment of our own LLM's CV as proof of quality** (self-preference). Validation needs judgments from outside our models (stage 7).
- **Two different numbers must not be shown side by side as if comparable.**

---

## 2026 sweep: re-checking stage 2 against the newest evidence (2026-11-07)

| Earlier assumption | 2026 evidence | Status |
|---|---|---|
| The industry is moving to per-requirement evaluation with evidence | **Workday Fit & Gap, August 2026** (primary). **Systematized review of recruitment AI through September 2026** (arXiv 2609.04286): "Mature systems still need lexical recall, structured constraints, inexpensive rankers, and human approval"; a credible system must "**distinguish unknown from negative evidence, ground consequential claims**", and "**final-output scores conceal pipeline failures**". | **Strengthened** |
| "Unknown" should be its own state | **"Beyond the Name", 2026** (arXiv 2609.16501): forcing a choice between two equal CVs **manufactures** a spurious selection ratio of 0.39 with position effects; **allowing ties gives ≥94% ties** for most models. A scorer forced to output a number invents differences. | **Strengthened**: our 0-100 forced output is exactly this design |
| LLM screeners show racial bias (Wilson & Caliskan, 2024) | **Gao, Jiang & Yan, June 2026** (arXiv 2606.28978), 14 models, 24,024 paired postings each: the 2023 model reproduces the pro-White gap; **every model released in 2024 or later shows a null gap or a pro-Black reversal** (up to −3.01 pp). Same on gender. | **Changed:** bias direction depends on the model generation. 2024 findings about specific models don't transfer to current models; each model must be audited as deployed. |
| LLM screeners are unstable | **Presentation sensitivity, September 2026** (29.6-41.4% flips, small models). **"Bias in the Tails", 2026** (arXiv 2604.19984, about 1M LLM-written CV summaries, 4 models): **factual content stays stable; evaluative framing ("exceptional", "proven") varies** with the candidate's name, at the extremes. | **Strengthened.** New for CV writing: evaluative adjectives are the unstable, bias-carrying part. Facts are the stable part. |
| Holistic scores vs per-criterion | **AutoScreen-FW, 2026** (arXiv 2603.18390): open models with a few chosen examples **plus explicit evaluation criteria** beat GPT-5-nano and sometimes GPT-5-mini at CV screening. | **Strengthened:** explicit criteria matter more than model size |
| Legal exposure of AI screening | **Mobley v. Workday, June 2026:** most of Workday's motion to dismiss was denied; age, disability and California (FEHA) claims proceed; the age collective's opt-in closed 7 March 2026. Allegations, not findings. | **Strengthened:** AI screening is under active litigation |
| EU AI Act timing | **Digital Omnibus adopted:** Regulation (EU) 2026/1744, in force 27 July 2026. **High-risk Annex III (employment) obligations moved to 2 December 2027.** | **Confirmed** (was "sources differ") |
| LinkedIn as a search channel | **LinkedIn Hiring Assistant 2** (announced September 2026, rolling out to English customers in November 2026): recruiters type non-keyword criteria that the agent interprets and they confirm. **"Trust signals"** combine verification, ATS data, pre-screening answers and **work history, and flag inconsistencies.** | **New:** CV-to-LinkedIn consistency is now machine-checked. See Research 03 on locking role titles. |
| Comeet | No 2026 screening announcement found. A 2026 review site lists "Candidate Match Insight Agent" and "Sourcing Agent" without details; plans mention "AI resume reviews". Comeet states its AI "will never make hiring decisions on its own." | **Unchanged.** Still needs the real test. |

---

## Pass 2 corrections and additions (2026-11-10)

Full detail in `00-gap-map.md`, section 5. Changes that touch this stage:

- **Correction, SmartRecruiters:** round 2 said "1-5 stars" from a secondary source. SmartRecruiters' own Winston Match FAQ describes **four bands (Very high, High, Medium, Low)**, built from separate models for skills, work experience, education, career progression and job-title relevance, weighted per job from real hiring outcomes. [primary]
- **Eightfold, own page:** deterministic matching models, plain-language reasons, skills shown to the candidate, no autonomous rejection or advancement. [primary]
- **Textkernel, own FAQ:** Hebrew is in the list of 29 CV-parsing languages. [primary] Possibly beta per the developer docs. [secondary]
- **Indeed, 2026:** its own team calls zero-shot LLM scores unstable across identical inputs and moved to a deterministic 1-5 grade read from token probabilities. [abstract and intro]
- **ManpowerGroup, 2026:** production matching fuses semantic vectors with full-text keyword relevance. Literal terms and meaning are both used. [abstract]
- **Pagan et al., Oct 2026:** Claude and Gemini are now covered. Gemini 3.5 Flash is the most favoured *writer*; Claude Sonnet 4.6 the best *evaluator*; self-preference is not the mechanism. [read]
- **Still unread in the primary:** SAP SuccessFactors, Oracle, iCIMS knowledge base, Workable, Comeet.
- **Pass 3 (same day):** Oracle and Workable read on their own pages; see `00-gap-map.md` section 6. Oracle: four 0-5 ratings (education, experience, skills, profile). Workable: must-have and disqualifier criteria, a score out of 100, and **optional automatic disqualification**. The earlier wording "no system rejects on its own" is narrowed accordingly. PDFium added as a fifth engine: it reverses Hebrew word order for our PDF and for the Word control alike.
- **Correction (2026-11-12):** these notes and `00-gap-map.md` say all five templates are single-column. The Tech Modern template has a dark sidebar holding skills, languages and military service. Measured in the template file; see `06-cv-generation.md` section 17.
