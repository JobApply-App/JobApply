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
| 5 | Real ATSs: per-requirement, coarse categories, human decides | A for Greenhouse, Workday (Aug 2026), Ashby; **C for iCIMS, SAP, SmartRecruiters, Oracle, Eightfold** | read those vendors' own docs |
| 6 | Automatic rejection = form answers | A (Workday manual via search, Greenhouse); C elsewhere | Comeet |
| 7 | Comeet behaviour | C (one vendor blog) | **the recruiter test (reminder set for Nov 11)**; Comeet's support site is unreachable from here |
| 8 | Holistic LLM scores unstable / per-criterion better | A, with the nuance in section 2 | size of the effect for *our* model and prompt: needs our own measurement (stage 7) |
| 9 | LLM-written CVs preferred by LLM screeners | A for the models tested; **unknown for Claude and Gemini** | none available; treat as untested |
| 10 | Tailoring: required, not differentiating | A (freelance, 2025) + B (Kickresume 2026) + A (theory 2026) | still no causal study of salaried hiring |
| 11 | Evidence beats prose; structured elicitation works | A (three 2026 field experiments) | none |
| 12 | Recruiters distrust AI-written and fabricated material; rising | B (LinkedIn Aug 2026 survey, primary) + C (Checkr, Greenhouse PDFs) | Greenhouse/Checkr PDFs are on blocked hosts |
| 13 | Recruiter first-scan behaviour (titles, companies, dates) | **C; no measured study since 2018** | genuinely thin; no 2024+ eye-tracking exists that I can find |
| 14 | Israeli recruiters' habits | **C (guides only)** | no representative Israeli data found; candidate for our own small survey |
| 15 | Role titles not locked in our CVs | A (code) | how often it happens: needs generated CVs (stage 6) |
| 16 | Hebrew PDF word order | A (root cause measured) | PDFBox/Tika; real ATS |
| 17 | Skills-based hiring changes little in practice | B (2024 report landing page) | read the PDF; look for a 2026 update |
| 18 | Regulation (EU AI Act dates, NYC LL144, Mobley v. Workday) | B/C | verify against official texts before relying on dates |

---

## 4. What remains before stage 3 can be called complete
1. **Vendor docs still at "secondary":** iCIMS, SAP SuccessFactors, SmartRecruiters (Winston), Oracle, Eightfold, Workable, plus Textkernel/DaXtra on Hebrew.
2. **Primary PDFs on blocked hosts:** Greenhouse 2026 AI in Hiring and Benchmark reports; LinkedIn Future of Talent 2026; Checkr 2026; Cowgill et al. EdWorkingPaper (Oct 2026); Burning Glass 2024.
3. **Stage 3 topics not yet started:** hiring manager vs recruiter; CV length, photo and format evidence; referrals; the candidate's side (how many applications, response rates in 2026).
4. **Things only we can measure:** our scorer's run-to-run stability; how often titles change; Comeet and PDFBox on our PDFs.
