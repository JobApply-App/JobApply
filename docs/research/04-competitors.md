# Research 04: how job-seeker tools compute and show "match" (2026)

Stage 4 of the scoring/CV research (2026-11-11). Question: how do the tools a job seeker can buy today calculate a match or ATS score, how do they present it, what do they claim, and what does their own data show?

**Evidence weighting:** 2026 first; 2025 valid but older; earlier is background.

**Marks:**
- **A**: read on the vendor's own page in this pass.
- **B**: vendor's own page, seen only through search excerpts.
- **C**: third-party reviews.
- Everything a vendor says about itself is a claim, not a measurement. Vendor *data* reports are observational and come from that vendor's users.

**Could not be read directly:** Jobscan and Teal block automated access (403). LinkedIn and Indeed publish little. Israeli tools were found only through search.

---

## 1. What each tool does

| Tool | What the number is | Scale and target | How it is built | What it says about real ATSs | Mark |
|---|---|---|---|---|---|
| **Jobscan** | "Match rate": CV vs one posting | 0-100; **target 75%** (older pages said 80%); its homepage adds that many succeed at 65% | Keyword comparison. Older material: hard skills weighted most, then title, education, soft skills. Current scanner page lists five categories including relevant skills, job level match, experience alignment | Calls the rate "a Jobscan visualization tool, not a score assigned by the employer's ATS" | B/C |
| **Teal** | Two numbers: a **match score** (paid) and a general **resume score** | Resume score: **80%+** is "good" | Match: keyword overlap with one saved posting. Resume score: structure, measurable results, keyword use, content strength | No statement found | B/C |
| **Rezi** | "Rezi Score": a **quality and readiness** grade, not a match | 1-100; **90+** ready, 50-89 improve, under 50 rework | Five areas: content, format, optimization (keywords from the posting), best practices, application readiness. Updates live while typing | "**Real ATS systems don't give your resume an official score.** Recruiters won't see the same percentage" | A (July 2026) |
| **Careerflow** | Two separate numbers: **Skill Match Score** and **Resume Analysis Score** | Match: **55-60%+** is the target | Match: keywords in the posting found in the CV, graded strong / partial / missing; score rises per keyword added. The user can mark a required skill "irrelevant", which removes it from the denominator | "Not a measure of your actual competence; it's a measure of the keyword alignment between two documents" | A (Nov 2026) |
| **Resume Worded** | "Score My Resume" (quality, 20+ checks) and "Targeted Resume" (missing keywords) | 0-100; reviews cite 85+ as good | Impact, brevity, style, bullet-level checks; separate keyword gap list | States that a CV lacking critical keywords "will be instantly rejected" | A |
| **Huntr** | "Match Score" inside the resume tailor | 0-100 in marketing; in-product bands **poor / fair / great coverage** | "Semantic match, every responsibility and qualification, not just keywords"; shows what is covered and missed; the user approves each AI change | None | A |
| **Jobright** | AI job matching; per-job explanation of "why I am a good fit" | Not published | Not published ("trained on 10 million job descriptions") | None | A (marketing only) |
| **Simplify** | CV score plus missing skills and keywords; "Autopilot" applies for the user | Not published | Not published | None | A (marketing only) |
| **LinkedIn Job Match** | Free: which required and preferred qualifications the profile meets. Premium: a **High / Medium / Low** label | Three bands | Not published. LinkedIn's help text: "a match summary that highlights required and preferred qualifications" | It *is* the platform | A for the free summary; C for the bands |
| **Indeed** | Employer side: "Smart Fit Score" 0-100. Job-seeker side: no visible score found | n/a | Not published | n/a | B |
| **Kickresume** | No published match method | n/a | n/a | n/a | A (stage 2) |

### Where JobApply sits
- Our **match score** blends an LLM judgment with structural terms on 0-100, and (stage 1) is broken in its structural part.
- Our **"ATS score for this CV"** is the same genre as Jobscan's and Careerflow's numbers: a lexical keyword proxy.
- Unlike Careerflow, Teal, Rezi and Resume Worded, we show the two numbers on one scale without saying they measure different things.

---

## 2. Patterns across the market

1. **Every "ATS score" sold to job seekers is the vendor's own keyword comparison.** No tool reproduces a score that an employer's system produces. Two vendors say so in writing (Rezi, Jobscan). Careerflow says its score measures only keyword alignment between two documents, yet in the same article tells users to aim for 55-60% "to pass initial screening", which implies a link it does not show. Confidence: high.
2. **The targets are arbitrary and incompatible.** "Good" is 55-60% at Careerflow, 75% at Jobscan, 80% at Teal, 85 at Resume Worded, 90 at Rezi. The same number means different things in each tool, and none publishes evidence for its threshold. Confidence: high.
3. **The mature tools split the number in two:** *match to this job* and *quality of the document*. Careerflow, Teal, Resume Worded and Rezi all keep them apart. Confidence: high.
4. **The direction of travel is from a bare percentage to a list:** covered / partial / missing per requirement (Careerflow, Huntr, LinkedIn's free summary), with bands in place of digits (LinkedIn High/Medium/Low, Huntr poor/fair/great). This matches what the employer-side systems do (stage 2). Confidence: medium-high.
5. **Scores can be gamed by design.** Careerflow lets the user drop a requirement from the denominator; every keyword tool rises when a word is pasted in. Reviewers and one Israeli recruiting consultant make the same point: the number measures closeness of wording, not depth. Confidence: high.
6. **No independent validation exists.** I found no study, by anyone other than a vendor, linking any tool's score to interviews, and no independent test of several tools on many CVs. Reviews show the same CV scoring 18 to 30+ points apart across tools, but those reviews are written by competitors. Confidence: high that the gap in evidence is real.
7. **Vendors disagree with each other on the facts.** Resume Worded says a CV without keywords is "instantly rejected". Rezi and Enhancv say ATSs do not reject on their own. Enhancv asked 25 US recruiters: **92% said their system does not auto-reject on content or format; 8% had content-based auto-rejection configured; all used knockout questions.** This agrees with stage 2.
8. **The newest tools move past the CV.** Jobright and Simplify both surface people the user knows at the company ("insider referrals"), and both offer automated applying. LinkedIn is going the other way: it caps Easy Apply per day and per burst to curb automation.

---

## 3. What the vendors' own 2026 data shows

These are observational numbers from each vendor's users. They show association, not cause.

### Huntr, Q3 2026 (84,753 applications, 4,796 users, 23,055 tailored CVs; read in full) [A]
- **Interview rate per application: entry-level titles 3.9%, senior titles 6.4%.**
- **Selective appliers do better:** 11-20 applications, 8.0% interview rate; 100+ applications, 2.4%.
- **Same person, two channels:** employer career site 6.2% vs job board 4.9%; former employer 17.6% vs 8.6% elsewhere.
- **Applying below one's level is penalised:** applicants with 10+ years got 3.0-3.9% on entry-level titles vs 5.5-6.6% on senior titles.
- **CV length shows no clear link to interviews;** two pages did as well as one at every career stage.
- Remote-only jobs 3.4% vs hybrid and onsite 5.5%.
- Survey (329 job seekers): **82% have used an AI chatbot on their CV; 63% of those say the AI put false details in it;** 25% would use AI to exaggerate; **88% say their CV leaves out important work; 33% say putting numbers on results is the hardest part;** 64% tailor for most or every application.
- Huntr's stated limits: users log their own outcomes; same-person comparisons do not remove differences in timing or in which jobs were chosen.

### Huntr, Q1 2026 (139,927 applications) [A]
- **Tailored CVs 4.23% vs untailored 2.07%**: "the largest single advantage in our resume data". "Untailored" includes CVs edited by hand outside the tool, and people who tailor may differ from those who do not.
- A summary with a dollar figure 6.97% vs a summary with no digits 4.78%. Huntr itself: "suggestive rather than ironclad".
- Employment gaps: under 3 months 4.39%, about the same as employed (4.19%); 1-2 years 3.44%; 2+ years 3.25%.
- More bullets, higher rate: 1-10 bullets about 4.9%, 21-30 bullets 7.92%.
- **The two Huntr reports disagree on length:** Q1 says two pages beat one by 48% overall; Q3 says no clear link. Treat length as unsettled.

### Enhancv, 2026 [A]
- Two-column test (357 runs): the words survive in almost every extractor, **the reading order does not**; under the worst extraction method, sections stayed intact 35% of the time with two columns vs 60% with one.
- "Does ATS detect AI resumes?": none of the ten largest ATSs ships AI-text detection.
- Photo: among CVs their customers flagged as "got me hired", 49.9% had a photo vs 39.8% of all downloads. Self-selected and observational. It **conflicts** with the Israeli field experiment in stage 3 (women without a photo got more callbacks). Photo stays unsettled.

### What this adds to stage 3
- **Tailoring:** a second 2026 source (after Kickresume) with tailored at about double untailored, in salaried hiring. Both are observational or small. Stage 3's "required, not differentiating" stands, with more weight on *required*.
- **Fabrication by AI CV tools is reported by users themselves** (63%), not only measured in a lab (96.7% in stage 3's study).
- **Overqualification is penalised by real employers** (Huntr). Our scoring rule that overqualification is never a deduction (CLAUDE.md principle 3) describes what we want the score to *encourage*, not how employers behave. If the score is meant to say "your chance of an interview", this is a tension the founder should decide on knowingly.
- **Juniors face lower odds per application** (3.9% vs 6.4%), a third source for stage 3's conclusion 9.

---

## 4. Claims in competitors' marketing that the evidence does not support
- "Tailored resumes get 2x more interviews" (Huntr): from its own observational data; real association, causation not shown.
- "3x interviews landed" (Jobright), "4x with insider referrals" (Jobright), "38% more likely to get hired" (Indeed Career Scout): no method published.
- "Rejected instantly without keywords" (Resume Worded); "90% of CVs don't pass the automatic filter" (an Israeli tool): contradicted by stage 2 and by Enhancv's recruiter interviews.
- Huntr's own before-and-after example turns "Built backend services for the main product" into "...handling 50M+ daily transactions across 12 microservices". The numbers appear from nowhere. That is the fabrication pattern, used as an advertisement.

---

## 5. Confidence, and what is still missing

| Conclusion | Confidence |
|---|---|
| Consumer "ATS scores" are vendor keyword proxies; no employer sees them | High |
| Thresholds differ by tool and are unvalidated | High |
| Splitting "match to job" from "document quality" is standard among mature tools | High |
| Per-requirement lists and bands are replacing bare percentages | Medium-high |
| No independent evidence that any score predicts interviews | High (absence searched for, not proven) |
| Tailored beats untailored by roughly 2x in vendor data | Medium (two vendor sources, both confounded) |
| Auto-apply at volume yields low interview rates | Low-medium (vendor blogs and anecdotes only; LinkedIn's caps are primary) |

**Not done, and why:**
- Jobscan's and Teal's own method pages: both refuse automated access.
- Israeli tools (Runner, Rezume and others): hosts not reachable; only search excerpts. No Israeli tool was found that publishes how it scores.
- Running the same CV through several tools: every tool needs an account. This is a 30-minute manual test the founder or I could do with sign-ins.
- Pricing and feature tables: left out on purpose; they do not bear on scoring.

---

## 6. What this means for JobApply (inputs to the decisions, not decisions)
1. **Do not sell a number as "the ATS score".** No such thing exists, three competitors already admit it, and the claim is the most criticised part of this market. An honest label is a differentiator.
2. **Show two things, separately:** *fit to this job* (per requirement: met, partly met, missing, unknown) and *CV readiness* (parsing, structure, clarity). Never on one shared scale.
3. **Bands over digits for fit**, with the reason per requirement. This is where LinkedIn, Huntr and the employer-side systems have landed.
4. **Do not let the score reward pasting keywords.** Credit a requirement only when the profile holds evidence for it. That is the gap every competitor leaves open, and it is where Ariel and the confidence data give us something they lack.
5. **"Unknown" is a state competitors do not have.** They read only the document, so anything absent is "missing". We know which skills are stated but unverified. Showing "stated, not yet verified" (the founder's adopted idea) is new in this market.
6. **Refusing to invent is a sellable feature.** 63% of AI users report false details added to their CV.
7. **Referral help is becoming standard** in the newest tools. It was the largest lever in stage 3.
8. **Be honest about odds for juniors and for people applying below their level.**

---

## 7. Two Israeli products the founder asked about (read 2026-11-11)

Both were opened in a real browser. Everything behind a login was not seen. **Weight:** these are product pages and legal documents, not evidence about hiring. They show what Israeli competitors offer and promise, nothing about what works.

### Tobi (tobi2.com)
**What it is** [A: landing page, terms of use, privacy policy v1.0 dated 15 Oct 2026]:
- An "AI agent that finds relevant jobs and submits your CV across the web". The public site is only a login page, a one-minute video and the legal pages. "1,500+ people already using the tool".
- Operated by Colors Intelligence Ltd, Tel Aviv, which also has products named Colors and "CV Ai".
- The logos on the page list its targets: LinkedIn, Indeed, Glassdoor, AllJobs, Drushim, JobMaster, Jobnet, Ethosia, Comeet, Greenhouse, Lever, Ashby, Workday, SmartRecruiters and others.

**How it works, from its own legal text:**
- The user uploads a CV, sets preferences and names target sites in a chat. Tobi opens those sites in a **cloud browser**, the user logs in to their own accounts there (typing directly, or handing credentials to the chat for that session), and Tobi then **finds jobs, rates their fit with AI, decides whether to apply, fills the forms, answers screening questions from a stored "answers bank", and submits**.
- **No approval per application.** The terms say submissions happen "automatically, on the basis of its fit assessment, without your individual approval of each submission", and that a submission "cannot usually be cancelled or corrected".
- "AI output" is defined to include the **fit score, the decision to apply, the choice of CV, wording adjustments and answers to questions**. The company disclaims any error in all of them, and also "an irrelevant submission, a duplicate, a submission to your current employer or to a competitor".
- The terms state that many sites forbid automation, that the user picks the sites and carries that risk, and that the company is not liable if a target site restricts or blocks the user's account.
- Paid by monthly subscription plus internal "tokens" consumed per action.
- It keeps a full activity log: jobs found, fit ratings, decisions, what was sent, screenshots of the filled forms.
- **How the fit score is computed is not published anywhere.**

**Observations:**
- The privacy policy still contains an unfilled placeholder, "[storage locations]", in the section on data leaving Israel. A sign the legal text was generated or templated and not finished.
- This is the mass-apply model. The evidence gathered so far points against it: selective appliers get interviews at about three times the rate of volume appliers (Huntr 2026, observational); LinkedIn caps automated applying; and recruiters are drowning in volume (stage 3).
- **Worth taking:** the activity log and the stored answers to screening questions. Stage 2 found that screening questions, not CV text, drive automatic rejection, and Ashby's data shows forms now ask twice as many questions as four years ago. Helping a user answer them well and consistently has real value, with the user approving.
- **Not worth taking:** applying without the user's approval, and logging in to the user's accounts on other sites. Both shift legal and reputational risk onto the user, and conflict with our "never invent, never act behind the user's back" position.

### Secret Hunter (secrethunter.io)
**What it is** [A: home page, premium page, employer page, footer; the blog, the "state of jobs" page and the AI-matches page did not load content or need a login]:
- An Israeli job-search site whose pitch is supply: "We pull secret jobs straight from company career pages", "we scan over 4,130 companies in Israel".
- Free: search, saved searches, a job tracker, WhatsApp and Telegram job channels, mobile and desktop apps.
- **Premium, 59 NIS a month:** alerts "two hours before everyone", the full job database, a "CV agent" that tailors the CV per job "and makes sure it passes ATS screening", unlimited AI CV checks, and **automatic applying to "8,000+ jobs"** ("while you sleep").
- "AI Matches": "every job is ranked and surfaced only if it fits you". **No method or scale is published.**
- A "Referrals Network" page exists and is empty ("No referrers yet").
- Employer side: paid job promotion, ads in its channels, a candidate database, and a **Comeet integration**. Its own figures to advertisers: 35K monthly active users, 38K channel subscribers, 28K email subscribers.

**Observations:**
- Its real asset is **job supply and distribution** (career-page scanning, WhatsApp and Telegram), not scoring. This is the area the founder's list already has under "job supply". It is also the hardest part to copy quickly.
- Its income comes from both sides: job seekers pay for speed and automation, employers pay for exposure. A product that takes employers' money to promote jobs has a weaker claim to an honest fit signal. Our one-sided model is an advantage for "should I apply" honesty.
- "Passes ATS screening" is the same unsupported promise as elsewhere in this market (section 4).
- **Worth taking:** direct career-page sourcing as the supply strategy; job alerts on channels people already use (WhatsApp, Telegram); speed of alert as a paid benefit.

### What the two add to the picture
1. Both Israeli products compete on **automation and volume** (apply for me) and on **supply** (jobs others miss). Neither competes on honesty of fit or on the quality of evidence in the CV. That space is open locally.
2. Neither publishes how it rates fit. In Israel, as abroad, the score is a black box.
3. Both lean on automatic applying, which the 2026 data and LinkedIn's own policy point against.

---

## 8. Founder decisions recorded on 2026-11-11
These settle open points from stages 3 and 4. They are product decisions, not research findings.

1. **Source weighting:** many competitor sites are themselves built and written with AI. Use them for ideas only. Conclusions rest on verified research first (peer-reviewed or primary data), vendor material second.
2. **CV length:** **one page is the default.** Two pages stay available as an option where the case needs it. (The data is unsettled, so this is a judgment call, and a reasonable one.)
3. **Photo:** **none for now**, for privacy reasons.
4. **Fabrication and AI-style writing:** a standing priority. The CV must contain nothing the profile does not support, no unrelated words, and no AI-writing tells; it should read in the plain, correct register of a CV. A dedicated research stage on how to build the CV follows (stage 6).
5. **Running the same CV through several competitor tools:** deferred. To be done later with the founder's sign-ins, and it can run on a cheaper model. Reminder kept here so it is not lost.
