from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import case, func, or_, select, text

from app.api.deps import ADMINS, ENGINEERS
from app.models.entities import (
    Category,
    Engineer,
    EngineerSkill,
    EngineerSubskill,
    Notification,
    Priority,
    SLAPolicy,
    StatusHistory,
    Subcategory,
    SystemSetting,
    Ticket,
    TicketAssignment,
    TicketStatus,
    User,
    now,
    utc,
)
from app.services.audit import audit

ACTIVE = (
    TicketStatus.WAITING_FOR_USER,
    TicketStatus.WAITING_FOR_VENDOR,
    TicketStatus.REOPENED,
    TicketStatus.NEW,
    TicketStatus.ASSIGNED,
    TicketStatus.OPEN,
    TicketStatus.IN_PROGRESS,
    TicketStatus.PENDING,
    TicketStatus.PENDING_USER,
    TicketStatus.PENDING_VENDOR,
)
TRANSITIONS = {
    "NEW": {"ASSIGNED"},
    "REOPENED": {"ASSIGNED", "IN_PROGRESS"},
    "WAITING_FOR_USER": {"IN_PROGRESS", "RESOLVED"},
    "WAITING_FOR_VENDOR": {"IN_PROGRESS", "RESOLVED"},
    "ASSIGNED": {
        "IN_PROGRESS",
        "PENDING",
        "WAITING_FOR_USER",
        "WAITING_FOR_VENDOR",
        "RESOLVED",
    },
    "OPEN": {
        "IN_PROGRESS",
        "PENDING",
        "WAITING_FOR_USER",
        "WAITING_FOR_VENDOR",
        "RESOLVED",
    },
    "IN_PROGRESS": {"PENDING", "WAITING_FOR_USER", "WAITING_FOR_VENDOR", "RESOLVED"},
    "PENDING": {"IN_PROGRESS", "RESOLVED"},
    "PENDING_USER": {"IN_PROGRESS", "RESOLVED"},
    "PENDING_VENDOR": {"IN_PROGRESS", "RESOLVED"},
    "RESOLVED": {"CLOSED", "IN_PROGRESS", "NEW", "REOPENED"},
    "CLOSED": {"NEW", "REOPENED"},
    "CANCELLED": {"NEW"},
}


def scope(stmt, user):
    stmt = stmt.where(Ticket.deleted == False)
    if user.role in ENGINEERS:
        return stmt.where(or_(Ticket.assignee_id == user.id, Ticket.requester_id == user.id))
    if user.role not in ADMINS:
        return stmt.where(Ticket.requester_id == user.id)
    return stmt


def can_work(user, ticket):
    return user.role in ADMINS or (user.role in ENGINEERS and ticket.assignee_id == user.id)


def get_ticket(db, ticket_id, user, lock=False):
    stmt = scope(select(Ticket).where(Ticket.id == ticket_id), user)
    if lock:
        stmt = stmt.with_for_update()
    ticket = db.scalar(stmt)
    if not ticket:
        raise HTTPException(404, "Ticket not found")
    return ticket


def assignment_lock(db):
    # All automatic/manual assignment and capacity edits share a transaction lock.
    if db.bind.dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(732041)"))


def notify(db, t, event, message, extra=(), internal=False):
    setting = db.get(SystemSetting, "notifications")
    if setting and not setting.value.get("enabled", True):
        return
    recipients = set(extra)
    if t.assignee_id:
        recipients.add(t.assignee_id)
    if not internal:
        recipients.add(t.requester_id)
    for uid in recipients:
        db.add(
            Notification(
                user_id=uid,
                ticket_id=t.id,
                event=event,
                message=f"{t.number}: {message}"[:512],
            )
        )


def assign(db, t, engineer_id, actor, reason, automatic=False):
    previous = t.assignee_id
    t.assignee_id = engineer_id
    t.assignment_reason = None if engineer_id else reason
    if engineer_id:
        engineer = db.get(Engineer, engineer_id)
        engineer.last_assigned_at = now()
        if t.status in (TicketStatus.NEW, TicketStatus.OPEN, TicketStatus.REOPENED):
            change_status(db, t, TicketStatus.ASSIGNED, actor)
    elif t.status in ACTIVE:
        change_status(db, t, TicketStatus.NEW, actor)
    db.add(
        TicketAssignment(
            ticket_id=t.id,
            previous_engineer_id=previous,
            engineer_id=engineer_id,
            actor_id=actor,
            reason=reason,
        )
    )
    event = "TICKET_REASSIGNED" if previous else "TICKET_ASSIGNED"
    audit(
        db,
        actor,
        event,
        "ticket",
        t.id,
        {"engineer_id": previous},
        {"engineer_id": engineer_id, "reason": reason, "automatic": automatic},
    )
    notify(db, t, event, "Assignment updated", extra=[previous] if previous else [])


def auto_assign(db, t, actor):
    assignment_lock(db)
    setting = db.get(SystemSetting, "assignment")
    rules = (
        setting.value
        if setting
        else {"enabled": True, "fallback": False, "strategy": "least_workload"}
    )
    eligible = []
    if rules.get("enabled", True):
        engineers = db.execute(
            select(Engineer, User)
            .join(User, User.id == Engineer.user_id)
            .where(
                User.active == True,
                User.role.in_(ENGINEERS),
                Engineer.available == True,
            )
        ).all()
        counts = dict(
            db.execute(
                select(Ticket.assignee_id, func.count())
                .where(Ticket.status.in_(ACTIVE), Ticket.deleted == False)
                .group_by(Ticket.assignee_id)
            ).all()
        )
        pressure = dict(
            db.execute(
                select(
                    Ticket.assignee_id,
                    func.sum(
                        case(
                            (Ticket.priority == Priority.CRITICAL, 4),
                            (Ticket.priority == Priority.HIGH, 2),
                            else_=1,
                        )
                        + case(
                            (Ticket.sla_due_at < now() + timedelta(minutes=warning_minutes(db)), 1),
                            else_=0,
                        )
                    ),
                )
                .where(Ticket.status.in_(ACTIVE), Ticket.deleted == False)
                .group_by(Ticket.assignee_id)
            ).all()
        )
        skills = {
            uid
            for (uid,) in db.execute(
                select(EngineerSkill.user_id).where(EngineerSkill.category_id == t.category_id)
            )
        }
        eligible = [
            e for e, u in engineers if counts.get(e.user_id, 0) < e.capacity and e.user_id in skills
        ]
        if not eligible and rules.get("fallback"):
            eligible = [e for e, u in engineers if counts.get(e.user_id, 0) < e.capacity]
        people = {u.id: u for e, u in engineers}
        subskills = {
            uid
            for (uid,) in db.execute(
                select(EngineerSubskill.user_id).where(
                    EngineerSubskill.subcategory_id == t.subcategory_id
                )
            )
        }

        def key(e):
            last = utc(e.last_assigned_at).timestamp() if e.last_assigned_at else 0
            if rules.get("strategy") == "scored":
                u = people[e.user_id]
                score = (
                    rules.get("category_weight", 40) * (e.user_id in skills)
                    + rules.get("subcategory_weight", 25) * (e.user_id in subskills)
                    + rules.get("location_weight", 15)
                    * bool(t.location and t.location == u.location)
                    + rules.get("team_weight", 10) * bool(t.team and t.team == u.team)
                    + rules.get("workload_weight", 10) * (1 - counts.get(e.user_id, 0) / e.capacity)
                    + rules.get("urgency_weight", 10)
                    * (1 - pressure.get(e.user_id, 0) / (5 * e.capacity))
                    * (2 if t.priority in (Priority.HIGH, Priority.CRITICAL) else 1)
                )
                return (-score, last, e.user_id)
            return (
                counts.get(e.user_id, 0) if rules.get("strategy") != "round_robin" else 0,
                last,
                e.user_id,
            )

        eligible.sort(key=key)
    if eligible:
        assign(
            db,
            t,
            eligible[0].user_id,
            actor,
            f"Automatic assignment ({rules.get('strategy', 'least_workload')}); {len(eligible)} eligible engineers",
            True,
        )
    else:
        reason = (
            "Automatic assignment disabled"
            if not rules.get("enabled", True)
            else "No available skilled engineer below capacity"
        )
        t.assignment_reason = reason
        audit(db, actor, "ASSIGNMENT_REQUIRED", "ticket", t.id, after={"reason": reason})
        admins = db.scalars(select(User.id).where(User.role.in_(ADMINS), User.active == True)).all()
        notify(db, t, "ASSIGNMENT_REQUIRED", reason, extra=admins)


def change_status(db, t, status, actor):
    previous = t.status.value
    t.status = status
    t.updated_at = now()
    if (
        status
        in (
            TicketStatus.IN_PROGRESS,
            TicketStatus.RESOLVED,
            TicketStatus.WAITING_FOR_USER,
            TicketStatus.WAITING_FOR_VENDOR,
        )
        and not t.acknowledged_at
    ):
        t.acknowledged_at = now()
    if status == TicketStatus.RESOLVED:
        t.resolved_at = now()
    if status == TicketStatus.CLOSED:
        t.closed_at = now()
    if previous in ("RESOLVED", "CLOSED") and status in ACTIVE:
        t.resolved_at = None
        t.closed_at = None
        policy = db.scalar(select(SLAPolicy).where(SLAPolicy.priority == t.priority))
        t.sla_due_at = now() + timedelta(minutes=policy.resolution_minutes) if policy else None
    db.add(StatusHistory(ticket_id=t.id, actor_id=actor, previous=previous, status=status.value))
    event = {
        "RESOLVED": "TICKET_RESOLVED",
        "CLOSED": "TICKET_CLOSED",
        "REOPENED": "TICKET_REOPENED",
    }.get(status.value, "STATUS_CHANGED")
    audit(db, actor, event, "ticket", t.id, {"status": previous}, {"status": status.value})
    notify(db, t, event, f"Status changed to {status.value}")


def validate_category(db, category_id, subcategory_id=None):
    c = db.get(Category, category_id) if category_id else None
    if not c or not c.active:
        raise HTTPException(422, "Choose an active category")
    if subcategory_id:
        s = db.get(Subcategory, subcategory_id)
        if not s or not s.active or s.category_id != category_id:
            raise HTTPException(422, "Invalid subcategory")


def warning_minutes(db):
    setting = db.get(SystemSetting, "notifications")
    return setting.value.get("sla_warning_minutes", 60) if setting else 60


def sla_scan(db):
    """Bulk outbox insertion avoids per-ticket queries at large ticket volumes."""
    from sqlalchemy import String, case, cast, literal, union_all
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert

    assignment_lock(db)
    setting = db.get(SystemSetting, "notifications")
    if setting and not setting.value.get("enabled", True):
        return
    warning = warning_minutes(db)
    timestamp = now()
    event = case((Ticket.sla_due_at < timestamp, "SLA_BREACHED"), else_="SLA_APPROACHING")
    candidates = []
    for recipient in [Ticket.requester_id, Ticket.assignee_id]:
        key = (
            cast(Ticket.id, String)
            + literal(":")
            + cast(recipient, String)
            + literal(":")
            + event
            + literal(":")
            + cast(Ticket.sla_due_at, String)
        )
        candidates.append(
            select(
                recipient,
                Ticket.id,
                event,
                Ticket.number + literal(": ") + event,
                literal(False),
                key,
                literal(timestamp),
            ).where(
                Ticket.status.in_(ACTIVE),
                Ticket.deleted == False,
                Ticket.sla_due_at <= timestamp + timedelta(minutes=warning),
                recipient != None,
            )
        )
    insert = pg_insert if db.bind.dialect.name == "postgresql" else sqlite_insert
    statement = (
        insert(Notification)
        .from_select(
            [
                "user_id",
                "ticket_id",
                "event",
                "message",
                "read",
                "dedupe_key",
                "created_at",
            ],
            union_all(*candidates),
        )
        .on_conflict_do_nothing(index_elements=["dedupe_key"])
    )
    db.execute(statement)
    db.commit()
