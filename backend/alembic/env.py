"""
Alembic environment. Runs migrations over a plain *sync* connection
(psycopg2) built from the same DATABASE_URL the async app uses -- see
app/config.py's `sync_database_url` property. Against Supabase this also
needs `sslmode=require` (see `psycopg2_connect_args`), which is why the
engine is built directly with `create_engine(...)` below rather than via
`engine_from_config`'s ini-section-based kwargs, which has no clean way to
carry a connect_args dict.
"""
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import create_engine, pool

# Make "app.*" importable when Alembic is invoked from backend/ (its normal
# working directory per the README).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings  # noqa: E402
from app.models import Base  # noqa: E402

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", settings.sync_database_url)

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
    connectable = create_engine(
        config.get_main_option("sqlalchemy.url"),
        poolclass=pool.NullPool,
        connect_args=settings.psycopg2_connect_args,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
