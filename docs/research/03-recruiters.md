# Research 03: what recruiters actually check (2024 onward)

Stage 3 of the scoring/CV research. Working notes, built up over several rounds.

> **Read the last section first: "Stage 3, verified" (2026-11-11).** It audits every claim below against its source, corrects six of them, adds the topics that were missing, and states the conclusions with a confidence level. Where the two disagree, the last section wins.


**Source marks:**
- **[primary]**: the original study or the vendor's own page.
- **[secondary]**: a report about it.
- **[vendor survey]**: a survey run by a company that sells CV or hiring products. Treat its numbers as directional.

---

**Evidence weighting (founder, 2026-11-07):**
- **2026 findings carry the most weight.**
- **2025 is valid but already older.**
- **Anything earlier is background.**
- Everything is still researched, and the notes record where newer work changes older work.

## Round 1: the AI-era recruiter

### Volume and AI-written applications
- Recruiters report a flood of low-effort, AI-generated applications. "90% report an increase in low-effort or spammy applications, largely driven by AI tools". [vendor survey, 2025, via search]
- **Greenhouse survey, November 2025:** 65% of hiring managers had caught applicants using AI deceptively, including scripted answers and **hidden prompt injections in CVs**. [vendor survey, via search; primary to fetch]
  - Hidden text aimed at AI screeners is now something recruiters look for. **Our CVs must never contain anything that looks like it**, such as invisible keywords or white text.
  - Our HTML guard tests (`test_html_guard.py`) already check for hidden-text CSS.
- **Can recruiters tell AI-written CVs?**
  - 53% *say* they can [Insight Global, vendor survey].
  - In a blind test only **33.5%** correctly spotted the AI-generated CVs among four [TopResume, vendor test].
  - Self-belief exceeds ability.
- **What gets a CV rejected is *generic* content, not AI use as such:**
  - 36% name generic content as a top rejection reason;
  - 62% say AI CVs *without personalisation* are more likely rejected [Resume Now, vendor survey];
  - "a stack of applications where the language is indistinguishable from one candidate to the next".
- **Implication for our CV generation:** the risk isn't "sounds like AI", it's "**sounds like everyone else**". Specific, verifiable detail tied to *this* job and *this* person is what separates a CV.
  - This lines up with the founder's complaint ("not banal") and with the self-preference finding from stage 2: AI-polished sameness may please an AI screener and bore a human.

### How long does a recruiter look, and at what?
- **No peer-reviewed eye-tracking study from 2024 onward was found.**
- The famous "6-7 seconds" comes from TheLadders, 2012 (6 s) and 2018 (7.4 s, 30 recruiters). **[historical]**
  - Reported first-pass targets: name, current title and company, previous title and company, dates, education.
- 2024-2025 figures (InterviewPal 2025, about 11 s with structured tools; ResumeGo 2024, a survey) have no verifiable methodology. [secondary]
- **Usable takeaway:** a first pass that scans *titles, companies, dates* still describes the reader. **The current title line and the most recent role carry the first impression.**
  - The same conclusion came from Comeet's AI summary of the most recent role in stage 2.
  - Treat it as plausible, not measured.

### Skills-based hiring: what employers say vs what they do
- **Burning Glass Institute + Harvard Business School, 2024**, "Skills-Based Hiring: The Long Road from Pronouncements to Practice":
  - **removing degree requirements changed actual hiring in fewer than 1 in 700 hires**;
  - nearly all real change came from 37% of firms;
  - at "skills-based hiring leaders", non-degree hires were retained 10 percentage points better. [primary landing page via search; PDF to read]
- **Implication:**
  - Degrees and titles still drive real decisions even where postings say "skills first".
  - Our score should not pretend a missing degree doesn't matter when the posting lists it. It should show it plainly (requirement met / not met), not hide it in a blend.
  - Equally, **transferable skills don't get credited by most employers in practice**. The CV must translate them into the posting's literal terms; our scorer giving pivots credit (CLAUDE.md principle 3) is right for the *user's* view, but the CV still has to make the case explicitly.

### LinkedIn data, 2025-2026
- **LinkedIn "Future of Recruiting 2025"** (1,000+ talent professionals): only **11%** were actively integrating generative AI into hiring, 26% experimenting, 32% not exploring. [primary page via search]
  - In 2025 most recruiters still read CVs themselves. AI screening is growing but not yet the norm, so **writing for a human reader stays the priority**.
- **Skills needed for the average job have changed about 25% in recent years**, and LinkedIn expects about 70% by 2030. The share of jobs listing an AI-literacy skill rose more than six-fold in a year. [LinkedIn Work Change report, January 2025]
- **Hiring slowed 3% in 2024 (vs 12% in 2023).** LinkedIn attributes it to macro conditions, not AI. [primary]
- **Application volume per job:** no official figure. Third-party claims (for example "34% of submissions via auto-apply tools") could not be traced. [unverified]

### Open questions for round 2
- Read the primary reports:
  - LinkedIn Future of Recruiting 2025;
  - the Greenhouse November 2025 hiring survey;
  - the Burning Glass/HBS 2024 PDF.
- **Measured evidence (2024+) on what raises callbacks:**
  - quantified achievements;
  - tailoring to the posting;
  - CV length;
  - photos (an Israeli norm question);
  - referrals.
  - Correspondence/audit studies (fake applications measured for callbacks) are the gold standard.
- **Israeli recruiters specifically:** what Israeli tech and non-tech recruiters say they read first, language expectations, military service, and the place of the "תמצית" (summary).
- **Hiring managers vs recruiters:** what each screens for.

---

## Round 2: does AI-written or tailored writing actually get people hired? (three causal studies, read in full)

Question I asked myself: *if everyone now tailors with AI, does tailoring still help? And if not, what does?* Three studies answer it from different angles. All three are on online labour platforms (Freelancer.com and a large freelance market), which limits how far they generalise to salaried jobs. See the self-check at the end.

### 1. Better writing helps employers see ability
**Wiles, Munyikwa & Horton, *Management Science* 71(12), 2025; NBER w30886 [primary].**
- **Field experiment:** about 500,000 jobseekers. The treated group got algorithmic writing help on their CVs (grammar and clarity). **Hired 8% more often.**
- **No drop in employer satisfaction.**
- **Their model:** better writing "does not signal ability but helps employers ascertain ability".
- **Date caveat:** the experiment predates ChatGPT (the paper is from 2023), and the tool fixed errors and readability; it didn't generate content. **[historical design, 2025 publication]** Read it as "clarity helps the reader judge", not as "AI-generated text helps".

### 2. After LLMs, tailoring stopped carrying information
**Galdin & Silbert, arXiv 2511.08785, 2025, Freelancer.com [primary].**
- **Measure:** an LLM measure of how tailored each application is to its posting.
- **Before LLMs, employers paid a premium for more customised applications. After LLMs, they didn't.**
- **Structural model:** if written applications become useless as a signal, **top-quintile workers are hired 19% less often and bottom-quintile workers 14% more often.** The market becomes less meritocratic.

### 3. The individual gain is real but small, and fades
**Cui, Santamarina & Ye (Yale), arXiv 2509.25054 v2, November 2025, Freelancer.com [primary].** An AI cover-letter tool launched on the platform.
- **Tailoring:**
  - access raised it by 0.16 SD;
  - actual use raised it by 1.36 SD.
- **Callbacks:**
  - access (everyone offered the tool) **+0.43 percentage points, about +6%** on a 7.02% base;
  - actual use **+3.56 pp, about +51%**;
  - **significant only at the 10% level, and the effect "tapered off after two months."**
- **The signal collapsed:** the correlation between a cover letter's alignment with the posting and callbacks **fell 51%**. **Employers shifted to other signals, "including workers' prior work histories"** (on that platform: review scores and past jobs).
- **Editing matters (correlational, within worker):** "most workers submit AI-generated drafts with minimal revision", but **more time spent editing the AI draft is associated with higher hiring success.**

### What the three studies say together
1. **Clarity and readability help** (Wiles). A clean, error-free, easy-to-scan CV lets the reader see ability. This is lasting value.
2. **Tailoring as such has stopped differentiating** (Galdin & Silbert; Cui et al.). When everyone mirrors the posting, mirroring carries no information. The early advantage for adopters faded within about two months.
3. **Employers move to evidence that is hard to fake:** work history, track record, verifiable outcomes (Cui et al.).
4. **Personal input on top of the AI draft goes with better outcomes** (Cui et al., correlational).

### Self-check: what I'm sure of and what I'm not
- **Sure:** the three results, their sizes and their caveats, read from the papers themselves.
- **Not sure:** whether freelance platforms generalise to salaried Israeli jobs.
  - Freelance employers see review scores; salaried recruiters see a CV.
  - That cuts *both ways*. With no review score, the CV's content (titles, companies, dates, outcomes) **is** the hard-to-fake evidence. That strengthens, not weakens, the conclusion that **concrete, verifiable facts** are what still separates candidates.
  - **To keep looking for:** a post-LLM study on salaried hiring.

### Implications for our CV generation (input to the final design)
- **Mirroring the posting is no longer enough.** It's table stakes. Literal keywords still matter for *being found* (stage 2), but they don't differentiate.
- **What differentiates is the evidence layer:**
  - real numbers;
  - scope (team size, accounts, budget);
  - concrete outcomes;
  - recognisable companies and titles, stated plainly.
- This is exactly what Ariel's probing collects. **The value of the product moves from "writing" to "extracting true specifics from the user"**, which an LLM alone can't invent.
- **The user's own edits are part of the value.** The live editor and the "personal touch" step should be encouraged, not skipped.
- **Clarity beats flourish** (Wiles): short, readable, error-free. And no AI polish for its own sake, since polish is exactly the presentation axis that flips LLM screeners (stage 2) and reads as generic to people (round 1).

---

## Round 3: salaried hiring after LLMs; Israeli recruiters; cross-checking

### Is there a post-LLM causal study of *salaried* hiring?
- **Not found** after a targeted search (2025-2026). The causal evidence is from freelance platforms (round 2). Lab work exists (LLM screeners, self-preference, gender bias in callbacks: arXiv 2504.21400, not yet read).
- Hiring-manager surveys exist ("80% say they can identify AI CVs"; "49% dismiss CVs they identify as AI"), but they are self-reported vendor surveys [vendor survey], and the blind test in round 1 (33.5%) contradicts the self-belief.
- **Status:** an open gap in the literature. I'll check again in later stages and won't draw salaried-market conclusions beyond what round 2 supports.

### Israeli recruiters [secondary: Israeli recruitment firms' and job sites' guides; no representative Israeli survey found]
- **First screen:**
  - recent roles, keywords, company names and years of experience;
  - **about half of recruiters spend up to 30 seconds** on the first screen [Manpower Israel guide].
- **Red flags:**
  - unexplained gaps;
  - **inconsistent dates**;
  - generic descriptions;
  - spelling errors [mojob].
- **Personal details:**
  - name, phone, email and city are enough; no date of birth or marital status [taasiya].
  - **No photo in high-tech and international companies** [owlapply].
- **Military service:**
  - relevant "only if it relates to the job" [Manpower];
  - other guides list it as a standard part of an Israeli CV.
  - Our product keeps it as its own section, and Ariel is told meaningful roles matter. The two views are compatible: **show it; give it bullets only when relevant**.
- **High-tech:** projects, GitHub and open-source count as much as formal roles. **Recruiters check LinkedIn against the CV** [easystudyai].
- **Robert Half (Brazil, 774 professionals, via ynet):**
  - the most common falsifications are **exaggerated technical skills and inflated job titles**;
  - **58% disqualified candidates early because of inconsistencies in the CV**.
  - Not Israeli, but consistent with the Israeli guides.

### Finding about our own product: role titles are not locked
- **Degree and institution** are marked "copy exactly from profile", and education is re-injected from the profile after generation.
- **The role title** (`experience[].role`) has no such rule in the prompt, and nothing after generation restores the profile's title. The model is free to rewrite it toward the posting's wording.
- **Why that's a risk:**
  1. recruiters cross-check LinkedIn;
  2. inflated or changed titles are a top falsification flag;
  3. inconsistency is a top early-rejection reason.
- **Not yet measured:** how often our CVs actually change a title. To check in stage 6 (generated CVs vs profiles).
- **A likely direction for the design:** keep the official title (localised in Hebrew is fine). Where the posting's wording differs, put the relevant term in the summary or a bullet, never in the title.

---

## 2026 sweep: re-checking stage 3 against the newest evidence (2026-11-07)

| Earlier assumption | 2026 evidence | Status |
|---|---|---|
| Tailoring no longer differentiates (Galdin & Silbert 2025; Cui et al. 2025, freelance) | **Kickresume field experiment, April-June 2026** (vendor, 204 real applications, customer service and sales): a **generic** AI CV got 10% positive responses vs **18% for an AI CV tailored** to each vacancy. | **Refined, not reversed.** In salaried CS/sales hiring in 2026, tailored still beat generic. The freelance studies say tailoring stopped *separating strong from weak candidates* when everyone does it. Both hold: tailoring is **required to stay in the race**, not enough to win it. The vendor sample is small; weight accordingly. |
| What employers fall back on: hard-to-fake evidence | **CV audit, 2026** (arXiv 2604.01933; 36,880 applications to 9,220 US graduate postings): callback gaps for non-White-male applicants are 18-28% in management roles. **Randomly assigned credentials narrowed the gaps only where applicants are judged against structured criteria**; gaps are smaller where ads mention tests, certifications or background checks. | **Strengthened:** verifiable credentials carry weight, most where screening is structured |
| Structured elicitation finds what matters | **Jabarian & Henkel, "Voice AI in Firms"** (arXiv 2607.28222 v2, September 2026; natural field experiment, 70,000 applicants): AI-interviewed applicants got **12% more offers**, with more starts and better retention and no productivity loss. The mechanism is "controlled variance": structured yet responsive interviews **collect more hiring-relevant information**. | **New, and directly relevant to Ariel:** structured, adaptive questioning extracts better evidence than unstructured conversation. Supports making Ariel's probing more structured (per requirement), not freer. |
| Recruiters suspect AI and fraud | **Checkr 2026** (about 3,000 US hiring managers): 86% saw hiring fraud in the past year; **67% suspected AI misrepresentation (up from 59% in 2025)**. **RefAssured, September 2026:** only 16% of HR and hiring managers fully trust an AI screen without humans. **Gartner** (candidates, 2,918): 26% trust AI to judge them fairly, while 52% think it already screens them. [vendor surveys] | **Strengthened:** suspicion is rising year over year. Fabrication risk is the main thing our grounding gate must prevent. |
| CV/LinkedIn consistency matters | **LinkedIn Hiring Assistant 2** (November 2026 rollout): automated trust signals across verification, work history and pre-screening, **flagging inconsistencies**. | **Strengthened, now automated.** The "role titles are not locked" finding moves up in priority. |
| Writing quality helps employers see ability (Wiles 2025, pre-LLM data) | No 2026 replication found. | **Unchanged; older evidence.** |
| A post-LLM causal study of salaried hiring | Still none found; the 2026 vendor experiment above is the closest. | **Gap remains** |

### What the 2026 evidence changes in the working conclusions
1. **Tailoring:** required, not differentiating. Keep tailoring (2026 salaried data), but put the product's weight on **verifiable, specific evidence**.
2. **Evaluative language is the risky part of an AI-written CV** ("Bias in the Tails", 2026): "exceptional", "proven track record", "results-driven" vary arbitrarily and carry bias. **Facts are stable.** Our tailor prompt should prefer facts and cut evaluative self-description. To check against the current prompt in stage 6.
3. **Ariel's interviews should be more structured, per requirement** (Voice AI, 2026). This is now evidence-backed, not just a design preference.
4. **Title and history consistency is machine-checked** (LinkedIn HA2). Lock role titles to the profile (the recommendation from round 3).

---

## Pass 2 corrections and additions (2026-11-10)

Full detail in `00-gap-map.md`, section 5. Changes that touch this stage:

- **Correction, Kickresume 2026:** the table above reports tailored AI 18% vs generic AI 10%. The same test had **human-written CVs at 31% (single column) and 12% (two columns)**. The single-column human CV was sent first, to the best-matched jobs, so its lead is confounded. **30 of 36 positive responses came from well-matched roles.** Fit decided most outcomes.
- **Correction, attribution:** the October 2026 employer experiment is **Boyd-Swan & Reynolds** (EdWorkingPaper 26-1604), not Cowgill. Finding: when AI is framed as replacing effort, employers discount strong credentials most; only in-person tests reassured both groups. [read]
- **Fabrication in automated CV improvement** (arXiv 2608.26171): 96.7% of outputs fabricated; guardrail prompts left 50% with at least one fabrication. [abstract]
- **AI skills as a hiring signal** (Stephany et al., 1,725 recruiters): +8 to 15 points on interview invitations. [abstract]
- **Candidates in 2026** (Greenhouse, 2,950 job seekers, PDF read): 78% tailor, 3% mass-apply with automation, 31% hear back from fewer than a quarter of employers, 57% believe they are auto-rejected unseen.
- **Burning Glass/HBS 2024 PDF read:** "not even 1 in 700 hires"; 45% of firms changed in name only. Background weight.
- **Structured criteria narrow callback gaps** (Braun et al., 36,880 applications). [abstract]
- **Still open in this stage:** hiring manager vs recruiter; CV length, photo and format evidence; referrals.

---

# Stage 3, verified (2026-11-11)

Done in three passes: (1) every claim above re-checked against the text of its source; (2) the missing topics researched; (3) every conclusion re-read against the evidence and given a confidence level.

**Marks:** **A** = I read the relevant passage in the primary source in this pass. **B** = primary source, abstract or summary only. **C** = secondary or vendor claim I could not trace. **None** = searched, nothing reliable exists.

## Part 1: audit of the earlier claims

### Confirmed against the source text
| Claim | Source text | Mark |
|---|---|---|
| Writing help raised hires 8% | Wiles, Munyikwa & Horton: "nearly half a million jobseekers" (480,948), "hired 8% more often". Pre-ChatGPT; the tool fixed errors, it did not generate content. | A |
| Without written signals, top-quintile workers hired 19% less, bottom 14% more | Galdin & Silbert: exact wording confirmed. This is a **model counterfactual**, not an observed outcome. | A |
| AI cover-letter tool: +0.43 pp access, +3.56 pp use (+51% on 7.02%), 10% significance, faded after two months | Cui et al.: all confirmed. Also: correlation of tailoring with *offers* fell 79%; one SD more editing time goes with +0.31 pp offer probability. | A |
| Callback gaps 18-28% in management roles; credentials narrow gaps only under structured criteria | Braun et al.: confirmed. | A |
| AI-led interviews: 12% more offers | Jabarian & Henkel: 8.70% vs 9.73%; also 18% more job starts. | A |
| AI-interview report: +17.5 to +20 pp at final interview; AUC +0.18 junior vs +0.08 others | Aka, Palikot et al.: confirmed. **Standard errors are large (8.5 and 11.8 pp)**: the direction is solid, the size is not. | A |
| Kickresume 2026: 31% / 12% / 18% / 10%; 30 of 36 from well-matched roles | Confirmed, including the vendor's own warning that versions were sent in phases, not head to head. 51 applications per version. | A (vendor, small) |
| Burning Glass/HBS: fewer than 1 in 700; 37% of firms drove the change; retention +10 pp | Confirmed. 2024 report on 2014-2023 data. | A (old) |
| LinkedIn Sept 2026: 64% say it is harder to know what is real; top matches 2.6x more likely to be interviewed | Confirmed; the 2.6x is LinkedIn's own product claim. | A |

### Corrected
| # | What the notes said | What the source supports | Why it matters |
|---|---|---|---|
| 1 | LinkedIn Hiring Assistant 2 "flags inconsistencies" | The press release says signals are "brought together in one place": verified status, ATS insights, pre-screening answers, work experience. **Nothing about flagging inconsistencies.** | "Title consistency is now machine-checked" was overstated. Consistency still matters (below), but on other evidence. |
| 2 | "Bias in the Tails" shows evaluative words in a CV are risky | The paper studies **summaries that LLMs write about candidates**: facts stay stable, the summariser's evaluative framing varies with the name. It says nothing about wording inside the CV. | The advice "prefer facts over self-praise" stays, but as my inference, not as this paper's finding. |
| 3 | Burning Glass shows "transferable skills don't get credited" | The report measures **degree requirements only**. | Removed. No evidence here either way on transferable skills. |
| 4 | LinkedIn 2025: "11% integrating, 26% experimenting, 32% not exploring" | The page confirms only the sum: **37% "actively integrating or experimenting", up from 27%**. The split could not be found. | Use 37%. And it is a 2025 figure; see 2026 below. |
| 5 | "In 2025 most recruiters still read CVs themselves, so writing for a human stays the priority" | Greenhouse 2026 (primary): **53% of recruiters review fewer than half of applications; 21% fewer than a tenth.** | Reversed in emphasis: a CV must first be *surfaced*, then persuade a person. Both, in that order. |
| 6 | "Structured AI interviews prove Ariel should be more structured" | The studies show structured, adaptive AI interviews collect better hiring information **for employers**. Applying it to Ariel is an analogy. | Kept as a reasonable design direction, labelled as analogy. |

### Downgraded to "could not trace" (C)
Kept only as colour; nothing below rests on them:
- "90% report more low-effort applications"; Insight Global 53%; TopResume 33.5% blind test; Resume Now 36% and 62%.
- Greenhouse "November 2025, 65% of hiring managers". Superseded by the Greenhouse 2026 report read in full.
- Checkr 2026 (86%, 67% vs 59%), RefAssured, Gartner: the pages are stubs or unreachable.
- InterviewPal "11 seconds"; ResumeGo.
- All Israeli guides (Manpower "half spend up to 30 seconds", mojob, taasiya, owlapply, easystudyai), and Robert Half Brazil via ynet.

## Part 2: the topics that were missing

### 2.1 The applicant's real odds (2025-2026 platform data)
**Ashby Talent Trends** (the ATS's own data; read on its site) [A]:
- **38 million applications, 93,000 jobs, 2021-2024:** 93.8% of applications are inbound, 4.8% sourced, **1% referred**.
- **Inbound offer rate fell about 70%: from 7 in 1,000 to 2 in 1,000 applications**, as inbound volume tripled.
- **Referred candidates: 40% reach an interview; 16% of those interviewed reach an offer.**
- **Still, inbound applicants are the largest source of hires: 43-52%, and 52% in Q2 2025, a four-year high.** Referrals about 18% of hires, sourced about 16% (250,000 hires, 2021 to mid-2025).
- Applications arrive in a spike: the **first week brings 2.5-3x the weekly volume** of later weeks.
- Questions per application form **nearly doubled** in four years; 46.8% of 2024 applications included a long-form question.
- 82% of 2024 jobs were filled; 97.5% of jobs at companies of 50+ moved at least one candidate to interview. "Ghost jobs" are rarer than surveys claim, on this platform.
- Ashby's customers are mostly tech and startups. Do not read these as market-wide rates.

**Huntr Q3 2026** (job-tracker data; via Forbes and search summaries, the report itself is unreachable) [C]:
- Median 102 days to a first offer, up from 78 a year earlier.
- People who sent 11-20 applications in three months got interviews on 8% of them; people who sent 100+ got 2.4%.
- **Caution:** this is not proof that applying less causes more interviews. People who apply selectively may differ in other ways.

**Greenhouse Candidate report 2026** [A]: 78% of US candidates tailor; 3% mass-apply with automation; 31% hear back from fewer than a quarter of employers.

**What this says, with confidence:** a cold application has low odds, a referral has far higher odds, and yet about half of hires still come from cold applications. **Fit and targeting are where the applicant has leverage** (also Kickresume: 30 of 36 responses from well-matched roles; LinkedIn Job Match).

### 2.2 Referrals
- Ashby (above): 1% of applications, about 18% of hires, 40% reach interview. [A]
- Armstrong & Metaxa, 2025 (448 computing students) [B]: **referrals and family income predicted hiring success; "adding keywords to resumes" and free coding practice did not.**
- **For us:** the single largest lever in the data is outside the CV. A product that only writes CVs is working on the smaller lever. Worth weighing a referral or networking aid in the feature list (the outreach module exists).

### 2.3 Who screens: recruiter, hiring manager, or software
- Greenhouse 2026 [A]: 68% of hiring managers say they are **more involved** than a year ago; 39% run more in-person interviews; 61% use software to detect AI in interviews. Hiring managers' top problems: authenticity (46%) and **telling qualified from unqualified (45%)**.
- Surati, Bellini & Black, 2026 (22 recruiters) [B]: recruiters believe they hold final authority while generative AI shapes the job definition, the summaries and the criteria they judge from.
- No rigorous study compares what recruiters and hiring managers each look for in a CV. Practitioner pieces say recruiters check must-haves and logistics, hiring managers read for depth. **[None]**
- **For us:** the CV passes three readers in order: software that surfaces, a recruiter who checks must-haves fast, a hiring manager who reads for substance and is primed to doubt. The top third must show the must-haves plainly; the bullets must hold up to a sceptical expert.

### 2.4 Format, length, photo, gaps
| Question | Best evidence | Mark | Reading |
|---|---|---|---|
| One column or two | Kickresume 2026: 31% vs 12%, confounded by timing. Stage 2: parsers mishandle columns. | C + our stage 2 | Single column is the safe default. All five of our templates already are. |
| One page or two | Only ResumeGo (a CV-writing company; sources disagree on its year and size). | **None** | No reliable evidence. Do not build rules on it. |
| Quantified achievements "+40% callbacks" | Traces to an undocumented TalentWorks analysis. No experiment isolates numbers in bullets. | **None** | Plausible, unproven. The 2026 experiments support *verified specifics* generally, not this number. |
| Applying early "8x" | TalentWorks 2017, 1,600 applications. Ashby confirms the first-week volume spike, not an advantage. | C | Unproven. |
| Dates vs years of experience | **Kristal et al., Nature Human Behaviour 2022**, preregistered UK audit, 9,022 applications: listing each job with **years worked instead of dates** raised callbacks about 8% vs a CV with no gap, about 15% vs a CV with a visible gap. | B (2022, peer-reviewed) | The strongest causal result on CV *format* that exists. Old by our rule, never contradicted. A candidate option for users with gaps; conflicts with recruiters' wish for dates, so it would need testing, not a default. |
| Photo | **Ruffle & Shtudiner (Israel)**: 5,312 CVs to 2,656 openings. Attractive men gained from a photo; **women without a photo got more callbacks than women with one, attractive or plain**. | B (about 2010, Israeli) | Old, but it is the only Israeli field evidence. Supports our no-photo default. |
| Name and ethnicity in Israel | Israeli correspondence tests (Law & Ethics of Human Rights, 2015): significant discrimination against Arab and Mizrahi applicants with identical CVs. | B (old) | Background. Supports structured, criteria-based presentation, which narrows gaps (Braun 2026). |
| AI skills on the CV | Stephany et al. 2026, stated intent: +8 to 15 pp. **Danilov et al. ("The Elusive Returns to AI Skills"), real applications: no average effect on callbacks**; positive only for vacancies listing few skills and in low-AI industries; such CVs seen as slightly lower in social skills. | B, conflicting | Real behaviour outweighs stated intent. **No general advice to add AI skills.** |

### 2.5 Trust, fraud and AI-written material (2026)
- Greenhouse 2026 [A]: 91% of recruiters and hiring managers suspected or caught deception in the past year; most common: **CV exaggeration (63%)**, fake references (48%). 74% of candidates use AI in the search.
- Boyd-Swan & Reynolds, Oct 2026 [A]: employers discount credentials they think AI earned, most for the strongest paper profiles; only in-person tests reassure.
- Two independent 2026 theory papers reach the same result: **Ashlagi et al.** and **Qian & Yu ("strategic feature collapse")**: as polished material gets cheap, the rational employer falls back on **observable quality: qualifications and work history**, and offers a separate tested route for those the observables exclude. [A/B]
- arXiv 2608.26171 [B]: automated CV improvement fabricated in 96.7% of outputs; prompts alone left half with a fabrication.
- **Reading:** the reader assumes inflation. Anything the CV says that the profile, LinkedIn or an interview cannot back up is a liability, not an asset.

### 2.6 Israel
- No representative Israeli data on recruiter behaviour exists publicly. **[None]** Hebrew press in 2026 (TheMarker, Calcalist, Mako, Ynet) quotes foreign surveys and individual founders.
- Market context, from press reports of official figures [C]: about 131,000-143,000 open jobs economy-wide during 2026; in high-tech about 17,000-18,000 open roles against about 15,000 registered tech job seekers, with **only about 10% of open tech roles at junior level**; Calcalist headlines a junior's chance of being hired in tech at 5%.
- **Reading:** the Israeli junior market is tight in exactly the segment the founder complained about. This is context for the product's honesty about odds, not evidence about CV content.

## Part 3: conclusions, with confidence

| # | Conclusion | Confidence | Rests on |
|---|---|---|---|
| 1 | **Fit decides most outcomes.** Applying to roles the person really fits matters more than how the CV is written. | **High** | Ashby funnel; Kickresume 30/36; LinkedIn Job Match; Huntr (weak) |
| 2 | **Polish has lost value; verifiable facts have gained it.** Employers respond to cheap polish by leaning on work history, qualifications and tested evidence. | **High** | Two theory papers 2026; Cui 2025; Boyd-Swan 2026; Greenhouse 2026; three AI-interview experiments |
| 3 | **Tailoring is required but does not differentiate.** Skipping it costs; doing it does not win. | **Medium-high** | Cui and Galdin (freelance, causal); Kickresume (salaried, small, vendor); 78% of candidates tailor. No causal salaried study exists. |
| 4 | **Clear, error-free, easy-to-scan writing helps.** | **Medium** | One large experiment, pre-LLM. Not replicated since. |
| 5 | **Never state what the user cannot back up.** Fabrication and inflation are what readers now look for, and automated CV tools produce them by default. | **High** | Greenhouse 2026; arXiv 2608.26171; Boyd-Swan 2026 |
| 6 | **Keep titles, employers and dates exactly as they are in the profile.** | **Medium-high** | Title relevance is a scored dimension (SmartRecruiters); Workable scores "validity and consistency"; exaggeration is the top fraud flag. *Not* on LinkedIn "flagging", which I had wrong. How often our CVs change titles is still unmeasured. |
| 7 | **The CV has to be surfaced before it is read.** Literal must-have terms from the posting, single column, standard headings. | **High** | Greenhouse 2026 review rates; stage 2 vendor docs and parsing tests |
| 8 | **A referral beats any CV change.** | **High** for the size of the gap; **medium** for causation (referred people may be better fits) | Ashby; Armstrong & Metaxa |
| 9 | **Juniors are hit hardest**, because their CVs carry the least information. Extra verified evidence helps them most. | **Medium-high** | Ashlagi theory; Stanford AUC result (large SE); Israeli market context (C) |
| 10 | **Structured, per-requirement elicitation produces better evidence** than free conversation. Applying this to Ariel is an analogy. | **Medium** | Jabarian & Henkel; Aka et al. |
| 11 | No-photo, single-column defaults are right for Israel. | **Medium** | Ruffle & Shtudiner (old); parsing tests |

### What I am not confident about, and will not build rules on
- CV length; numbers in bullets as a specific effect; applying early; AI skills as a line item; how long a recruiter looks and where; what Israeli recruiters do differently. Each is either unproven or unstudied.
- The size of any effect in the **Israeli salaried** market. Almost all causal evidence is from US or freelance settings.

### What would move these to near-certain
Only our own data can: (a) the recruiter test with the kit; (b) tracking interview outcomes per application in the product, which no outside study can replace; (c) a short survey of Israeli recruiters. Outside reading has reached the point of diminishing returns for this stage: the last three passes changed emphasis and corrected my wording, but did not overturn conclusions 1, 2, 5 or 7.

## What this means for the product (inputs to the decisions, not decisions)
1. **Lead with fit, honestly.** A trustworthy "should I apply" signal is worth more than CV polish. This raises the priority of fixing the match score (stage 1).
2. **The CV writer's job is to state verified facts clearly in the posting's terms**, and to refuse to invent. Code-level checks against the profile, not only prompt instructions.
3. **Ariel's value is producing evidence** the CV can carry: scope, numbers, outcomes, per requirement.
4. **Tell users the odds and the levers**, including the one outside the CV (referrals).
5. **Measure outcomes in the product.** Interview-rate tracking is the only way to settle what outside research cannot.
