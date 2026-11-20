---
title: CV keyword and number quotas were removed from the writer prompt on purpose
author: RonMorim
date: 2026-11-20
branch: claude/cv-guidelines
cost: { minutes: 1, tokens: 2431 }
id: l-fcf26b94
scope: repo
status: active
src: agent
touches:
  - backend/agents/tailor.py
  - docs/research/08-cv-writing-guidelines.md
---

## Decided
The writer prompt (`backend/agents/tailor.py` `_SYSTEM_PROMPT`) carries no keyword coverage target, gap-term quota, "number in every bullet", derived approximations or "fill the page" rule. Its rules come from `docs/research/08-cv-writing-guidelines.md`, built from 10 published CV skills and recruiter surveys; none of them sets a quota, and recruiters read full keyword coverage as fake. Measured 2026-11-20 on 34 pairs: violations per CV 1.38 to 0.97, tools moved 19 to 11, invented activities 10 to 4, with 84% of the supported ad terms still used (87% before).

## Tried and ruled out
Keeping the quotas with the honesty line on top (#172): tools moved onto other work and technical inflation barely changed until the quotas went.

## Watch out
`test_the_writer_has_no_keyword_or_number_quotas` keeps them out. The benchmark's `noquota` variant (`cv_prompts.without_quotas`) is written against the older prompt and stops on the current one by design.
