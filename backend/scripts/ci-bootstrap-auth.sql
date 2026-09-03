-- CI ONLY — never run this against a real database.
--
-- Supabase provides the `auth` schema. The app's migrations depend on two
-- pieces of it: public.profiles carries a foreign key to auth.users(id)
-- (migration b19a4c6d2e71), and the RLS policies call auth.uid()
-- (b19a4c6d2e71, d2f7a4c891e3, 30cb3de92412, e34f0ea56e30).
--
-- On a plain Postgres neither exists, so `alembic upgrade head` aborts on
-- the first migration that needs them:
--
--     psycopg2.errors.InvalidSchemaName: schema "auth" does not exist
--
-- That is why the migration chain had never been applied anywhere except an
-- already-populated Supabase project — including by the deploy step that
-- now runs it. This file creates the minimum surface those migrations
-- touch so CI can exercise the chain from empty.
--
-- It is not a Supabase emulation and must not grow into one. If a migration
-- ever needs more of `auth` than this, that is worth a deliberate look
-- rather than another column here.

CREATE SCHEMA IF NOT EXISTS auth;

-- Only `id` is ever referenced, and only as a foreign-key target.
CREATE TABLE IF NOT EXISTS auth.users (
    id uuid PRIMARY KEY
);

-- Postgres resolves function references when CREATE POLICY runs, so
-- auth.uid() has to exist before the RLS migrations apply.
--
-- The body mirrors Supabase's: read the request-scoped JWT claims and
-- return the subject. In CI nothing sets those claims, so it returns NULL —
-- which is also what it returns for the application's own connections in
-- production, since they connect directly rather than through PostgREST.
-- That equivalence is the point: these policies are not the enforcement
-- layer, and a stub that pretended otherwise would be misleading.
CREATE OR REPLACE FUNCTION auth.uid() RETURNS uuid
LANGUAGE sql STABLE
AS $$
  SELECT NULLIF(
    NULLIF(current_setting('request.jwt.claims', true), '')::json ->> 'sub',
    ''
  )::uuid
$$;
