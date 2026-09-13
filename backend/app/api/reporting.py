from datetime import timedelta

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
