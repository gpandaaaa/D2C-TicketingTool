from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.api.deps import ADMINS, ENGINEERS, current_user, require
from app.core.database import get_db
from app.models.entities import (
    AuthSession,
    Category,
    Engineer,
    Notification,
    Priority,
    Ticket,
    TicketStatus,
    User,
    now,
)
from app.services.tickets import ACTIVE, scope, warning_minutes

router = APIRouter()


def duration_expr(db, end, start):
    if db.bind.dialect.name == "postgresql":
        return func.extract("epoch", end - start) / 3600
    return (func.julianday(end) - func.julianday(start)) * 24


@router.get("/dashboard")
@router.get("/reports/dashboard")
@router.get("/admin/dashboard", dependencies=[Depends(require(*ADMINS))])
def dashboard(user: User = Depends(current_user), db: Session = Depends(get_db)):
    base = scope(select(Ticket), user)
    if user.role in ENGINEERS:
        base = base.where(Ticket.assignee_id == user.id)
    today = now().replace(hour=0, minute=0, second=0, microsecond=0)

    def count(*conditions):
        return db.scalar(select(func.count()).select_from(base.where(*conditions).subquery())) or 0

    total = count()
    resolved = count(Ticket.resolved_at != None)
    ontime = count(Ticket.resolved_at != None, Ticket.resolved_at <= Ticket.sla_due_at)
    metrics = {
        "total": total,
        "open": count(Ticket.status.in_(ACTIVE)),
        "in_progress": count(Ticket.status == TicketStatus.IN_PROGRESS),
        "pending": count(
            Ticket.status.in_(
                [
                    TicketStatus.PENDING,
                    TicketStatus.WAITING_FOR_USER,
                    TicketStatus.WAITING_FOR_VENDOR,
                    TicketStatus.PENDING_USER,
                    TicketStatus.PENDING_VENDOR,
                ]
            )
        ),
        "resolved": count(Ticket.status == TicketStatus.RESOLVED),
        "closed": count(Ticket.status == TicketStatus.CLOSED),
        "critical": count(Ticket.priority == Priority.CRITICAL, Ticket.status.in_(ACTIVE)),
        "high": count(Ticket.priority == Priority.HIGH, Ticket.status.in_(ACTIVE)),
        "unassigned": count(Ticket.assignee_id == None, Ticket.status.in_(ACTIVE)),
        "sla_breaches": count(Ticket.sla_due_at < now(), Ticket.status.in_(ACTIVE)),
        "due_soon": count(
            Ticket.sla_due_at.between(now(), now() + timedelta(minutes=warning_minutes(db))),
            Ticket.status.in_(ACTIVE),
        ),
        "created_today": count(Ticket.created_at >= today),
        "resolved_today": count(Ticket.resolved_at >= today),
        "sla_compliance": round(100 * ontime / resolved, 1) if resolved else None,
    }
    sub = base.subquery()
    metrics["average_resolution_hours"] = (
        db.scalar(select(func.avg(duration_expr(db, sub.c.resolved_at, sub.c.created_at)))) or 0
    )
    metrics["average_response_hours"] = (
        db.scalar(select(func.avg(duration_expr(db, sub.c.acknowledged_at, sub.c.created_at)))) or 0
    )

    def group(col):
        return [
            {
                "label": str(k.value if hasattr(k, "value") else k or "Unspecified"),
                "value": v,
            }
            for k, v in db.execute(select(col, func.count()).select_from(sub).group_by(col))
        ]

    charts = {
        "priority": group(sub.c.priority),
        "status": group(sub.c.status),
        "location": group(sub.c.location),
    }
    charts["category"] = [
        {"label": name or "Uncategorized", "value": count}
        for name, count in db.execute(
            select(Category.name, func.count())
            .select_from(sub)
            .outerjoin(Category, sub.c.category_id == Category.id)
            .group_by(Category.name)
        )
    ]
    charts["engineer"] = [
        {"label": name or "Unassigned", "value": count}
        for name, count in db.execute(
            select(User.name, func.count())
            .select_from(sub)
            .outerjoin(User, sub.c.assignee_id == User.id)
            .group_by(User.name)
        )
    ]
    charts["daily"] = [
        {"label": str(day), "value": n}
        for day, n in db.execute(
            select(func.date(sub.c.created_at), func.count())
            .where(sub.c.created_at >= today - timedelta(days=29))
            .group_by(func.date(sub.c.created_at))
            .order_by(func.date(sub.c.created_at))
        )
    ]
    daily = {str(i["label"]): i["value"] for i in charts["daily"]}
    charts["daily"] = [
        {
            "label": str((today - timedelta(days=d)).date()),
            "value": daily.get(str((today - timedelta(days=d)).date()), 0),
        }
        for d in range(29, -1, -1)
    ]
    metrics["created_week"] = count(Ticket.created_at >= today - timedelta(days=7))
    metrics["created_month"] = count(Ticket.created_at >= today - timedelta(days=30))
    if user.role in ADMINS:
        metrics["active_users"] = db.scalar(
            select(func.count()).select_from(User).where(User.active == True)
        )
        metrics["active_engineers"] = db.scalar(
            select(func.count())
            .select_from(User)
            .where(User.active == True, User.role.in_(ENGINEERS))
        )
        metrics["active_sessions"] = db.scalar(
            select(func.count(func.distinct(AuthSession.user_id))).where(
                AuthSession.expires_at > now()
            )
        )
    workload = []
    if user.role in ADMINS or user.role in ENGINEERS:
        stmt = (
            select(Engineer, User.name)
            .join(User, User.id == Engineer.user_id)
            .where(User.role.in_(ENGINEERS))
        )
        if user.role in ENGINEERS:
            stmt = stmt.where(Engineer.user_id == user.id)
        counts = dict(
            db.execute(
                select(Ticket.assignee_id, func.count())
                .where(Ticket.status.in_(ACTIVE), Ticket.deleted == False)
                .group_by(Ticket.assignee_id)
            ).all()
        )
        workload = [
            {
                "id": e.user_id,
                "name": name,
                "active": counts.get(e.user_id, 0),
                "capacity": e.capacity,
                "available": e.available,
            }
            for e, name in db.execute(stmt.order_by(User.name).limit(100))
        ]
    return {
        "metrics": metrics,
        "charts": charts,
        "workload": workload,
        "system": {"database": "connected", "time": now()},
    }


@router.get("/notifications")
def notifications(
    offset: int = Query(0, ge=0),
    limit: int = Query(25, ge=1, le=100),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    stmt = select(Notification).where(Notification.user_id == user.id)
    return {
        "items": db.scalars(
            stmt.order_by(Notification.id.desc()).offset(offset).limit(limit)
        ).all(),
        "total": db.scalar(select(func.count()).select_from(stmt.subquery())),
        "unread": db.scalar(
            select(func.count()).select_from(stmt.where(Notification.read == False).subquery())
        ),
    }


@router.post("/notifications/read-all")
def read_all(user: User = Depends(current_user), db: Session = Depends(get_db)):
    db.execute(update(Notification).where(Notification.user_id == user.id).values(read=True))
    db.commit()
    return {"success": True}


@router.patch("/notifications/{notification_id}")
def read(
    notification_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    n = db.get(Notification, notification_id)
    if not n or n.user_id != user.id:
        raise HTTPException(404, "Notification not found")
    n.read = True
    db.commit()
    return {"success": True}


@router.get("/admin/engineer-activity")
def engineer_activity(
    engineer_id: int | None = None,
    event: str = Query("all", pattern="^(all|assigned|completed)$"),
    search: str = Query("", max_length=200),
    date_from: date | None = None,
    date_to: date | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(25, ge=1, le=100),
    export: bool = False,
    user: User = Depends(require(*ADMINS)),
    db: Session = Depends(get_db),
):
    """Historical events, not current assignee snapshots; completion means RESOLVED."""
    import csv
    import io
    from datetime import datetime, time, timezone

    from fastapi import Response
    from sqlalchemy import literal, or_, union_all
    from sqlalchemy.orm import aliased

    from app.models.entities import StatusHistory, TicketAssignment
    from app.services.audit import audit

    if date_from and date_to and date_from > date_to:
        raise HTTPException(422, "Start date must not be after end date")
    assignments = select(
        TicketAssignment.id.label("event_id"),
        TicketAssignment.ticket_id.label("ticket_id"),
        TicketAssignment.engineer_id.label("engineer_id"),
        TicketAssignment.actor_id.label("actor_id"),
        TicketAssignment.created_at.label("occurred_at"),
        literal("assigned").label("event"),
        TicketAssignment.reason.label("details"),
    ).where(TicketAssignment.engineer_id != None)
    completed = select(
        StatusHistory.id.label("event_id"),
        StatusHistory.ticket_id.label("ticket_id"),
        StatusHistory.actor_id.label("engineer_id"),
        StatusHistory.actor_id.label("actor_id"),
        StatusHistory.created_at.label("occurred_at"),
        literal("completed").label("event"),
        literal("Ticket resolved").label("details"),
    ).where(StatusHistory.status == "RESOLVED")
    events = union_all(assignments, completed).subquery()
    person, actor = aliased(User), aliased(User)
    stmt = (
        select(
            events,
            Ticket.number,
            Ticket.title,
            Ticket.status.label("current_status"),
            person.name.label("engineer"),
            person.email.label("engineer_email"),
            actor.name.label("actor"),
        )
        .join(Ticket, Ticket.id == events.c.ticket_id)
        .join(person, person.id == events.c.engineer_id)
        .outerjoin(actor, actor.id == events.c.actor_id)
    )
    if engineer_id is not None:
        stmt = stmt.where(events.c.engineer_id == engineer_id)
    if event != "all":
        stmt = stmt.where(events.c.event == event)
    if search:
        term = f"%{search}%"
        stmt = stmt.where(
            or_(
                Ticket.number.ilike(term),
                Ticket.title.ilike(term),
                person.name.ilike(term),
                person.email.ilike(term),
            )
        )
    if date_from:
        stmt = stmt.where(
            events.c.occurred_at >= datetime.combine(date_from, time.min, timezone.utc)
        )
    if date_to:
        stmt = stmt.where(
            events.c.occurred_at
            < datetime.combine(date_to + timedelta(days=1), time.min, timezone.utc)
        )
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    if export and total > 10000:
        raise HTTPException(
            422, "Export exceeds 10,000 events. Narrow the date or engineer filters."
        )
    rows = [
        dict(r)
        for r in db.execute(
            stmt.order_by(events.c.occurred_at.desc(), events.c.event, events.c.event_id.desc())
            .offset(0 if export else offset)
            .limit(10000 if export else limit)
        ).mappings()
    ]
    if not export:
        return {"items": rows, "total": total}
    output = io.StringIO()
    fields = [
        "occurred_at",
        "event",
        "number",
        "title",
        "engineer",
        "engineer_email",
        "actor",
        "current_status",
        "details",
    ]
    writer = csv.writer(output)
    writer.writerow(fields)
    for row in rows:
        values = []
        for key in fields:
            value = row[key]
            value = str(value.value if hasattr(value, "value") else value or "")
            values.append(
                "'" + value
                if value.lstrip().startswith(("=", "+", "-", "@", "\t", "\r", "\n"))
                else value
            )
        writer.writerow(values)
    audit(
        db,
        user.id,
        "ENGINEER_REPORT_EXPORTED",
        "report",
        "engineer-activity",
        after={
            "rows": total,
            "engineer_id": engineer_id,
            "event": event,
            "date_from": str(date_from),
            "date_to": str(date_to),
        },
    )
    db.commit()
    return Response(
        "\ufeff" + output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="engineer-activity.csv"'},
    )


@router.get("/admin/email-deliveries")
def email_deliveries(
    offset: int = Query(0, ge=0),
    limit: int = Query(25, ge=1, le=100),
    user: User = Depends(require(*ADMINS)),
    db: Session = Depends(get_db),
):
    from app.core.config import settings
    from app.models.entities import EmailDelivery

    stmt = (
        select(EmailDelivery, Ticket.number, User.email)
        .select_from(EmailDelivery)
        .join(Ticket, Ticket.id == EmailDelivery.ticket_id)
        .join(User, User.id == EmailDelivery.recipient_id)
    )
    return {
        "enabled": settings.smtp_enabled,
        "total": db.scalar(select(func.count()).select_from(EmailDelivery)),
        "items": [
            {
                "id": d.id,
                "ticket": n,
                "recipient": email,
                "status": d.status,
                "attempts": d.attempts,
                "last_error": d.last_error,
                "sent_at": d.sent_at,
            }
            for d, n, email in db.execute(
                stmt.order_by(EmailDelivery.id.desc()).offset(offset).limit(limit)
            )
        ],
    }


@router.post("/admin/email-deliveries/{delivery_id}/retry")
def retry_email(
    delivery_id: int, user: User = Depends(require(*ADMINS)), db: Session = Depends(get_db)
):
    from app.models.entities import EmailDelivery
    from app.services.audit import audit

    d = db.get(EmailDelivery, delivery_id, with_for_update=True)
    if not d or d.status != "failed":
        raise HTTPException(409, "Only failed deliveries can be retried")
    d.status, d.attempts, d.available_at = "pending", 0, now()
    audit(db, user.id, "EMAIL_RETRY_REQUESTED", "email_delivery", d.id)
    db.commit()
    return {"success": True}
