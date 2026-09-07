"""Конфигурация Alembic для Prediction Store."""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from alembic.ddl.postgresql import PostgresqlImpl
from sqlalchemy import (
    Column,
    MetaData,
    PrimaryKeyConstraint,
    String,
    Table,
    engine_from_config,
    inspect,
    pool,
)

from sports_forecast.service.db.engine import get_database_url
from sports_forecast.service.db.models import Base


class SportsForecastPostgresqlImpl(PostgresqlImpl):
    """Расширяет Alembic version table для длинных исторических revision IDs."""

    __dialect__ = "postgresql"

    def version_table_impl(
        self,
        *,
        version_table: str,
        version_table_schema: str | None,
        version_table_pk: bool,
        **_kwargs: object,
    ) -> Table:
        """Создать PostgreSQL `alembic_version` с запасом для revision identity."""
        version_table_object = Table(
            version_table,
            MetaData(),
            Column("version_num", String(64), nullable=False),
            schema=version_table_schema,
        )
        if version_table_pk:
            version_table_object.append_constraint(
                PrimaryKeyConstraint("version_num", name=f"{version_table}_pkc")
            )
        return version_table_object


config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", os.environ.get("DATABASE_URL", get_database_url()))
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Сгенерировать SQL миграций без подключения к БД."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Применить миграции через короткоживущее DB-соединение."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        if connection.dialect.name == "postgresql" and inspect(connection).has_table(
            "alembic_version"
        ):
            connection.exec_driver_sql(
                "ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(64)"
            )
        # `inspect()` начинает implicit transaction в PostgreSQL. Зафиксировать
        # preflight до Alembic, иначе outer rollback отменит весь fresh upgrade.
        connection.commit()
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
