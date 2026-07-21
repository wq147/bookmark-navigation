from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.db import configure_sqlite
from app.models import Base

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)
restore_url = config.attributes.get("navigation_restore_url")
config.set_main_option(
    "sqlalchemy.url",
    restore_url or os.getenv("DATABASE_URL", config.get_main_option("sqlalchemy.url")),
)
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(url=config.get_main_option("sqlalchemy.url"), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}), prefix="sqlalchemy.", poolclass=pool.NullPool
    )
    if connectable.url.drivername.startswith("sqlite"):
        configure_sqlite(connectable)
    with connectable.connect() as connection:
        is_sqlite = connection.dialect.name == "sqlite"
        if is_sqlite:
            # SQLite table-recreate migrations must drop the old table. With
            # foreign keys enabled that DROP fires ON DELETE CASCADE against
            # rows already copied into the replacement table.
            connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
            # SQLAlchemy 2 starts an implicit transaction for the PRAGMA. End
            # it so Alembic can own and commit its migration transaction.
            connection.commit()
        context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()
        if is_sqlite:
            violations = connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
            if violations:
                raise RuntimeError(f"Foreign key violations after migration: {violations[:5]}")


run_migrations_offline() if context.is_offline_mode() else run_migrations_online()
