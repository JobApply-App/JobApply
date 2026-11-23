-- Minimal stand-in for Supabase's auth schema, for testing a backup restore
-- on a plain local Postgres (docs/backup-restore.md, "Test a restore
-- locally"). auth.dump holds only the rows of auth.users and
-- auth.identities, so their tables must exist first; the columns match the
-- COPY lists in that dump. Never run this against Supabase, which owns the
-- real auth schema.
CREATE ROLE anon NOLOGIN; CREATE ROLE authenticated NOLOGIN; CREATE ROLE service_role NOLOGIN;
CREATE ROLE supabase_auth_admin NOLOGIN;
CREATE SCHEMA auth;
CREATE TABLE auth.users (
  instance_id text, id uuid PRIMARY KEY, aud text, role text, email text, encrypted_password text,
  email_confirmed_at text, invited_at text, confirmation_token text, confirmation_sent_at text,
  recovery_token text, recovery_sent_at text, email_change_token_new text, email_change text,
  email_change_sent_at text, last_sign_in_at text, raw_app_meta_data jsonb, raw_user_meta_data jsonb,
  is_super_admin text, created_at text, updated_at text, phone text, phone_confirmed_at text,
  phone_change text, phone_change_token text, phone_change_sent_at text, email_change_token_current text,
  email_change_confirm_status text, banned_until text, reauthentication_token text,
  reauthentication_sent_at text, is_sso_user text, deleted_at text, is_anonymous text);
CREATE TABLE auth.identities (
  provider_id text, user_id uuid REFERENCES auth.users(id), identity_data jsonb, provider text,
  last_sign_in_at text, created_at text, updated_at text, id uuid PRIMARY KEY);
CREATE FUNCTION auth.uid() RETURNS uuid LANGUAGE sql STABLE AS $$
  SELECT NULLIF(NULLIF(current_setting('request.jwt.claims', true), '')::json ->> 'sub', '')::uuid $$;
CREATE FUNCTION auth.role() RETURNS text LANGUAGE sql STABLE AS $$ SELECT 'authenticated'::text $$;
CREATE FUNCTION auth.jwt() RETURNS jsonb LANGUAGE sql STABLE AS $$ SELECT '{}'::jsonb $$;
