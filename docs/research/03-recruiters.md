# Research 03: what recruiters actually check (2024 onward)

Stage 3 of the scoring/CV research. Working notes, built up over several rounds.

**Recency rule:** sources from 2024 onward are the evidence. Anything older is marked **[historical]**.

**Source marks:**
- **[primary]**: the original study or the vendor's own page.
- **[secondary]**: a report about it.
- **[vendor survey]**: a survey run by a company that sells CV or hiring products. Treat its numbers as directional.

---

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
