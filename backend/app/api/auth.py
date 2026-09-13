from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

from app.api.deps import current_user, user_out
from app.core.config import settings
from app.core.database import get_db
from app.core.security import digest, hash_password, secret, verify_password
from app.models.entities import AuthSession, LoginAttempt, User, now, utc
from app.schemas.enterprise import Login, Password
from app.services.audit import audit

router = APIRouter()
DUMMY = hash_password(secret())


@router.post("/auth/login")
def login(data: Login, request: Request, response: Response, db: Session = Depends(get_db)):
    ip = request.client.host if request.client else "unknown"
    if db.bind.dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": "login:" + ip})
    cutoff = now() - timedelta(minutes=15)
    db.execute(delete(LoginAttempt).where(LoginAttempt.created_at < cutoff))
    attempts = db.scalar(
        select(func.count()).select_from(LoginAttempt).where(LoginAttempt.ip_address == ip)
    )
    if attempts >= 30:
        raise HTTPException(429, "Too many login attempts. Try again in 15 minutes.")
    db.execute(delete(AuthSession).where(AuthSession.expires_at < now()))
    user = db.scalar(select(User).where(User.email == data.email.strip().lower()).with_for_update())
    valid = verify_password(data.password, user.password_hash if user else DUMMY)
    locked = user and user.locked_until and utc(user.locked_until) > now()
    if not user or not valid or not user.active or locked:
        db.add(LoginAttempt(ip_address=ip))
        if user and not locked:
            user.failed_logins += 1
            if user.failed_logins >= 5:
                user.locked_until = now() + timedelta(minutes=15)
        audit(
            db,
            user.id if user else None,
            "FAILED_LOGIN",
            "user",
            user.id if user else "unknown",
        )
        db.commit()
        raise HTTPException(401, "Invalid credentials or account temporarily unavailable")
    user.failed_logins = 0
    user.locked_until = None
    user.last_login = now()
    token = secret()
    csrf = secret()
    db.add(
        AuthSession(
            token_hash=digest(token),
            user_id=user.id,
            csrf_token=csrf,
            expires_at=now() + timedelta(minutes=settings.access_token_expire_minutes),
        )
    )
    audit(db, user.id, "LOGIN", "user", user.id)
    db.commit()
    response.set_cookie(
        "helpdesk_session",
        token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
        max_age=settings.access_token_expire_minutes * 60,
        path="/",
    )
    return {"user": user_out(user), "csrf_token": csrf}


@router.get("/auth/me")
@router.get("/me")
def me(request: Request, user: User = Depends(current_user)):
    return {"user": user_out(user), "csrf_token": request.state.session.csrf_token}


@router.post("/auth/logout")
def logout(
    request: Request,
    response: Response,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    db.delete(request.state.session)
    audit(db, user.id, "LOGOUT", "user", user.id)
    db.commit()
    response.delete_cookie("helpdesk_session", path="/")
    return {"success": True}


@router.post("/auth/password")
def password(
    data: Password,
    response: Response,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    if not data.current_password or not verify_password(data.current_password, user.password_hash):
        raise HTTPException(400, "Current password is incorrect")
    user.password_hash = hash_password(data.password)
    db.execute(delete(AuthSession).where(AuthSession.user_id == user.id))
    audit(db, user.id, "PASSWORD_CHANGED", "user", user.id)
    db.commit()
    response.delete_cookie("helpdesk_session", path="/")
    return {"success": True}
