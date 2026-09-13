from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import digest
from app.models.entities import AuthSession, Role, User, now, utc

ADMINS = (Role.ADMIN, Role.SUPER_ADMIN, Role.IT_ADMIN)
ENGINEERS = (Role.ENGINEER, Role.IT_AGENT)
STAFF = ADMINS + ENGINEERS


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = request.cookies.get("helpdesk_session")
    bearer = request.headers.get("authorization", "")
    uses_bearer = bearer.startswith("Bearer ")
    if uses_bearer:
        token = bearer[7:]
    session = db.get(AuthSession, digest(token)) if token else None
    if not session or utc(session.expires_at) <= now():
        raise HTTPException(401, "Invalid or expired session")
    user = db.get(User, session.user_id)
    if not user or not user.active:
        raise HTTPException(401, "Account unavailable")
    if not uses_bearer and request.method not in ("GET", "HEAD", "OPTIONS"):
        if request.headers.get("X-CSRF-Token") != session.csrf_token:
            raise HTTPException(403, "Invalid CSRF token")
    request.state.session = session
    return user


def require(*roles):
    def gate(user: User = Depends(current_user)):
        if user.role not in roles:
            raise HTTPException(403, "Insufficient permission")
        return user

    return gate


def user_out(u):
    return {
        k: getattr(u, k)
        for k in (
            "id",
            "email",
            "name",
            "role",
            "department",
            "location",
            "active",
            "last_login",
            "created_at",
            "employee_id",
            "team",
            "phone",
        )
    }
