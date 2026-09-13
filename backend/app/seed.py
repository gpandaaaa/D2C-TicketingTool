"""Explicit, development-only seed. Password is provided through the environment."""

import os

from sqlalchemy import select

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.security import hash_password
from app.models.entities import (
    Category,
    Engineer,
    EngineerSkill,
    KnowledgeArticle,
    Location,
    Priority,
    Role,
    SLAPolicy,
    Subcategory,
    SystemSetting,
    Team,
    Ticket,
    TicketComment,
    TicketStatus,
    User,
)
from app.schemas.enterprise import (
    AssignmentRules,
    NotificationRules,
    TicketCreate,
    WorkflowConfig,
)
from app.services.audit import audit


def seed():
    if settings.environment != "development":
        raise RuntimeError("Demo seeding is disabled outside development")
    password = os.environ.get("SEED_PASSWORD", "")
    if len(password) < 12:
        raise RuntimeError("Set SEED_PASSWORD to a development password of at least 12 characters")
    with SessionLocal() as db:
        if db.scalar(select(User).limit(1)):
            print("Database already has users; seed skipped")
            return
        categories = [
            Category(name=n)
            for n in [
                "Hardware",
                "Software",
                "Network",
                "VPN",
                "Account / Access",
                "Email",
                "Security",
                "Printer",
                "Application",
                "VDI",
                "Other",
            ]
        ]
        db.add_all(categories)
        db.add_all(
            [Team(name=n) for n in ["Infrastructure", "Workplace", "Applications", "Security"]]
        )
        db.add_all([Location(name=n) for n in ["Bengaluru", "Gurugram", "Chennai", "Remote"]])
        admin = User(
            name="D2C Administrator",
            email="admin@example.local",
            employee_id="D2C-0001",
            role=Role.ADMIN,
            password_hash=hash_password(password),
            department="IT",
            team="Infrastructure",
            location="Bengaluru",
        )
        db.add(admin)
        db.flush()
        engineers = []
        for i, name in enumerate(
            ["Aarav Sharma", "Diya Rao", "Arjun Mehta", "Ananya Iyer", "Kabir Singh"]
        ):
            u = User(
                name=name,
                email=f"engineer{i + 1}@example.local",
                employee_id=f"IT-{i + 1:04d}",
                role=Role.ENGINEER,
                password_hash=hash_password(password),
                department="IT",
                team=[
                    "Infrastructure",
                    "Workplace",
                    "Applications",
                    "Security",
                    "Infrastructure",
                ][i],
                location=["Bengaluru", "Gurugram", "Chennai", "Bengaluru", "Remote"][i],
            )
            db.add(u)
            db.flush()
            db.add(Engineer(user_id=u.id, capacity=10))
            db.flush()
            engineers.append(u)
            for c in categories:
                if (
                    (i == 0 and c.name in ["Network", "VPN"])
                    or (i == 1 and c.name in ["Hardware", "Printer"])
                    or (i == 2 and c.name in ["Software", "Application", "VDI", "Email"])
                    or (i == 3 and c.name in ["Security", "Account / Access"])
                    or i == 4
                ):
                    db.add(EngineerSkill(user_id=u.id, category_id=c.id))
        users = []
        for i, name in enumerate(
            [
                "Priya Nair",
                "Rohan Kapoor",
                "Ishita Das",
                "Vikram Patel",
                "Neha Gupta",
                "Aditya Roy",
                "Meera Shah",
                "Karan Malhotra",
                "Sneha Reddy",
                "Rahul Verma",
            ]
        ):
            u = User(
                name=name,
                email=f"user{i + 1}@example.local",
                employee_id=f"D2C-{i + 10:04d}",
                role=Role.USER,
                password_hash=hash_password(password),
                department=["Commerce", "Marketing", "Operations"][i % 3],
                location=["Bengaluru", "Gurugram", "Chennai"][i % 3],
            )
            db.add(u)
            users.append(u)
        for p, response, resolution in [
            (Priority.CRITICAL, 15, 60),
            (Priority.HIGH, 30, 240),
            (Priority.MEDIUM, 60, 480),
            (Priority.LOW, 240, 1440),
        ]:
            db.add(
                SLAPolicy(
                    name=p.value.title(),
                    priority=p,
                    response_minutes=response,
                    resolution_minutes=resolution,
                )
            )
        for c in categories:
            db.add(Subcategory(category_id=c.id, name=f"{c.name} support"))
        for key, value in [
            ("assignment", AssignmentRules(strategy="scored").model_dump()),
            ("workflow", WorkflowConfig().model_dump()),
            ("notifications", NotificationRules().model_dump()),
        ]:
            db.add(SystemSetting(key=key, value=value))
        db.add(
            KnowledgeArticle(
                title="Connect securely to the corporate VPN",
                category="VPN",
                content="Open your approved VPN client. Select the corporate gateway and sign in with your work account. Complete multifactor authentication. If connection fails, attach a screenshot of the error to a VPN ticket. Never share your password or authentication code.",
                tags="vpn,network",
                published=True,
                author_id=admin.id,
            )
        )
        audit(db, admin.id, "DEVELOPMENT_SEEDED", "system", "seed")
        db.commit()
        from app.api.tickets import create, update_impl
        from app.schemas.enterprise import TicketEdit

        examples = [
            ("VPN disconnects during checkout monitoring", "VPN"),
            ("Laptop battery no longer charging", "Hardware"),
            ("Commerce dashboard access request", "Account / Access"),
            ("Suspicious email needs review", "Security"),
            ("Office Wi-Fi is unstable", "Network"),
            ("Spreadsheet application crashes", "Software"),
            ("Printer queue is stuck", "Printer"),
            ("VDI session freezes after login", "VDI"),
            ("Order application error on launch", "Application"),
            ("Outlook calendar is not syncing", "Email"),
            ("External monitor is flickering", "Hardware"),
            ("VPN authentication timeout", "VPN"),
        ]
        for i, (title, category) in enumerate(examples):
            c = next(c for c in categories if c.name == category)
            t_data = create(
                TicketCreate(
                    title=title,
                    description=f"{title}. This is affecting daily Samsung D2C operations. Please investigate and help restore service.",
                    category_id=c.id,
                    priority=list(Priority)[i % 4],
                ),
                users[i % len(users)],
                db,
            )
            t = db.get(Ticket, t_data["id"])
            db.add(
                TicketComment(
                    ticket_id=t.id,
                    author_id=users[i % len(users)].id,
                    body="I can provide additional details and screenshots if needed.",
                )
            )
            if i % 4 == 1:
                update_impl(db, t, TicketEdit(status=TicketStatus.IN_PROGRESS), admin)
            if i % 4 == 2:
                update_impl(db, t, TicketEdit(status=TicketStatus.WAITING_FOR_USER), admin)
            if i % 4 == 3:
                update_impl(
                    db,
                    t,
                    TicketEdit(
                        status=TicketStatus.RESOLVED,
                        resolution="Configuration corrected and service verified with requester.",
                    ),
                    admin,
                )
            db.commit()
        print("Development seed loaded: 1 admin, 5 engineers, 10 users, 12 tickets.")


if __name__ == "__main__":
    seed()
