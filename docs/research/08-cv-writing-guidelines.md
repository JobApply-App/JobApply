# 08 — Our CV-writing guidelines (2026-11-20)

The rules the CV writer (`backend/agents/tailor.py`, `_SYSTEM_PROMPT`) follows,
and why. Built from ten published CV-writing skills, five recruiter surveys and
articles, and the founder's spot check of 20 claims
(`benchmark/claims-sheet-he.md`, `07-benchmark-results.md`). Nothing here is
copied in as a skill: each rule is ours, written once, and the prompt carries it.

When a rule here and the prompt disagree, this document is the intent and the
prompt is the bug.

## Sources read

| Source | What it contributed |
|---|---|
| [amanattar/resume-tailoring-skill](https://github.com/amanattar/resume-tailoring-skill) | Title reframing to the standard industry term, never past what can be defended; company and dates exact |
| [SankaiAI/ats-optimized-resume-agent-skill](https://github.com/SankaiAI/ats-optimized-resume-agent-skill) | A humanization pass; a final gate: no invented metrics, tools, titles or projects; no keyword stuffing |
| [coinluu/resume-jd-optimizer-cn](https://github.com/coinluu/resume-jd-optimizer-cn) | A truthfulness policy: the verb-evidence ladder, forbidden upgrades, the interview test |
| [jezweb/claude-skills](https://github.com/jezweb/claude-skills) | About 60% of bullets with a measured result, not all of them |
| [composiohq/awesome-claude-skills](https://github.com/composiohq/awesome-claude-skills) | One page under ten years of experience; action, method, result |
| [yanliudesign/resume-builder-skill](https://github.com/yanliudesign/resume-builder-skill), [mohitagw15856/pm-claude-skills](https://github.com/mohitagw15856/pm-claude-skills), anneheartrecord/resume-tuning, aas-ee/resume-skills | The same formula and weak-opener bans; nothing new |
| [Resume Genius hiring insights 2026](https://resumegenius.com/blog/job-hunting/hiring-insights-report) | Recruiters' top AI tells: unnatural phrasing, repetitive or generic language, vague or inflated claims |
| [SHRM on AI-written resumes](https://www.shrm.org) | Recruiters distrust a CV that contains every keyword of the ad |
| [BuiltIn on AI screening](https://builtin.com/articles/ai-resume-screening-writing-advice) | Modern ATS matching is semantic; stuffing is discounted |
| [Blake Crosley on ATS optimisation](https://blakecrosley.com/ja/work/ai-resume-optimization) | Exact terms still matter: "container orchestration" is not found by a search for "Kubernetes" |
| [Dice: polish, don't write](https://www.dice.com/career-advice/use-ai-to-polish-your-resume-not-write-it-into-oblivion) | Invented metrics are exposed at the interview |

## What every source agrees on

1. Never invent. Reframe what is true, in the reader's vocabulary.
2. Employer names, titles' substance and dates are exact.
3. Keywords go where the candidate did that thing, and nowhere else.
4. A bullet is an action, the method, and a result when there is one.
5. Quantify real results only.
6. No generic, repetitive or machine-sounding language.

None of them sets a keyword quota. The sources that discuss coverage
(SHRM, BuiltIn, Resume Genius) say a CV that matches every term reads as
fake to the person who decides.

## Our rules

### A. Honesty (the founder's line, 2026-11-20)

Allowed:
- The same work in the employer's vocabulary, and a military or local title
  translated into its civilian function.
- A stronger verb for the same act ("ran" to "led").
- Every number the profile states. A stated result is the strongest line on
  the page; dropping it is a loss, not caution.
- Small, plausible detail that adds no new fact.

Not allowed:
- A technical claim larger than the work (Docker deploys are not "CI/CD
  pipelines").
- A tool from the skills list placed on work the profile does not tie it to.
- Work moved to another role, or given an outcome the profile does not state.
- An activity the profile does not describe.
- A number, scope or result the profile does not state, including estimates
  "derived" from other facts.

This line overrides every other rule. A keyword that can only be placed by
crossing it is left out.

### B. Keywords

- Use the ad's exact term when the candidate did that thing under another
  name ("client check-ins" to "QBRs" when the activity is the same). Exact
  strings still matter to search (Crosley).
- The summary and skills carry the ad's core terms that the profile
  supports; each skill or summary term is backed by a bullet.
- No coverage target, no count, no audit that adds terms. A missing term
  costs a little; a false one costs the interview.
- Market vocabulary for a verified employer's industry is a suggestion, not
  a quota.

### C. Bullets

- Open with a concrete active verb. No "responsible for", "helped", passive
  voice, or the banned AI vocabulary.
- Action, method, and a result where the profile states one. Without a
  stated result, describe the scope in words. Not every bullet needs a
  number (jezweb's 60% is a ceiling to expect, not a floor to force).
- Most relevant bullet first; the most relevant role gets the most bullets.
- No phrase, metric or opening verb repeated across bullets.

### D. Selection and length

- One page. Choose the roles that serve this job; drop a low-signal role
  rather than pad it. Do not write to fill space.
- Military service is always present; how much is a judgement about this
  candidate and this job (see `06-cv-generation.md` and the prompt).
- Missing facts are asked for (`missing_data`), never assumed.

## Rejected, and why

| Rule found | Where | Why we don't use it |
|---|---|---|
| Place ≥ 16 of 20 ad keywords; 80% coverage; audits that "force" missing terms in | Our own prompt until 2026-11-20 | The source of most tool-moved and technical-inflation claims in part C; recruiters read full coverage as fake |
| ≥ 3 vocabulary-gap terms per verified employer | Our own prompt | Same: a quota on words the candidate may never have used |
| Every bullet carries a number | Our own prompt | Pushes the model to invent or derive numbers; the founder rejected "100% weekly readiness" |
| Derived approximations ("40 partners × 18 months ≈ 78 syncs") | Our own prompt | An estimate printed as a fact; Dice: invented metrics fail at interview |
| "The page should feel FULL" | Our own prompt | Rewards padding; one-page fit is the template's job |
| Estimate a metric when none is given | jezweb | Same as derived numbers |
| Choose the weakest confirmed verb (verb-evidence ladder) | coinluu | The founder accepted a stronger verb for the same act. Kept only its core: never upgrade participation to ownership of an outcome, execution to strategy |
| Mark doubtful facts "[to confirm]" in the CV | coinluu | Our CV goes to a recruiter; doubtful facts are asked for with `missing_data` instead |

## Open

- Titles are not locked; changed titles are allowed when they translate the
  same function (founder, 2026-11-20).
- One-page fit with 8 or more bullets is not yet checked in the PDF.
