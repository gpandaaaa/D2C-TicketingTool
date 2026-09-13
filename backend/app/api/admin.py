from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import ADMINS, ENGINEERS, current_user, require, user_out
from app.core.database import get_db
from app.core.security import hash_password
from app.models.entities import (
    AuditLog,
    AuthSession,
    Category,
    Engineer,
    EngineerSkill,
    EngineerSubskill,
    Location,
    Priority,
    Role,
    SLAPolicy,
    Subcategory,
    SystemSetting,
    Team,
    Ticket,
    TicketStatus,
    User,
    now,
)
from app.schemas.enterprise import (
    AssignmentRules,
    CategoryEdit,
    EngineerEdit,
    NotificationRules,
    Password,
    SLAEdit,
    SubcategoryEdit,
    UserCreate,
    UserEdit,
    WorkflowConfig,
)
from app.services.audit import audit
from app.services.tickets import ACTIVE, assignment_lock

router = APIRouter()
admin = require(*ADMINS)


def paginate(db, stmt, offset, limit):
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
    return {
        "items": db.scalars(stmt.offset(offset).limit(limit)).all(),
        "total": total,
        "offset": offset,
        "limit": limit,
    }


@router.get("/admin/users")
@router.get("/users")
def users(
    q: str = "",
    role: Role | None = None,
    active: bool | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(25, ge=1, le=100),
    _: User = Depends(admin),
    db: Session = Depends(get_db),
):
    stmt = select(User).order_by(User.name)
    if q:
        stmt = stmt.where(
            or_(
                User.name.ilike(f"%{q}%"),
                User.email.ilike(f"%{q}%"),
                User.employee_id.ilike(f"%{q}%"),
            )
        )
    if role:
        aliases = (
            ADMINS
            if role == Role.ADMIN
            else ENGINEERS
            if role == Role.ENGINEER
            else (Role.USER, Role.EMPLOYEE, Role.MANAGER)
            if role == Role.USER
            else (role,)
        )
        stmt = stmt.where(User.role.in_(aliases))
    if active is not None:
        stmt = stmt.where(User.active == active)
    result = paginate(db, stmt, offset, limit)
    result["items"] = [user_out(u) for u in result["items"]]
    return result


@router.post("/admin/users", status_code=201)
def create_user(data: UserCreate, user: User = Depends(admin), db: Session = Depends(get_db)):
    values = data.model_dump(exclude={"password"})
    values["email"] = values["email"].strip().lower()
    u = User(**values, password_hash=hash_password(data.password))
    db.add(u)
    db.flush()
    if u.role in ENGINEERS:
        db.add(Engineer(user_id=u.id))
    audit(
        db,
        user.id,
        "CREATE_USER",
        "user",
        u.id,
        after={"email": u.email, "role": u.role.value},
    )
    db.commit()
    return user_out(u)


@router.post("/admin/engineers", status_code=201)
def create_engineer(data: UserCreate, user: User = Depends(admin), db: Session = Depends(get_db)):
    return create_user(data.model_copy(update={"role": Role.ENGINEER}), user, db)


@router.get("/admin/users/{user_id}")
def user_detail(user_id: int, _: User = Depends(admin), db: Session = Depends(get_db)):
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(404, "User not found")
    return user_out(u)


@router.patch("/admin/users/{user_id}")
def edit_user(
    user_id: int,
    data: UserEdit,
    user: User = Depends(admin),
    db: Session = Depends(get_db),
):
    assignment_lock(db)
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(404, "User not found")
    values = data.model_dump(exclude_unset=True)
    if any(values.get(k, "valid") is None for k in ("role", "active", "name", "email")):
        raise HTTPException(422, "Required fields cannot be null")
    if u.id == user.id and (
        values.get("active") is False or ("role" in values and values["role"] not in ADMINS)
    ):
        raise HTTPException(409, "You cannot disable or demote your own administrator account")
    if (
        values.get("active") is False or ("role" in values and values["role"] not in ENGINEERS)
    ) and u.role in ENGINEERS:
        count = db.scalar(
            select(func.count())
            .select_from(Ticket)
            .where(
                Ticket.assignee_id == u.id,
                Ticket.status.in_(ACTIVE),
                Ticket.deleted == False,
            )
        )
        if count:
            raise HTTPException(
                409,
                "Reassign active tickets before disabling or changing this engineer role",
            )
    if "email" in values:
        values["email"] = values["email"].lower()
    before = {k: getattr(u, k) for k in values}
    for k, v in values.items():
        setattr(u, k, v)
    if u.role in ENGINEERS and not db.get(Engineer, u.id):
        db.add(Engineer(user_id=u.id))
    role_changed = before.get("role", u.role) != u.role
    active_changed = before.get("active", u.active) != u.active
    if role_changed or active_changed:
        db.execute(delete(AuthSession).where(AuthSession.user_id == u.id))
    audit(db, user.id, "UPDATE_USER", "user", u.id, before, values)
    if role_changed:
        audit(
            db,
            user.id,
            "ROLE_CHANGE",
            "user",
            u.id,
            {"role": before["role"]},
            {"role": u.role},
        )
    if active_changed:
        audit(db, user.id, "ENABLE_USER" if u.active else "DISABLE_USER", "user", u.id)
    db.commit()
    return user_out(u)


@router.delete("/admin/users/{user_id}")
def deactivate(user_id: int, user: User = Depends(admin), db: Session = Depends(get_db)):
    return edit_user(user_id, UserEdit(active=False), user, db)


@router.post("/admin/users/{user_id}/password")
def reset_password(
    user_id: int,
    data: Password,
    user: User = Depends(admin),
    db: Session = Depends(get_db),
):
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(404, "User not found")
    u.password_hash = hash_password(data.password)
    u.failed_logins = 0
    u.locked_until = None
    db.execute(delete(AuthSession).where(AuthSession.user_id == u.id))
    audit(db, user.id, "PASSWORD_RESET", "user", u.id)
    db.commit()
    return {"success": True}


@router.get("/admin/engineers")
def engineers(
    q: str = "",
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    _: User = Depends(admin),
    db: Session = Depends(get_db),
):
    stmt = select(User).where(User.role.in_(ENGINEERS)).order_by(User.name)
    if q:
        stmt = stmt.where(or_(User.name.ilike(f"%{q}%"), User.email.ilike(f"%{q}%")))
    result = paginate(db, stmt, offset, limit)
    ids = [u.id for u in result["items"]]
    profiles = {e.user_id: e for e in db.scalars(select(Engineer).where(Engineer.user_id.in_(ids)))}
    counts = dict(
        db.execute(
            select(Ticket.assignee_id, func.count())
            .where(
                Ticket.assignee_id.in_(ids),
                Ticket.status.in_(ACTIVE),
                Ticket.deleted == False,
            )
            .group_by(Ticket.assignee_id)
        ).all()
    )
    resolved = dict(
        db.execute(
            select(Ticket.assignee_id, func.count())
            .where(Ticket.assignee_id.in_(ids), Ticket.resolved_at != None)
            .group_by(Ticket.assignee_id)
        ).all()
    )
    breaches = dict(
        db.execute(
            select(Ticket.assignee_id, func.count())
            .where(
                Ticket.assignee_id.in_(ids),
                Ticket.status.in_(ACTIVE),
                Ticket.sla_due_at < now(),
                Ticket.deleted == False,
            )
            .group_by(Ticket.assignee_id)
        ).all()
    )
    skills = {}
    subskills = {}
    for skill in db.scalars(select(EngineerSkill).where(EngineerSkill.user_id.in_(ids))):
        skills.setdefault(skill.user_id, []).append(skill.category_id)
    for skill in db.scalars(select(EngineerSubskill).where(EngineerSubskill.user_id.in_(ids))):
        subskills.setdefault(skill.user_id, []).append(skill.subcategory_id)
    from app.api.reporting import duration_expr

    averages = dict(
        db.execute(
            select(
                Ticket.assignee_id,
                func.avg(duration_expr(db, Ticket.resolved_at, Ticket.created_at)),
            )
            .where(Ticket.assignee_id.in_(ids), Ticket.resolved_at != None)
            .group_by(Ticket.assignee_id)
        ).all()
    )
    result["items"] = [
        dict(
            user_out(u),
            available=profiles[u.id].available,
            capacity=profiles[u.id].capacity,
            active_tickets=counts.get(u.id, 0),
            resolved_tickets=resolved.get(u.id, 0),
            sla_breaches=breaches.get(u.id, 0),
            average_resolution_hours=averages.get(u.id, 0),
            utilization=round(100 * counts.get(u.id, 0) / profiles[u.id].capacity),
            skills=skills.get(u.id, []),
            subskills=subskills.get(u.id, []),
        )
        for u in result["items"]
        if u.id in profiles
    ]
    return result


@router.patch("/admin/engineers/{user_id}")
def engineer_edit(
    user_id: int,
    data: EngineerEdit,
    user: User = Depends(admin),
    db: Session = Depends(get_db),
):
    assignment_lock(db)
    e = db.get(Engineer, user_id)
    u = db.get(User, user_id)
    if not e or u.role not in ENGINEERS:
        raise HTTPException(404, "Engineer not found")
    count = db.scalar(
        select(func.count())
        .select_from(Ticket)
        .where(
            Ticket.assignee_id == user_id,
            Ticket.status.in_(ACTIVE),
            Ticket.deleted == False,
        )
    )
    if data.capacity < count:
        raise HTTPException(409, "Capacity cannot be below current workload")
    for cid in data.skills:
        if not db.get(Category, cid):
            raise HTTPException(422, "Invalid category skill")
    for sid in data.subskills:
        if not db.get(Subcategory, sid):
            raise HTTPException(422, "Invalid subcategory skill")
    before = {
        "available": e.available,
        "capacity": e.capacity,
        "skills": list(
            db.scalars(select(EngineerSkill.category_id).where(EngineerSkill.user_id == user_id))
        ),
    }
    e.available = data.available
    e.capacity = data.capacity
    db.execute(delete(EngineerSkill).where(EngineerSkill.user_id == user_id))
    db.execute(delete(EngineerSubskill).where(EngineerSubskill.user_id == user_id))
    db.add_all([EngineerSkill(user_id=user_id, category_id=c) for c in set(data.skills)])
    db.add_all([EngineerSubskill(user_id=user_id, subcategory_id=c) for c in set(data.subskills)])
    audit(db, user.id, "UPDATE_ENGINEER", "user", user_id, before, data.model_dump())
    db.commit()
    return {"success": True}


@router.get("/categories")
def categories(_: User = Depends(current_user), db: Session = Depends(get_db)):
    return db.scalars(select(Category).where(Category.active == True).order_by(Category.name)).all()


@router.get("/configuration")
def configuration(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return {
        "categories": db.scalars(select(Category).order_by(Category.name)).all(),
        "subcategories": db.scalars(select(Subcategory).order_by(Subcategory.name)).all(),
        "teams": db.scalars(select(Team).order_by(Team.name)).all(),
        "locations": db.scalars(select(Location).order_by(Location.name)).all(),
        "sla": db.scalars(select(SLAPolicy)).all(),
        "statuses": [s.value for s in TicketStatus],
        "priorities": [p.value for p in Priority],
        "settings": {s.key: s.value for s in db.scalars(select(SystemSetting))},
    }


RESOURCE = {
    "categories": Category,
    "subcategories": Subcategory,
    "teams": Team,
    "locations": Location,
}


@router.post("/admin/config/{resource}", status_code=201)
def create_config(
    resource: str,
    data: SubcategoryEdit | CategoryEdit,
    user: User = Depends(admin),
    db: Session = Depends(get_db),
):
    model = RESOURCE.get(resource)
    if not model:
        raise HTTPException(404, "Configuration resource not found")
    values = data.model_dump()
    if resource == "subcategories":
        if not isinstance(data, SubcategoryEdit) or not db.get(Category, data.category_id):
            raise HTTPException(422, "Category required")
    else:
        values.pop("category_id", None)
    item = model(**values)
    db.add(item)
    db.flush()
    audit(db, user.id, "ADMIN_CONFIG_CREATED", resource, item.id, after=values)
    db.commit()
    db.refresh(item)
    return item


@router.patch("/admin/config/{resource}/{item_id}")
def edit_config(
    resource: str,
    item_id: int,
    data: SubcategoryEdit | CategoryEdit,
    user: User = Depends(admin),
    db: Session = Depends(get_db),
):
    model = RESOURCE.get(resource)
    item = db.get(model, item_id) if model else None
    if not item:
        raise HTTPException(404, "Configuration not found")
    values = data.model_dump()
    if resource != "subcategories":
        values.pop("category_id", None)
    elif "category_id" in values and values["category_id"] != item.category_id:
        raise HTTPException(422, "Subcategory parent cannot be changed")
    before = {k: getattr(item, k) for k in values}
    for k, v in values.items():
        setattr(item, k, v)
    audit(db, user.id, "ADMIN_CONFIG_UPDATED", resource, item_id, before, values)
    db.commit()
    db.refresh(item)
    return item


@router.put("/admin/sla/{priority}")
def sla(
    priority: Priority,
    data: SLAEdit,
    user: User = Depends(admin),
    db: Session = Depends(get_db),
):
    item = db.scalar(select(SLAPolicy).where(SLAPolicy.priority == priority))
    before = None
    if not item:
        item = SLAPolicy(name=priority.value, priority=priority, **data.model_dump())
        db.add(item)
    else:
        before = {
            "response_minutes": item.response_minutes,
            "resolution_minutes": item.resolution_minutes,
        }
        for k, v in data.model_dump().items():
            setattr(item, k, v)
    audit(db, user.id, "SLA_UPDATED", "sla", priority.value, before, data.model_dump())
    db.commit()
    return {"success": True}


def setting_save(db, key, data, user):
    assignment_lock(db)
    item = db.get(SystemSetting, key)
    before = item.value if item else None
    if item:
        item.value = data.model_dump()
    else:
        db.add(SystemSetting(key=key, value=data.model_dump()))
    audit(
        db,
        user.id,
        "ADMIN_SETTINGS_UPDATED",
        "settings",
        key,
        before,
        data.model_dump(),
    )
    db.commit()
    return data


@router.put("/admin/settings/assignment")
def assignment_settings(
    data: AssignmentRules, user: User = Depends(admin), db: Session = Depends(get_db)
):
    return setting_save(db, "assignment", data, user)


@router.put("/admin/settings/workflow")
def workflow_settings(
    data: WorkflowConfig, user: User = Depends(admin), db: Session = Depends(get_db)
):
    return setting_save(db, "workflow", data, user)


@router.put("/admin/settings/notifications")
def notification_settings(
    data: NotificationRules, user: User = Depends(admin), db: Session = Depends(get_db)
):
    return setting_save(db, "notifications", data, user)


@router.get("/admin/audit-logs")
@router.get("/audit-logs")
def logs(
    q: str = "",
    actor_id: int | None = None,
    action: str | None = None,
    entity: str | None = None,
    ticket: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    sort: str = Query("newest", pattern="^(newest|oldest)$"),
    offset: int = Query(0, ge=0),
    limit: int = Query(25, ge=1, le=100),
    _: User = Depends(admin),
    db: Session = Depends(get_db),
):
    stmt = select(AuditLog)
    if q:
        stmt = stmt.outerjoin(User, AuditLog.actor_id == User.id).where(
            or_(
                AuditLog.action.ilike(f"%{q}%"),
                AuditLog.entity_id.ilike(f"%{q}%"),
                User.name.ilike(f"%{q}%"),
                User.employee_id.ilike(f"%{q}%"),
            )
        )
    if actor_id:
        stmt = stmt.where(AuditLog.actor_id == actor_id)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if entity:
        stmt = stmt.where(AuditLog.entity == entity)
    if ticket:
        t = db.scalar(select(Ticket).where(Ticket.number == ticket))
        stmt = stmt.where(
            AuditLog.entity == "ticket",
            AuditLog.entity_id == str(t.id if t else ticket),
        )
    if date_from:
        stmt = stmt.where(AuditLog.created_at >= date_from)
    if date_to:
        stmt = stmt.where(
            AuditLog.created_at
            < (
                date_to + timedelta(days=1)
                if date_to.hour == date_to.minute == date_to.second == 0
                else date_to
            )
        )
    result = paginate(
        db,
        stmt.order_by(AuditLog.id.desc() if sort == "newest" else AuditLog.id.asc()),
        offset,
        limit,
    )
    ids = {e.actor_id for e in result["items"] if e.actor_id}
    people = {
        u.id: {"name": u.name, "employee_id": u.employee_id}
        for u in db.scalars(select(User).where(User.id.in_(ids)))
    }
    result["people"] = people
    return result
