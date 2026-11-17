---
title: "Column-aware CV upload extraction: regions get letters by identity, not by area"
author: RonMorim
date: 2026-11-13
branch: claude/determined-rosalind-708c36
cost: { minutes: 12, tokens: 187998 }
id: l-9d9108d0
scope: repo
status: active
src: agent
touches:
  - backend/services/pdf_columns.py
  - backend/tests/test_cv_pdf_columns.py
  - docs/cv-upload-columns.md
  - backend/services/cv_aggregator_service.py
---

## Decided
- backend/services/pdf_columns.py finds a gutter and reads multi-column pages region by region; backend/services/cv_aggregator_service.py `_plumber_page_text` uses it. One-column pages return None from `reading_regions` and keep the old `extract_text(layout=True)` + `_fix_rtl_visual` path byte-for-byte (verified on the 8 Canva PDFs from docs/research/06-cv-generation.md section 49).
- A gutter is accepted only if both sides have >=10% of chars, overlap vertically, have few inner crossings and are mostly "stacked" lines; this is what rejects a one-column CV's right-margin dates.

## Tried and ruled out
- Selecting a region's chars by its segments' bounding boxes: the rotated "RESUME" word on Canva's dark-tech template has a tall box that stole letters from the name and profile ("progra" / "mmer"). Chars are now matched by identity from `extract_words(return_chars=True)`; only space glyphs (which extract_words drops) are matched by box. Non-upright words are excluded on column pages.

## Watch out
- Label-column templates (headings in their own narrow column) come out as a list of headings before the content.
- Tests render PDFs with Chromium (backend/tests/test_cv_pdf_columns.py) and skip if it's missing; CI installs it. `test_the_old_path_did_mix_these_columns` guards that the fixtures still reproduce the bug.
