import sys
from logging.config import fileConfig
from pathlib import Path
from urllib.parse import urlsplit

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

# This is a DEDICATED Alembic environment for the `linkedin` schema only
# (backend/models/linkedin_job.py, on the Postgres engine in
# backend/core/postgres.py) — NOT a project-wide migration setup. Every
# other table in this repo is still created via backend/core/migrations.py's
# create_all() against the SQLite ENGINE (backend/core/database.py); that
# mechanism is untouched by this. See backend/core/postgres.py's docstring.
_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))

from backend.core.postgres import LinkedInBase, _to_sync_dsn, ensure_sslmode  # noqa: E402
from backend.config import APP_ENV, DATABASE_URL  # noqa: E402
from backend.models import linkedin_job  # noqa: E402,F401  (registers the table on LinkedInBase.metadata)

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# DATABASE_URL is already environment-aware (backend/config.py's
# _select_env_var(): DATABASE_URL -> DATABASE_URL_DEV/_PROD by APP_ENV) —
# `alembic -c alembic_linkedin.ini upgrade head` runs against whichever
# Supabase project APP_ENV/backend/.env currently resolve to. See
# backend/alembic_linkedin/README's "Migrations" section for the exact
# per-environment commands.
if DATABASE_URL:
    print(f"[alembic_linkedin] APP_ENV={APP_ENV} — migrating {urlsplit(DATABASE_URL).hostname}")
    config.set_main_option("sqlalchemy.url", ensure_sslmode(_to_sync_dsn(DATABASE_URL)))

target_metadata = LinkedInBase.metadata

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
            connection=connection, target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
