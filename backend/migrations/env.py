from alembic import context

from app.core.database import Base, engine
from app.models import entities  # noqa: F401 -- registers migration metadata


def migrate(connection):
    context.configure(connection=connection, target_metadata=Base.metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


connection = context.config.attributes.get("connection")
if connection is not None:
    migrate(connection)
else:
    with engine.connect() as connection:
        migrate(connection)
