import io
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from conftest import PASSWORD
from sqlalchemy import delete, func, select, text, update

from app.models.entities import (
    AuditLog,
    AuthSession,
    Engineer,
    EngineerSkill,
    Notification,
    Role,
    SystemSetting,
    Ticket,
    TicketComment,
    TicketStatus,
    User,
    now,
)
from app.services.tickets import sla_scan


def create(env, payload, client=None):
    c = client or env["client"](4)
    r = c.post("/api/v1/tickets", json=payload)
    assert r.status_code == 201, r.text
    return r.json()


def test_authentication_and_logout(env):
    c = env["client"](login=False)
    assert c.get("/api/v1/tickets").status_code == 401
    assert (
        c.post(
            "/api/v1/auth/login",
            json={"email": "p0@example.local", "password": "wrong"},
        ).status_code
        == 401
    )
    c = env["client"]()
    assert c.get("/api/v1/me").json()["user"]["role"] == "ADMIN"
    session = c.cookies.get("helpdesk_session")
    assert c.post("/api/v1/auth/logout").status_code == 200
    c.cookies.set("helpdesk_session", session)
    assert c.get("/api/v1/me").status_code == 401
    with env["db"]() as db:
        assert {"LOGIN", "LOGOUT", "FAILED_LOGIN"} <= set(db.scalars(select(AuditLog.action)))


@pytest.mark.parametrize("index", [1, 4, 5])
def test_admin_rbac(env, index):
    c = env["client"](index)
    for path in [
        "/admin/users",
        "/admin/engineers",
        "/admin/audit-logs",
        "/admin/dashboard",
    ]:
        assert c.get("/api/v1" + path).status_code == 403
    assert (
        c.post(
            "/api/v1/admin/users",
            json={
                "name": "New User",
                "email": "new@example.local",
                "password": PASSWORD,
            },
        ).status_code
        == 403
    )
    assert c.put("/api/v1/admin/settings/assignment", json={}).status_code == 403


def test_csrf_and_origin(env):
    c = env["client"]()
    del c.headers["X-CSRF-Token"]
    assert c.post("/api/v1/auth/logout").status_code == 403
    c = env["client"](login=False)
    assert (
        c.post(
            "/api/v1/auth/login",
            headers={"Origin": "https://evil.example"},
            json={"email": "p0@example.local", "password": PASSWORD},
        ).status_code
        == 403
    )


def test_session_expiry_disabled_and_reset(env):
    admin = env["client"]()
    user = env["client"](4)
    assert (
        admin.post(
            "/api/v1/admin/users/5/password",
            json={"password": "New-Secure-Password-2026"},
        ).status_code
        == 200
    )
    assert user.get("/api/v1/me").status_code == 401
    user = env["client"](5)
    assert admin.patch("/api/v1/admin/users/6", json={"active": False}).status_code == 200
    assert user.get("/api/v1/me").status_code == 401
    with env["db"]() as db:
        db.execute(update(AuthSession).values(expires_at=now() - timedelta(minutes=1)))
        db.commit()
    assert admin.get("/api/v1/me").status_code == 401


def test_password_change(env):
    c = env["client"](4)
    assert (
        c.post(
            "/api/v1/auth/password",
            json={"current_password": "bad", "password": PASSWORD},
        ).status_code
        == 400
    )
    assert (
        c.post(
            "/api/v1/auth/password",
            json={"current_password": PASSWORD, "password": "Changed-Password-2026!"},
        ).status_code
        == 200
    )
    assert c.get("/api/v1/me").status_code == 401


def test_lockout(env):
    c = env["client"](login=False)
    for _ in range(5):
        assert (
            c.post(
                "/api/v1/auth/login",
                json={"email": "p4@example.local", "password": "wrong"},
            ).status_code
            == 401
        )
    assert (
        c.post(
            "/api/v1/auth/login",
            json={"email": "p4@example.local", "password": PASSWORD},
        ).status_code
        == 401
    )


def test_user_management_no_secrets(env):
    c = env["client"]()
    r = c.post(
        "/api/v1/admin/users",
        json={
            "name": "Fresh Engineer",
            "email": "fresh@example.local",
            "password": PASSWORD,
            "role": "ENGINEER",
            "employee_id": "IT-99",
            "team": "IT",
            "phone": "123",
            "location": "Remote",
        },
    )
    assert r.status_code == 201, r.text
    uid = r.json()["id"]
    assert "password" not in r.text
    assert (
        c.patch(
            f"/api/v1/admin/engineers/{uid}",
            json={"capacity": 5, "skills": [1, 2], "available": True},
        ).status_code
        == 200
    )
    assert (
        c.post(
            "/api/v1/admin/users",
            json={
                "name": "Duplicate",
                "email": "fresh@example.local",
                "password": PASSWORD,
            },
        ).status_code
        == 409
    )
    assert "password_hash" not in c.get("/api/v1/admin/users").text
    assert c.patch("/api/v1/admin/users/1", json={"active": False}).status_code == 409
    assert c.patch("/api/v1/admin/users/1", json={"role": "USER"}).status_code == 409


def test_complete_lifecycle(env, ticket_payload):
    user = env["client"](4)
    t = create(env, ticket_payload, user)
    tid = t["id"]
    assert t["number"].startswith("D2C-")
    assert t["status"] == "ASSIGNED"
    assert t["assignee_id"] == 2
    eng = env["client"](1)
    assert eng.patch(f"/api/v1/tickets/{tid}", json={"status": "IN_PROGRESS"}).status_code == 200
    assert (
        eng.post(
            f"/api/v1/tickets/{tid}/comments", json={"body": "Investigating VPN routes"}
        ).status_code
        == 201
    )
    assert (
        eng.patch(f"/api/v1/tickets/{tid}", json={"status": "WAITING_FOR_USER"}).status_code == 200
    )
    assert (
        user.post(
            f"/api/v1/tickets/{tid}/comments", json={"body": "Confirmed the details"}
        ).status_code
        == 201
    )
    r = eng.patch(
        f"/api/v1/tickets/{tid}",
        json={"status": "RESOLVED", "resolution": "Corrected VPN routes"},
    )
    assert r.status_code == 200, r.text
    assert user.patch(f"/api/v1/tickets/{tid}", json={"status": "CLOSED"}).status_code == 200
    data = user.get(f"/api/v1/tickets/{tid}").json()
    assert data["ticket"]["resolution"] == "Corrected VPN routes"
    assert data["ticket"]["closed_at"]
    events = {e["action"] for e in data["activity"]}
    assert {
        "CREATE_TICKET",
        "TICKET_ASSIGNED",
        "STATUS_CHANGED",
        "COMMENT_ADDED",
        "TICKET_RESOLVED",
        "TICKET_CLOSED",
    } <= events
    r = user.patch(f"/api/v1/tickets/{tid}", json={"status": "REOPENED"})
    assert r.status_code == 200, r.text
    assert r.json()["resolved_at"] is None
    assert eng.get("/api/v1/notifications").json()["total"] >= 3
    for index in (0, 1, 4):
        assert env["client"](index).get("/api/v1/dashboard").status_code == 200


def test_scope_and_invalid_transitions(env, ticket_payload):
    t = create(env, ticket_payload)
    tid = t["id"]
    other = env["client"](5)
    eng = env["client"](2)
    user = env["client"](4)
    for c in (other, eng):
        assert c.get(f"/api/v1/tickets/{tid}").status_code == 404
        assert c.patch(f"/api/v1/tickets/{tid}", json={"status": "RESOLVED"}).status_code == 404
        assert (
            c.post(f"/api/v1/tickets/{tid}/comments", json={"body": "Unauthorized"}).status_code
            == 404
        )
        assert c.get("/api/v1/tickets").json()["total"] == 0
    assert (
        user.patch(
            f"/api/v1/tickets/{tid}", json={"status": "RESOLVED", "resolution": "bad"}
        ).status_code
        == 403
    )
    assert user.patch(f"/api/v1/tickets/{tid}", json={"status": "CLOSED"}).status_code == 409
    assert (
        user.post(
            f"/api/v1/tickets/{tid}/comments", json={"body": "secret", "internal": True}
        ).status_code
        == 403
    )
    assigned = env["client"](1)
    assert assigned.patch(f"/api/v1/tickets/{tid}", json={"status": "CLOSED"}).status_code == 409
    assert assigned.patch(f"/api/v1/tickets/{tid}", json={"status": "RESOLVED"}).status_code == 422
    assert (
        assigned.patch(f"/api/v1/tickets/{tid}", json={"priority": "CRITICAL"}).status_code == 403
    )
    assert user.patch(f"/api/v1/tickets/{tid}", json={"assignee_id": 3}).status_code == 422


def test_internal_comments_hidden(env, ticket_payload):
    t = create(env, ticket_payload)
    eng = env["client"](1)
    user = env["client"](4)
    eng.post(
        f"/api/v1/tickets/{t['id']}/comments",
        json={"body": "Private troubleshooting", "internal": True},
    )
    response = user.get(f"/api/v1/tickets/{t['id']}").json()
    assert not response["comments"]
    assert not any(e["action"] == "COMMENT_ADDED" for e in response["activity"])
    assert not any(
        n["event"] == "COMMENT_ADDED" for n in user.get("/api/v1/notifications").json()["items"]
    )


@pytest.mark.parametrize(
    "mode", ["no_skill", "capacity", "disabled", "unavailable", "disabled_rule"]
)
def test_assignment_exclusions(env, ticket_payload, mode):
    with env["db"]() as db:
        if mode == "no_skill":
            db.execute(delete(EngineerSkill))
        if mode == "disabled":
            db.execute(update(User).where(User.role == Role.ENGINEER).values(active=False))
        if mode == "unavailable":
            db.execute(update(Engineer).values(available=False))
        if mode == "disabled_rule":
            db.get(SystemSetting, "assignment").value = {"enabled": False}
        if mode == "capacity":
            for uid in (2, 3, 4):
                for j in range(2):
                    db.add(
                        Ticket(
                            number=f"busy-{uid}-{j}",
                            title="Busy ticket",
                            description="Existing",
                            requester_id=5,
                            assignee_id=uid,
                            status=TicketStatus.IN_PROGRESS,
                            category_id=1,
                        )
                    )
        db.commit()
    t = create(env, ticket_payload)
    assert t["assignee_id"] is None
    assert t["assignment_reason"]
    with env["db"]() as db:
        assert db.scalar(select(AuditLog).where(AuditLog.action == "ASSIGNMENT_REQUIRED"))


def test_balancing_and_round_robin(env, ticket_payload):
    c = env["client"](4)
    tickets = [create(env, ticket_payload, c) for _ in range(6)]
    assert [t["assignee_id"] for t in tickets] == [2, 3, 4, 2, 3, 4]
    assert create(env, ticket_payload, c)["assignee_id"] is None


def test_generalist_fallback_and_score(env, ticket_payload):
    with env["db"]() as db:
        db.get(SystemSetting, "assignment").value = {
            "enabled": True,
            "fallback": True,
            "strategy": "scored",
            "location_weight": 100,
            "team_weight": 0,
            "workload_weight": 0,
        }
        db.get(User, 2).location = "Remote"
        db.get(User, 4).location = "Remote"
        db.commit()
    t = create(env, {**ticket_payload, "category_id": 2})
    assert t["assignee_id"] == 3


def test_reassignment_and_capacity_guard(env, ticket_payload):
    t = create(env, ticket_payload)
    a = env["client"]()
    r = a.post(
        f"/api/v1/tickets/{t['id']}/assign",
        json={"engineer_id": 3, "reason": "Workload balancing"},
    )
    assert r.status_code == 200
    assert a.post(f"/api/v1/tickets/{t['id']}/assign", json={"engineer_id": 3}).status_code == 409
    assert a.patch("/api/v1/admin/users/3", json={"active": False}).status_code == 409
    with env["db"]() as db:
        e = db.scalar(select(AuditLog).where(AuditLog.action == "TICKET_REASSIGNED"))
        assert e.before["engineer_id"] == 2
        assert e.after["engineer_id"] == 3
        assert e.after["reason"] == "Workload balancing"
        assert e.actor_id == 1


def test_sla_and_notifications(env, ticket_payload):
    t = create(env, ticket_payload)
    with env["db"]() as db:
        ticket = db.get(Ticket, t["id"])
        assert round((ticket.sla_due_at - ticket.created_at).total_seconds() / 60) == 240
        ticket.sla_due_at = now() - timedelta(minutes=1)
        db.commit()
        sla_scan(db)
        sla_scan(db)
        assert (
            db.scalar(
                select(func.count())
                .select_from(Notification)
                .where(Notification.event == "SLA_BREACHED")
            )
            == 2
        )
    a = env["client"]()
    assert a.get("/api/v1/dashboard").json()["metrics"]["sla_breaches"] == 1
    assert a.get("/api/v1/tickets?sla=breached").json()["total"] == 1


def test_attachments(env, ticket_payload):
    t = create(env, ticket_payload)
    c = env["client"](4)
    base = f"/api/v1/tickets/{t['id']}/attachments"
    r = c.post(base, files={"file": ("../../log.txt", b"VPN error code 100", "text/plain")})
    assert r.status_code == 201, r.text
    assert r.json()["name"] == "log.txt"
    aid = r.json()["id"]
    assert c.get(base + "/" + str(aid)).content == b"VPN error code 100"
    assert env["client"](5).get(base + "/" + str(aid)).status_code == 404
    assert (
        c.post(
            base, files={"file": ("fake.png", b"<script>evil</script>", "image/png")}
        ).status_code
        == 422
    )
    assert c.post(base, files={"file": ("bad.html", b"<h1>x</h1>", "text/html")}).status_code == 422
    assert c.post(base, files={"file": ("empty.txt", b"", "text/plain")}).status_code == 422
    assert (
        c.post(
            base,
            files={"file": ("large.txt", b"a" * (10 * 1024 * 1024 + 1), "text/plain")},
        ).status_code
        == 413
    )
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("../evil.exe", "bad")
    assert (
        c.post(base, files={"file": ("bad.zip", archive.getvalue(), "application/zip")}).status_code
        == 422
    )


def test_audit_immutable_and_filtered(env, ticket_payload):
    t = create(env, ticket_payload)
    a = env["client"]()
    response = a.get(
        "/api/v1/admin/audit-logs",
        params={"ticket": t["number"], "sort": "oldest", "limit": 1},
    ).json()
    assert response["total"] >= 2
    assert len(response["items"]) == 1
    assert response["items"][0]["ip_address"]
    with env["db"]() as db:
        with pytest.raises(Exception):
            db.execute(text("UPDATE audit_logs SET action='TAMPERED'"))
            db.commit()
        db.rollback()
        with pytest.raises(Exception):
            db.execute(text("DELETE FROM audit_logs"))
            db.commit()


def test_search_filters_pagination_and_bulk(env, ticket_payload):
    c = env["client"](4)
    one = create(env, ticket_payload, c)
    two = create(
        env,
        {
            **ticket_payload,
            "title": "Laptop screen issue",
            "description": "Display is flickering",
            "category_id": 2,
        },
        c,
    )
    a = env["client"]()
    assert a.get("/api/v1/tickets?q=VPN").json()["total"] == 1
    assert a.get("/api/v1/tickets?q=E4").json()["total"] == 2
    assert a.get("/api/v1/tickets?category_id=2").json()["total"] == 1
    assert a.get("/api/v1/tickets?assignment=unassigned").json()["total"] == 1
    result = a.get("/api/v1/tickets?limit=1&offset=1").json()
    assert result["total"] == 2
    assert len(result["items"]) == 1
    assert a.get("/api/v1/tickets?limit=10000").status_code == 422
    assert (
        a.post(
            "/api/v1/tickets/bulk",
            json={
                "ids": [one["id"], two["id"]],
                "action": "priority",
                "priority": "CRITICAL",
            },
        ).status_code
        == 200
    )
    assert a.get("/api/v1/tickets?priority=CRITICAL").json()["total"] == 2
    assert a.get("/api/v1/tickets/export?ids=" + str(one["id"])).status_code == 200
    assert c.get("/api/v1/tickets/export?ids=" + str(one["id"])).status_code == 403


def test_configuration(env):
    a = env["client"]()
    r = a.post("/api/v1/admin/config/categories", json={"name": "Printer"})
    assert r.status_code == 201
    cid = r.json()["id"]
    assert (
        a.post(
            "/api/v1/admin/config/subcategories",
            json={"name": "Laser", "category_id": cid},
        ).status_code
        == 201
    )
    assert (
        a.put(
            "/api/v1/admin/sla/HIGH",
            json={"response_minutes": 15, "resolution_minutes": 120},
        ).status_code
        == 200
    )
    assert (
        a.put(
            "/api/v1/admin/sla/HIGH",
            json={"response_minutes": 0, "resolution_minutes": 120},
        ).status_code
        == 422
    )
    assert (
        a.put("/api/v1/admin/settings/assignment", json={"strategy": "random"}).status_code == 422
    )
    assert (
        a.put(
            "/api/v1/admin/settings/workflow",
            json={"reopen_days": 3, "labels": {"OPEN": "Received"}},
        ).status_code
        == 200
    )
    assert (
        a.put(
            "/api/v1/admin/settings/notifications",
            json={"enabled": True, "sla_warning_minutes": 45},
        ).status_code
        == 200
    )


def test_invalid_payload_and_soft_delete(env, ticket_payload):
    c = env["client"](4)
    assert c.post("/api/v1/tickets", json={**ticket_payload, "category_id": 999}).status_code == 422
    assert c.post("/api/v1/tickets", json={**ticket_payload, "requester_id": 1}).status_code == 422
    t = create(env, ticket_payload, c)
    a = env["client"]()
    assert a.delete(f"/api/v1/tickets/{t['id']}").status_code == 200
    assert a.get(f"/api/v1/tickets/{t['id']}").status_code == 404
    assert a.get("/api/v1/admin/audit-logs?ticket=" + t["number"]).json()["total"] > 0


def test_creation_retry_is_idempotent(env, ticket_payload):
    c = env["client"](4)
    headers = {"Idempotency-Key": "request-one"}
    first = c.post("/api/v1/tickets", json=ticket_payload, headers=headers)
    second = c.post("/api/v1/tickets", json=ticket_payload, headers=headers)
    assert first.status_code == second.status_code == 201
    assert first.json()["id"] == second.json()["id"]
    assert c.get("/api/v1/tickets").json()["total"] == 1
    assert (
        c.post(
            "/api/v1/tickets",
            json={**ticket_payload, "title": "Changed request"},
            headers=headers,
        ).status_code
        == 409
    )


def test_postgres_concurrent_assignment_respects_capacity(env, ticket_payload):
    if env["engine"].dialect.name != "postgresql":
        pytest.skip("PostgreSQL transaction-lock integration test")
    clients = [env["client"](4) for _ in range(8)]
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda c: c.post("/api/v1/tickets", json=ticket_payload), clients))
    assert all(r.status_code == 201 for r in results)
    tickets = [r.json() for r in results]
    assert len({t["number"] for t in tickets}) == 8
    counts = {uid: sum(t["assignee_id"] == uid for t in tickets) for uid in (2, 3, 4)}
    assert counts == {2: 2, 3: 2, 4: 2}
    assert sum(t["assignee_id"] is None for t in tickets) == 2


def test_reopen_window_and_disabled_login(env, ticket_payload):
    t = create(env, ticket_payload)
    admin = env["client"]()
    user = env["client"](4)
    assert (
        admin.patch(
            f"/api/v1/tickets/{t['id']}",
            json={"status": "RESOLVED", "resolution": "Fixed"},
        ).status_code
        == 200
    )
    with env["db"]() as db:
        db.get(Ticket, t["id"]).resolved_at = now() - timedelta(days=8)
        db.commit()
    assert user.patch(f"/api/v1/tickets/{t['id']}", json={"status": "REOPENED"}).status_code == 409
    assert admin.patch("/api/v1/admin/users/6", json={"active": False}).status_code == 200
    c = env["client"](login=False)
    assert (
        c.post(
            "/api/v1/auth/login",
            json={"email": "p5@example.local", "password": PASSWORD},
        ).status_code
        == 401
    )


def test_engineer_can_submit_personal_request_without_elevated_rights(env, ticket_payload):
    engineer = env["client"](1)
    with env["db"]() as db:
        db.get(Engineer, 2).available = False
        db.commit()
    t = create(env, ticket_payload, engineer)
    assert t["assignee_id"] == 3
    assert engineer.get(f"/api/v1/tickets/{t['id']}").status_code == 200
    assert (
        engineer.patch(
            f"/api/v1/tickets/{t['id']}", json={"status": "RESOLVED", "resolution": "Bypass"}
        ).status_code
        == 403
    )
    assigned = env["client"](2)
    assigned.post(
        f"/api/v1/tickets/{t['id']}/comments", json={"body": "Private note", "internal": True}
    )
    assert engineer.get(f"/api/v1/tickets/{t['id']}").json()["comments"] == []
    assert (
        assigned.patch(
            f"/api/v1/tickets/{t['id']}", json={"status": "RESOLVED", "resolution": "Fixed"}
        ).status_code
        == 200
    )
    assert (
        engineer.patch(f"/api/v1/tickets/{t['id']}", json={"status": "CLOSED"}).status_code == 200
    )


def test_history_pagination(env, ticket_payload):
    t = create(env, ticket_payload)
    user = env["client"](4)
    with env["db"]() as db:
        db.add_all(
            [
                TicketComment(ticket_id=t["id"], author_id=5, body=f"Comment {i}", internal=False)
                for i in range(105)
            ]
        )
        db.commit()
    detail = user.get(f"/api/v1/tickets/{t['id']}").json()
    assert len(detail["comments"]) == 100 and detail["comment_total"] == 105
    remaining = user.get(f"/api/v1/tickets/{t['id']}/conversation?offset=100").json()
    assert len(remaining["items"]) == 5
    assert user.get(f"/api/v1/tickets/{t['id']}/activity?limit=1").json()["total"] >= 2


def test_configured_round_robin(env, ticket_payload):
    with env["db"]() as db:
        db.get(SystemSetting, "assignment").value = {
            "enabled": True,
            "strategy": "round_robin",
            "fallback": False,
        }
        db.get(Engineer, 2).last_assigned_at = now()
        db.get(Engineer, 3).last_assigned_at = now() - timedelta(days=1)
        db.get(Engineer, 4).last_assigned_at = now() - timedelta(days=2)
        db.commit()
    assert create(env, ticket_payload)["assignee_id"] == 4


def test_bulk_resolution_is_atomic(env, ticket_payload):
    c = env["client"](4)
    a = create(env, ticket_payload, c)
    b = create(env, ticket_payload, c)
    admin = env["client"]()
    response = admin.post(
        "/api/v1/tickets/bulk",
        json={
            "ids": [a["id"], b["id"]],
            "action": "status",
            "status": "RESOLVED",
            "resolution": "Common network fix verified",
        },
    )
    assert response.status_code == 200, response.text
    assert c.get("/api/v1/tickets?status=RESOLVED").json()["total"] == 2
    response = admin.post(
        "/api/v1/tickets/bulk",
        json={"ids": [a["id"], 999999], "action": "priority", "priority": "CRITICAL"},
    )
    assert response.status_code == 404
    assert c.get(f"/api/v1/tickets/{a['id']}").json()["ticket"]["priority"] == "HIGH"


def test_preserved_asset_and_knowledge_apis(env):
    admin = env["client"]()
    asset = admin.post("/api/v1/assets", json={"asset_type": "Laptop", "serial_number": "SERIAL-1"})
    assert asset.status_code == 201, asset.text
    aid = asset.json()["id"]
    assert admin.post(f"/api/v1/assets/{aid}/assign", json={"user_id": 5}).status_code == 200
    user = env["client"](4)
    assert len(user.get("/api/v1/assets").json()) == 1
    assert len(user.get(f"/api/v1/assets/{aid}/history").json()) == 2
    assert env["client"](5).get(f"/api/v1/assets/{aid}/history").status_code == 404
    assert (
        admin.post(
            "/api/v1/knowledge",
            json={
                "title": "Network troubleshooting",
                "category": "Network",
                "content": "Restart the approved VPN client.",
                "published": True,
            },
        ).status_code
        == 201
    )
    assert len(user.get("/api/v1/knowledge?q=VPN").json()) == 1


def test_sla_approaching_and_notification_permissions(env, ticket_payload):
    t = create(env, ticket_payload)
    with env["db"]() as db:
        db.get(Ticket, t["id"]).sla_due_at = now() + timedelta(minutes=30)
        db.commit()
        sla_scan(db)
        sla_scan(db)
        assert (
            db.scalar(
                select(func.count())
                .select_from(Notification)
                .where(Notification.event == "SLA_APPROACHING")
            )
            == 2
        )
    user = env["client"](4)
    notes = user.get("/api/v1/notifications").json()
    nid = notes["items"][0]["id"]
    assert env["client"](5).patch(f"/api/v1/notifications/{nid}").status_code == 404
    assert user.patch(f"/api/v1/notifications/{nid}").status_code == 200
    assert user.post("/api/v1/notifications/read-all").status_code == 200
    assert user.get("/api/v1/notifications").json()["unread"] == 0


def test_authentication_ip_rate_limit(env):
    c = env["client"](login=False)
    for i in range(30):
        assert (
            c.post(
                "/api/v1/auth/login",
                json={"email": f"unknown{i}@example.local", "password": "unknown"},
            ).status_code
            == 401
        )
    assert (
        c.post(
            "/api/v1/auth/login", json={"email": "p0@example.local", "password": PASSWORD}
        ).status_code
        == 429
    )


def test_null_and_blank_required_fields(env, ticket_payload):
    c = env["client"](4)
    assert c.post("/api/v1/tickets", json={**ticket_payload, "title": "   "}).status_code == 422
    admin = env["client"]()
    assert admin.patch("/api/v1/admin/users/5", json={"role": None}).status_code == 422


def test_profile_edit_preserves_sessions_and_legacy_role_filter(env):
    admin = env["client"]()
    response = admin.patch(
        "/api/v1/admin/users/1",
        json={"name": "Updated Administrator", "role": "ADMIN", "active": True},
    )
    assert response.status_code == 200
    assert admin.get("/api/v1/me").status_code == 200
    with env["db"]() as db:
        db.get(User, 5).role = Role.EMPLOYEE
        db.commit()
    assert admin.get("/api/v1/admin/users?role=USER").json()["total"] == 2


def test_successful_logins_do_not_throttle_shared_office_ip(env):
    client = env["client"](login=False)
    for _ in range(35):
        response = client.post(
            "/api/v1/auth/login", json={"email": "p4@example.local", "password": PASSWORD}
        )
        assert response.status_code == 200
