#!/bin/sh
# Create (or recreate) the local benchmark database with the same recipe CI
# uses for its test database (.github/workflows/ci.yml). Run from the repo root,
# with the project's virtualenv active. Destroys any existing jobapply_bench.
set -eu
DB=jobapply_bench
export DATABASE_URL="postgresql://$(whoami)@localhost:5432/$DB"
dropdb --if-exists "$DB"
createdb "$DB"
psql "$DATABASE_URL" -q -v ON_ERROR_STOP=1 -f backend/scripts/ci-bootstrap-auth.sql
alembic -c alembic_app_schema.ini upgrade head
alembic -c alembic_linkedin.ini upgrade head
psql "$DATABASE_URL" -q -v ON_ERROR_STOP=1 \
  -c 'ALTER TABLE public.profiles DROP CONSTRAINT IF EXISTS fk_profiles_id_auth_users;'
echo "ready: export DATABASE_URL=$DATABASE_URL"
