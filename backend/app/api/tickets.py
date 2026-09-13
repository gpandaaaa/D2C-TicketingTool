import csv
import hashlib
import io
import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, aliased

from app.api.deps import ADMINS, ENGINEERS, STAFF, current_user, require, user_out
from app.core.database import get_db
from app.models.entities import (
    Attachment,
    AuditLog,
    Category,
    Engineer,
    Priority,
    SLAPolicy,
    StatusHistory,
    SystemSetting,
    Ticket,
    TicketComment,
    TicketRequest,
    TicketStatus,
    User,
    now,
    utc,
)
from app.schemas.api import CommentIn
from app.schemas.enterprise import Assignment, BulkAction, TicketCreate, TicketEdit
from app.services.audit import audit
from app.services.tickets import (
    ACTIVE,
    TRANSITIONS,
    assign,
    assignment_lock,
    auto_assign,
    can_work,
    change_status,
    get_ticket,
    notify,
    scope,
    validate_category,
    warning_minutes,
)

router = APIRouter()


def serialize(t):
    return {c.name: getattr(t, c.name) for c in Ticket.__table__.columns}


def ticket_query(
    user,
    q=None,
    status=None,
    priority=None,
    category_id=None,
    assignee_id=None,
    requester_id=None,
    assignment=None,
    sla=None,
    date_from=None,
    date_to=None,
    team=None,
    location=None,
    mine=False,
    warning=60,
):
    stmt = scope(select(Ticket), user)
    if q:
        requester = aliased(User)
        engineer = aliased(User)
        stmt = (
            stmt.join(requester, Ticket.requester_id == requester.id)
            .outerjoin(engineer, Ticket.assignee_id == engineer.id)
            .outerjoin(Category, Ticket.category_id == Category.id)
        )
        term = f"%{q}%"
        stmt = stmt.where(
            or_(
                *[
                    col.ilike(term)
                    for col in (
                        Ticket.number,
                        Ticket.title,
                        Ticket.description,
                        requester.name,
                        requester.email,
                        requester.employee_id,
                        engineer.name,
                        Category.name,
                    )
                ]
            )
        )
    for col, val in [
        (Ticket.status, status),
        (Ticket.priority, priority),
        (Ticket.category_id, category_id),
        (Ticket.assignee_id, assignee_id),
        (Ticket.requester_id, requester_id),
        (Ticket.team, team),
        (Ticket.location, location),
    ]:
        if val is not None:
            stmt = stmt.where(col == val)
    if mine:
        stmt = stmt.where(
            Ticket.assignee_id == user.id if user.role in STAFF else Ticket.requester_id == user.id
        )
    if assignment == "unassigned":
        stmt = stmt.where(Ticket.assignee_id == None, Ticket.status.in_(ACTIVE))
    if assignment == "assigned":
        stmt = stmt.where(Ticket.assignee_id != None)
    if sla in ("breached", "approaching", "within"):
        stmt = stmt.where(Ticket.status.in_(ACTIVE))
        if sla == "breached":
            stmt = stmt.where(Ticket.sla_due_at < now())
        elif sla == "approaching":
            stmt = stmt.where(
                Ticket.sla_due_at >= now(),
                Ticket.sla_due_at <= now() + timedelta(minutes=warning),
            )
        else:
            stmt = stmt.where(Ticket.sla_due_at > now() + timedelta(minutes=warning))
    if date_from:
        stmt = stmt.where(Ticket.created_at >= date_from)
    if date_to:
        stmt = stmt.where(
            Ticket.created_at
            < (
                date_to + timedelta(days=1)
                if date_to.hour == date_to.minute == date_to.second == 0
                else date_to
            )
        )
    return stmt


@router.get("/tickets")
def listing(
    q: str | None = Query(None, max_length=200),
    status: TicketStatus | None = None,
    priority: Priority | None = None,
    category_id: int | None = None,
    assignee_id: int | None = None,
    requester_id: int | None = None,
    assignment: str | None = None,
    sla: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    team: str | None = None,
    location: str | None = None,
    mine: bool = False,
    offset: int = Query(0, ge=0),
    limit: int = Query(25, ge=1, le=100),
    sort: str = Query("newest", pattern="^(newest|oldest|updated|sla)$"),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    stmt = ticket_query(
        user,
        q,
        status,
        priority,
        category_id,
        assignee_id,
        requester_id,
        assignment,
        sla,
        date_from,
        date_to,
        team,
        location,
        mine,
        warning_minutes(db),
    )
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    order = {
        "newest": Ticket.created_at.desc(),
        "oldest": Ticket.created_at.asc(),
        "updated": Ticket.updated_at.desc(),
        "sla": Ticket.sla_due_at.asc(),
    }[sort]
    items = db.scalars(stmt.order_by(order, Ticket.id).offset(offset).limit(limit)).all()
    ids = {t.requester_id for t in items} | {t.assignee_id for t in items if t.assignee_id}
    people = {u.id: u.name for u in db.scalars(select(User).where(User.id.in_(ids)))}
    return {
        "items": [
            dict(
                serialize(t),
                requester_name=people.get(t.requester_id),
                engineer_name=people.get(t.assignee_id),
            )
            for t in items
        ],
        "total": total,
        "offset": offset,
        "limit": limit,
    }


@router.post("/tickets", status_code=201)
def create(
    data: TicketCreate,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
    idempotency_key: str | None = Header(None, max_length=128),
):
    assignment_lock(db)
    # Direct service callers (seed) omit the optional HTTP header.
    key = (
        hashlib.sha256(f"{user.id}:{idempotency_key}".encode()).hexdigest()
        if isinstance(idempotency_key, str)
        else None
    )
    fingerprint = hashlib.sha256(data.model_dump_json().encode()).hexdigest()
    if key:
        prior = db.get(TicketRequest, key)
        if prior:
            if prior.fingerprint != fingerprint:
                raise HTTPException(409, "Idempotency key was used for a different request")
            return serialize(get_ticket(db, prior.ticket_id, user))
    validate_category(db, data.category_id, data.subcategory_id)
    policy = db.scalar(select(SLAPolicy).where(SLAPolicy.priority == data.priority))
    if not policy:
        raise HTTPException(422, "An administrator must configure SLA for this priority")
    t = Ticket(
        number=f"tmp-{uuid.uuid4().hex[:24]}",
        requester_id=user.id,
        status=TicketStatus.OPEN,
        **data.model_dump(),
    )
    if not t.team:
        t.team = user.team
    if not t.location:
        t.location = user.location
    t.sla_due_at = now() + timedelta(minutes=policy.resolution_minutes)
    t.response_due_at = now() + timedelta(minutes=policy.response_minutes)
    db.add(t)
    db.flush()
    t.number = f"D2C-{now().year}-{t.id:06d}"
    audit(
        db,
        user.id,
        "CREATE_TICKET",
        "ticket",
        t.id,
        after={"number": t.number, "title": t.title},
    )
    db.add(StatusHistory(ticket_id=t.id, actor_id=user.id, status="OPEN"))
    notify(db, t, "TICKET_CREATED", "Ticket created")
    auto_assign(db, t, user.id)
    if key:
        db.add(TicketRequest(key=key, fingerprint=fingerprint, ticket_id=t.id))
    db.commit()
    db.refresh(t)
    return serialize(t)


@router.get("/tickets/export")
def export(
    ids: str = Query(..., max_length=1000),
    user: User = Depends(require(*ADMINS)),
    db: Session = Depends(get_db),
):
    try:
        selected = [int(i) for i in ids.split(",")]
    except ValueError:
        raise HTTPException(422, "Invalid ticket IDs")
    if len(selected) > 100:
        raise HTTPException(422, "Export at most 100 selected tickets")
    rows = db.scalars(scope(select(Ticket).where(Ticket.id.in_(selected)), user)).all()
    output = io.StringIO()
    writer = csv.writer(output)
    fields = [
        "number",
        "title",
        "priority",
        "status",
        "requester_id",
        "assignee_id",
        "created_at",
        "sla_due_at",
    ]
    writer.writerow(fields)
    for t in rows:
        values = [str(getattr(t, f) or "") for f in fields]
        writer.writerow(
            ["'" + v if v.startswith(("=", "+", "-", "@", "\t", "\r")) else v for v in values]
        )
    audit(db, user.id, "EXPORT_TICKETS", "ticket", "bulk", after={"ids": selected})
    db.commit()
    return Response(
        output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="tickets.csv"'},
    )


def update_impl(db, t, data, user):
    operator = can_work(user, t)
    changes = data.model_dump(exclude_unset=True)
    if any(v is None for k, v in changes.items() if k not in ("subcategory_id", "team")):
        raise HTTPException(422, "Fields cannot be null")
    if not operator and set(changes) - {"status"}:
        raise HTTPException(403, "Only ticket closure or reopening is permitted")
    if operator and user.role in ENGINEERS and set(changes) - {"status", "resolution"}:
        raise HTTPException(403, "Only status and resolution can be changed by engineers")
    if "category_id" in changes or "subcategory_id" in changes:
        validate_category(
            db,
            changes.get("category_id", t.category_id),
            changes.get("subcategory_id", t.subcategory_id),
        )
    if data.status and data.status != t.status:
        if not operator:
            setting = db.get(SystemSetting, "workflow")
            days = setting.value.get("reopen_days", 7) if setting else 7
            allowed = t.status == TicketStatus.RESOLVED and data.status == TicketStatus.CLOSED
            if t.status in (
                TicketStatus.RESOLVED,
                TicketStatus.CLOSED,
            ) and data.status in (TicketStatus.REOPENED, TicketStatus.NEW):
                when = t.closed_at or t.resolved_at
                allowed = bool(days and when and now() - utc(when) <= timedelta(days=days))
            if not allowed:
                raise HTTPException(409, "Ticket cannot make this transition")
        elif user.role not in ADMINS and data.status.value not in TRANSITIONS.get(
            t.status.value, set()
        ):
            raise HTTPException(409, "Invalid status transition")
        if (
            data.status
            in (
                TicketStatus.ASSIGNED,
                TicketStatus.IN_PROGRESS,
                TicketStatus.WAITING_FOR_USER,
                TicketStatus.WAITING_FOR_VENDOR,
            )
            and not t.assignee_id
        ):
            raise HTTPException(409, "Assign an engineer first")
        if (
            data.status == TicketStatus.RESOLVED
            and not (data.resolution or t.resolution or "").strip()
        ):
            raise HTTPException(422, "A resolution is required")
        if data.status == TicketStatus.CLOSED and not t.resolved_at:
            raise HTTPException(409, "Resolve the ticket before closing")
    before = {k: getattr(t, k) for k in changes if k != "status"}
    for k, v in changes.items():
        if k != "status":
            setattr(t, k, v)
    if "priority" in changes:
        policy = db.scalar(select(SLAPolicy).where(SLAPolicy.priority == t.priority))
        if not policy:
            raise HTTPException(422, "SLA policy missing")
        t.sla_due_at = t.created_at + timedelta(minutes=policy.resolution_minutes)
        t.response_due_at = t.created_at + timedelta(minutes=policy.response_minutes)
    if data.status and data.status != t.status:
        change_status(db, t, data.status, user.id)
        if data.status in (TicketStatus.REOPENED, TicketStatus.NEW):
            if t.assignee_id:
                assign(db, t, None, user.id, "Reopened: reassessing assignment")
            db.flush()
            auto_assign(db, t, user.id)
    if before:
        audit(
            db,
            user.id,
            "UPDATE_TICKET",
            "ticket",
            t.id,
            before,
            {k: getattr(t, k) for k in before},
        )
        for k, event in [
            ("priority", "PRIORITY_CHANGE"),
            ("category_id", "CATEGORY_CHANGE"),
        ]:
            if k in before and before[k] != getattr(t, k):
                audit(
                    db,
                    user.id,
                    event,
                    "ticket",
                    t.id,
                    {k: before[k]},
                    {k: getattr(t, k)},
                )
    t.updated_at = now()


def manual_impl(db, t, data, user):
    if t.status not in ACTIVE:
        raise HTTPException(409, "Only active tickets can be assigned")
    if data.engineer_id:
        e = db.get(Engineer, data.engineer_id)
        u = db.get(User, data.engineer_id)
        if not e or not u.active or u.role not in ENGINEERS or not e.available:
            raise HTTPException(422, "Engineer is unavailable")
        count = db.scalar(
            select(func.count())
            .select_from(Ticket)
            .where(
                Ticket.assignee_id == e.user_id,
                Ticket.status.in_(ACTIVE),
                Ticket.deleted == False,
                Ticket.id != t.id,
            )
        )
        if count >= e.capacity:
            raise HTTPException(409, "Engineer is at capacity")
    if t.assignee_id == data.engineer_id:
        raise HTTPException(409, "Ticket is already assigned to this engineer")
    assign(db, t, data.engineer_id, user.id, data.reason)


@router.post("/tickets/bulk")
def bulk(
    data: BulkAction,
    user: User = Depends(require(*ADMINS)),
    db: Session = Depends(get_db),
):
    assignment_lock(db)
    for tid in sorted(set(data.ids)):
        t = get_ticket(db, tid, user, True)
        if data.action == "assign":
            manual_impl(
                db,
                t,
                Assignment(engineer_id=data.engineer_id, reason=data.reason),
                user,
            )
        elif data.action == "priority":
            if not data.priority:
                raise HTTPException(422, "Priority is required")
            update_impl(db, t, TicketEdit(priority=data.priority), user)
        else:
            if not data.status:
                raise HTTPException(422, "Status is required")
            update_impl(
                db,
                t,
                TicketEdit(
                    **{
                        "status": data.status,
                        **({"resolution": data.resolution} if data.resolution else {}),
                    }
                ),
                user,
            )
        db.flush()
    db.commit()
    return {"success": True, "count": len(set(data.ids))}


@router.get("/tickets/{ticket_id}")
def detail(ticket_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    t = get_ticket(db, ticket_id, user)
    comments = select(TicketComment).where(TicketComment.ticket_id == t.id)
    if not can_work(user, t):
        comments = comments.where(TicketComment.internal == False)
    comment_total = db.scalar(select(func.count()).select_from(comments.subquery()))
    entries = db.scalars(comments.order_by(TicketComment.id).limit(100)).all()
    events_query = select(AuditLog).where(
        AuditLog.entity == "ticket", AuditLog.entity_id == str(t.id)
    )
    if not can_work(user, t):
        events_query = events_query.where(
            or_(
                AuditLog.after["internal"].as_boolean() == False,
                AuditLog.after["internal"].as_boolean().is_(None),
            )
        )
    activity_total = db.scalar(select(func.count()).select_from(events_query.subquery()))
    events = db.scalars(events_query.order_by(AuditLog.id).limit(100)).all()
    people_ids = (
        {c.author_id for c in entries}
        | {e.actor_id for e in events if e.actor_id}
        | {t.requester_id}
    )
    if t.assignee_id:
        people_ids.add(t.assignee_id)
    people = {u.id: user_out(u) for u in db.scalars(select(User).where(User.id.in_(people_ids)))}
    attachments = (
        db.execute(
            select(
                Attachment.id,
                Attachment.name,
                Attachment.size,
                Attachment.created_at,
                Attachment.author_id,
            )
            .where(Attachment.ticket_id == t.id)
            .order_by(Attachment.id)
            .limit(100)
        )
        .mappings()
        .all()
    )
    timeline = [
        {
            "id": e.id,
            "actor_id": e.actor_id,
            "action": e.action,
            "created_at": e.created_at,
            "before": e.before,
            "after": e.after,
        }
        for e in events
    ]
    return {
        "comment_total": comment_total,
        "activity_total": activity_total,
        "ticket": serialize(t),
        "comments": entries,
        "activity": timeline,
        "people": people,
        "attachments": attachments,
        "transitions": list(TRANSITIONS.get(t.status.value, set())),
    }


@router.patch("/tickets/{ticket_id}")
def update(
    ticket_id: int,
    data: TicketEdit,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    assignment_lock(db)
    t = get_ticket(db, ticket_id, user, True)
    update_impl(db, t, data, user)
    db.commit()
    db.refresh(t)
    return serialize(t)


@router.delete("/tickets/{ticket_id}")
def remove(
    ticket_id: int,
    user: User = Depends(require(*ADMINS)),
    db: Session = Depends(get_db),
):
    assignment_lock(db)
    t = get_ticket(db, ticket_id, user, True)
    change_status(db, t, TicketStatus.CANCELLED, user.id)
    t.deleted = True
    audit(db, user.id, "DELETE_TICKET", "ticket", t.id)
    db.commit()
    return {"success": True}


@router.post("/tickets/{ticket_id}/assign")
@router.post("/tickets/{ticket_id}/reassign")
def manual(
    ticket_id: int,
    data: Assignment,
    user: User = Depends(require(*ADMINS)),
    db: Session = Depends(get_db),
):
    assignment_lock(db)
    t = get_ticket(db, ticket_id, user, True)
    manual_impl(db, t, data, user)
    db.commit()
    db.refresh(t)
    return serialize(t)


@router.post("/tickets/{ticket_id}/comments", status_code=201)
def comment(
    ticket_id: int,
    data: CommentIn,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    t = get_ticket(db, ticket_id, user, True)
    if not data.body.strip():
        raise HTTPException(422, "Comment cannot be blank")
    if data.internal and not can_work(user, t):
        raise HTTPException(403, "Internal notes are restricted")
    c = TicketComment(ticket_id=t.id, author_id=user.id, **data.model_dump())
    db.add(c)
    db.flush()
    t.updated_at = now()
    if can_work(user, t) and not t.acknowledged_at:
        t.acknowledged_at = now()
    audit(
        db,
        user.id,
        "COMMENT_ADDED",
        "ticket",
        t.id,
        after={"comment_id": c.id, "internal": c.internal},
    )
    notify(db, t, "COMMENT_ADDED", "A new comment was added", internal=c.internal)
    db.commit()
    db.refresh(c)
    return c


@router.get("/tickets/{ticket_id}/conversation")
def conversation(
    ticket_id: int,
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=100),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    t = get_ticket(db, ticket_id, user)
    stmt = select(TicketComment).where(TicketComment.ticket_id == ticket_id)
    if not can_work(user, t):
        stmt = stmt.where(TicketComment.internal == False)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.execute(
        stmt.add_columns(User.name)
        .join(User, TicketComment.author_id == User.id)
        .order_by(TicketComment.id)
        .offset(offset)
        .limit(limit)
    ).all()
    return {
        "total": total,
        "items": [
            {
                "id": c.id,
                "author_name": name,
                "body": c.body,
                "internal": c.internal,
                "created_at": c.created_at,
            }
            for c, name in rows
        ],
    }


@router.get("/tickets/{ticket_id}/activity")
def activity(
    ticket_id: int,
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=100),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    t = get_ticket(db, ticket_id, user)
    stmt = select(AuditLog).where(AuditLog.entity == "ticket", AuditLog.entity_id == str(ticket_id))
    if not can_work(user, t):
        stmt = stmt.where(
            or_(
                AuditLog.after["internal"].as_boolean() == False,
                AuditLog.after["internal"].as_boolean().is_(None),
            )
        )
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.execute(
        stmt.add_columns(User.name)
        .outerjoin(User, AuditLog.actor_id == User.id)
        .order_by(AuditLog.id)
        .offset(offset)
        .limit(limit)
    ).all()
    return {
        "total": total,
        "items": [
            {
                "id": a.id,
                "actor_name": name or "System",
                "action": a.action,
                "before": a.before,
                "after": a.after,
                "created_at": a.created_at,
            }
            for a, name in rows
        ],
    }
