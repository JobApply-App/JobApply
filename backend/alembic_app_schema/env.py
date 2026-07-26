import sys
from logging.config import fileConfig
from pathlib import Path
from urllib.parse import urlsplit

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

# Dedicated Alembic environment for the app's primary-datastore tables
# (backend/jobs.db's SQLite schema, ported to Postgres's `public` schema —
# see backend/alembic_app_schema/versions/413f4ed8fbc6_create_app_tables.py
# for the full type-mapping/FK-safety rationale). Schema-only: this does
# NOT change what the running app reads from — that's still SQLite (see
# CLAUDE.md) until a real cutover is separately planned. Kept as its own
# Alembic environment (not merged into backend/alembic_linkedin/) since it
# targets a different schema (`public` vs `linkedin`) and has no ORM base
# to autogenerate from — every table here is hand-authored DDL mirroring
# the audited SQLite schema, not reflected from declarative model classes.
_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))

from backend.core.postgres import _to_sync_dsn, ensure_sslmode  # noqa: E402
from backend.config import APP_ENV, DATABASE_URL  # noqa: E402

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# DATABASE_URL is already environment-aware (backend/config.py's
# _select_env_var(): DATABASE_URL -> DATABASE_URL_DEV/_PROD by APP_ENV) —
# `alembic -c alembic_app_schema.ini upgrade head` runs against whichever
# Supabase project APP_ENV/backend/.env currently resolve to. See
# backend/alembic_app_schema/README for the exact per-environment commands.
if DATABASE_URL:
    print(f"[alembic_app_schema] APP_ENV={APP_ENV} — migrating {urlsplit(DATABASE_URL).hostname}")
    config.set_main_option("sqlalchemy.url", ensure_sslmode(_to_sync_dsn(DATABASE_URL)))

# No declarative model to autogenerate from — every revision in versions/
# is hand-authored DDL mirroring the audited backend/jobs.db schema.
target_metadata = None

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        # This environment shares a physical database with alembic_linkedin
        # (same DATABASE_URL/Supabase project, different schemas) — without
        # an explicit, distinct version_table the two unrelated revision
        # graphs would collide in Postgres's default `alembic_version`
        # table (both writing rows keyed by their own revision hash into
        # one shared tracking table), corrupting `alembic current`/`upgrade`
        # for whichever environment runs second. See run_migrations_online()
        # below for the online-mode equivalent.
        version_table="alembic_version_app_schema",
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata,
            # See run_migrations_offline()'s comment — distinct from
            # alembic_linkedin's default `alembic_version` table since both
            # environments target the same physical Postgres database.
            version_table="alembic_version_app_schema",
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
