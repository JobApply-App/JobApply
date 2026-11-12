# Research 06: how to build the CV, and how ours is built today

Stage 6 of the scoring/CV research (2026-11-12). The founder's priorities for this stage: the CV must never contain invented details, unrelated words, or signs of AI writing, and should read in the plain, correct register of a CV.

**Evidence weighting:** 2026 first; 2025 valid but older; earlier is background. Vendor material is for ideas only.

**Marks:** **A** = relevant passages read in the primary source, or read in our own code. **B** = abstract or summary only. **C** = secondary.

---

## In plain words

**The question:** what makes an AI-written CV go wrong, and is our system built in a way that invites those mistakes?

**The short answer:** our system already has more protection against invented facts than the research describes as typical. But the instructions we give the AI model pull in two opposite directions at once: "never invent" and "you must fit in 16 of the job's 20 keywords, and every line must carry a number". The 2026 research says that second kind of pressure is exactly what produces invented details.

**An example of how it goes wrong.** Dana's profile says: "Handled customer check-in calls for about 40 accounts." The job asks for "QBRs", "Salesforce" and "churn reduction".
- Our instructions tell the model to use the job's exact words, to put a number in every line, and to keep revising until 80% of the job's keywords appear.
- A likely result: "Ran QBRs for 40 accounts in Salesforce, reducing churn."
- What is true in that line: 40 accounts, and the calls.
- What was added: that the calls were formal quarterly reviews, that she used Salesforce, and that churn went down. No number was invented, so our fact-checker, which looks for unfamiliar numbers and names, would catch "Salesforce" only if that word appears nowhere in her profile, and would not catch the other two at all.

**What the research says to do instead** (sections 3 to 5): let the code decide which of the job's terms the profile actually supports, hand the model only those, ask the user about the rest, and check the result claim by claim.

---

## 1. How our CV is built today (read from the code)

### The pipeline
1. One large prompt to the model (`backend/agents/tailor.py`, `_SYSTEM_PROMPT`): **about 43,000 characters, about 6,000 words, 794 lines**. Temperature 0.
2. The model either returns the CV as structured data, or returns **questions for the user** ("missing_data") when a must-have requirement might be met but the profile is silent.
3. Code then:
   - validates the structure and trims to length limits;
   - **injects** contact details and education from the profile (the model is told never to write them);
   - **restores any employer** the model dropped;
   - runs a **word scrubber** for AI-style vocabulary and long dashes (`ai_scrubber.py`);
   - runs the **grounding gate** (`cv_grounding.py`): every experience bullet is checked for numbers and proper names that do not appear in the user's profile; a flagged bullet is rewritten using profile text only, re-checked, and removed if it still fails, with a notice to the user;
   - for Hebrew, runs a **separate localisation pass** that is rejected if it changes any number, date, company name, or the count of roles, bullets, degrees or skill groups.

### What is already right, by the evidence in this document
| Feature | Why it matters |
|---|---|
| Temperature 0 | Lower temperature gave fewer fabrications in the one study that varied it (section 3) |
| Contact, education and employers set by code, not by the model | "Structural invariants" are one of the layers the 2026 work recommends |
| Asking the user instead of guessing | The strongest single measure in the fabrication study was a checkpoint with a person who knows the truth |
| A fact check that repairs or removes, and tells the user | Same layered idea; and it never ships a line it could not verify |
| Hebrew pass with hard invariants | Translation is a second chance to drift; ours is fenced |
| One page | Matches the founder's decision |

### What the gate does not cover (stated in its own docstring, confirmed by reading)
- It checks **literals** (numbers, capitalised names), not **claims**. "Led a team of senior managers" has no literal and passes.
- It checks **experience bullets only**. The summary, the target title, the skills list and the military section are not checked.
- Its name detector looks for Latin capital letters, so it sees little in Hebrew text.
- **Role titles** are not locked to the profile (stage 3 finding, still open).

---

## 2. Where our instructions work against "never invent"

All quoted from `_SYSTEM_PROMPT`. Each is a place where the prompt creates pressure that the research links to fabrication.

| # | What the prompt says | The problem |
|---|---|---|
| 1 | "KEYWORD COMMIT: you are required to place ≥ 16 of these 20 terms verbatim"; "If fewer than 16, revise"; a missing term is "a critical failure and force it into the summary or skills section" | A quota on the job's words, enforced by revision, regardless of what the profile supports. The same prompt says "never keyword-stuff". Both cannot hold. |
| 2 | "at least 3 of the listed cv_vocabulary_gap terms for each VERIFIED entity MUST appear verbatim"; "Repeat until ≥ 3 gap terms are present" | Mandatory insertion of industry terms the candidate's own CV did not use. |
| 3 | "every bullet that CAN carry a number MUST carry a number"; "XYZ FRAMEWORK: mandatory for every bullet, zero exceptions"; the summary "MUST contain at least one concrete number" | A required number is the classic way to get an invented one. |
| 4 | "Derivable approximations ... 'weekly syncs for 40+ partners over 18 months' = ~78 syncs" | Tells the model to compute numbers the user never stated. The grounding gate would then flag "78" as unverified. The prompt and the gate disagree. |
| 5 | Terminology bridging: "Client Portfolio Mgmt → ARR Management", "Account Check-ins → Executive Business Reviews", "Escalation Handling → Risk Mitigation" | These change the claim, not only the word. Owning a client list is not managing recurring revenue. |
| 6 | "the page should feel FULL: dense, substantive, no visual gaps" next to "Never pad" | Opposite instructions. |
| 7 | "ATS systems match character strings, not meaning"; "The summary is scanned first by every ATS"; "em-dashes ... Advanced ATS systems ... auto-reject AI submissions" | Not supported. Stages 2 and 4: systems mix literal and semantic matching, rarely reject on content, and none of the ten largest detects AI text. False premises make the model over-weight literal insertion. |
| 8 | The keyword count is 20 in one place ("≥ 16 of 20"), 15 in two others ("≥ 12 / 15", "K1-K15") | Internal inconsistency; the model cannot satisfy both. |
| 9 | Persona "placed candidates at top-tier B2B SaaS companies"; "CUSTOMER SUCCESS JDs ... STRICTLY FORBID: Python, SQL"; "VOLUNTEERING (Perach)"; "his answer" | Written around one person's career. For another user it can remove true, relevant skills (a Customer Success applicant who does use SQL, for a job that asks for it) or assume a volunteering programme they never did. |
| 10 | The role title field has no "copy from profile" rule | Stage 3, still open. |

**Size itself is a problem.** The prompt holds well over a hundred separate rules. **Jaroslawicz et al., 2025** ("How many instructions can LLMs follow at once?", 20 models) [A]: adherence falls as the number of simultaneous instructions grows; even the best models reached only 68% at the highest density tested (500), and the task they used was keyword inclusion, the same kind of instruction ours is full of. Two related 2025 benchmarks point the same way [C]. Our own code comment says the same thing about the Hebrew rule: "one instruction among hundreds was not" reliable.

---

## 3. What the 2026 research says about invented content

### How often, and what kind
- **Takano, July 2026** (arXiv 2608.26171; 180 controlled runs, one model, claim-level ground truth) [A]:
  - with an ordinary prompt, **96.7% of improved CVs contained at least one unsupported claim, 6.8 per CV**. Most common: new unsupported claims (58%), then altered claims, then items from a list of plausible-but-absent things;
  - **a strict "do not add facts" instruction cut the count by 86%, yet half the CVs still had at least one**;
  - **a human checking against the truth** removed every invented identity detail and almost every claim baited by the job description (47% of baits taken with no protection, 5% with the instruction, 2% with the human), but cut the overall count by only 59%: subtle changes, such as dropping a limiting word like "basic" or "prototype", **slipped past the reviewer about half the time**;
  - the instruction and the human were good at different things; the author recommends both;
  - a newer model still fabricated in 90% of runs: "not resolved by model progress alone";
  - **people changing field were the most exposed**.
  - *Correction to my earlier note:* I wrote in `00-gap-map.md` that the human checkpoint "closed most of the rest". It did not. It was decisive on the gravest errors and weak on subtle ones.
  - Limits: one author, one model, an AI judge for scoring, 20 CVs.
- **"Grounded Optimization", July 2026** (arXiv 2607.01457; 25 synthetic CVs, three models, four temperatures) [A]:
  - names four failure types: tools that did not exist at the time of the job; **terms from the wrong domain pulled in to match the job description**; **true content silently compressed away**; and outright invention;
  - **the wrong-domain kind was 79-89% of failures**, and arises "when optimizing for keyword coverage";
  - the "compressed away" kind matters as much as invention: "the most distinctive accomplishments, those that differentiate one candidate from another, are silently folded into generic summaries";
  - grounding instructions alone reached zero detected fabrications at low temperature with a capable model; with higher temperature or weaker models, the code-level checks were needed too.
- **Huntr survey, Q3 2026** (329 job seekers) [A, vendor]: 63% of those using AI on their CV say it put false details there.
- **Demir, 2026** and **Wang & Song, Nov 2026** [B]: models tend to answer rather than say the source is silent; when a text lacks the needed evidence they fill the gap.

### What reduces it
The 2026 engineering papers agree on a layered design; none claims a single fix:
1. **Decide in code what may be said.** Match the job's terms against the profile first; pass the model only supported terms. (Both CV papers; "HALO", 2026 [B]: "zero hallucination is not a property a model possesses but a property a system enforces".)
2. **Fix the unchangeable fields in code**: employer, title, dates, education. (We do all but title.)
3. **Instruct plainly, without competing quotas.** A single clear no-additions rule worked far better than nothing.
4. **Check the output against the source**, claim by claim, with deterministic checks where possible.
5. **Ask the person** when the source is silent. (We do.)
6. **Show the person exactly what changed**, because subtle changes are the ones reviewers miss. A reviewer shown a finished CV catches the blatant errors; one shown "this word was added, this qualifier was dropped" can catch the rest.

**Confidence:** high that fabrication is the default behaviour of CV-rewriting models and that prompts alone do not stop it (two independent 2026 studies plus user reports); medium on the exact rates (small studies).

---

## 4. What the research says about "sounds like AI"

### What readers actually notice
- **Russell, Karpinska & Iyyer, ACL 2025** [A]: five people who use LLMs often for writing, voting together, **misjudged 1 of 300 articles**, better than nearly every detection tool, and even after "humanizer" tools were applied. People who rarely use LLMs were poor at it and overconfident. What the experts cited: **"AI vocabulary" (their examples: vibrant, crucial, significantly)**, then **formulaic sentence and document structure**, then lack of originality.
- **Morgenstern et al., Nov 2026** (11,882 Wikipedia editor flags plus student data) [A]: people cite many kinds of evidence, and the common thread is **a mismatch with what the context calls for**, not any single word. A text is called AI-written when it does not sound like the genre it claims to be.
- **Em-dash:** two preregistered 2026 studies [A] found the long dash roughly doubled in US congressional press releases in 2025 and rose from 4.2% to 11.6% of medical preprint discussions after ChatGPT. **Freeburg, 2026** [B]: the dash survives even when models are told to avoid formatting; rates differ sharply by model family.
- **Holzwarth et al., Aug 2026** [A]: by the end of 2025, 89% of biomedical papers showed excess LLM-associated vocabulary. Marker words are now everywhere, so a word list alone separates less and less.
- **Stage 3 reminder:** recruiters say they can spot AI CVs; a blind test put them near chance. Recruiters who use AI tools daily are likely closer to Russell's experts than to the average.
- **Enhancv, 2026** [A, vendor]: none of the ten largest ATSs detects AI-written text. The reader who matters is a person.

### What this means
1. **Our scrubber targets the right first-order signals** (vocabulary, long dashes). Russell's top cue is vocabulary.
2. **It cannot fix the second and third cues**: formulaic structure and sameness. Every bullet built on one mandatory template ("achievement, measured by, by doing"), every summary with the same three-part shape, is a formula a practised reader recognises. The mandatory template is itself a tell.
3. **Blind word replacement has costs.** The scrubber turns "facilitated" into "helped", while the prompt bans bullets that rely on "Helped to". It turns "align with" into "matches" and "enhance" into "improve" wherever they occur, including inside product names or quoted job terms. Each is small; together they can produce odd sentences.
4. **The scrubber is English only.** Nothing equivalent runs on Hebrew.
5. **The most reliable way to not sound like AI is to say only specific, true things in the genre's own plain form.** That is the same rule as section 3. Generic filler and fabrication come from one cause: text written to fill a shape instead of to report a fact.

### Hebrew
- No research on AI-writing markers in Hebrew was found. **[None]** Israeli press pieces [C] list: the long dash (rare in typed Hebrew), English terms repeated in brackets after a Hebrew word, literal translations ("מספק בהירות" for "provides clarity"), and a symmetrical, summarising structure.
- Our Hebrew pass already bans several calques and filler phrases by name. There is no measurement of how its output reads to an Israeli recruiter. That needs people, not papers.

**Confidence:** medium-high that vocabulary and formula are the main cues; high that a word list alone is not enough; low on anything specific to Hebrew.

---

## 5. What the evidence says about CV content itself

Gathered from stages 3 and 4, kept short. Nothing here is strong.

| Element | Best evidence | Standing |
|---|---|---|
| Clear, error-free writing | Wiles et al.: +8% hires (pre-LLM) | Medium |
| Tailored to the job | Huntr 2026: 4.23% vs 2.07% interviews; Kickresume 2026 | Medium (observational) |
| Numbers | Huntr 2026: a dollar figure in the summary 6.97% vs 4.78%, "suggestive rather than ironclad". The "+40% callbacks" figure has no traceable source | Low-medium |
| The "X, measured by Y, by doing Z" bullet formula | A 2014 post by a Google executive. **No study** | None. It is advice, not evidence |
| More, fuller bullets | Huntr 2026: interview rate rises with bullet count | Low-medium (confounded with experience) |
| Length | Founder decision: one page by default | Decided |
| Photo | Founder decision: none | Decided |
| Exact titles, employers, dates | Stage 3 | Medium-high |

**Reading:** the evidence supports *true specifics stated clearly* and *using the job's terms where they are true*. It does not support forcing every line into one formula or requiring a number in every line. Those rules in our prompt come from career-advice tradition, and section 3 shows what they cost.

---

## 6. What could not be done in this stage
- **Measuring our own output.** No model key exists in this environment, so I could not generate CVs and count fabrications, title changes, keyword insertions or AI-style wording. Everything in section 2 is a reading of the instructions, which shows *pressure*, not *rate*. The grounding module's own notes record about 10% of bullets flagged on one real profile, with the flags looking like real fabrications; that is the only measured number we have, from one user.
- **Hebrew output quality.** Needs native readers.
- **The Comeet test** (stage 2) is still pending and bears on formatting.

**Proposed measurement for stage 7** (needs a key; can run on a cheaper model): take 10-20 real or realistic profiles and 3 jobs each; generate; then count per CV: claims not in the profile, changed qualifiers, job terms present in the CV but absent from the profile, changed titles, banned-style words, and repeated sentence shapes. Run twice: with today's prompt, and with a version without the quotas.

---

## 7. Conclusions, with confidence

| # | Conclusion | Confidence |
|---|---|---|
| 1 | Our protections against invented *facts* are stronger than what the research describes as typical: code-set fields, a repairing fact check, user questions, fenced translation | High (read in code) |
| 2 | Our prompt contains quotas (keywords, numbers, fullness) that push toward the very fabrication the rest of the system tries to stop | High that the pressure exists; **unmeasured** how often it wins |
| 3 | The dominant fabrication in CV rewriting is importing the job's terms without support, and it comes from optimising keyword coverage | Medium-high (one 2026 study with numbers, one consistent) |
| 4 | Prompt rules alone leave a large residue; code checks and a person are both needed | High |
| 5 | A reviewer misses subtle changes about half the time unless they are pointed out | Medium (one study, one reviewer) |
| 6 | "Sounds like AI" is mainly vocabulary, then formula and sameness; a word list handles only the first | Medium-high |
| 7 | A mandatory sentence template for every bullet is itself an AI tell and has no evidence behind it | Medium |
| 8 | Several premises in our prompt about how ATSs work are false | High (stages 2 and 4) |
| 9 | Parts of the prompt still assume one specific user | High (read in code) |
| 10 | Nothing is known from research about AI tells in Hebrew | High that the gap exists |

---

## 8. Inputs to the design decisions (not decisions)

In the order the evidence suggests they matter:
1. **Remove the quotas from the prompt.** Replace "place 16 of 20 keywords" with: code matches the job's terms to the profile and passes the model the supported list; unsupported must-haves become questions to the user or lines in "what is missing" (which stage 5 already wants to show).
2. **Stop requiring a number in every line and stop computed approximations.** Use a number when the profile has one.
3. **Lock role titles to the profile**, as education and employers already are.
4. **Extend the fact check** to the summary, target title and skills list, and add a check for job terms that appear in the CV but nowhere in the profile.
5. **Show the user a "what changed" view**: terms added, qualifiers dropped, lines merged or removed. This is where a person's review is weakest and where it can be made strong.
6. **Drop the single mandatory bullet formula**; vary sentence shape; keep the plain-verb guidance.
7. **Remove the false ATS claims and the one-user assumptions** from the prompt.
8. **Shorten the prompt drastically** once the quotas are gone; move rules that code can enforce into code.
9. **Review the word scrubber** for replacements that damage meaning, and build a Hebrew counterpart from real examples with native readers.
10. **Measure before and after** (section 6). Without that, every item above is a reasoned bet.

---

# Second pass: the wider evidence (2026-11-12)

The founder asked for much more evidence on this stage, from many studies, including the criticisms. This pass adds about 50 sources. About 45 were opened on arXiv and read at abstract level; the ones marked **A** were read further. Search-only items are marked **C**.

**How to read this part:** each heading is one question. Under it: what the studies found, where they disagree, and what it means for our CV builder. Section 16 gives the updated confidence table.

## 9. Is invention really the default, or only in some tasks?

**It depends on the task, and the difference matters for us.**

| Finding | Source | Mark |
|---|---|---|
| Rewriting and "improving" a document: unsupported claims in 96.7% of CVs | Takano 2026 | A |
| Summarising clinical trials (GPT-4o, Claude Sonnet 4.6, Gemini 2.5 Flash; 1,800 summaries): **"unsupported claims" was the dominant failure for all three models** | Williams 2026 | B |
| Summarising science: LLM summaries were **nearly five times more likely than human ones to state conclusions more broadly than the source** (4,900 summaries, 10 models); happened "even when explicitly prompted for accuracy"; **newer models did worse** | Peters & Chin-Yee, Royal Society Open Science 2025 | B |
| Patient summaries of radiology reports (18,000 pairs, six models): even the best model **failed to carry over a changed certainty word in 22% of summaries and a severity word in 21%** | Stanford group, Nov 2026 | B |
| Summaries versus human-written references: people's references are still more faithful and informative; model output wins on fluency; and different models write alike ("stylistic homogeneity") | Liu et al. 2026 | B |
| **Against the trend:** asked direct questions about a document, five current models **never invented an absent fact (0 of 5,760 probes)**; when overloaded they refused instead | Eliav 2026 | A |
| **Against the trend:** revising patent claims with retrieved material, four current models showed no detectable copying-in of outside templates (9,600 calls) | 2026, arXiv 2609.36550 | B |

**Reading:** models are now fairly reliable at *reporting what a text says*. They become unreliable when asked to *make it better, shorter, broader or more impressive*. A CV builder is the second kind of task. The specific failures to expect are: adding, broadening, and **dropping the small limiting words** ("basic", "assisted", "pilot", "part-time"). The last one recurs across four independent studies and is the hardest for a person to notice.

**Confidence that rewriting tasks invite unsupported and broadened claims: high** (five studies, three domains, peer-reviewed among them).

## 10. Does a longer, stricter prompt help?

- **Eliav, July 2026** (five models including Claude Sonnet 5 and Gemini Flash; rule count raised from 10 to 160) [A]: **the share of responses that followed every rule fell to zero by 80 rules, "for every model, every format, and both placements"**. Formatting the rules as markdown, plain text or tables made no reliable difference. *Not peer reviewed; a synthetic task.*
- **Jaroslawicz et al., 2025** (20 models) [A]: same direction; best models 68% at 500 rules.
- Two more 2025 benchmarks agree [C].
- **PACT, 2026** (rule-following under pressure, 48 scenarios) [B]: compliance with standing rules varies widely across models when a shortcut is convenient.
- **Our prompt has well over 100 rules.** On this evidence, the realistic expectation is that some rules are broken in every single generation, and we do not control which.
- **Critique:** both main studies count rules of one simple kind in an artificial task. Real prompts mix important and trivial rules, and a model may keep the important ones. That is plausible and untested.
- **Reading:** fewer rules, and every rule that code can enforce moved into code. **Confidence: medium-high.**

## 11. Do the prompt techniques we rely on have support?

| Technique in our prompt | Evidence | Verdict |
|---|---|---|
| **Expert persona** ("You are a 20-year veteran Tech Recruiter") | Wharton, Dec 2025 (six models): expert personas did not improve factual accuracy; when they mattered they more often hurt [B]. **Disputed:** a March 2026 paper argues that study's design hid real effects [B]. | **Unsettled.** No evidence it helps accuracy. May shape tone. Not worth defending, not proven harmful. |
| **Self-audit** ("run a self-audit before output", "re-check until ≥ 3") | Medical question answering, 2026: asking the model to critique and revise itself "does not consistently improve accuracy" and can add new errors [B]. A claim-splitting study, 2026: an instruction that *licenses self-correction* made the model replace what the source said with its own belief in 4.3% of claims, against 0.2-0.5% with a neutral instruction [B]. | **Weak, and can backfire.** A self-check inside the same call is not a check. |
| **Worked examples with numbers** (our sample bullets: "22%", "98%", "40+ suppliers") | Studies of in-context examples: output clusters around the examples, and with more examples models reproduce them [C, three papers 2024]. | **Real risk.** Our prompt warns against copying, and our fact check would flag a leaked number, so the damage is limited. |
| **Temperature 0** | Peters & Chin-Yee and "Grounded Optimization" both recommend low temperature [B/A]. | **Supported.** |
| **Asking the user when the profile is silent** | Takano 2026; a deployed government assistant that routes unclear requests to a clarifying question (2026) [B]; "Pause or Fabricate" (2026) [B]. | **Supported.** |

## 12. How should the output be checked?

- **Split into claims, check each against the source.** This is the standard design in 2026 (several papers) [B]. It can run on small, cheap models.
- **A second model does not automatically make it safer.** One 2026 study required a language model *and* a separate entailment model to agree before accepting a claim; **accuracy went down**, because correct answers were overturned [A]. Double-checking has to be designed, not just added.
- **AI judges of faithfulness are swayed by cues** such as length and stated confidence; forcing them to quote evidence before scoring reduced this [B, 2026].
- **Human reviewers pass text that is mostly right.** "Averaging bias", 2026: people's overall "faithful" labels tracked the *average* sentence, so summaries with a real local error were often approved [B]. This matches Takano's reviewer missing half of the subtle changes.
- **Showing people which claims are backed helps a great deal.** "Provenance Density", 2026 (81 participants): with a display of which claims were verified, people separated true from invented text (effect size d = 1.82); with no signal they could not [A]. A plain "made with AI" label did not help and lowered trust in true content too.
- **Omission is a separate error and needs its own check** (medical summarisation, Stanford 2026; "Grounded Optimization") [B].
- **Stricter grounding costs readability** (4,500 health summaries, 2026): more faithful text was harder to read [B]. A real trade-off, not a free win.
- **Reading for us:** our fact check covers numbers and names. The evidence points to adding (1) a check for *qualifier changes and broadened claims*, (2) a check for *dropped content*, and (3) a user-facing view marking each line as "from your profile" or "reworded" or "new, please confirm". **Confidence that a provenance view improves the user's review: medium** (one good study, different domain).

## 13. Does "humanizing" the text work?

- **"Humanized but Still True?", Oct 2026** (11 commercial humanizer tools) [A]: **every tool changed or dropped at least one checkable detail in 35-65% of documents**; counting only numbers and names, 10 of 11 tools still altered one in 20% or more. The tools are scored publicly on evading detectors and on overall similarity, which does not notice a changed number. No reliable trade-off was found between keeping facts and evading detection.
- **Russell et al., 2025** [A]: practised readers still identified humanized text.
- **Reading:** rewriting a finished CV to "sound human" is a second chance to corrupt facts and does not fool an experienced reader. Our own scrubber is much narrower (a fixed word list and dashes), which is the safer kind, but the lesson holds: **do the style work before the fact check, never after it.** In our pipeline the scrubber runs *before* the grounding gate, which is the right order; the Hebrew pass runs after it, protected by its own number and name invariants.

## 14. Can anyone actually tell, and does it cost the applicant?

| Finding | Source | Mark |
|---|---|---|
| Practised LLM users identify AI text almost perfectly; occasional users are near chance and overconfident | Russell et al., ACL 2025 | A |
| Recruiters shown AI-written cover letters did no better than chance | Tilburg (Abbas Nejad et al.), two field experiments, accepted at the Journal of Labor Economics 2026 | C |
| **AI-improved cover letters scored higher but did not get more interview invitations**: the gains were in the generic opening and closing, while recruiters attend to personal motivation and clarity. Told that applicants used AI, recruiters valued unaided letters more | same Tilburg study | C |
| **Admissions essays (7,500 applications, 2020-2025):** AI raised writing quality, yet **applicants with AI-written essays were admitted less often than comparable non-users**; in an experiment, officers often recognised AI writing and rated essays they believed AI-written lower | Isley et al. (Harvard), Sept 2026 | B |
| Expert writers preferred human writing 82.7% of the time over prompted AI; **lay readers consistently preferred the AI text** | 2026, arXiv 2601.18353 | B |
| Automatic detectors are unreliable: on human-written text their false-positive rates ranged from 0% to 100% across 13 detectors, and professional editing changed the scores | 135,389 document pairs, Aug 2026 | B |
| AI-based screening tools scored an AI-written CV up to 50% higher than the human-written equivalent | Privacy International, 2026 | C |
| Stage 2: LLM screeners favour LLM-written text; stage 3: hiring managers say they distrust it | earlier stages | A |

**Reading, and it is not one-sided:**
- **Software screeners tend to reward AI-polished text. Experienced human readers tend to penalise text they believe is AI-written. Casual readers cannot tell and may prefer it.**
- So "sounding like AI" is a risk with exactly the readers who decide late in the process (hiring managers, practised recruiters), and no help with them.
- The Tilburg and Harvard results agree on the important point: **polish in the generic parts earns nothing; the specific, personal content is what readers weigh.**
- **Confidence: medium.** Admissions and cover letters are not CVs, and two of these I know only through summaries.

## 15. Language: Hebrew
- **Translation trades fluency against faithfulness.** 130,486 translated paragraphs, 2026 [B]: the more natural a translation read, the less faithful it tended to be, for people and for machine translation alike. Our Hebrew pass asks for natural Israeli Hebrew and is fenced by invariants on numbers, dates and names; **meaning shifts that involve none of those are not fenced.**
- **Grammatical gender is hard for models** (French, Arabic, Hindi benchmark, 15 models, 2026) [B]. Hebrew was not tested. Our choice of first-person past-tense verbs, which are the same for both genders, sidesteps most of it.
- A multilingual detector benchmark (2026) covers eight languages; Hebrew is not among them [B].
- **Still no study of AI-writing markers or CV quality in Hebrew. [None]**

## 16. Updated conclusions

| # | Conclusion | Before | Now |
|---|---|---|---|
| 1 | Rewriting tasks invite unsupported and broadened claims | High | **High**, now on five studies in three domains |
| 2 | The most missed error is a dropped or changed limiting word | Medium | **Medium-high** (four independent studies) |
| 3 | A prompt with this many rules cannot be fully followed | Medium-high | **Medium-high** (a second, 2026, study; both use artificial tasks) |
| 4 | Self-audit instructions inside the same prompt are a weak safeguard | not stated | **Medium** |
| 5 | The expert persona line helps | assumed | **Unsettled; no support** |
| 6 | Checking claim by claim against the profile is the right design | High | **High**; but adding a second checker can hurt if combined naively |
| 7 | Showing the user what is backed and what is new makes their review effective | Medium | **Medium** (stronger evidence for the idea, still not from our domain) |
| 8 | A "humanizer" step is harmful | not stated | **High** (11 of 11 tools altered facts) |
| 9 | Experienced human readers penalise text they believe is AI-written | Medium | **Medium** (new: admissions data, Tilburg) |
| 10 | AI polish of generic parts earns nothing with human readers | Medium | **Medium-high** (Tilburg, Harvard, stage 3's Cui et al.) |
| 11 | Stricter grounding makes text somewhat harder to read | not stated | **Medium** (one large study) |
| 12 | Models rarely invent when simply reporting what a source says | not stated | **Medium** (one large 2026 test). This is why "pass the model only supported terms and ask it to state them" is a sound design |

### What changed in my own view during this pass
- I had treated "models invent" as a general fact. The wider reading shows it is specific to *improving and rewriting*. That makes the design direction clearer, not weaker: reduce the "improve" freedom, increase the "report" structure.
- I had not weighed the cost side. Grounding reduces readability somewhat, and a badly combined second checker reduced accuracy in one study. Neither is a reason to hold back; both are reasons to measure.
- The reader evidence is mixed in a way I under-stated: casual readers like AI prose. The case against AI-sounding CVs rests on *experienced* readers and on the generic-polish-earns-nothing result, not on a universal dislike.

### Still not known
- Rates for **our** system (section 6): needs a key.
- Anything about Hebrew.
- Whether recruiters penalise a CV, as distinct from a cover letter or essay, that they believe is AI-written. The nearest studies are adjacent, not direct.

---

# Third pass: how the CV should look and read (2026-11-12)

The founder asked for design and writing insights: what the CV should look like, in what order, in which fonts, with which words, and how to use the information we already hold.

**An honest note on this evidence.** Research on CV *design* is thin and mostly old. The peer-reviewed experiments are from 1988-2019; the 2026 material is vendor data, which shows association only. Reading and typography research is solid but was not done on CVs. So this part combines three kinds of source, marked as usual: **A** read in the source or measured in our own files, **B** abstract or a summary of the source, **C** secondary. Where a popular rule has nothing behind it, that is said.

## 17. What our five templates do today (measured in the files)

| | Classic | Modern | Executive | Minimalist | Tech Modern |
|---|---|---|---|---|---|
| Font | Times New Roman | Inter (sans) + Source Serif | Georgia | Helvetica / Arial | Segoe UI / Arial |
| Bullet text size | 8.5 pt | 9 pt | 8.5 pt | 8 pt | **8 pt** |
| Smallest text | 8 pt | 7 pt | 7.5 pt | 7.5 pt | **6.5 pt** |
| Dates: size and colour | 8.5 pt, dark grey | 8 pt, **pale grey** | 8 pt, **pale grey** | 7.5 pt, **pale grey** | 7 pt, **pale grey** |
| Columns | one | one | one | one | **main column + dark sidebar** |
| Italics | yes | a little | yes | no | no |

- **Order in all five:** name, target title, contact line, summary, experience, education, then skills, languages, military service, volunteering.
- **Section headings:** uppercase with widened letter-spacing in all five.
- **The pale grey used for dates** in four templates (`#94A3B8`, `#A1A1AA`) has a contrast of **2.56 to 1** against white. The accessibility standard for small text is 4.5 to 1.
- **Correction to earlier notes:** I wrote in stage 2 that all five templates are single-column. Tech Modern has a sidebar holding skills, languages and military service, with light text on a dark background.
- Hebrew uses the embedded Heebo font; italics were already removed for Hebrew.

## 18. Size and legibility

- **Critical print size.** Vision research (Legge and colleagues; a review in the Journal of Vision) [B]: reading speed is flat across a wide range of sizes and **drops sharply below a "critical print size", about 0.2 degrees of letter height for people with normal sight**. At a normal reading distance of 40 cm that works out to roughly **8 pt** type (my arithmetic, and it varies with the font's letter proportions).
- People with mild vision loss read 10 pt at 144 words a minute and 16 pt at 163; the authors argue minimum print size should rise above 10 pt [B].
- Reading is **slowed, not stopped**, below the critical size.
- **What this means for us:** our bullet text (8-9 pt) sits *at* the threshold for a reader with perfect sight, and our small text (6.5-7.5 pt) is below it. Dates, among the first things a recruiter looks for (stage 3), are both small and pale in four templates. Anyone over 45, anyone reading a printout, and anyone viewing the page fitted to a laptop screen is reading below comfortable size.
- **Why the templates are small:** to fit one page. This is a direct trade-off with the one-page default. It is solved by saying less, not by shrinking type.
- **Confidence: medium-high** that body text under 9 pt and pale small text cost readability; the exact threshold depends on font and reader.

## 19. Which font

- **No font is best for everyone.** Wallace et al., ACM TOCHI 2022 (352 readers) [B]: reading speed differed by **35% between a person's fastest and slowest font**, with no loss of comprehension, and the best font differed from person to person.
- **Familiar beats exotic.** Legibility reviews [C]: familiarity with a typeface speeds reading; serif versus sans-serif makes no reliable difference.
- **Appropriateness matters for impression.** Shaikh & Fox (2008) [B]: the same CV in a typeface judged appropriate for the job made the applicant seem more knowledgeable, professional and trustworthy than in a neutral or unsuitable typeface.
- **Easy to read is judged more true and more intelligent.** Reber & Schwarz (1999) [B]: the same statement was believed less when printed in a hard-to-read form. Oppenheimer (2006, five experiments) [B]: needlessly complex words *and* hard-to-read fonts lowered ratings of the author's intelligence.
- **Hebrew:** one trial of a dyslexia-oriented Hebrew font (230+ participants) found modest gains mainly for dyslexic readers, and no overall difference between serif and sans-serif [C]. No study of Hebrew fonts in CVs or business documents. **[None]**
- **Reading:** the choice among common, well-made fonts matters little. What matters is that the font is ordinary, clean and familiar, and that the page is easy to read. Our five font choices are all acceptable. **Offering many fonts is not where value lies.**

## 20. Layout

- **TheLadders eye-tracking, 2018** [C, a company's own study, sample size not given; the only eye-tracking work on CVs]:
  - the worst-performing CVs had a "cluttered look and feel, characterized by long sentences, multiple columns, and very little white space", and "a poor layout that doesn't guide the eye down the page";
  - recruiters scan titles and subheadings; the report recommends making them bold;
  - short, declarative accomplishment statements did better than paragraph-length descriptions.
  - the 2012 edition: the six things looked at are name, current title and company, previous title and company, their dates, and education.
- **Formal beats creative.** Arnulf, Tegner & Larssen, 2010 (90 raters, half of them professional recruiters) [B]: a formal layout was preferred over coloured or artistic designs for shortlisting. One later study reportedly found the opposite for a graphic layout [C]. **Not settled; the safer reading is conservative.**
- **Margins help.** Chaparro et al., 2004 [B]: text with margins was read with better speed and comprehension than text without.
- **Bullets help recall of the listed items**, across five experiments, **less so when the items are unlike each other**, and they reduce attention to nearby prose [B].
- **Columns:** stage 2 (our measurements and Enhancv's 357 tests): a second column breaks reading order in some extraction engines.
- **Reading for us:**
  1. One column, clear bold role titles, visible dates, generous margins, and real white space between roles.
  2. Tech Modern's sidebar is the one template that goes against the layout evidence and the parsing evidence at once.
  3. A page packed to the edges to "feel full" (a rule in our prompt) is the cluttered pattern that did worst.

## 21. Order of sections

- **No experiment compares section orders.** No peer-reviewed study compares chronological with skills-first ("functional") CVs on real outcomes either. **[None]** Career sites assert that recruiters distrust the functional format; none cites data.
- What exists:
  - the eye-tracking finding that the eye goes to current title, company and dates first [C];
  - Risavy's 2017 review of the CV literature [B]: write clear, concise CVs "with additional attention given to the Experience and Education sections"; and notes most of this literature is old;
  - Huntr 2025 (157,445 tailored CVs) [A, vendor]: CVs that led to interviews had a summary 92.7% of the time against 89.3% for the rest; the difference is tiny.
- **Reading:** our order (summary, experience, education, then skills and the rest) matches what little evidence exists and what readers expect. There is no basis for changing it. For a recent graduate with little experience, putting education above experience is conventional; no study supports or contradicts it.

## 22. Dates and gaps

- **Behavioural Insights Team trial, UK, 2019-2020** (9,022 real applications; the same experiment later published in Nature Human Behaviour) [B]: writing each job's duration as a **number of years in place of calendar dates raised positive callbacks by 4.8 percentage points (14.6%)**; it worked best for high-skill and full-time roles. A 2.5-year gap, explained or not, made no significant difference in this trial, which the authors note does not match earlier studies.
- Huntr Q1 2026 [A, vendor]: interview rates start to fall after about six months out of work.
- **Reading:** the strongest causal finding on CV *formatting* that exists, and it conflicts with recruiters' wish to see dates. A candidate for an optional layout for users with gaps, to be tested, not a default.

## 23. Writing: what to say and how

### What has evidence
| Rule | Evidence | Mark |
|---|---|---|
| **No spelling or grammar errors** | Martin-Lacroux & Lacroux, 2016 (536 recruiters): spelling errors hurt shortlisting chances **as much as lacking professional experience**; recruiters who spell poorly themselves penalised less. The CVs tested had five or more errors. | B |
| **Plain words over impressive ones** | Oppenheimer 2006: needless long words lowered the author's rated intelligence. Matches stage 6's "AI vocabulary" finding from another angle. | B |
| **Job-related statements of competence help** | Earl, Bright & Adams (1998), replicated: adding statements of competencies relevant to the job raised managers' ratings; where on the page they appeared made no difference. | C |
| **Self-praise unrelated to the job hurts** | Knouse and colleagues (1988, 1994): impression-management statements improved ratings when tied to the job and **lowered them when not**. One study of 81 managers rated CVs with such tactics unfavourably on nearly every dimension. A later study of real CVs found some self-focused tactics helped. Mixed. | C |
| **Concrete over abstract** | Hansen & Wänke, 2010: the same content was judged more probably true in concrete wording. The original study has been criticised and a preregistered replication exists whose result I could not read. | C, contested |
| **Short, separate statements** | TheLadders 2018; Huntr 2025: interviewed CVs averaged **4.4 bullets per role at about 160 characters**, against 4.7 at 157 for the rest. | C / A (vendor) |
| **Clear, error-free prose** | Wiles et al. (stage 3): +8% hires. | A |
| **Detail in cover text relates to interviews** | Wingate et al., 2025, Int. J. of Selection and Assessment (183 job seekers): more detail, clarity and structure went with more interviews and faster employment. Known to me through summaries. | C |

### What has no evidence
- **"Power words" and lists of strong verbs.** I found no experiment showing that any set of verbs improves ratings or callbacks. Vendor pages recommend them "because ATS keyword matching favors them", which stages 2 and 4 do not support.
- **The "achieved X, measured by Y, by doing Z" formula** (stage 6, first pass).
- **Accomplishments versus duties** as a tested contrast: asserted everywhere, tested nowhere I could find. It is plausible, and consistent with "concrete and job-related".
- **Recruiters reading personality from a CV:** they do it, and it is mostly wrong. Burns, Christiansen and colleagues (2014) [B]: such inferences had low agreement between raters and little validity. So there is no reliable "tone" to engineer.

### What this adds up to
The evidence supports a short list, and it is the same list as the anti-fabrication rules:
1. Say what the person did, in the job's own terms where true.
2. Use the plainest accurate word.
3. One fact per line; keep lines to roughly one and a half printed lines.
4. Give a number when the person has one.
5. Do not praise; describe.
6. Zero language errors.

**A "strong word" is a specific one.** "Reduced" is stronger than "optimized" because it says what happened, not because it is on a list. A verb list in a prompt produces the repeated, formulaic openings that practised readers recognise as AI writing.

## 24. Using the information we already hold

What we have per user that a plain CV tool does not: a profile with evidence per skill, verified or not, dated; answers to Ariel's questions; and the job's requirements.

1. **Select before writing.** Decide in code which experiences and facts bear on this job's requirements; give the model those. This also solves length: the page fits because less is said, not because the type is small.
2. **Order by relevance within a role, and keep the most distinctive facts.** One 2026 paper named the quiet loss of "the most distinctive accomplishments" as a failure type of its own.
3. **Prefer verified facts for prominent positions** (summary, first bullet of the latest role). Unverified ones can appear lower, or prompt a confirmation.
4. **Use the user's own numbers and words** from Ariel's answers verbatim where they are clear. Their phrasing is the least "AI-sounding" text we have. Huntr: 88% of job seekers say their CV leaves out important work, and a third say putting numbers on results is the hardest part; this is what Ariel is for.
5. **Skills list:** Huntr 2025: interviewed and non-interviewed CVs listed almost the same number of skills (26.5 vs 26.0). Count does not matter; relevance and backing elsewhere on the page do. Our cap of 20, ordered by relevance to the job, is reasonable.
6. **LinkedIn link:** present on 71.7% of interviewed CVs against 64.3% of the rest (Huntr 2025). Weak evidence; cheap to include when the user has one.
7. **Certifications:** interviewed CVs listed slightly *fewer* (1.06 vs 1.23). List the relevant ones only.

## 25. Design insights, in order of how well they are supported

| # | Insight | Support | What it would change |
|---|---|---|---|
| 1 | **Raise the minimum text size**; nothing under about 8.5-9 pt, bullets 9.5-10 pt | Vision research (strong, not CV-specific) | All five templates; needs less text per page |
| 2 | **Dates in dark text**, same size as body | Contrast standard (measured: 2.56:1 today) + dates are a first-glance item | Four templates |
| 3 | **Fit the page by selecting content, not by shrinking** | Follows from 1, and from the fabrication evidence | Generation logic and the "feel full" rule |
| 4 | **One column everywhere**; retire or rework the sidebar template | Parsing tests (ours, Enhancv's) + eye-tracking report | Tech Modern |
| 5 | **Bold role titles; clear white space between roles; real margins** | Eye-tracking report; margins experiment | Check each template |
| 6 | **Conservative look**; colour only as a thin accent | One experiment, one contrary | Already true of four templates |
| 7 | **Avoid italics for running text and light text on dark** | Fluency research; general legibility | Classic, Executive, Tech Modern |
| 8 | **Plain headings**; consider dropping wide letter-spacing | Our own stage 1 note that letter-spaced headings broke text search in an extracted PDF | All five; worth a parsing check |
| 9 | **Fewer templates, better made**, not more fonts | Wallace 2022: no font wins; differences are personal | Product choice |
| 10 | **Optional "years" format** for users with gaps | One large field trial | New option, to be tested |
| 11 | **A spelling and grammar pass on every export**, in both languages | 536-recruiter experiment | New check; Hebrew needs a native-quality checker |

### What I would not change on the evidence
- Section order.
- The choice among our current fonts.
- One page as the default (the founder's decision; the data on length is unsettled).

### Not known
- Anything measured on Hebrew CVs: fonts, size, order, wording.
- Whether any of the above moves interview rates for our users. Items 1, 2 and 4 are safe on general grounds; the rest are best treated as things to test.

**Founder decision, 2026-11-12:** the "years in place of dates" format (section 22, insight 10) is **not** adopted for now.

---

# Fourth pass: what 1,500 example CVs actually look like (2026-11-12)

The founder asked for a systematic look at sites that display large numbers of CVs. I downloaded and parsed a sample from five sites and measured each CV the same way.

## 26. What was collected

| Source | What it is | Sample |
|---|---|---|
| **Kickresume, "hired by" samples** | CVs contributed by users who got a job at a named employer (Apple, IBM, Amazon, universities, small firms). Names are replaced; the text is the person's own. | **332 CVs, 4,212 experience lines** |
| Kickresume, site-written samples | Samples that repeat the site's own stock phrases ("Achieved a GPA of 3.98", "Employee of the Month"). I separated these out by those phrases. | 371 CVs |
| Kickresume, unclear | No employer named, no stock phrases. | 97 CVs |
| Enhancv examples | Written by the vendor for each job title. | 288 CVs, 3,696 lines |
| Careerflow examples | Written by the vendor; published November 2026. | 203 CVs, 1,827 lines |
| BeamJobs examples | Vendor-written. Lines extracted from 150 pages. | 672 lines |
| Novorésumé examples | Vendor-written. Lines extracted from 87 pages. | 504 lines |

**Total: 1,291 fully parsed CVs plus 1,176 lines from two more sites.** 12 pages failed to parse and are excluded.

**How to read this, honestly:**
- The 332 "hired by" CVs are the only ones written by real applicants. They show what real CVs of people who were hired look like. **They do not show that the CV caused the hire**, and there is no comparison group of people who were not hired.
- They skew international (many European), early-career, and several years old.
- Everything else is the vendors' idea of a good CV, much of it machine-written. Per the founder's instruction it is treated as a picture of what the market sells, not as evidence.
- My separation of real from site-written samples is by stock phrases, so some site-written samples may remain in the "real" group.

## 27. The main finding: real CVs and vendor examples differ most on numbers

| | Lines containing a number | Lines with a % sign | CVs where 80%+ of lines have a number | CVs with no number at all in the experience section |
|---|---|---|---|---|
| **Real, hired (332)** | **15.5%** | 4.5% | **2.7%** | **38.8%** |
| Kickresume site-written | 14.2% | 9.8% | 0.8% | 44.4% |
| Novorésumé | 69.6% | 22.4% | n/a | n/a |
| BeamJobs | 82.7% | 60.0% | n/a | n/a |
| Enhancv | 50.5% | 44.3% | 19.4% | 0% |
| Careerflow (Nov 2026) | **100%** | 31.4% | **100%** | 0% |

- **A number in every line is a vendor pattern.** Among real CVs of people who were hired, about one line in six has a number, and more than a third of the CVs have none.
- **Our prompt requires a number in every line that can carry one.** A CV that follows it will resemble the vendor examples, and will be unlike nearly all real CVs in this sample.
- This does not show that numbers hurt. Stage 4's vendor data hinted that a number in the *summary* goes with more interviews. It shows that **uniform quantification is not what real successful CVs look like**, and stage 6's first pass showed what the demand for numbers does to accuracy.
- Enhancv's examples have a visible formula: a verb, then "enhancing / ensuring / resulting in" something "by 20%". The word "enhancing" appears 112 times per 1,000 lines there, against 2 per 1,000 in real CVs.

## 28. Length and shape of a line

| | Median line length | Middle half | Lines over 240 characters |
|---|---|---|---|
| **Real, hired** | **91 characters** | 62-137 | 4.1% |
| Kickresume site-written | 111 | 89-139 | 0.5% |
| Enhancv | 117 | 108-128 | 0% |
| Careerflow | 104 | 92-123 | 0.1% |
| BeamJobs | 117 | n/a | n/a |
| Novorésumé | 103 | n/a | n/a |

- Real lines are **shorter and far more varied in length**. Vendor lines cluster tightly around one length: Enhancv's middle half spans only 20 characters.
- **Our prompt asks for 55-240 characters and says "rich multi-clause bullets (up to 240 chars) are preferred".** That is about twice the length of a typical real line. Huntr's data (stage 4) put lines on interviewed CVs near 160 characters, so the truth for a strong CV is probably between 90 and 160, not 240.
- **Uniformity itself is the tell.** Every vendor corpus is more regular than the real one, in length, in opening verb and in structure.

## 29. Opening words

| | Share of lines opening with one of the ten most common first words | Lines opening with a past-tense verb |
|---|---|---|
| **Real, hired** | **21.5%** | 50.4% |
| Novorésumé | 27.0% | n/a |
| BeamJobs | 28.9% | n/a |
| Careerflow | 40.7% | 53.3% |
| Kickresume site-written | 44.1% | 94.0% |
| Enhancv | 48.3% | 86.8% |

- Real CVs use a wide spread of opening words (1,112 different first words across 4,212 lines). Vendor examples recycle a small set.
- Most common in real CVs: developed, managed, conducted, collaborated, provided, led, assisted, implemented. Ordinary verbs.
- **Half of real lines do not start with a past-tense verb at all.** They start with a noun ("Coordination of..."), a present-tense verb for a current job ("Run social media accounts"), or "Responsible for" (22 per 1,000 lines). Our prompt bans all of these outright.
- I am not claiming those forms are good writing. The point is narrower: **a CV in which every line opens with a punchy past-tense verb is a recognisable house style of CV tools.** Present tense for a current role is simply normal.

## 30. Words associated with AI writing, per 1,000 lines

| Word | Real, hired | Enhancv | Careerflow (Nov 2026) |
|---|---|---|---|
| enhancing | 1.9 | 112.0 | 0 |
| ensuring | 29.7 | 91.5 | 0 |
| resulting in | 36.8 | 80.4 | 0 |
| utilized | 5.7 | 38.1 | 0 |
| facilitated | 7.4 | 33.5 | 1.1 |
| cross-functional | 9.7 | 40.6 | 0.5 |
| comprehensive | 13.5 | 42.2 | 0 |
| effectively | 13.3 | 43.3 | 0 |
| streamlined | 4.3 | 18.9 | 0 |
| spearheaded | 9.3 | 13.8 | 0 |

- **Real people do use these words**, at low rates. A blanket ban is harsher than reality; what marks machine text is the *rate*.
- **The newest vendor corpus has already scrubbed them all.** Careerflow's November 2026 examples contain essentially none of these words, and plain verbs throughout, yet they are instantly recognisable: every single line has a number, lines are one length, and each CV follows one mould.
- **So the tell has moved from vocabulary to structure.** This matches stage 6's reading of the detection research (vocabulary first, formula second), and it means our word scrubber is fighting last year's problem. What needs guarding now is sameness: line length, line shape, a number everywhere.

## 31. Sections and their order in real CVs

| Measure | Real, hired (332) |
|---|---|
| Starts with a summary or profile | 73% |
| Has a summary at all | 74%; median 332 characters (middle half 240-448) |
| Has experience / education / skills | 93% / 95% / 87% |
| Experience placed before education | 74% |
| Hobbies or interests | 42% |
| Certifications or courses | 36% |
| Volunteering | 24% |
| Awards | 19% |
| References | 6% |
| Roles listed | median 3 |
| Lines per role | median 4 (middle half 2-5) |
| Words in the whole CV | **median 345** (middle half 267-509) |
| Written as bullet lists | 75% of roles |
| Dates as month and year | 92% of dated roles |

- **Most common order: summary, experience, education, skills, then extras.** This is our order.
- **Real CVs are short: about 350 words.** Vendor examples run 450-600. A one-page CV at a readable type size holds roughly 400-450 words, so the one-page default and larger type are compatible **if we write as much as real people do and no more**.
- **Our summary limit (360 characters) matches the real median.**
- **Summaries are where real people use clichés:** "proven track record" in 15% of real summaries, "dynamic" 12%, "results-driven" 10%, "seeking" 20%. Vendor examples have mostly dropped them. Clichés are common, not effective; there is no evidence either way on outcomes.
- 31% of the real CVs list a date of birth and 23% a nationality, a European habit. We do not, and Israeli guidance agrees.

## 32. Visual design on these sites

- **Enhancv (288 examples, read from the page code):** nearly all use one sans-serif body font (Inter); 248 use uppercase section headings; 206 show skill or language levels as dots or sliders; none has a photo; 130 are one page and 158 are two. Roughly half use the site's two-column layouts.
- **Kickresume (32 sample images viewed by eye):** most are two-column or have a coloured side band; many show skills as bars or stars; strong header colours are common; photos are rare.
- **Reading:** the template business sells visual variety: columns, colour, rating bars. None of it has evidence behind it, two-column layouts fail in some parsers (stages 2 and 4), and a rating bar ("Python ●●●●○") carries no checkable information and cannot be read by software at all.
- **Our plain single-column templates are closer to the evidence than the market is.** The gap in ours is type size and contrast (section 25), not a lack of decoration.

## 33. What this pass changes

| # | Finding from the sample | Consequence for our builder |
|---|---|---|
| 1 | Numbers appear in about 1 line in 6 of real hired CVs; in every line of the newest vendor examples | Remove "every bullet must carry a number". Use numbers the user has, where they have them. A number in the summary and in the first line of the latest role, if true, is a reasonable aim |
| 2 | Real lines are about 90 characters, varied | Drop the preference for 240-character lines; aim for one to one-and-a-half printed lines; allow natural variation |
| 3 | Real CVs use many different openings, including present tense for a current job | Stop forcing one sentence shape; allow present tense for the current role; keep banning empty filler, but by meaning, not by a fixed list of opening phrases |
| 4 | The newest machine-written CVs are clean of "AI words" and still obvious | Add checks for sameness: spread of line lengths, repeated openings, share of lines with numbers, repeated sentence skeletons |
| 5 | Real CVs run about 350 words | Fit one page by writing less. This is what makes larger type possible |
| 6 | Our section order is the common one | Keep it |
| 7 | Hobbies appear in 42% of real CVs, volunteering in 24% | Optional sections should be available when the user has something real to put there; no evidence they help or hurt |
| 8 | Template sites sell columns, colour and rating bars | Do not follow. Never add skill-level bars |

**Confidence:** high on the descriptive facts (measured on 1,291 CVs with the same code). Low to medium on what they imply for outcomes: this sample shows what real hired CVs look like, not which features got them hired.

**A check on myself:** the "real" group could differ from the vendor groups for reasons other than authorship (older, more junior, more European). Juniors have fewer numbers to report. So the true gap for experienced candidates is probably smaller than 15% against 100%. It is still far too large to be explained that way: even among real CVs, only 2.7% have numbers in most lines.

## 34. Still missing for this stage
- **Hebrew CVs.** None of these sites has a Hebrew corpus. The Israeli sites that might (AllJobs, Drushim, JobMaster) do not publish CVs. This remains the largest hole.
- **Outcome-linked data of our own.** Only tracking which of our generated CVs lead to interviews will tell us which of these features matter.
- **Our own output measured the same way.** The parser built for this pass can be pointed at our generated CVs to report the same numbers (share of lines with a number, line-length spread, opening-word concentration). That makes "does our CV look like a real one or like a vendor sample" a measurable question for stage 7.

---

# Fifth pass: Hebrew CV examples and the founder's list of sites (2026-11-12)

The founder sent eight sites to review. Each was opened and read; the full examples were parsed with the same kind of code as the fourth pass.

## 35. What each site turned out to be

| Site | What is there | What was taken | Notes |
|---|---|---|---|
| **Nayeret** (nayeret.ai) | 13 full Hebrew CVs by role, each with tips, "ready sentences" with placeholders, common mistakes | all 13 | Plain Israeli Hebrew, no long dashes. Says the details are invented. |
| **Custro** (custro.com/he) | 10 full Hebrew CVs by role (updated Aug 2026); 3 downloadable templates and 11 shown in its editor | all 10, plus the template page and its guidance | The most explicit guidance on layout and file format of any site reviewed. |
| **Wizlu** (wizlu.co.il) | 11 full CVs, mostly senior hi-tech roles, in Hebrew with heavy English | 11 (the page is built in JavaScript; read through a real browser) | Calls them "real" examples; the details are fictional (`noa.cohen@example.com`). Uses long dashes and check marks. |
| **CV Hebrew** (cv-hebrew.com) | Says "hundreds of examples"; in fact about 12 profession pages, each a long guide, published 2022-2023 | 12 pages read | No full CVs to measure. Older advice (e.g. "never more than one page"; an example role dated 2001-2004). |
| **Kickresume** | Already sampled in the fourth pass (800 pages). Its AI writer page has a separate gallery of "AI-generated resume examples". | confirmed the split | The fourth pass separated real "hired by" CVs from site-written ones; the AI gallery is a third kind, kept out. |
| **Resume Worded** | 334 example pages | 60 pages, 1,186 lines | 64% of lines with a number; top ten opening words cover 48% of lines. Same vendor pattern as section 27. |
| **Novorésumé** | Sampled in the fourth pass | 87 pages | |
| **Zety** | Refuses automated access | none | |

**All 34 Hebrew CVs are written by the sites, with invented details.** None is a real applicant's CV. They show what Israeli CV sites recommend in 2026, not what works. Real Hebrew CVs are still the missing piece.

## 36. Hebrew examples, measured (34 CVs, 192 experience lines)

| | Nayeret (13) | Custro (10) | Wizlu (11) |
|---|---|---|---|
| Lines with a number | 55% | 91% | 87% |
| Median line length | 62 characters | 69 | 62 |
| Lines opening with a first-person past verb (הובלתי, בניתי, ניהלתי) | 50% | 63% | 22% |
| Lines containing an English term | 18% | 30% | 91% |
| Median words per CV | 163 | 145 | 203 |
| Has a summary | 12 of 13 | **none** in the full examples (offered separately as two versions) | 10 of 11 |
| Military / national service section | 5 of 13 | 8 of 10 | 0 of 11 |

**Section order, as each site uses it:**
- Nayeret: תקציר › ניסיון תעסוקתי › (שירות צבאי / לאומי) › השכלה › (קורסים ותעודות) › כישורים › שפות
- Custro: ניסיון תעסוקתי › שירות צבאי › השכלה › כישורים וכלים › שפות
- Wizlu: תקציר מקצועי › תחומי מומחיות › ניסיון תעסוקתי › השכלה והסמכות › כלים וטכנולוגיות › שפות

## 37. What the Hebrew sites agree on (and how it compares with ours)

| Point | What the sites say | Our product today | Gap |
|---|---|---|---|
| **Summary heading** | Nayeret: **"תקציר"**. Wizlu: "תקציר מקצועי". Custro's guide: "התקציר". None of *these three* uses "תמצית" (**corrected in section 42: AllJobs does**). | **"תמצית"**, with a code comment calling "תקציר מקצועי" a calque | **Our choice is the minority form.** "תקציר" is plain, used by two of three sites, and is not a calque. Worth the founder's decision |
| **Military service** | Placed **right after experience**, before education (Custro 8 of 10; Nayeret whenever present). (**Narrower than it looked: recruiter-run sites differ, see section 43.**) Custro: for a released soldier "the military service *is* the experience": build it like a job with 3-4 lines and numbers | Placed near the **end** of the page, after skills and languages | Move it up for Hebrew CVs, at least when it is recent or substantial |
| **National service** | Nayeret's heading: **"שירות צבאי / לאומי"** | "שירות צבאי" only | Users who did national service (שירות לאומי) have no correct heading |
| **Length** | One page up to about five years of experience; two acceptable after (Nayeret, Custro). Custro: "always one full, balanced page, not a page and a half" | One page by default (founder's decision) | Consistent. The "about five years" threshold is a reasonable rule for when to offer two |
| **Photo and personal details** | No photo; no ID number, age, marital status or parents' names (Nayeret, Custro) | None of these | Consistent |
| **Columns and rating bars** | Custro: one column, standard headings, no tables, no text boxes, nothing in the document header; the one two-column template is labelled "check against ATS". Nayeret: no columns and no skill bars ("JavaScript 80%"): "screening systems don't read them and recruiters don't understand what they mean" | Four single-column templates; Tech Modern has a sidebar | Same conclusion as section 25: retire or rework the sidebar |
| **Fonts** | Custro: use fonts present on every computer (Arial, Times New Roman) in Word files; send PDF unless Word is requested | Embedded Heebo in PDF | PDF with an embedded font is the safe case; only matters if we offer Word export |
| **File name** | Custro: full name and role, e.g. "דנה-לוי-מנהלת-שיווק.pdf", never "קורות חיים סופי 3" | Already sends a proper UTF-8 file name (`resumes.py`) | Check that it contains the name and role |
| **Contact line** | Name, a title line under it, then city · phone · email · LinkedIn on one or two lines | Same | Consistent |

## 38. Writing Hebrew lines: what the examples show

- **Three verb forms are in use:**
  - first-person past ("הובלתי", "בניתי", "צמצמתי"): the most common in Nayeret and Custro. Gender-neutral, which is why our Hebrew pass already uses it;
  - present tense for a current role ("מלמדת", "מנהלת", "מוביל"): common in all three, and **gendered**;
  - verbal nouns ("ניהול", "הובלת", "השקת"): Wizlu's dominant style (ניהול alone opens 14 lines). Gender-neutral and compact.
  - **Insight:** now that we hold the user's chosen Hebrew form (stage of PR #136), present tense for the current role becomes possible in the right gender. Verbal nouns are the neutral fallback. A CV where every line opens "הובלתי / בניתי / ניהלתי" has the same sameness problem as section 29.
- **English inside Hebrew** depends on the field: about 18% of lines in general roles (teacher, bookkeeper, nurse), 91% in senior hi-tech. Our localisation keeps the job's English terms, which matches the hi-tech pattern; for non-tech roles the examples are almost all Hebrew.
- **Hebrew lines are short**: median about 64 characters, against 91 in real English CVs. Hebrew is compact (prefixes attach to words), so the same content takes fewer characters. A character limit tuned for English is about 40% too generous for Hebrew.
- **AI-style markers in Hebrew examples:** Wizlu's lines use long dashes and English-in-brackets; Nayeret and Custro use plain hyphens and full Hebrew sentences. This matches the Israeli press list of Hebrew AI tells (stage 6, section 4), which I could now see in practice: the long dash is the most visible one.
- **Numbers:** two of the three Hebrew sites put a number in nearly every line, and Custro instructs "an achievement line with a number in every section". The same vendor pattern as section 27, now in Hebrew.

## 39. Ideas worth borrowing (inspiration, not evidence)

1. **"What the reader looks for first", per role.** Nayeret opens each example with the three things the reader checks first (for a teacher: subjects and grades taught, teaching licence, and what changed for the pupils). That is a ready-made rule for choosing the summary and the first line of the latest role.
2. **Sentences with blanks instead of invented numbers.** Nayeret's "ready sentences" look like: "הכנתי [X] כיתות לבגרות ב-[X] יחידות, עם שיעור זכאות של [X]%". The structure is offered; **the number must come from the person.** This is the honest version of what our prompt does wrong: in place of asking the model for a number, Ariel can ask the user to fill the blank, and the line is only used when they do.
3. **Common-mistakes lists per role**, written for the user: for example "do not write 'loves children'; show it through what you did".
4. **A two-version summary**, one for someone moving into the role, one for someone experienced in it (Custro).
5. **Custro's copy-paste test**: copy all the text from the PDF into a plain text file; if the order is scrambled, a screening system will see it scrambled. A simple check we can run automatically on every export.

## 40. What this pass changes

| # | Change suggested by the Hebrew examples | Strength |
|---|---|---|
| 1 | Consider "תקציר" in place of "תמצית" for the Hebrew summary heading | Medium (three sites; no outcome data) |
| 2 | Move military service up, after experience, in Hebrew CVs | Medium (consistent across sites; matches how Israeli readers treat service) |
| 3 | Offer "שירות צבאי / לאומי" so national-service users have a correct heading | High (a correctness fix, not a preference) |
| 4 | Shorter line limits for Hebrew than for English | Medium (measured) |
| 5 | Vary verb forms; allow present tense in the user's chosen gender for the current role, verbal nouns as the neutral option | Medium |
| 6 | Use "fill the blank" questions for numbers in place of asking the model for numbers | High that it prevents invented numbers; medium that it improves the CV |
| 7 | Add the copy-paste reading-order check to every export | High (cheap, and directly tests the failure the Hebrew word-order research found in stage 2) |
| 8 | **Scrub the Hebrew output for AI markers.** Checked in the code: the word-and-dash scrubber runs *before* the Hebrew pass (`tailor.py` lines 1871 and 1901), and the Hebrew pass (`cv_localize.py`) has no scrubber of its own. Its instructions to the model also contain ten long dashes, which tends to invite the same in the output. **So a Hebrew CV can currently ship with long dashes.** A small fix: run the scrubber again after localisation, and remove the dashes from that prompt | High (a confirmed gap against the founder's standing rule) |

**Done (2026-11-12, founder decision, commit 9ed9e37):** items 1, 2, 3 and 8. The Hebrew summary heading is now "תקציר"; in Hebrew CVs, service sits in the main column right after experience and before education (English is unchanged); national service and civic service get their own heading ("שירות לאומי", "שירות אזרחי"); and the Hebrew output is scrubbed after localisation, with no long dashes left in its prompt. Verified in all five templates, with real PDF extraction tests passing.

**Still missing:** real Hebrew CVs of people who were hired. Everything Hebrew in this document is still either the sites' recommendations or our own reasoning.

---

# Sixth pass (2026-11-12): the founder's list of Israeli sites, checked one by one

The founder sent about 30 links: Israeli job boards and placement companies, CV builders, template galleries and writing guides. Each was opened in a real browser (text and full-page screenshot); template images and downloadable files were saved and read; one builder was driven by hand. Raw material stays in the session scratchpad. This pass matters more than the earlier Hebrew pass because it reaches **sites run by recruiters and placement companies**, not only AI-built CV vendors.

## 41. What each site turned out to be

| Site | Who runs it | What was there | Reached? |
|---|---|---|---|
| AllJobs (builder page, full guide, 2023 article) | Israel's largest job board | Official guide ("7 parts"), 7 Hebrew template images | Yes |
| Drushim (builder intro, article 296) | Major job board | Builder intro, article on how much experience to list | Yes (builder needs an account) |
| Embuild | Placement company | Builder with 5 templates and **10 full example CVs by profession** | Yes, and the builder was driven by hand |
| GoldenJob | Placement company | Long guide (May 2024) | Yes |
| JobsSeek | Job site | Guide plus **3 Word and PDF template files** | Yes, files downloaded |
| WorkFinder | Job board | Builder, 35 templates (6 free/premium viewed) | Yes |
| Click Jobs | Job board | Builder form (needs registration to download) | Yes |
| BMate | CV-writing service since 2007 | Short guidance page (2019 era) | Yes |
| NoBsResume | International free builder | One full Hebrew example | Yes |
| ResumeBird, ResumeCoach, CVWizard | International template companies | Landing pages, one Hebrew example (ResumeBird) | Yes |
| OwlApply | International AI tool | 60 templates, 22 marked ATS | Yes |
| WPS, MobiSystems, Notion | Office/notes software | Word/Notion template galleries | Yes |
| EnResume, EasyStudyAI | Small Israeli tools | Blog posts | Yes |
| taasuka.gov.il (two pages) | Israeli Employment Service | | **No: the government site answers 403 from outside Israel** |
| JobNinja | Job site | | **No: Cloudflare blocks automated access** |
| Barak L | CV service | | **No: connection reset** |
| Canva (design link and two searches) | | | **No: login required and 403 on every public page.** The design link is a private design that only the founder can open |
| Google image search | | | Not reachable from this environment |

**Still worth doing by hand:** the Employment Service pages (open them from Israel and save as PDF), and the founder's own Canva design.

## 42. The summary heading: both words are in use

The previous pass said "none uses תמצית". **That was wrong;** it was based on three AI-built sites.

| Heading | Where |
|---|---|
| **תקציר** / תקציר מקצועי | Embuild (all 10 examples), JobsSeek (3 files and guide), WorkFinder, EasyStudy, ResumeBird, and earlier Nayeret, Wizlu, Custro |
| **תמצית** | **AllJobs: its official guide and all 7 templates**; BMate |
| Others | "פסקת פרופיל אישי" (GoldenJob), "סיכום מקצועי" (NoBs, a translation), "אודות" (Click Jobs), "על עצמי" (JobsSeek, no-experience file) |

**Reading:** "תקציר" is the more common word on today's sites, and "תמצית" is the established word of the largest board. Neither reads as wrong to an Israeli recruiter, and there is no outcome data either way. The founder's switch to "תקציר" stands; it was a choice between two correct words, not a fix.

## 43. Where military service goes: the earlier evidence was too narrow

| Placement | Sources |
|---|---|
| **After education** | **AllJobs guide (its 7-part order) and all 7 AllJobs templates**; JobsSeek classic and hi-tech files; GoldenJob and BMate (at the end, after education and skills) |
| **One line at the bottom**, under "נוסף" ("שירות צבאי מלא, מש"קית ת"ש") | **Embuild: 9 of its 10 examples** |
| **Right after experience** | Custro (8 of 10) and Nayeret: the two AI-built vendors the previous pass relied on |
| **Moved up and written like a job** | When there is little or no work experience: JobsSeek's no-experience file (education, then service with bullets, then experience); Embuild's no-experience example (service appears in the summary); GoldenJob ("if most of your experience was in the service, describe it in more detail") |

**Honest reading:** the sites run by recruiters and placement companies do **not** put service right after experience for people who have work experience. They keep it short and low on the page. They move it up and expand it only when the service *is* the experience: a young or recently released candidate.

**What this means for the change made today (commit 9ed9e37):** service now always sits right after experience in Hebrew CVs. That suits a junior candidate, but it does not match the recruiter convention for someone with several years of work. **Recommended rule, for the founder's decision:**
- Work experience of about two years or more: service goes after education, kept to one or two lines (role, unit, years).
- Little or no work experience, or service ended recently: service stays where it is now, after experience, written like a job.
- National service and civic service follow the same rule under their own heading (already done).

## 44. How lines are written: recruiters use verbal nouns

- **AllJobs guide, explicitly:** do not write in first person ("הכנתי מצגות", "ניהלתי אנשים") because it reads like a personal story. Use **verbal nouns** ("הכנת מצגות", "ניהול עובדים", "יצירת שיתופי פעולה").
- **GoldenJob:** "avoid writing in the first person" (although its own example line starts "הובלתי").
- **Embuild, measured:** 90 experience lines across 10 examples. **None** starts with a first-person past verb; they open with "הכנת", "ניהול", "קליטת", "תיאום", "טיפול". About a quarter contain a number. The median line is 47 characters.
- **First person** ("הובלתי", "פיתחתי", "הגדלתי") is what the content sites teach: EasyStudy, GoldenJob's example, Custro, Nayeret.

**Our product today:** the Hebrew prompt (`cv_localize.py`) tells the model to start *every* line with a first-person past verb. That is the vendor style, not the recruiter style. Verbal nouns are also gender-neutral, and shorter in Hebrew.

**Recommendation for the founder's decision:** make verbal nouns the default for Hebrew lines, with first person allowed occasionally for a standout achievement. This also helps against the sameness problem in section 29 (every line opening "הובלתי / בניתי / ניהלתי").

## 45. Other findings, briefly

- **Numbers:** recruiter-written examples put a number in about a quarter of lines (Embuild), close to the 15.5% measured in real hired English CVs (section 27). The template companies put one in every line. This is more support for dropping the "number in every bullet" rule.
- **Font size and spacing:** AllJobs recommends Arial 11 in black, section headings up to 12, and line spacing of 1.35 to 1.5. GoldenJob says 11 to 12. EasyStudy says 10 to 12, with margins of at least 1.5 cm. JobsSeek's file uses Arial at about 10.6. Our templates use 6.5 to 9 pt (section 18). This is the strongest agreement anywhere in this research, and it supports enlarging our text.
- **Photo:** the recruiter guides advise against one (AllJobs, Embuild, EasyStudy; JobsSeek says "not required"). Builders show photos to sell templates: WorkFinder's samples all have one, Click Jobs asks for an upload, and AllJobs has one in 2 of 7. The founder's no-photo decision matches the guides.
- **Age:** AllJobs templates show a birth year, and its guide suggests an "age anchor" such as the service years. The other guides say to leave age out. We leave it out; the law forbids age discrimination, and privacy comes first.
- **Skill ratings:** Click Jobs asks the user to rate each skill from 1 to 5. That is the pattern Nayeret and stage 2 warn against, because systems can't read it and recruiters can't interpret it.
- **Translated foreign templates are a warning sign.**
  - ResumeBird's Hebrew sample is a lawyer who presents cases "to judges and juries" (Israel has no juries), lists a job in Los Angeles, gives a full street address, and opens with "רקורד מוכח" and "להט ומסירות לצדק".
  - OwlApply's Hebrew ATS page shows English American CVs only.
  - NoBs' Hebrew example uses third-person masculine verbs ("הוביל", "הנחה") and "סיכום מקצועי", which reads as machine translation.
  - **This is exactly what our Hebrew pass must not produce.**
- **Statistics on these sites are unreliable.**
  - Recruiters supposedly read a CV for 6 seconds "according to LinkedIn and Glassdoor" (EasyStudy), 7 seconds (GoldenJob), or 10 to 30 seconds (AllJobs).
  - Click Jobs gives both 15 and 6 seconds on the same page.
  - EasyStudy says 75% of companies reject CVs "automatically". Stage 2 found automatic keyword rejection to be largely a myth.
  - None of these figures should reach our product text.
- **Machine-written Hebrew in the guides themselves:** EasyStudy's 2026 guide is full of long dashes, the same marker we just removed from our output.
- **Reading order in another site's PDF:** text extracted from JobsSeek's Hebrew PDF comes out scrambled. Brackets are mirrored, numbers stick to the next word ("כתבו2", "עם6"), and a range such as "2 to 3" splits across lines. This is the failure stage 2 described, seen in a real file. It supports item 7 of section 40, a copy-paste reading-order check on every export. Our own PDFs pass the Hebrew heading extraction tests.

## 46. How the builders work (the mechanics, for our own flow)

- **The common flow:** choose a template, fill a form split into sections, watch a live preview, then download a PDF. Embuild, WorkFinder, NoBs, CVWizard, ResumeCoach and ResumeBird all follow it.
- **Starting from an existing file:** WorkFinder and ResumeCoach parse an uploaded CV into the form ("AI breaks it into the form"). We already do this.
- **Gates:**
  - Click Jobs, Drushim and AllJobs need registration or a profile on the board.
  - NoBs keeps everything in the browser, with no account at all.
  - EnResume, WorkFinder (premium), ResumeBird and ResumeCoach charge at download.
  - Embuild and JobsSeek are free with no signup.
- **What Embuild does well (driven by hand):**
  - Each section shows a "done / missing" dot.
  - Every field has a plain example placeholder, e.g. "two or three lines: what you do, how many years, and what you are looking for now".
  - Validation is inline ("צריך מספר טלפון").
  - There are five templates of the same content, switchable at any time.
  - **Example CVs by profession** (customer service, bookkeeper, warehouse, no experience, and others) open straight in the builder.
  - Each example comes with "what to write" notes for that profession. For a bookkeeper, for instance: name your certificate grade (סוג 2 / סוג 3) and list which entries you post yourself.
- **Ideas worth borrowing (inspiration, not evidence):**
  - Per-profession "what recruiters look for" notes shown next to the user's own lines. These would come from the job description in our case, not from a fixed list.
  - A placeholder sentence per field written in plain Israeli Hebrew.
  - The profession examples as a "see what good looks like" link in the editor.

## 47. What this pass changes

| # | Change | Strength | Status |
|---|---|---|---|
| 1 | Correct section 37: "תמצית" *is* used, by AllJobs. "תקציר" stays as a choice between two correct words | High (direct observation) | Recorded here |
| 2 | Make service placement depend on experience: after education for experienced candidates, after experience (as today) for juniors | **High that recruiter sites do this**; no outcome data | **Waiting on the founder.** Today's code always puts it after experience |
| 3 | Hebrew lines: verbal nouns by default in place of first person | Medium-high (the largest board's guide plus one placement company's 90 lines, against content sites) | **Waiting on the founder** |
| 4 | Body text at 10.5 to 11 pt, headings up to 12 | High (every guide that gives a number agrees) | Waiting (already proposed in section 25) |
| 5 | Drop "a number in every bullet" | High (now also Hebrew recruiter evidence) | Waiting (already proposed) |
| 6 | Never let site statistics ("6 seconds", "75% rejected automatically") into product text | High | Rule to keep |
| 7 | Reading-order check on every export | High | Waiting (section 40, item 7) |

## 48. Founder decisions on service and line form, and the research behind the second (2026-11-12)

**Service placement (decided, implemented in commit 07b950c).** The founder rejected a rule based on years of experience. The system is meant to be tailored per person: a former major or captain, or someone whose service role is relevant to the job, keeps its weight even after ten years of civilian work. The final rule:
- The tailoring model decides how much to write about the service, for this person and this job. It writes 2 to 3 lines when the role is relevant to the job, when it was a senior or representative role (an officer with command or staff responsibility, or an owner of people, budget or systems), when it is a large part of the working life, or when the job asks for operational leadership. Otherwise it writes one line.
- The layout follows that choice: service with lines of its own goes right after Experience; a single line goes right after Education. This applies in every language.
- Service is never dropped (the old prompt dropped it for engineering roles). A rank the profile states may follow the function in brackets, and the Hebrew pass renders it as the Hebrew rank.

**How lines should be written: what recruiters expect.** Sources read in full:

| Source | What it says | Lines in its own examples |
|---|---|---|
| AllJobs guide | Verbal nouns, not first person ("הכנת מצגות", "ניהול עובדים") | 5 full examples: verbal nouns throughout ("פיתוח ותחזוקה", "הובלת כיתה") |
| Drushim, "how recruiters look at your CV" | "ניהלתי צוות - לא. ניהול צוות - כן" | |
| Drushim guide | "Don't settle for what you did; show what you achieved" | |
| Reichman University career center | No first or third person; "verbs or verbal nouns only" | |
| Tel Aviv University career center | "Active verbs", no vague terms | 2 examples: verbal nouns ("גיוס", "מיון", "קליטת עובדים") |
| Embuild (placement company) | | 90 lines: all verbal nouns, none in first person |
| **Manpower** (placement company) | **First person where you want to highlight your own contribution** ("יזמתי, הובלתי"); the company description in third person | |
| GoldenJob, EasyStudy, Custro, Nayeret | Teach first-person past verbs | Mostly first person |

**Reading:** the two forms do different jobs. Scope and responsibility, meaning what the role covered, is written as verbal nouns: the established, neutral and compact recruiter register. A result the candidate personally drove can be in first person, which is exactly Manpower's point: it makes the contribution theirs. All the sources agree on what matters more than the form: achievements over duties, relevance to the job, and no inflation. None of this is experimental evidence; these are practitioners' guides, weighted toward those who hire.

**Implemented (founder's direction, "adaptive, not one fixed form"):** the Hebrew pass now chooses the form line by line. Verbal nouns are the default for scope; first-person past is allowed for the strongest one or two achievement lines of a role. It never uses "אני", never third person, never "אחראי/ת על", and never opens three lines in a row with the same word. The previous rule, "every line opens with a first-person past verb", is gone.

**Canva:** the founder asked for design inspiration from Canva's thousands of CV templates (not the founder's own design). Canva runs a security check that blocks automated browsers on every page, including the public template galleries and their images. I did not try to get around it. A search confirms Israeli creators publish Hebrew CV templates there, for example one creator with 138 templates and a 13-template "דרושים • קורות חיים • HR" collection. Ways to reach them, all needing the founder:
1. Run the research from a session that drives the founder's own Chrome (Claude in Chrome, from the desktop app). This is the cleanest route, since Canva then sees an ordinary signed-in browser.
2. Save a set of Canva templates (screenshots or exported PDFs) into a folder and upload them here.

---

# Seventh pass (2026-11-12): Canva's CV templates, through the founder's own Chrome

## 49. What Canva's templates look like, and which parts of that design we can use

This section answers the open item at the end of section 48. The founder's own Chrome (Claude in Chrome) ran Canva's in-app template search while signed in. It only viewed template previews: it opened no template in the editor, created no design, and did not open the founder's own designs.

### What was collected and how

- **39 searches:**
  - **Hebrew:** "קורות חיים" alone, and with הייטק, מינימליסטי, מעוצב, סטודנט, מנהל, ללא ניסיון, מתכנת, מעצבת, מורה, אקדמי, שירות לקוחות, מכירות, עברית, לחייל משוחרר, מהנדס, אחות, רואה חשבון, עם תמונה, יוצר תוכן; also "קו״ח" and "רזומה".
  - **English:** resume, cv, ATS resume, software engineer, tech, executive, manager, customer service, creative, graphic designer, academic cv, teacher, minimalist, professional, nurse, sales, student, and hebrew resume.
- **What came back:**
  - **2,211 distinct templates** were recorded (title and preview image), 80 to 250 per search.
  - **1,506** of them are CVs by title. The rest were cover letters, job ads and timetables, which Canva's broad search mixes in.
  - Every search reports about 20,000 matches, so it ranks the whole CV catalogue rather than filtering it.
- **Measured by machine on all 1,506 preview images (1131 × 1600 px):**
  - page background;
  - how much strong colour the page carries;
  - the main accent hue.
- **Measured by eye on a stratified sample of 224** (32 per role group, chosen by a fixed random seed), plus the top 32 results of the plain Hebrew search:
  - columns or sidebar;
  - photo;
  - rating bars, dots or stars;
  - dark page;
  - type style.

  An automatic column detector was tried first. When checked against the images it **missed about a quarter of the multi-column pages**, so the column counts below come from the visual coding only.
- **Text size** was estimated from the spacing of text lines in the full-size preview images, for the 224 sampled templates. It is a rough method; treat it as ±1 pt.
- **Israeli creators:** the creators of every Hebrew-titled CV template were looked up, and their collections were opened:
  - Marina Zlochin, 20K followers, collection "משאבי אנוש - תבניות בעברית" (38 items, 7 of them CVs);
  - שחר אהרוני, 3.7K followers, collection "דרושים • קורות חיים • HR" (13 items, 3 of them CVs; the rest are job-ad posts).
- **Limits:**
  - One coder (me), no second rater.
  - Canva's ranking may depend on the signed-in account.
  - Template pages do not name their fonts, so fonts are identified by eye.
  - **No template was exported to PDF and run through a parser here.** Exporting would have meant creating designs in the founder's account. Statements about how parsers read these layouts rest on stage 2 and section 20, not on a new test.

**Screenshots:** contact sheets per role group, the Hebrew templates enlarged, and type close-ups are kept locally in `docs/research/canva-shots/`. The folder is excluded from git, and that is deliberate: this repository is public, and the images are other people's designs. The templates named below can be opened at `https://www.canva.com/templates/<id>/`.

### The market in numbers

**Layout (sample of 224; "multi" means a sidebar or two or more columns of text side by side):**

| Group (searches) | One reading flow | Multi-column | Photo | Rating bars/dots/stars |
|---|---|---|---|---|
| Tech (הייטק, מתכנת, מהנדס, software engineer, tech) | 11 | 21 | 18 | 5 |
| Management (מנהל, executive, manager, רואה חשבון) | 5 | 27 | 20 | 1 |
| Service, sales, nursing | 5 | 27 | 18 | 3 |
| Creative (מעוצב, מעצבת, creative, graphic designer, יוצר תוכן) | 6 | 26 | 25 | 9 |
| Academia and teaching | 5 | 27 | 21 | 4 |
| Entry level (סטודנט, ללא ניסיון, student, חייל משוחרר) | 5 | 27 | 16 | 1 |
| **"ATS resume"** | **14** | **18** | **18** | 1 |
| **All 224** | **51 (23%)** | **173 (77%)** | **136 (61%)** | **24 (11%)** |

**Colour (all 1,506, by machine):**
- **88%** of pages are white, 3% cream, 3% tinted and **6% dark**.
- **42%** carry almost no strong colour; outside a photo, colour is usually a single accent.
- **By title words:** "white" 714, "modern" 540, "black" 411, "minimal(ist)" 401 and 374, "professional" 397, **"blue" 323** (plus "navy" 28), "simple" 298. Then green 114, beige 111, creative 104, pink 94, brown 93, grey 177.
- The machine's hue count over-reports red and orange, because skin tones in photos fall in that range. **The title words are the better colour signal.**

**Type:**
- **Body text:** the median line pitch is **15 to 17 pt** in every group, and the median ink height of a line is about 9 pt. That puts body text at **about 10 to 11 pt with roughly 1.5 line spacing.** It is the same figure the Israeli guides give (section 45), and well above ours (6.5 to 9 pt, section 17).
- **The name** is by far the largest element, roughly three to five times the body size (estimated by eye).
- **Families seen (identified by eye):**
  - geometric sans in the Montserrat/Poppins style: the default for corporate, tech and service;
  - Arial-like grotesques on the plain "ATS" pages;
  - very wide or letter-spaced capitals for names and headings ("C A H A Y A  D E W I");
  - a serif display face for names in management and academia;
  - handwritten and script names in creative and teaching templates, about one in six of those groups.

### What separates the role groups

| Group | Look | Colour | Typical extras |
|---|---|---|---|
| **Tech** | Navy or charcoal sidebars, dark pages (8% of the group), a photo in a circle | Blue in 29% of titles, black in 31% | Skill bars and dots in "Programming languages"; "Tech stack" chips |
| **Management** | The most conservative: white pages, a navy or charcoal sidebar or top bar, serif or spaced-capital name, summary first | Black 32%, blue 21%, pink 1% | "Executive snapshot" box, "Key achievements" |
| **Service, sales, nursing** | Friendly: rounded photos, teal or soft-blue blocks, contact icons | Blue 29% | Language bars; nurses almost always shown with a photo |
| **Creative** | The most decoration: pastel or pink backgrounds, illustrations, florals, stickers, polaroid photos, huge display words ("resume") | Pink 15% (2% or less elsewhere except academia); the highest colour load (75th percentile 0.18, against 0.01 for "ATS") | The most rating bars (9 of 32); handwritten names |
| **Academia** | Mostly teacher templates: playful and pastel, some serif | Beige or brown 17% | **Hardly any real academic CVs** (publications, grants, courses taught). "academic cv" returns ordinary two-column pages |
| **Entry level** | Generic student layouts; "חייל משוחרר" returns English student templates with nothing Israeli about them | Blue 27% | "Objective" sections, a lot of empty space |
| **"ATS"** | Plainer: 14 of 32 in one flow, no dark pages, almost no colour | Black 40% | **But 18 of 32 are still multi-column and 18 still carry a photo.** The label is a search keyword, not a property |

### How the content is written (both languages)

- **English templates:**
  - The section names are "Profile / About me / Summary", "Work experience", "Education", "Skills" (often shown as bars), "Languages" (often as bars), "References" (names and phone numbers, or "available upon request"), and "Hobbies / Interests".
  - The text is mostly Lorem ipsum, or one generic paragraph reused across templates.
  - A role line is "Title / Company / City" with the dates beside it. The bullets open with past-tense verbs.
- **Hebrew templates** (10 CVs with Hebrew titles among the 1,506, all by the two creators above; 7 of the top 32 for "קורות חיים" are in Hebrew):
  - **Section names:**
    - Marina Zlochin's set: "פרופיל מקצועי", "ניסיון תעסוקתי", "מיומנויות אישיות", "השכלה", "שפות", "תחומי עניין", "יצירת קשר".
    - שחר אהרוני: "תקציר הקריירה", "ניסיון מקצועי", "השכלה", "מיומנויות", "שפות", "פרטים נוספים", "הערות" (the CV ends with "המלצות ניתן לצרף"); in another of hers, "אודות", "ניסיון תעסוקתי", "השכלה", "כישורים".
  - **Role line:** "2022 - היום | מנהלת שיווק ודיגיטל" or "יוני 2020 - היום | מנהלת כח אדם | חברת XYZ". Dates come first, then a vertical bar, then the role and the company.
  - **Bullets are verbal nouns throughout:** "בניית והוצאה לפועל של תוכניות שיווק", "ניהול קמפיינים ברשתות החברתיות", "יצירת תוכן", "עבודה שוטפת מול ספקים". That is the recruiter register from sections 44 and 48, **and the one our Hebrew pass now uses by default.** Latin words such as "Google" sit inside Hebrew lines.
  - **No Hebrew template has a military service section.**
  - Sample names are female ("נועה לוי", "תמר כהן", "ישראלה ישראלי"), with feminine role titles ("מנהלת").
  - The single-column template repeats the name and contact details in a footer.
  - **Type:** names are set in a tall, condensed, bold Hebrew display face, or in a slanted display face, with a photo beside them. The body is a plain Hebrew sans that looks like Assistant or Heebo.
  - **Layout:**
    - 9 of 10 are right-to-left in two columns: a narrow tinted column holds profile, skills, languages and contact, and the main column holds experience and education.
    - 1 of 10 is a single column with a pink header band.
    - 6 of 10 have a photo.
    - Colours are cream and brown, pastel pink, sky blue, or black and white.
- **The Hebrew gap:** Canva's Hebrew searches return mostly English templates. Across 21 Hebrew searches only these 10 Hebrew CV templates turned up, and 7 of them are one content set in different colours. **A well-made right-to-left Hebrew CV is close to absent from the largest template library.** This is room for us, not a lack of demand: Canva counts 20,000 CV templates in total.

### Design language we can adopt (it survives a parser and has support)

1. **The name as the one large element**, about two and a half to four times body size, with the target role in a smaller line beneath and **contact details on one text line** under that. Canva does this in nearly every template, and it matches what recruiters look at first (section 20).
2. **Body text at 10 to 11 pt and line spacing of about 1.4 to 1.5.** Canva (measured here), the Israeli guides (section 45) and the vision research (section 18) all point the same way. **This is the strongest single takeaway.**
3. **One accent colour, used only on headings, thin rules and the name.** The market's restraint on white pages (88% white, 42% with no strong colour) is compatible with the "conservative look" evidence (section 20).
4. **An accent chosen by role family, as a quiet signal:**
   - navy or charcoal for management and finance;
   - blue or teal for tech, service and health;
   - a warmer accent such as terracotta or plum for creative roles;
   - near-black for academia and law.

   This borrows Canva's role coding without its layouts. The "typeface appropriate to the job" result (Shaikh & Fox, section 19) supports letting the look fit the field; the colour mapping itself is a convention, not evidence.
5. **Thin rules under section headings, and white space between roles**, in place of boxes.
6. **The role line:** bold title, then company, with dates on the same line, dark and at body size. In Hebrew, the Israeli templates' order "dates | role | company" is familiar to local readers and worth offering.
7. **Hebrew headings from the local templates:** "ניסיון תעסוקתי" / "ניסיון מקצועי", "השכלה", "שפות", "תקציר" (section 42). "תחומי עניין" and "פרטים נוספים" are optional sections that local readers recognise.
8. **A full-width tinted header band** holding the name and contact as real text is acceptable. It keeps a single reading flow. The colour must keep 4.5:1 contrast.

### Structures that parsing systems read badly (do not adopt)

| Structure | How common on Canva | Why to avoid it |
|---|---|---|
| **Sidebars and two or more columns** | **77%** of the sample; 9 of 10 Hebrew templates; 18 of 32 even under "ATS" | Extraction mixes the reading order (stage 2; Enhancv's 357 tests; section 20). Right-to-left Hebrew adds a second ordering problem (section 45: JobsSeek's PDF came out scrambled) |
| **Text boxes and framed blocks** (boxed sections, tabs, cards, pastel blocks in Hebrew templates) | Common in creative, entry-level and Hebrew templates | In a design tool each box is a separate positioned frame with no reading order. Parsers read frames in drawing order or drop them |
| **Rating bars, dots and stars** for skills and languages | **11%** overall, 28% in creative | Software cannot read them, and recruiters cannot interpret "●●●○○" (sections 32 and 45) |
| **Icons in place of words** (phone, mail and pin icons with no label) | In most templates with a photo | The icon is an image; if the label is dropped, "phone" disappears with it. Keep the word or the plain value |
| **Photo** | **61%** | Israeli guides advise against it (section 45); the founder decided on no photo; it also invites bias |
| **Light text on dark backgrounds, and dark pages** | 6% of pages fully dark; dark sidebars are common | Legibility (section 25, item 7); and when the background is a separate shape, text can extract as white on white |
| **Script, handwritten and very wide letter-spaced display type** for names and headings | About one in six creative and teaching templates; spaced capitals are common everywhere | Letter-spaced headings break text search in an extracted PDF (our own finding, section 25, item 8); script is read more slowly (section 19) |
| **Timelines with dots and connectors, progress circles, skill "chips" in shapes** | Common in tech and creative | The decoration carries information that only the drawing holds |
| **Contact details only in a footer or header region** | One of the Hebrew templates repeats them in the footer | Some parsers skip page headers and footers; keep contact in the body |

**A note on the "ATS" label:** Canva's "ATS" templates are plainer, but most still have columns and photos. If our product says "ATS-safe", that must stay a property we test (stage 2), never a style name.

### What this pass changes

| # | Change | Strength | Status |
|---|---|---|---|
| 1 | Body text to 10 to 11 pt, line spacing about 1.4 to 1.5 | High: Canva measured here, Israeli guides, vision research | Waiting (section 25, item 1; section 47, item 4). Now triple-sourced |
| 2 | Keep one reading flow; retire or rework Tech Modern's sidebar | High (parsing evidence); the market does the opposite, and that is a sales choice, not evidence | Waiting (section 25, item 4) |
| 3 | An accent colour per role family, applied only to headings, rules and the name | Medium: market convention plus the appropriateness study; no outcome data | **For the founder's decision** |
| 4 | Offer the Israeli role-line order ("2022 - היום \| תפקיד \| חברה") in Hebrew CVs | Medium: what the local templates and guides show | **For the founder's decision** |
| 5 | Never show ratings, icons without labels, photos, or text in boxes | High | Already true of our templates; keep it as a rule |
| 6 | Say "ATS-safe" only for what our parsing tests confirm | High | Rule to keep |
| 7 | A right-to-left Hebrew single-column CV is a gap in the largest template library | Observation (10 Hebrew templates in 1,506) | For the product and marketing story; any claim must match what we can show |

**Still open:** exporting a handful of Canva templates to PDF and running them through our parsing tests would turn the right-hand column of the "do not adopt" table from inference into measurement. It needs designs created in an account, so it is the founder's call.
