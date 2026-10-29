import os

from alembic import context
from sqlalchemy import create_engine


def database_url() -> str:
    # Propriétaire des tables pour migrer ; DATABASE_URL (rôle de l'API) sert de repli, notamment aux tests.
    url = os.environ.get("MIGRATION_DATABASE_URL") or os.environ["DATABASE_URL"]
    return url.replace("postgresql://", "postgresql+psycopg://", 1)


def run_migrations_online() -> None:
    engine = create_engine(database_url())
    with engine.connect() as connection:
        context.configure(connection=connection)
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
