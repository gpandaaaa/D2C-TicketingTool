"""Baseline of the supplied application's existing tables."""

from alembic import op
from migrations.schema_v1 import Base

revision = "0001"
down_revision = None


def upgrade():
    Base.metadata.create_all(op.get_bind())


def downgrade():
    raise RuntimeError("Destructive downgrade is intentionally disabled; restore a database backup")
