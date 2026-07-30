"""Alembic 环境：URL 从应用配置注入（docs/12 §2.1，禁止硬编码）。"""

from logging.config import fileConfig

import app.models.entities  # noqa: F401  确保全部表注册到 metadata
from alembic import context
from app.core.config import get_settings
from app.models.base import Base
from sqlalchemy import engine_from_config, pool

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 同步驱动跑迁移（psycopg v3 同样支持 sync）
config.set_main_option(
    "sqlalchemy.url", get_settings().database_url.replace("+asyncpg", "+psycopg")
)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
