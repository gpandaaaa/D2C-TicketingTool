"""Run inside a development backend container to verify the real SLA worker."""

import time

from sqlalchemy import func, select

from app.api.tickets import create, update_impl
from app.core.config import settings
from app.core.database import SessionLocal
from app.models.entities import Category, Notification, Role, Ticket, TicketStatus, User, now
from app.schemas.enterprise import TicketCreate, TicketEdit
from app.services.audit import audit

if settings.environment != "development":
    raise RuntimeError("Worker acceptance is development-only")
with SessionLocal() as db:
    admin = db.scalar(select(User).where(User.role == Role.ADMIN, User.active == True))
    category = db.scalar(
        select(Category).where(Category.name == "Network", Category.active == True)
    )
    if not admin or not category:
        raise RuntimeError("Load development seed data first")
    result = create(
        TicketCreate(
            title="SLA worker acceptance",
            description="Development-only scheduled notification acceptance check.",
            category_id=category.id,
        ),
        admin,
        db,
    )
    ticket_id = result["id"]
    ticket = db.get(Ticket, ticket_id)
    ticket.sla_due_at = now()
    audit(
        db,
        admin.id,
        "SLA_ACCEPTANCE_SETUP",
        "ticket",
        ticket_id,
        after={"reason": "Development worker verification"},
    )
    db.commit()
count = 0
for _ in range(23):
    with SessionLocal() as db:
        count = db.scalar(
            select(func.count())
            .select_from(Notification)
            .where(Notification.ticket_id == ticket_id, Notification.event == "SLA_BREACHED")
        )
    if count >= 2:
        break
    time.sleep(2)
if count < 2:
    raise AssertionError(
        "Background SLA worker did not deliver both notifications within 46 seconds"
    )
with SessionLocal() as db:
    admin = db.scalar(select(User).where(User.role == Role.ADMIN))
    ticket = db.get(Ticket, ticket_id)
    update_impl(
        db,
        ticket,
        TicketEdit(
            status=TicketStatus.RESOLVED,
            resolution="Background worker delivery verified for requester and engineer.",
        ),
        admin,
    )
    update_impl(db, ticket, TicketEdit(status=TicketStatus.CLOSED), admin)
    db.commit()
print(f"Worker acceptance passed: ticket {ticket_id}, {count} SLA notifications delivered.")
