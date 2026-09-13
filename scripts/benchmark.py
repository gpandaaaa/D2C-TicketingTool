"""Isolated PostgreSQL query benchmark; creates and removes its own schema."""

import json
import os
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

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
from app.services.tickets import sla_scan

url = os.environ["TEST_DATABASE_URL"]
schema = "benchmark_" + uuid.uuid4().hex
control = create_engine(url)
with control.begin() as conn:
    conn.execute(text(f"CREATE SCHEMA {schema}"))
engine = create_engine(url, connect_args={"options": f"-csearch_path={schema},public"})
try:
    cfg = Config("backend/alembic.ini")
    with engine.connect() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "head")
    factory = sessionmaker(engine, autoflush=False)
    password = "Benchmark-Only-Password!"
    hashed = hash_password(password)
    with factory() as db:
        for i in range(501):
            db.add(
                User(
                    name=f"Performance User {i}",
                    email=f"perf{i}@example.local",
                    password_hash=hashed,
                    role=Role.ADMIN if i == 0 else Role.ENGINEER if i <= 50 else Role.USER,
                    active=True,
                )
            )
        db.add_all(
            [Category(name=n) for n in ["Network", "Hardware", "Software", "Security", "Access"]]
        )
        db.flush()
        for uid in range(2, 52):
            db.add(Engineer(user_id=uid, capacity=1000))
            db.flush()
            db.add(EngineerSkill(user_id=uid, category_id=(uid % 5) + 1))
        for priority in Priority:
            db.add(
                SLAPolicy(
                    name=priority.value,
                    priority=priority,
                    response_minutes=30,
                    resolution_minutes=240,
                )
            )
        db.add(
            SystemSetting(key="notifications", value={"enabled": True, "sla_warning_minutes": 60})
        )
        db.commit()
    with engine.begin() as conn:
        conn.execute(
            text("""INSERT INTO tickets (number,kind,title,description,status,priority,category_id,requester_id,assignee_id,created_at,updated_at,deleted,sla_due_at,resolved_at)
        SELECT 'D2C-PERF-' || lpad(n::text,6,'0'),'INC','Network diagnostic request '||n,'Employee connectivity issue for benchmark record '||n,
          (CASE WHEN n%20=0 THEN 'IN_PROGRESS' ELSE 'CLOSED' END)::ticketstatus,
          (CASE WHEN n%4=0 THEN 'HIGH' ELSE 'MEDIUM' END)::priority,
          (n%5)+1,(n%450)+52,(n%50)+2,
          now()-(n%180)*interval '1 day',now()-(n%10)*interval '1 hour',false,
          now()+interval '2 hours',CASE WHEN n%20<>0 THEN now() ELSE NULL END
        FROM generate_series(1,100000) AS n""")
        )
        conn.execute(text("ANALYZE tickets"))

    def override():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override
    result = {
        "tickets": 100000,
        "users": 501,
        "engineers": 50,
        "database": "PostgreSQL 16",
        "seconds": {},
    }
    with TestClient(app) as client:
        login = client.post(
            "/api/v1/auth/login", json={"email": "perf0@example.local", "password": password}
        )
        assert login.status_code == 200
        for path in [
            "/tickets?limit=25",
            "/tickets?q=D2C-PERF-050000&limit=25",
            "/tickets?status=IN_PROGRESS&priority=HIGH&limit=25",
            "/tickets?offset=99975&limit=25",
            "/dashboard",
            "/admin/engineers?limit=50",
        ]:
            timings = []
            for _ in range(3):
                start = time.perf_counter()
                response = client.get("/api/v1" + path)
                timings.append(time.perf_counter() - start)
                assert response.status_code == 200, response.text
            result["seconds"][path] = {
                "median": round(sorted(timings)[1], 4),
                "max": round(max(timings), 4),
            }
    with factory() as db:
        start = time.perf_counter()
        sla_scan(db)
        result["sla_scan_seconds"] = round(time.perf_counter() - start, 4)
    Path("artifacts").mkdir(exist_ok=True)
    Path("artifacts/benchmark.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
finally:
    app.dependency_overrides.clear()
    engine.dispose()
    with control.begin() as conn:
        conn.execute(text(f"DROP SCHEMA {schema} CASCADE"))
    control.dispose()
