---
title: Backend pytest refuses the remote DATABASE_URL; pypdf is not installed
author: RonMorim
date: 2026-10-26
branch: main
cost: { minutes: 1, tokens: 0 }
id: l-7129ead4
scope: repo
status: active
src: agent
touches:
  - backend/config.py
  - backend/requirements.txt
  - backend/services/document_verifier.py
  - backend/services/pdf_builder.py
---

## Decided
- Run backend tests against a throwaway local Postgres, never the Supabase URL in backend/.env. The conftest guard aborts the whole run when DATABASE_URL points at a remote host. A shell `DATABASE_URL=...` prefix is ignored, because backend/config.py loads backend/.env with override=True.
- Use pymupdf (`import fitz`) to read PDF text. It is pinned in backend/requirements.txt.

## Tried and ruled out
- pypdf: not in requirements and not in .venv. backend/services/document_verifier.py imports it, and a broad except turns the ImportError into empty text.

## Watch out
- Hebrew text extracted from our PDFs comes out in visual word order ("לוי דנה" for "דנה לוי"). Compare names word by word, not as a whole string (backend/services/pdf_builder.py ats_text_issues).
