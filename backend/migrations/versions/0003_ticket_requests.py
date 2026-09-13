"""Make client retries of ticket creation idempotent."""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"


def upgrade():
    op.create_table(
        "ticket_requests",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("ticket_id", sa.Integer(), sa.ForeignKey("tickets.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_ticket_requests_ticket_id", "ticket_requests", ["ticket_id"])


def downgrade():
    raise RuntimeError("Restore a database backup to downgrade")
