---
title: Eliya keeps support conversations 90 days and answers only from backend/knowledge/eliya_product.md
author: RonMorim
date: 2026-10-31
branch: feat/eliya-support
cost: { minutes: 17, tokens: 171520 }
id: l-ee86e336
scope: repo
status: active
src: agent
touches:
  - backend/alembic_app_schema/versions/e4b8c2a7f915_add_support_messages.py
  - backend/api/deps.py
  - backend/api/routes/chat.py
  - backend/core/migrations.py
  - backend/knowledge/eliya_product.md
  - backend/models/support_message.py
  - backend/repositories/support_message_repository.py
  - backend/tests/test_ariel_language_default.py
  - backend/tests/test_eliya_support.py
  - frontend/src/app/api/chat/public/route.ts
---

## Decided
- Ron chose to keep Eliya conversations (support_messages) for 90 days, for both anonymous visitors and signed-in users. The privacy page states it in Hebrew and English. purge_expired runs on each history request.
- Ron chose one knowledge file, backend/knowledge/eliya_product.md, as Eliya's only source of product facts. It is updated in the same PR as any feature users can see. Daily limits are not written in the file: chat.py reads them live from deps.py.
- Footer Help opens Eliya for everyone. She is support (product, sign-up, login, technical). Career requests go to Ariel.
- A signed-in request claims the browser session's anonymous rows. Signing out rotates the browser's session id.

## Tried and ruled out
- Keeping conversations for as long as the account exists: rejected for 90 days, which is less stored data and enough to resume a conversation.
- Having Ron write and approve each knowledge update himself: rejected for updating the file in each feature PR.
- Logging from the Next proxy to Supabase public_chat_logs: removed. Rows were kept forever, never read, and had no user link.

## Watch out
- The chat router has router-level llm_rate_limit (10/min), so every /api/chat/* route counts against it, the history GET included. Elia's panel stays mounted on every page, so it fetches history only when opened.
- The model reads the knowledge file at import, so restart the backend after editing it.
- There is no "10 AI analyses a day" limit in the code, though the landing page claims one. Only llm_rate_limit (10 a minute) exists.
