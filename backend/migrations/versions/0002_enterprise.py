"""Enterprise sessions, engineers, workflow, notifications and audit protection."""

import sqlalchemy as sa
from alembic import op
from migrations.schema_v2 import Base

revision = "0002"
down_revision = "0001"


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        with op.get_context().autocommit_block():
            for value in ["ADMIN", "ENGINEER", "USER"]:
                op.execute(f"ALTER TYPE role ADD VALUE IF NOT EXISTS '{value}'")
            for value in [
                "ASSIGNED",
                "PENDING",
                "WAITING_FOR_USER",
                "WAITING_FOR_VENDOR",
                "REOPENED",
            ]:
                op.execute(f"ALTER TYPE ticketstatus ADD VALUE IF NOT EXISTS '{value}'")
    existing = set(sa.inspect(bind).get_table_names())
    # Create dependencies before adding references to existing tables.
    for table in Base.metadata.sorted_tables:
        if table.name not in existing:
            table.create(bind, checkfirst=True)
    additions = {
        "users": [
            sa.Column("team", sa.String(100)),
            sa.Column("phone", sa.String(40)),
            sa.Column("last_login", sa.DateTime(timezone=True)),
        ],
        "tickets": [
            sa.Column("resolution", sa.Text()),
            sa.Column("subcategory_id", sa.Integer()),
            sa.Column("assignment_reason", sa.String(255)),
            sa.Column("deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("location", sa.String(120)),
            sa.Column("acknowledged_at", sa.DateTime(timezone=True)),
            sa.Column("response_due_at", sa.DateTime(timezone=True)),
        ],
        "audit_logs": [
            sa.Column("ip_address", sa.String(64)),
            sa.Column("user_agent", sa.String(512)),
        ],
    }
    for name, columns in additions.items():
        for column in columns:
            op.add_column(name, column)
    with op.batch_alter_table("tickets") as batch:
        batch.create_foreign_key(
            "fk_ticket_subcategory", "subcategories", ["subcategory_id"], ["id"]
        )
    for name, cols in [
        ("ix_ticket_scope", ["requester_id", "updated_at"]),
        ("ix_ticket_workload", ["assignee_id", "status"]),
        ("ix_ticket_sla", ["sla_due_at", "status"]),
    ]:
        op.create_index(name, "tickets", cols)
    op.create_index("ix_audit_filter", "audit_logs", ["entity", "entity_id", "created_at"])
    with op.batch_alter_table("engineers") as batch:
        batch.create_check_constraint("ck_engineer_capacity", "capacity > 0 AND capacity <= 1000")
    with op.batch_alter_table("sla_policies") as batch:
        batch.create_check_constraint(
            "ck_sla_positive", "response_minutes > 0 AND resolution_minutes > 0"
        )
    if bind.dialect.name == "postgresql":
        op.execute(
            """CREATE FUNCTION reject_audit_mutation() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'Audit records are immutable'; END $$"""
        )
        op.execute(
            "CREATE TRIGGER audit_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON audit_logs FOR EACH STATEMENT EXECUTE FUNCTION reject_audit_mutation()"
        )
        op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA public")
        for col in ["title", "description", "number"]:
            op.execute(
                f"CREATE INDEX ix_ticket_search_{col} ON tickets USING gin ({col} public.gin_trgm_ops)"
            )
    else:
        op.execute(
            "CREATE TRIGGER audit_no_update BEFORE UPDATE ON audit_logs BEGIN SELECT RAISE(ABORT, 'Audit records are immutable'); END"
        )
        op.execute(
            "CREATE TRIGGER audit_no_delete BEFORE DELETE ON audit_logs BEGIN SELECT RAISE(ABORT, 'Audit records are immutable'); END"
        )
    # Existing engineers gain profiles; no passwords or demo accounts are created.
    op.execute(
        "INSERT INTO engineers (user_id,available,capacity) SELECT id,true,10 FROM users WHERE role IN ('IT_AGENT','ENGINEER')"
    )


def downgrade():
    raise RuntimeError("Destructive downgrade is intentionally disabled; restore a database backup")
