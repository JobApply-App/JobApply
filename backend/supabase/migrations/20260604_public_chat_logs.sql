-- ── public_chat_logs ──────────────────────────────────────────────────────────
--
-- Stores every message exchanged in the public "Ask Ariel" widget that appears
-- on the landing page for unauthenticated visitors.
--
-- Design decisions:
--   • session_id  — client-generated UUID stored in localStorage; groups all
--                   messages from a single anonymous browsing session.
--   • role        — 'user' | 'assistant' only (system prompts are never stored).
--   • message_text — raw text; no PII normalisation at insert time.
--   • RLS policy  — anon role may INSERT but never SELECT.  Only service-role
--                   (e.g. admin dashboard or analytics jobs) can read the data.
--                   This keeps visitor conversations private while still letting
--                   the Next.js API route write without a service-role key.
-- ─────────────────────────────────────────────────────────────────────────────

create table if not exists public_chat_logs (
  id           uuid        primary key default gen_random_uuid(),
  session_id   uuid        not null,
  role         text        not null check (role in ('user', 'assistant')),
  message_text text        not null,
  created_at   timestamptz not null default now()
);

-- Index for grouping / ordering a session's messages
create index if not exists idx_public_chat_logs_session
  on public_chat_logs (session_id, created_at);

-- ── Row-Level Security ────────────────────────────────────────────────────────

alter table public_chat_logs enable row level security;

-- Anon visitors may INSERT (the Next.js API route uses the anon key server-side)
create policy "anon_insert_public_chat_logs"
  on public_chat_logs
  for insert
  to anon
  with check (true);

-- No SELECT for anon or authenticated users — only service_role can read logs
-- (service_role bypasses RLS automatically; no explicit policy needed)
