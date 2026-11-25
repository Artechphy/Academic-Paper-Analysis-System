from alembic import context
from sqlalchemy import create_engine, pool

from app.config import settings
from app.db import models  # noqa: F401 - register model tables on Base.metadata
from app.db.base import Base


def _include_name(name, type_, _parent_names):
    # The migration owns this table until downgrade removes it.
    return type_ != "table" or name != "spacing_rule_severity_0003"


def run_migrations_offline() -> None:
    context.configure(
        url=settings.database_url,
        target_metadata=Base.metadata,
        literal_binds=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connection = context.config.attributes.get("connection")
    if connection is not None:
        context.configure(connection=connection, target_metadata=Base.metadata, include_name=_include_name)
        with context.begin_transaction():
            context.run_migrations()
        return

    engine = create_engine(settings.database_url, poolclass=pool.NullPool)
    try:
        with engine.connect() as connection:
            context.configure(connection=connection, target_metadata=Base.metadata, include_name=_include_name)
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
