from pathlib import Path

from alembic import command
from alembic.config import Config
from migrations.schema_v1 import AuditLog as OldAudit
from migrations.schema_v1 import Role as OldRole
from migrations.schema_v1 import Ticket as OldTicket
from migrations.schema_v1 import User as OldUser
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models.entities import AuditLog, Engineer, Role, Ticket, User


def test_upgrade_preserves_original_records(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/legacy.db")
    cfg = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    with engine.connect() as connection:
        cfg.attributes["connection"] = connection
        command.upgrade(cfg, "0001")
    with Session(engine) as db:
        user = OldUser(
            name="Existing Engineer",
            email="existing@example.local",
            role=OldRole.IT_AGENT,
            password_hash="existing-hash-preserved",
        )
        db.add(user)
        db.flush()
        db.add(
            OldTicket(
                number="INC-2026-000001",
                title="Existing VPN ticket",
                description="Preserve this description",
                requester_id=user.id,
                assignee_id=user.id,
            )
        )
        db.add(OldAudit(actor_id=user.id, action="created", entity="ticket", entity_id="1"))
        db.commit()
    with engine.connect() as connection:
        cfg.attributes["connection"] = connection
        command.upgrade(cfg, "head")
        command.upgrade(cfg, "head")
    with Session(engine) as db:
        user = db.scalar(select(User))
        assert user.role == Role.IT_AGENT and user.password_hash == "existing-hash-preserved"
        assert db.scalar(select(Ticket)).number == "INC-2026-000001"
        assert db.scalar(select(Ticket)).description == "Preserve this description"
        assert db.get(Engineer, user.id).capacity == 10
        assert db.scalar(select(AuditLog)).action == "created"
    engine.dispose()
