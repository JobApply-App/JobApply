#!/bin/sh
# Container entrypoint: apply pending schema migrations, then serve.
#
# Why this exists: backend/core/migrations.py's init_db() deliberately does
# NOT touch the schema on Postgres — it only checks connectivity — because
# the Postgres schema is owned by backend/alembic_app_schema/. That left
# `alembic upgrade head` as a step someone had to remember to run by hand,
# outside the deploy pipeline entirely. Nothing enforced it, so a deploy
# carrying a schema change could ship and start serving against the old
# schema, failing only later at the first query that touched a new column.
#
# Running it here binds the migration to the deploy that carries it.
#
# `set -e` is the load-bearing part: if the migration fails, the container
# exits non-zero and the platform keeps the previous healthy release live,
# rather than starting an app whose code expects a schema the database does
# not have. A failed deploy is a much better outcome than a running one that
# is quietly wrong.
#
# On SQLite (no DATABASE_URL) this is skipped — that path is still managed by
# init_db()'s own SQLite-only migration functions.
set -e

if [ -n "$DATABASE_URL" ]; then
    echo "[entrypoint] Applying app-schema migrations (alembic upgrade head)..."
    alembic -c alembic_app_schema.ini upgrade head
    echo "[entrypoint] Migrations applied."
else
    echo "[entrypoint] DATABASE_URL unset — SQLite mode, migrations handled by init_db()."
fi

exec "$@"
