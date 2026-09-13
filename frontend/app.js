import { api, send, state } from "./api.js";
import {
  esc,
  admin,
  engineer,
  toast,
  loading,
  errorView,
  empty,
  date,
  field,
} from "./ui.js";
import { dashboardPage } from "./dashboard.js";
import { ticketsPage, createPage, detailPage } from "./tickets.js";
import { usersPage, engineersPage, configPage, auditPage } from "./admin.js";
import { engineerActivityPage } from "./engineer-activity.js";
const app = document.querySelector("#app");
let generation = 0;
document.body.classList.toggle(
  "dark",
  localStorage.getItem("d2c-theme") === "dark",
);
function nav(href, text, icon) {
  return `<a class="nav-item" href="#/${href}" data-nav="${href.split("?")[0]}"><span class="nav-icon">${icon}</span>${text}</a>`;
}
function shell() {
  app.innerHTML = `<div class="app-layout"><aside class="sidebar"><div class="brand"><strong>SAMSUNG</strong><span class="divider"></span><span>D2C · SERVICE DESK</span></div><div class="nav-label">WORKSPACE</div>${nav("dashboard", "Overview", "◫")}${nav("tickets", "Tickets", "▤")}${nav("tickets?mine=true", "My tickets", "▣")}${admin() ? nav("tickets?assignment=unassigned", "Unassigned", "◷") : ""}${nav("create", "Create ticket", "＋")}${nav("knowledge", "Knowledge base", "▥")}${nav("reports", "Analytics", "▥")}<div class="nav-label">${admin() ? "ADMIN CONSOLE" : "ACCOUNT"}</div>${admin() ? nav("users", "Users & accounts", "♧") + nav("engineers", "Engineers", "⚙") + nav("configuration", "Configuration", "☷") + nav("audit", "Audit logs", "◴") + nav("engineer-activity", "Engineer activity", "▤") : ""}${nav("notifications", "Notifications", "♧")}${nav("settings", "My settings", "⚙")}<div class="sidebar-footer">SAMSUNG D2C<br>Internal IT operations<br><span>Connected. Supported. Productive.</span></div></aside><div class="main-area"><header class="topbar"><button class="mobile-menu icon-button" aria-label="Open navigation">☰</button><form class="global-search"><input aria-label="Search tickets" placeholder="Search tickets, people, and more…"></form><div class="top-actions"><button class="icon-button" id="theme" aria-label="Toggle dark mode">◐</button><a class="notification-link" href="#/notifications" aria-label="Notifications">♧<span id="notification-count" class="count" hidden></span></a><div class="profile"><div class="avatar">${esc(
    state.user.name
      .split(" ")
      .map((s) => s[0])
      .slice(0, 2)
      .join(""),
  )}</div><div><strong>${esc(state.user.name)}</strong><small>${admin() ? "Administrator" : engineer() ? "IT Engineer" : "Employee"}</small></div></div><button class="secondary" id="logout">Sign out</button></div></header><main id="content" class="content"></main></div></div>`;
  document.querySelector("#theme").onclick = () => {
    document.body.classList.toggle("dark");
    localStorage.setItem(
      "d2c-theme",
      document.body.classList.contains("dark") ? "dark" : "light",
    );
  };
  document.querySelector("#logout").onclick = async () => {
    try {
      await send("/auth/logout");
      state.user = null;
      login();
    } catch (e) {
      toast(e.message, true);
    }
  };
  document.querySelector(".global-search").onsubmit = (e) => {
    e.preventDefault();
    location.hash =
      "/tickets?q=" + encodeURIComponent(e.target.querySelector("input").value);
  };
  document.querySelector(".mobile-menu").onclick = () =>
    document.querySelector(".sidebar").classList.toggle("open");
  document.querySelector(".sidebar").onclick = (e) => {
    if (e.target.closest("a"))
      document.querySelector(".sidebar").classList.remove("open");
  };
  refreshNotifications();
}
async function refreshNotifications() {
  if (!state.user) return;
  try {
    const n = await api("/notifications?limit=1");
    const el = document.querySelector("#notification-count");
    if (el) {
      el.hidden = !n.unread;
      el.textContent = n.unread > 99 ? "99+" : n.unread;
    }
  } catch {}
}
setInterval(refreshNotifications, 60000);
function login(message = "") {
  app.innerHTML = `<div class="login-layout"><section class="login-story"><div class="brand"><strong>SAMSUNG</strong><span class="divider"></span><span>D2C · SERVICE DESK</span></div><div><h1>Great work starts<br>with great support.</h1><p>Your dedicated IT workspace. Get the help you need, stay connected, and keep moving forward.</p><div class="login-feature"><span>◈</span>One place for every IT request</div><div class="login-feature"><span>◷</span>Clear updates, from request to resolution</div></div><footer><small style="color:#a6bbdf">SAMSUNG D2C · INTERNAL IT OPERATIONS</small></footer></section><section class="login-main"><form class="login-card"><div class="eyebrow">Welcome to your service desk</div><h2>Sign in to your workspace</h2><p>Use your work account to continue.</p>${field("email", "Work email", "", "email", 'required autocomplete="username" placeholder="you@company.com"')}${field("password", "Password", "", "password", 'required autocomplete="current-password" placeholder="Enter your password"')}<p class="form-error" role="alert">${esc(message)}</p><button type="submit">Sign in →</button><p class="login-note">Your session stays signed in for its configured duration.<br>Need access or a password reset? Contact your IT administrator.</p></form></section></div>`;
  document.querySelector(".login-card").onsubmit = async (e) => {
    e.preventDefault();
    const button = e.submitter;
    button.disabled = true;
    button.textContent = "Signing in…";
    try {
      const data = await send(
        "/auth/login",
        Object.fromEntries(new FormData(e.target)),
      );
      state.user = data.user;
      state.csrf = data.csrf_token;
      state.config = await api("/configuration");
      shell();
      location.hash = "/dashboard";
      await route();
    } catch (err) {
      document.querySelector(".form-error").textContent = err.message;
      button.disabled = false;
      button.textContent = "Sign in →";
    }
  };
}
async function notifications(target) {
  let offset = 0;
  async function load() {
    const data = await api("/notifications?offset=" + offset);
    target.innerHTML = `<div class="page-head"><div><div class="eyebrow">Stay in the loop</div><h1>Notifications</h1><p>${data.unread} unread updates</p></div><button class="secondary" id="read-all">Mark all as read</button></div><div class="card">${data.items.length ? data.items.map((n) => `<div class="notification ${n.read ? "" : "unread"}"><div class="avatar">${n.event.includes("SLA") ? "◷" : "▤"}</div><div class="body"><strong>${esc(n.event.replaceAll("_", " "))}</strong><p>${esc(n.message)}</p><small>${date(n.created_at)}</small></div><button class="secondary" data-notification="${n.id}" data-ticket="${n.ticket_id}">View ticket →</button></div>`).join("") : empty("You’re all caught up", "Ticket updates and assignments will appear here.")}<div id="pagination" class="pagination"></div></div>`;
    target.querySelector("#read-all").onclick = async () => {
      await send("/notifications/read-all");
      toast("All notifications marked as read");
      load();
      refreshNotifications();
    };
    target.querySelectorAll("[data-notification]").forEach(
      (b) =>
        (b.onclick = async () => {
          await send("/notifications/" + b.dataset.notification, {}, "PATCH");
          location.hash = "/tickets/" + b.dataset.ticket;
          refreshNotifications();
        }),
    );
    const { pager } = await import("./ui.js");
    pager(
      data.total,
      offset,
      25,
      (n) => {
        offset = n;
        load();
      },
      target,
    );
  }
  await load();
}
async function knowledge(target) {
  const data = await api("/knowledge");
  target.innerHTML = `<div class="page-head"><div><div class="eyebrow">Self-service support</div><h1>Knowledge base</h1><p>Practical guidance from your IT team.</p></div>${admin() || engineer() ? '<button id="new-article">＋ New article</button>' : ""}</div><div class="toolbar"><input id="kb-search" placeholder="Search articles…" aria-label="Search articles"></div><div id="articles"></div>`;
  const render = (q) =>
    (target.querySelector("#articles").innerHTML =
      data
        .filter((a) =>
          (a.title + a.content).toLowerCase().includes(q.toLowerCase()),
        )
        .map(
          (a) =>
            `<article class="card"><div class="eyebrow">${esc(a.category)}</div><h2>${esc(a.title)}</h2><p class="description">${esc(a.content)}</p><small>Updated ${date(a.updated_at)}</small></article>`,
        )
        .join("") || empty("No articles found"));
  render("");
  target.querySelector("#kb-search").oninput = (e) => render(e.target.value);
  if (target.querySelector("#new-article"))
    target.querySelector("#new-article").onclick = async () => {
      const { modal } = await import("./ui.js");
      modal(
        "Publish knowledge article",
        `${field("title", "Title", "", "text", 'required minlength="3"')}${field("category", "Category", "", "text", "required")}<label>Content<textarea name="content" required></textarea></label>`,
        async (fd) => {
          await send("/knowledge", {
            ...Object.fromEntries(fd),
            published: true,
          });
          toast("Article published");
          knowledge(target);
        },
        "Publish article",
      );
    };
}
function settings(target) {
  target.innerHTML = `<div class="page-head"><div><div class="eyebrow">Account preferences</div><h1>My settings</h1><p>Manage your password and workspace appearance.</p></div></div><div class="grid-equal"><section class="card"><h2>Profile</h2>${["name", "email", "employee_id", "department", "team", "location", "role", "last_login"].map((k) => `<div class="metric-inline"><span>${esc(k.replaceAll("_", " "))}</span><strong>${esc(k === "last_login" ? date(state.user[k]) : state.user[k] || "—")}</strong></div>`).join("")}<p class="muted" style="margin-top:20px">Contact an administrator to update account details.</p></section><form id="password-form" class="card"><h2>Change password</h2>${field("current_password", "Current password", "", "password", 'required autocomplete="current-password"')}${field("password", "New password", "", "password", 'required minlength="12" maxlength="128" autocomplete="new-password"')}<small>Use at least 12 characters. Changing your password signs out all sessions.</small><p class="form-error" role="alert"></p><button type="submit">Update password</button></form></div>`;
  target.querySelector("form").onsubmit = async (e) => {
    e.preventDefault();
    e.submitter.disabled = true;
    try {
      await send("/auth/password", Object.fromEntries(new FormData(e.target)));
      state.user = null;
      login("Password changed. Sign in with your new password.");
    } catch (err) {
      target.querySelector(".form-error").textContent = err.message;
      e.submitter.disabled = false;
    }
  };
}
async function route() {
  if (!state.user) return;
  const id = ++generation;
  const [path, query = ""] = (location.hash.slice(1) || "/dashboard").split(
    "?",
  );
  const previous = document.querySelector("#content");
  const target = document.createElement("main");
  target.id = "content";
  target.className = "content";
  previous.replaceWith(target);
  target.innerHTML = loading();
  document
    .querySelectorAll("[data-nav]")
    .forEach((a) =>
      a.classList.toggle(
        "active",
        a.getAttribute("href") === location.hash ||
          (!location.hash && a.dataset.nav === "dashboard"),
      ),
    );
  try {
    if (
      ["/users", "/engineers", "/configuration", "/audit", "/engineer-activity"].includes(path) &&
      !admin()
    )
      throw new Error("Administrator access is required.");
    if (path === "/dashboard" || path === "/reports")
      await dashboardPage(target, path === "/reports");
    else if (path === "/tickets")
      await ticketsPage(target, new URLSearchParams(query));
    else if (path === "/create") await createPage(target);
    else if (/^\/tickets\/\d+$/.test(path))
      await detailPage(target, Number(path.split("/")[2]));
    else if (path === "/users") await usersPage(target);
    else if (path === "/engineers") await engineersPage(target);
    else if (path === "/configuration") await configPage(target);
    else if (path === "/engineer-activity") await engineerActivityPage(target);
    else if (path === "/audit") await auditPage(target);
    else if (path === "/notifications") await notifications(target);
    else if (path === "/knowledge") await knowledge(target);
    else if (path === "/settings") settings(target);
    else
      target.innerHTML = empty(
        "Page not found",
        "Choose a destination from the navigation.",
      );
  } catch (err) {
    if (id === generation) {
      target.innerHTML = errorView(err);
      target.querySelector("#retry").onclick = route;
    }
  }
}
window.addEventListener("hashchange", route);
window.addEventListener("session-expired", () => {
  state.user = null;
  login("Your session expired. Please sign in again.");
});
window.addEventListener("unhandledrejection", (e) => {
  toast(e.reason?.message || "An action failed. Please try again.", true);
  e.preventDefault();
});
try {
  const data = await api("/auth/me");
  state.user = data.user;
  state.csrf = data.csrf_token;
  state.config = await api("/configuration");
  shell();
  await route();
} catch {
  login();
}
