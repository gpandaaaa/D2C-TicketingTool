"""Administrative CLI. Creates the first production admin without demo data."""

import argparse
import getpass
import os

from sqlalchemy import select

from app.core.database import SessionLocal
from app.core.security import hash_password
from app.models.entities import Priority, Role, SLAPolicy, SystemSetting, User
from app.schemas.enterprise import (
    AssignmentRules,
    NotificationRules,
    UserCreate,
    WorkflowConfig,
)
from app.services.audit import audit


def bootstrap(email, name, password):
    data = UserCreate(email=email, name=name, password=password, role=Role.ADMIN)
    with SessionLocal() as db:
        if db.scalar(
            select(User.id).where(User.role.in_([Role.ADMIN, Role.IT_ADMIN, Role.SUPER_ADMIN]))
        ):
            raise RuntimeError("An administrator already exists; use the Admin Console")
        user = User(
            name=data.name,
            email=data.email.lower(),
            role=Role.ADMIN,
            password_hash=hash_password(data.password),
        )
        db.add(user)
        db.flush()
        for priority, response, resolution in [
            (Priority.CRITICAL, 15, 60),
            (Priority.HIGH, 30, 240),
            (Priority.MEDIUM, 60, 480),
            (Priority.LOW, 240, 1440),
        ]:
            if not db.scalar(select(SLAPolicy).where(SLAPolicy.priority == priority)):
                db.add(
                    SLAPolicy(
                        name=priority.value,
                        priority=priority,
                        response_minutes=response,
                        resolution_minutes=resolution,
                    )
                )
        for key, value in [
            ("assignment", AssignmentRules(strategy="scored").model_dump()),
            ("workflow", WorkflowConfig().model_dump()),
            ("notifications", NotificationRules().model_dump()),
        ]:
            if not db.get(SystemSetting, key):
                db.add(SystemSetting(key=key, value=value))
        audit(db, user.id, "ADMIN_BOOTSTRAPPED", "user", user.id)
        db.commit()
    print(
        "Administrator created. Configure categories, teams, locations and engineers before accepting tickets."
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["bootstrap-admin"])
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", required=True)
    args = parser.parse_args()
    bootstrap(
        args.email,
        args.name,
        os.environ.get("BOOTSTRAP_PASSWORD")
        or getpass.getpass("Administrator password (12+ characters): "),
    )
