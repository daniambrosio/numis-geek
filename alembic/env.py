from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

from numis_geek.config import DATABASE_URL
from numis_geek.db.base import Base
import numis_geek.models  # noqa: F401 — ensures all models are registered

config = context.config
config.set_main_option("sqlalchemy.url", DATABASE_URL)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
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
    url = config.get_main_option("sqlalchemy.url")
    # SQLite: o app segue escrevendo durante o deploy — espera o lock em vez
    # de cair com "database is locked" (incidente 2026-10-30, spec 65).
    connect_args = {"timeout": 30} if url.startswith("sqlite") else {}
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        connect_args=connect_args,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
