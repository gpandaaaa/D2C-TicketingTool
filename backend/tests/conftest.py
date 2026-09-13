import os
import sys
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.database import get_db
from app.core.security import hash_password
from app.main import app
from app.models.entities import (
    Category,
    Engineer,
    EngineerSkill,
    Priority,
    Role,
    SLAPolicy,
    SystemSetting,
    User,
)

PASSWORD = "Test-Only-Password-2026!"


@pytest.fixture
def env(tmp_path):
    url = os.environ.get("TEST_DATABASE_URL", f"sqlite:///{tmp_path}/test.db")
    schema = "test_" + uuid.uuid4().hex
    pg = url.startswith("postgresql")
    if pg:
        control = create_engine(url)
        with control.begin() as conn:
            conn.execute(text(f"CREATE SCHEMA {schema}"))
        engine = create_engine(url, connect_args={"options": f"-csearch_path={schema},public"})
    else:
        engine = create_engine(url, connect_args={"check_same_thread": False})

        @event.listens_for(engine, "connect")
        def foreign_keys(conn, record):
            conn.execute("PRAGMA foreign_keys=ON")

    cfg = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    with engine.connect() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "head")
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with factory() as db:
        people = []
        for i, role in enumerate(
            [
                Role.ADMIN,
                Role.ENGINEER,
                Role.ENGINEER,
                Role.ENGINEER,
                Role.USER,
                Role.USER,
            ]
        ):
            u = User(
                name=f"Person {i}",
                email=f"p{i}@example.local",
                role=role,
                password_hash=hash_password(PASSWORD),
                employee_id=f"E{i}",
                location="Bengaluru",
                team="IT",
            )
            db.add(u)
            people.append(u)
        db.add_all(
            [
                Category(name="Network"),
                Category(name="Hardware"),
                Category(name="Security"),
            ]
        )
        db.flush()
        for u in people[1:4]:
            db.add(Engineer(user_id=u.id, capacity=2))
            db.flush()
            db.add(EngineerSkill(user_id=u.id, category_id=1))
        for p in Priority:
            db.add(
                SLAPolicy(
                    name=p.value,
                    priority=p,
                    response_minutes=30,
                    resolution_minutes=240,
                )
            )
        db.add(
            SystemSetting(
                key="assignment",
                value={
                    "enabled": True,
                    "fallback": False,
                    "strategy": "least_workload",
                },
            )
        )
        db.commit()

    def override():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override
    clients = []

    def client(index=0, login=True):
        c = TestClient(app)
        clients.append(c)
        if login:
            r = c.post(
                "/api/v1/auth/login",
                json={"email": f"p{index}@example.local", "password": PASSWORD},
            )
            assert r.status_code == 200, r.text
            c.headers["X-CSRF-Token"] = r.json()["csrf_token"]
        return c

    yield {"db": factory, "client": client, "engine": engine, "people": people}
    for c in clients:
        c.close()
    app.dependency_overrides.clear()
    engine.dispose()
    if pg:
        with control.begin() as conn:
            conn.execute(text(f"DROP SCHEMA {schema} CASCADE"))
        control.dispose()


@pytest.fixture
def ticket_payload():
    return {
        "title": "VPN connectivity issue",
        "description": "VPN disconnects during work",
        "category_id": 1,
        "priority": "HIGH",
        "location": "Bengaluru",
        "team": "IT",
    }
