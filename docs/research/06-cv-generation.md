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
