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
