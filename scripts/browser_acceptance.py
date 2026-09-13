"""Live Chromium acceptance. Run against a seeded local or Docker deployment."""

import json
import os
import re
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

URL = os.environ.get("APP_URL", "http://127.0.0.1:8000")
PASSWORD = os.environ.get("SEED_PASSWORD", "D2C-Local-Only-2026!")
Path("artifacts").mkdir(exist_ok=True)
with sync_playwright() as p:
    browser = p.chromium.launch(
        executable_path=os.environ.get(
            "CHROME_PATH",
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        ),
        headless=True,
    )
    context = browser.new_context(viewport={"width": 1440, "height": 1000}, reduced_motion="reduce")
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))

    def login(email):
        page.goto(URL)
        page.get_by_label("Work email").fill(email)
        page.get_by_label("Password", exact=True).fill(PASSWORD)
        page.get_by_role("button", name="Sign in →").click()
        expect(page.get_by_role("heading", name="Overview", exact=True)).to_be_visible()

    def route(path, heading):
        page.goto(URL + "/#/" + path)
        expect(page.get_by_role("heading", name=heading, exact=True)).to_be_visible()

    login("admin@example.local")
    page.screenshot(path="artifacts/admin-dashboard-light.png", full_page=True)
    page.get_by_role("button", name="Toggle dark mode").click()
    page.reload()
    expect(page.locator("body")).to_have_class(re.compile("dark"))
    expect(page.get_by_role("heading", name="Overview", exact=True)).to_be_visible()
    page.screenshot(path="artifacts/admin-dashboard-dark.png", full_page=True)
    page.get_by_role("button", name="Toggle dark mode").click()
    route("users", "Users & accounts")
    page.locator("tbody tr").filter(has_text="admin@example.local").get_by_role(
        "button", name="Edit", exact=True
    ).click()
    page.locator("dialog").get_by_role("button", name="Save changes", exact=True).click()
    expect(page.locator("dialog")).not_to_be_visible()
    expect(page.get_by_role("heading", name="Users & accounts", exact=True)).to_be_visible()
    page.get_by_role("button", name="Create user").click()
    dialog = page.locator("dialog")
    dialog.get_by_label("Full name").fill("Browser Test User")
    dialog.get_by_label("Work email").fill(
        "browser" + str(__import__("time").time_ns()) + "@example.local"
    )
    dialog.get_by_label("Initial password").fill(PASSWORD)
    dialog.get_by_role("button", name="Create user", exact=True).click()
    expect(dialog).not_to_be_visible()
    route("engineers", "Engineer management")
    page.get_by_role("button", name="Configure", exact=True).first.click()
    expect(page.locator("dialog")).to_be_visible()
    page.locator("dialog").get_by_role("button", name="Cancel", exact=True).click()
    route("configuration", "Service configuration")
    for tab in [
        "Sla",
        "Assignment",
        "Workflow",
        "Notifications",
        "Teams",
        "Locations",
        "Subcategories",
    ]:
        page.get_by_role("button", name=tab, exact=True).click()
        expect(page.locator("#config-body")).not_to_be_empty()
    route("audit", "Audit logs")
    page.get_by_role("button", name="View event").first.click()
    expect(page.locator("dialog")).to_be_visible()
    page.locator("dialog").get_by_role("button", name="Done", exact=True).click()
    route("reports", "Service analytics")
    page.screenshot(path="artifacts/analytics.png", full_page=True)
    page.get_by_role("button", name="Sign out", exact=True).click()
    expect(page.get_by_role("heading", name="Sign in to your workspace")).to_be_visible()
    login("user1@example.local")
    route("create", "Create a ticket")
    page.get_by_label("Ticket title *").fill("Browser acceptance: VPN evidence")
    page.locator('textarea[name="description"]').fill(
        "VPN connection is unstable. **Please investigate.**"
    )
    page.locator('select[name="category_id"]').select_option(label="VPN")
    page.locator("#files").set_input_files(
        {
            "name": "diagnostic.txt",
            "mimeType": "text/plain",
            "buffer": b"VPN handshake failed",
        }
    )
    page.screenshot(path="artifacts/create-ticket.png", full_page=True)
    page.get_by_role("button", name="Submit ticket").click()
    expect(
        page.get_by_role("heading", name="Browser acceptance: VPN evidence", exact=True)
    ).to_be_visible()
    ticket_url = page.url
    tid = int(ticket_url.rsplit("/", 1)[-1])
    expect(page.get_by_role("link", name=re.compile("diagnostic.txt"))).to_be_visible()
    page.locator("#comment-form textarea").fill("I am available for troubleshooting.")
    page.get_by_role("button", name="Send comment", exact=True).click()
    expect(page.get_by_text("I am available for troubleshooting.", exact=True)).to_be_visible()
    data = page.evaluate('async id => (await fetch("/api/v1/tickets/"+id)).json()', tid)
    assigned = data["people"][str(data["ticket"]["assignee_id"])]["email"]
    page.get_by_role("button", name="Sign out", exact=True).click()
    login(assigned)
    page.goto(ticket_url)
    expect(
        page.get_by_role("heading", name="Browser acceptance: VPN evidence", exact=True)
    ).to_be_visible()
    page.locator("#status-form select").select_option("IN_PROGRESS")
    page.get_by_role("button", name="Update status", exact=True).click()
    page.locator("dialog").get_by_role("button", name="Confirm", exact=True).click()
    expect(page.locator("dialog")).not_to_be_visible()
    page.locator("#status-form select").select_option("RESOLVED")
    page.locator("#status-form textarea").fill(
        "Updated VPN profile and verified stable connectivity."
    )
    page.get_by_role("button", name="Update status", exact=True).click()
    page.locator("dialog").get_by_role("button", name="Confirm", exact=True).click()
    expect(page.locator("dialog")).not_to_be_visible()
    expect(page.get_by_role("heading", name="Resolution", exact=True)).to_be_visible()
    page.screenshot(path="artifacts/ticket-detail.png", full_page=True)
    page.get_by_role("button", name="Sign out", exact=True).click()
    login("user1@example.local")
    page.goto(ticket_url)
    expect(page.get_by_role("heading", name="Resolution", exact=True)).to_be_visible()
    page.locator("#status-form select").select_option("CLOSED")
    page.get_by_role("button", name="Update status", exact=True).click()
    page.locator("dialog").get_by_role("button", name="Confirm", exact=True).click()
    expect(page.locator("dialog")).not_to_be_visible()
    expect(page.locator(".detail-meta")).to_contain_text("Closed")
    route("notifications", "Notifications")
    page.get_by_role("button", name="Mark all as read").click()
    route("dashboard", "Overview")
    page.set_viewport_size({"width": 390, "height": 844})
    page.screenshot(path="artifacts/mobile-dashboard.png", full_page=True)
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), (
        "Mobile overflow"
    )
    page.get_by_role("button", name="Open navigation").click()
    expect(page.locator(".sidebar")).to_have_class(re.compile("open"))
    page.goto(URL + "/api/docs")
    expect(page.get_by_role("heading", name="Service Desk API", exact=True)).to_be_visible()
    expect(page.locator("#endpoints details").first).to_be_visible()
    page.get_by_label("Find an endpoint").fill("attachments")
    expect(page.locator("#endpoints details")).to_have_count(2)
    assert not errors, errors
    Path("artifacts/browser-result.json").write_text(
        json.dumps(
            {
                "url": URL,
                "ticket_id": tid,
                "engineer": assigned,
                "javascript_errors": errors,
                "result": "passed",
            },
            indent=2,
        )
    )
    print("Browser acceptance passed:", tid, assigned)
    browser.close()
