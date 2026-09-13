from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import STAFF, current_user, require
from app.core.database import get_db
from app.models.entities import Asset, AssetHistory, AssetStatus, KnowledgeArticle, User
from app.schemas.api import ArticleIn, AssetAssign, AssetIn
from app.services.audit import audit

router = APIRouter()


@router.get("/assets")
def assets(
    q: str | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(25, ge=1, le=100),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    stmt = select(Asset).order_by(Asset.asset_tag)
    if user.role not in STAFF:
        stmt = stmt.where(Asset.assigned_user_id == user.id)
    if q:
        stmt = stmt.where(
            or_(
                Asset.asset_tag.ilike(f"%{q}%"),
                Asset.serial_number.ilike(f"%{q}%"),
                Asset.hostname.ilike(f"%{q}%"),
            )
        )
    return db.scalars(stmt.offset(offset).limit(limit)).all()


@router.post("/assets", status_code=201)
def create_asset(
    data: AssetIn, user: User = Depends(require(*STAFF)), db: Session = Depends(get_db)
):
    from app.services.tickets import assignment_lock

    assignment_lock(db)
    sequence = (db.scalar(select(func.max(Asset.id))) or 0) + 1
    a = Asset(asset_tag=f"AST-{sequence:06d}", **data.model_dump())
    db.add(a)
    db.flush()
    db.add(AssetHistory(asset_id=a.id, actor_id=user.id, action="created", detail={}))
    audit(db, user.id, "created", "asset", str(a.id))
    db.commit()
    db.refresh(a)
    return a


@router.post("/assets/{asset_id}/assign")
def assign_asset(
    asset_id: int,
    data: AssetAssign,
    user: User = Depends(require(*STAFF)),
    db: Session = Depends(get_db),
):
    a = db.get(Asset, asset_id)
    if not a:
        raise HTTPException(404, "Asset not found")
    if data.user_id and not db.get(User, data.user_id):
        raise HTTPException(404, "User not found")
    old = a.assigned_user_id
    a.assigned_user_id = data.user_id
    a.status = AssetStatus.ASSIGNED if data.user_id else AssetStatus.AVAILABLE
    db.add(
        AssetHistory(
            asset_id=a.id,
            actor_id=user.id,
            action="assignment_changed",
            detail={"from": old, "to": data.user_id},
        )
    )
    audit(
        db,
        user.id,
        "assigned",
        "asset",
        str(a.id),
        before={"user_id": old},
        after={"user_id": data.user_id},
    )
    db.commit()
    return a


@router.get("/assets/{asset_id}/history")
def asset_history(asset_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    a = db.get(Asset, asset_id)
    if not a or (user.role not in STAFF and a.assigned_user_id != user.id):
        raise HTTPException(404, "Asset not found")
    return db.scalars(
        select(AssetHistory)
        .where(AssetHistory.asset_id == asset_id)
        .order_by(AssetHistory.created_at.desc())
    ).all()


@router.get("/knowledge")
def knowledge(q: str | None = None, db: Session = Depends(get_db), _: User = Depends(current_user)):
    stmt = select(KnowledgeArticle).where(KnowledgeArticle.published == True)
    if q:
        stmt = stmt.where(
            or_(
                KnowledgeArticle.title.ilike(f"%{q}%"),
                KnowledgeArticle.content.ilike(f"%{q}%"),
            )
        )
    return db.scalars(stmt.order_by(KnowledgeArticle.updated_at.desc()).limit(100)).all()


@router.post("/knowledge", status_code=201)
def article(
    data: ArticleIn,
    user: User = Depends(require(*STAFF)),
    db: Session = Depends(get_db),
):
    a = KnowledgeArticle(author_id=user.id, **data.model_dump())
    db.add(a)
    db.flush()
    audit(db, user.id, "created", "knowledge_article", str(a.id))
    db.commit()
    return a
