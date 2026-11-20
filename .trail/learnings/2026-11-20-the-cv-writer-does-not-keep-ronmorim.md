---
title: "The CV writer does not keep the profile's education order, so model output must never be paired with profile facts by index"
author: RonMorim
date: 2026-11-20
branch: claude/education-order-fix
cost: { minutes: 7, tokens: 111543 }
id: l-605040d0
scope: repo
status: active
src: agent
touches:
  - backend/agents/tailor.py
  - backend/tests/test_hebrew_cv_layout.py
  - backend/services/cv_localize.py
---

## Decided
- `_localized_education` (backend/agents/tailor.py) pairs the model's Hebrew education wording with profile entries by dates, not by position (PR #174). Dates and honors stay from the profile.
- Root cause of benchmark p06's swap (course shown at the high school in 2009 - 2012, bagrut in 2021): the prompt says "same order", but the model listed the newest entry first. Index pairing put each name on the other entry's dates.

## Tried and ruled out
- The Hebrew localisation pass (`cv_localize_he`, backend/services/cv_localize.py) as the cause: `validate_localization` rejects any change to education dates or their order.
- Education extraction as the cause: p06's profile data was correct.

## Watch out
- A prompt instruction like "keep the same order" is not a guarantee. Any merge of model output into profile facts (education, military, experience) should match on a copied field (dates, company), not on index.
- `validate_localization` checks education dates only, not degree/institution text. A localiser that swapped only the names between entries would still pass it.
- To find a benchmark's results, look in the worktree that produced them: results are gitignored. Stage 7's cvs-v1..v3 live in .worktrees/adjacent-titles/docs/research/benchmark/results/.
