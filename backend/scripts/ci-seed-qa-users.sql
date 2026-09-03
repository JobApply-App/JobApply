-- CI ONLY — never run this against a real database.
--
-- Several test modules address fixed QA accounts by UUID rather than minting
-- a user per run, e.g. backend/tests/test_match_triggers.py:
--
--     _QA_A = "2631c93b-93bb-4313-a2c2-79dbb786d199"   # qa.test2.jobapply...
--
-- Those rows exist in the shared Supabase project, which is why the tests
-- pass there and fail on a fresh database with:
--
--     ForeignKeyViolation: table "user_job_matches" violates constraint
--     "fk_user_job_matches_user_id_profiles"
--
-- The constraint is correct and is deliberately left enforced — it is one
-- this codebase owns, and it is exactly the kind of per-user scoping the
-- tests exist to check. What CI was missing is the accounts themselves.
--
-- Creating them here keeps the tenant FKs real while making the suite
-- independent of one particular Supabase project. Keep this list in sync
-- with the UUID constants in backend/tests/ — a missing row shows up as a
-- ForeignKeyViolation naming the table that needed it.

INSERT INTO public.profiles (id, email, onboarding_status)
VALUES
  -- qa.test2.jobapply.claude@gmail.com — test_match_triggers, test_analytics_service
  ('2631c93b-93bb-4313-a2c2-79dbb786d199', 'qa.test2@example.invalid', 'complete'),
  -- qa-test-linkedin-tab@example.com — test_match_triggers (second tenant, isolation checks)
  ('b0dbf35a-929c-4db3-a04a-24fbe3a3d59d', 'qa-linkedin-tab@example.invalid', 'complete'),
  -- third fixed account used across trust-score and dashboard tests
  ('e2472fa3-db25-4e53-9d0b-2aed67bcfe0e', 'qa-trust@example.invalid', 'complete'),
  -- deterministic ids used by ordering/pagination tests
  ('a2c1f0de-0000-4000-8000-000000000001', 'qa-fixed-1@example.invalid', 'complete'),
  ('a2c1f0de-0000-4000-8000-000000000002', 'qa-fixed-2@example.invalid', 'complete')
ON CONFLICT (id) DO NOTHING;
