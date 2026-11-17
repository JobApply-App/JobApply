---
title: Domain fit is judged by the scorer against profile_entities domains; a different field scores neutral 50
author: RonMorim
date: 2026-11-17
branch: claude/domain-from-profile
cost: { minutes: 1, tokens: 1454 }
id: l-ee18bbcb
scope: repo
status: active
src: agent
touches:
  - CLAUDE.md
---

## Decided
- The domain dimension was 50 for every job: _compute_structural read cv_data["domains"], which build_cv_data never sets. Domains now come from profile_entities (entity_type='domain', from the CV upload and Ariel chats; unverified inferred rows excluded, same rule as skills) via match_score_service._profile_domains.
- The scorer call returns domain_fit same / adjacent / different, mapped to 100 / 75 / 50 in match_dimensions.score_domain_context. The literal name search is only the fallback; it never worked for Hebrew because _norm strips Hebrew letters.
- A different field is 50, the same as no signal (was 40): CLAUDE.md principle 3. Prior-employer floor still wins.

## Watch out
- build_cv_data dropped role dates, so PR #167's years-from-dates sum never ran (it fell back to the verdict word). It now passes dates from the profile's period/start/end. Tests with hand-built cv_data hid this: test through build_cv_data, not a hand-made dict.
- build_cv_data emits experience most-recent-first; _llm_dual_score reverses it, so check the order the prompt actually shows before relying on it.
