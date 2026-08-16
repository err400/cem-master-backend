"""Alembic environment.

Two things worth knowing before editing this file:

1. The database URL comes from ``app.config.get_settings()``, i.e. the same
   ``DATABASE_URL`` the application uses. It is not duplicated in alembic.ini,
   so the migration tool can never be pointed at a different database than the
   app by accident, and no credentials sit in a committed file.

2. This project is PostgreSQL-only -- ``app/config.py`` rejects any other URL,
   and the models use ``postgresql.JSONB``. So there is deliberately NO SQLite
   support here, and in particular no ``render_as_batch``: that is SQLite's
   table-rebuild emulation for ALTER, and enabling it produces migrations full
   of ``op.batch_alter_table`` that are pointless on Postgres.
"""

from __future__ import annotations

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# Make the application package importable when Alembic is invoked from anywhere.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings  # noqa: E402
from app.database import Base  # noqa: E402

# Importing the models module is what populates Base.metadata. Without this the
# autogenerate diff would see an empty schema and cheerfully propose dropping
# every table.
import app.models  # noqa: F401,E402

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def get_url() -> str:
    """Resolve the database URL, most explicit source first.

    1. ``sqlalchemy.url`` set programmatically on the Config object. Used by
       tests and any caller driving Alembic through its Python API -- this must
       win, or such a caller would silently migrate the default database
       instead of the one it asked for.
    2. ``DATABASE_URL`` in the environment.
    3. The application's own configured URL, so ``alembic upgrade head`` with no
       arguments always targets the same database the app will open.

    alembic.ini deliberately does not set ``sqlalchemy.url``, so (1) is absent
    unless a caller sets it on purpose.
    """
    configured = config.get_main_option("sqlalchemy.url", None)
    if configured:
        return configured
    return os.getenv("DATABASE_URL") or get_settings().database_url


def run_migrations_offline() -> None:
    """Emit SQL to stdout without connecting -- useful for reviewing a migration."""
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    url = get_url()
    section = config.get_section(config.config_ini_section) or {}
    section["sqlalchemy.url"] = url

    connectable = engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # compare_type catches a column changing e.g. String(80) -> String(220).
            # Off by default, and its absence is a common source of "the migration
            # ran but the column is still the old type".
            compare_type=True,
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
