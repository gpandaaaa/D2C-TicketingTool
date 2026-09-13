import { api, send, state } from "./api.js";
import {
  esc,
  label,
  badge,
  date,
  empty,
  field,
  options,
  option,
  modal,
  confirmAction,
  toast,
  pager,
  debounce,
} from "./ui.js";
const roles = ["ADMIN", "ENGINEER", "USER"];
function userForm(u = {}) {
  const offeredRoles = [
    ...roles,
    ...(u.role && !roles.includes(u.role) ? [u.role] : []),
  ];
  return `<div class="form-grid">${field("name", "Full name", u.name || "", "text", 'required minlength="2" maxlength="160"')}${!u.id ? field("email", "Work email", "", "email", "required") : field("email", "Work email", u.email || "", "email", "required") + field("employee_id", "Employee ID", u.employee_id || "")}${!u.id ? field("employee_id", "Employee ID", "") : ""}<label>Role<select name="role">${offeredRoles.map((r) => option(r, label(r), u.role || "USER")).join("")}</select></label>${field("department", "Department", u.department || "")}<label>Team<select name="team">${option("", "No team")}${u.team && !state.config.teams.some((t) => t.active && t.name === u.team) ? option(u.team, u.team, u.team) : ""}${state.config.teams
    .filter((t) => t.active)
    .map((t) => option(t.name, t.name, u.team))
    .join(
      "",
    )}</select></label><label>Location<select name="location">${option("", "No location")}${u.location && !state.config.locations.some((l) => l.active && l.name === u.location) ? option(u.location, u.location, u.location) : ""}${state.config.locations
    .filter((l) => l.active)
    .map((l) => option(l.name, l.name, u.location))
    .join(
      "",
    )}</select></label>${field("phone", "Phone", u.phone || "", "tel")}${!u.id ? field("password", "Initial password", "", "password", 'required minlength="12" maxlength="128" autocomplete="new-password"') : ""}</div>${u.id ? `<label class="check-label"><input type="checkbox" name="active" ${u.active ? "checked" : ""}>Account enabled</label>` : ""}`;
}
export async function usersPage(target) {
  let offset = 0,
    items = [];
  target.innerHTML = `<div class="page-head"><div><div class="eyebrow">Admin console</div><h1>Users & accounts</h1><p>Manage access, roles, and employee profiles.</p></div><button id="new-user">＋ Create user</button></div><div class="card"><div class="toolbar"><input id="user-search" placeholder="Search name, email, employee ID…" aria-label="Search users"><select id="role-filter" aria-label="Filter role">${option("", "All roles")}${roles.map((r) => option(r, label(r))).join("")}</select><select id="active-filter" aria-label="Filter account status">${option("", "All accounts")}${option("true", "Enabled")}${option("false", "Disabled")}</select></div><div id="user-results"></div><div id="pagination" class="pagination"></div></div>`;
  async function load() {
    const q = target.querySelector("#user-search").value,
      role = target.querySelector("#role-filter").value,
      active = target.querySelector("#active-filter").value;
    const data = await api(
      `/admin/users?offset=${offset}&q=${encodeURIComponent(q)}${role ? "&role=" + role : ""}${active ? "&active=" + active : ""}`,
    );
    items = data.items;
    target.querySelector("#user-results").innerHTML = items.length
      ? `<div class="table-wrap"><table><thead><tr><th>Employee</th><th>Role</th><th>Department / team</th><th>Location</th><th>Status</th><th>Last login</th><th>Actions</th></tr></thead><tbody>${items.map((u) => `<tr><td><strong>${esc(u.name)}</strong><br><small>${esc(u.email)} · ${esc(u.employee_id || "—")}</small></td><td>${badge(u.role)}</td><td>${esc(u.department || "—")}<br><small>${esc(u.team || "")}</small></td><td>${esc(u.location || "—")}</td><td>${badge(u.active ? "ENABLED" : "DISABLED", u.active ? "resolved" : "critical")}</td><td>${date(u.last_login)}</td><td><button class="link-button" data-edit="${u.id}">Edit</button> · <button class="link-button" data-password="${u.id}">Reset password</button><br><a href="#/tickets?requester_id=${u.id}">Tickets</a> · <button class="link-button" data-activity="${u.id}">Activity</button></td></tr>`).join("")}</tbody></table></div>`
      : empty("No users found");
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
    target.querySelectorAll("[data-edit]").forEach(
      (b) =>
        (b.onclick = () => {
          const u = items.find((u) => u.id === +b.dataset.edit);
          modal("Edit " + u.name, userForm(u), async (fd) => {
            const values = Object.fromEntries(fd);
            values.active = fd.has("active");
            await send("/admin/users/" + u.id, values, "PATCH");
            toast("User updated");
            await load();
          });
        }),
    );
    target.querySelectorAll("[data-password]").forEach(
      (b) =>
        (b.onclick = () =>
          modal(
            "Reset user password",
            field(
              "password",
              "New password",
              "",
              "password",
              'required minlength="12" maxlength="128"',
            ) +
              '<p class="muted">This signs the user out of all sessions. Share the new password through your approved secure channel.</p>',
            async (fd) => {
              await send("/admin/users/" + b.dataset.password + "/password", {
                password: fd.get("password"),
              });
              toast("Password reset");
            },
          )),
    );
    target.querySelectorAll("[data-activity]").forEach(
      (b) =>
        (b.onclick = async () => {
          const events = await api(
            "/admin/audit-logs?actor_id=" + b.dataset.activity + "&limit=25",
          );
          modal(
            "Recent user activity",
            events.items
              .map(
                (e) =>
                  `<div class="event"><strong>${esc(label(e.action))}</strong><small>${date(e.created_at)} · ${esc(e.entity)} ${esc(e.entity_id)}</small></div>`,
              )
              .join("") || empty("No activity yet"),
            async () => {},
            "Done",
          );
        }),
    );
  }
  target.querySelector("#new-user").onclick = () =>
    modal(
      "Create user",
      userForm(),
      async (fd) => {
        const values = Object.fromEntries(fd);
        values.employee_id = values.employee_id || null;
        await send("/admin/users", values);
        toast("User created");
        await load();
      },
      "Create user",
    );
  target.querySelector("#user-search").oninput = debounce(() => {
    offset = 0;
    load();
  });
  for (const id of ["role-filter", "active-filter"])
    target.querySelector("#" + id).onchange = () => {
      offset = 0;
      load();
    };
  await load();
}
export async function engineersPage(target) {
  let offset = 0;
  target.innerHTML = `<div class="page-head"><div><div class="eyebrow">Admin console</div><h1>Engineer management</h1><p>Balance workloads, configure skills, and manage availability.</p></div><button id="new-engineer">＋ Create engineer</button></div><div class="card"><div class="toolbar"><input id="engineer-search" aria-label="Search engineers" placeholder="Search engineers…"></div><div id="engineer-results"></div><div id="pagination" class="pagination"></div></div>`;
  async function load() {
    const data = await api(
      "/admin/engineers?offset=" +
        offset +
        "&limit=25&q=" +
        encodeURIComponent(target.querySelector("#engineer-search").value),
    );
    target.querySelector("#engineer-results").innerHTML = data.items.length
      ? `<div class="table-wrap"><table><thead><tr><th>Engineer</th><th>Skills</th><th>Availability</th><th>Workload</th><th>SLA breaches</th><th>Resolved</th><th>Avg. resolution</th><th>Actions</th></tr></thead><tbody>${data.items.map((e) => `<tr><td><strong>${esc(e.name)}</strong><br><small>${esc(e.team || "No team")} · ${esc(e.location || "No location")}</small></td><td style="white-space:normal;min-width:150px;max-width:250px">${e.skills.map((id) => `<span class="badge" style="margin:2px">${esc(state.config.categories.find((c) => c.id === id)?.name)}</span>`).join("") || "<small>No skills configured</small>"}</td><td>${badge(e.active && e.available ? "AVAILABLE" : "UNAVAILABLE", e.active && e.available ? "resolved" : "pending")}</td><td>${e.active_tickets} / ${e.capacity}<div class="bar-track" style="width:100px;margin:7px 0"><div class="bar ${e.utilization > 80 ? "red" : ""}" style="width:${Math.min(100, e.utilization)}%"></div></div><small>${e.utilization}% utilized</small></td><td>${e.sla_breaches}</td><td>${e.resolved_tickets}</td><td>${(e.average_resolution_hours || 0).toFixed(1)}h</td><td><button class="link-button" data-engineer="${e.id}">Configure</button><br><a href="#/tickets?assignee_id=${e.id}">View tickets →</a></td></tr>`).join("")}</tbody></table></div>`
      : empty(
          "No engineers yet",
          "Create an engineer, then configure their skills and capacity.",
        );
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
    target.querySelectorAll("[data-engineer]").forEach(
      (b) =>
        (b.onclick = () => {
          const e = data.items.find((e) => e.id === +b.dataset.engineer);
          modal(
            "Configure " + e.name,
            `${field("capacity", "Maximum active tickets", e.capacity, "number", 'required min="1" max="1000"')}<label class="check-label"><input type="checkbox" name="available" ${e.available ? "checked" : ""}>Available for new assignments</label><h3 style="margin-top:20px">Category skills</h3><div class="checks">${state.config.categories.map((c) => `<label class="check-label"><input type="checkbox" name="skills" value="${c.id}" ${e.skills.includes(c.id) ? "checked" : ""}>${esc(c.name)}</label>`).join("")}</div><h3>Subcategory skills</h3><div class="checks">${state.config.subcategories.map((c) => `<label class="check-label"><input type="checkbox" name="subskills" value="${c.id}" ${e.subskills.includes(c.id) ? "checked" : ""}>${esc(c.name)}</label>`).join("")}</div><p class="muted">Edit team, location and account status in Users & accounts.</p>`,
            async (fd) => {
              await send(
                "/admin/engineers/" + e.id,
                {
                  capacity: +fd.get("capacity"),
                  available: fd.has("available"),
                  skills: fd.getAll("skills").map(Number),
                  subskills: fd.getAll("subskills").map(Number),
                },
                "PATCH",
              );
              toast("Engineer updated");
              await load();
            },
          );
        }),
    );
  }
  target.querySelector("#engineer-search").oninput = debounce(() => {
    offset = 0;
    load();
  });
  target.querySelector("#new-engineer").onclick = () =>
    modal(
      "Create engineer",
      userForm({ role: "ENGINEER" }),
      async (fd) => {
        const values = Object.fromEntries(fd);
        values.role = "ENGINEER";
        values.employee_id = values.employee_id || null;
        await send("/admin/engineers", values);
        toast("Engineer created. Configure skills to enable assignment.");
        await load();
      },
      "Create engineer",
    );
  await load();
}
export async function configPage(target) {
  state.config = await api("/configuration");
  let tab = "categories";
  target.innerHTML = `<div class="page-head"><div><div class="eyebrow">Admin console</div><h1>Service configuration</h1><p>Business rules that power your service desk.</p></div></div><div class="tabs">${["categories", "subcategories", "teams", "locations", "sla", "assignment", "workflow", "notifications"].map((k) => `<button data-tab="${k}">${label(k)}</button>`).join("")}</div><div id="config-body"></div>`;
  const body = target.querySelector("#config-body");
  async function refresh() {
    state.config = await api("/configuration");
    render();
  }
  function render() {
    target
      .querySelectorAll("[data-tab]")
      .forEach((b) => b.classList.toggle("active", b.dataset.tab === tab));
    if (["categories", "subcategories", "teams", "locations"].includes(tab)) {
      const items = state.config[tab];
      body.innerHTML = `<div class="card"><div class="card-head"><h2>${label(tab)}</h2><button id="add-config">＋ Add ${tab.replace(/ies$/, "y").replace(/s$/, "")}</button></div><div class="table-wrap"><table><thead><tr><th>Name</th>${tab === "subcategories" ? "<th>Category</th>" : ""}<th>Status</th><th>Action</th></tr></thead><tbody>${items.map((i) => `<tr><td>${esc(i.name)}</td>${tab === "subcategories" ? `<td>${esc(state.config.categories.find((c) => c.id === i.category_id)?.name)}</td>` : ""}<td>${badge(i.active ? "ACTIVE" : "INACTIVE", i.active ? "resolved" : "pending")}</td><td><button class="link-button" data-item="${i.id}">Edit</button></td></tr>`).join("")}</tbody></table></div>${items.length ? "" : empty("No " + tab + " configured")}</div>`;
      const edit = (item = {}) =>
        modal(
          item.id ? "Edit " + item.name : "Create " + tab,
          field(
            "name",
            "Name",
            item.name || "",
            "text",
            'required minlength="2" maxlength="100"',
          ) +
            (tab === "subcategories"
              ? `<label>Category<select name="category_id" required>${options(state.config.categories, item.category_id)}</select></label>`
              : "") +
            `<label class="check-label"><input name="active" type="checkbox" ${item.active !== false ? "checked" : ""}>Enabled</label>`,
          async (fd) => {
            const values = { name: fd.get("name"), active: fd.has("active") };
            if (tab === "subcategories")
              values.category_id = +fd.get("category_id");
            await send(
              "/admin/config/" + tab + (item.id ? "/" + item.id : ""),
              values,
              item.id ? "PATCH" : "POST",
            );
            toast("Configuration saved");
            await refresh();
          },
        );
      body.querySelector("#add-config").onclick = () => edit();
      body
        .querySelectorAll("[data-item]")
        .forEach(
          (b) =>
            (b.onclick = () =>
              edit(items.find((i) => i.id === +b.dataset.item))),
        );
    } else if (tab === "sla") {
      body.innerHTML = `<div class="card"><h2>SLA policies</h2><p class="muted">Targets apply to new tickets. Existing tickets keep their deadlines unless their priority changes or they reopen.</p><div class="table-wrap"><table><thead><tr><th>Priority</th><th>First response</th><th>Resolution</th><th>Action</th></tr></thead><tbody>${state.config.sla.map((s) => `<tr><td>${badge(s.priority)}</td><td>${s.response_minutes} minutes</td><td>${s.resolution_minutes / 60} hours</td><td><button class="link-button" data-sla="${s.priority}">Edit policy</button></td></tr>`).join("")}</tbody></table></div></div>`;
      body.querySelectorAll("[data-sla]").forEach(
        (b) =>
          (b.onclick = () => {
            const s = state.config.sla.find(
              (s) => s.priority === b.dataset.sla,
            );
            modal(
              label(s.priority) + " SLA",
              field(
                "response_minutes",
                "Response target (minutes)",
                s.response_minutes,
                "number",
                'required min="1" max="525600"',
              ) +
                field(
                  "resolution_minutes",
                  "Resolution target (minutes)",
                  s.resolution_minutes,
                  "number",
                  'required min="1" max="525600"',
                ),
              async (fd) => {
                await send(
                  "/admin/sla/" + s.priority,
                  {
                    response_minutes: +fd.get("response_minutes"),
                    resolution_minutes: +fd.get("resolution_minutes"),
                  },
                  "PUT",
                );
                toast("SLA policy saved");
                await refresh();
              },
            );
          }),
      );
    } else {
      const config = state.config.settings[tab] || {};
      let form = "";
      if (tab === "assignment")
        form = `<label class="check-label"><input type="checkbox" name="enabled" ${config.enabled !== false ? "checked" : ""}>Enable automatic assignment</label><label class="check-label"><input type="checkbox" name="fallback" ${config.fallback ? "checked" : ""}>Allow generalist fallback when no skilled engineer is eligible</label><label>Selection strategy<select name="strategy">${["scored", "least_workload", "round_robin"].map((s) => option(s, label(s), config.strategy)).join("")}</select></label><div class="form-grid">${["category", "subcategory", "location", "team", "workload", "urgency"].map((k) => field(k + "_weight", label(k) + " weight", config[k + "_weight"] ?? 10, "number", 'min="0" max="100" required')).join("")}</div><p class="muted">Active account, availability and capacity are mandatory. Scoring prefers matching skills, team and location, spare capacity, and lower priority/SLA pressure; ties go to the least recently assigned engineer. Weights apply to the scored strategy.</p>`;
      if (tab === "workflow")
        form =
          field(
            "reopen_days",
            "Requester reopen window (days)",
            config.reopen_days ?? 7,
            "number",
            'min="0" max="365" required',
          ) +
          `<p class="muted">Set 0 to disable requester reopening. Status transitions remain controlled to preserve lifecycle integrity. Customize display labels below.</p><div class="form-grid">${[...state.config.priorities, ...["OPEN", "ASSIGNED", "IN_PROGRESS", "WAITING_FOR_USER", "WAITING_FOR_VENDOR", "RESOLVED", "CLOSED", "REOPENED", "CANCELLED"]].map((s) => field(s, label(s) + " label", config.labels?.[s] || label(s), "text", 'required maxlength="60"')).join("")}</div>`;
      if (tab === "notifications")
        form = `<label class="check-label"><input type="checkbox" name="enabled" ${config.enabled !== false ? "checked" : ""}>Enable in-app notifications</label>${field("sla_warning_minutes", "SLA warning window (minutes)", config.sla_warning_minutes ?? 60, "number", 'required min="1" max="1440"')}<p class="muted">The background worker checks SLA deadlines every 30 seconds. Each warning is delivered once per recipient and deadline.</p>`;
      body.innerHTML = `<form class="card" id="settings-form" style="max-width:780px"><h2>${label(tab)} settings</h2>${form}<div class="form-actions"><button type="submit">Save settings</button></div></form>`;
      body.querySelector("form").onsubmit = async (e) => {
        e.preventDefault();
        const fd = new FormData(e.target);
        let values;
        if (tab === "workflow")
          values = {
            reopen_days: +fd.get("reopen_days"),
            labels: Object.fromEntries(
              [...fd].filter(([k]) => k !== "reopen_days"),
            ),
          };
        else if (tab === "notifications")
          values = {
            enabled: fd.has("enabled"),
            sla_warning_minutes: +fd.get("sla_warning_minutes"),
          };
        else {
          values = Object.fromEntries(fd);
          values.enabled = fd.has("enabled");
          values.fallback = fd.has("fallback");
          for (const k in values)
            if (k.endsWith("_weight")) values[k] = +values[k];
        }
        e.submitter.disabled = true;
        try {
          await send("/admin/settings/" + tab, values, "PUT");
          toast("Settings saved");
          await refresh();
        } finally {
          e.submitter.disabled = false;
        }
      };
    }
  }
  target.querySelectorAll("[data-tab]").forEach(
    (b) =>
      (b.onclick = () => {
        tab = b.dataset.tab;
        render();
      }),
  );
  render();
}
export async function auditPage(target) {
  let offset = 0;
  target.innerHTML = `<div class="page-head"><div><div class="eyebrow">Admin console · Read-only ledger</div><h1>Audit logs</h1><p>A traceable record of access, changes, and ticket activity.</p></div></div><div class="card"><form id="audit-filters"><div class="toolbar"><input name="q" placeholder="Search action, employee, entity…" aria-label="Search audit logs"><input name="ticket" placeholder="Ticket reference or ID" aria-label="Filter ticket"><input name="actor_id" type="number" min="1" placeholder="Actor user ID" aria-label="Filter actor"><input name="action" placeholder="Exact action, e.g. LOGIN" aria-label="Filter action"><select name="entity" aria-label="Filter entity">${["", "ticket", "user", "settings", "sla", "system", "categories"].map((s) => option(s, s ? label(s) : "All entities")).join("")}</select><input type="date" name="date_from" aria-label="Audit from date"><input type="date" name="date_to" aria-label="Audit until date"><select name="sort" aria-label="Sort audit events">${option("newest", "Newest first")}${option("oldest", "Oldest first")}</select></div></form><div id="audit-results"></div><div id="pagination" class="pagination"></div></div>`;
  const form = target.querySelector("form");
  form.onsubmit = (e) => e.preventDefault();
  async function load() {
    const params = new URLSearchParams();
    for (const [k, v] of new FormData(form)) if (v) params.set(k, v);
    params.set("offset", offset);
    const data = await api("/admin/audit-logs?" + params);
    target.querySelector("#audit-results").innerHTML = data.items.length
      ? `<div class="table-wrap"><table><thead><tr><th>Timestamp</th><th>Actor</th><th>Action</th><th>Entity</th><th>IP address</th><th>Details</th></tr></thead><tbody>${data.items.map((e) => `<tr><td>${date(e.created_at)}</td><td>${esc(data.people[e.actor_id]?.name || "System")}<br><small>${esc(data.people[e.actor_id]?.employee_id || "")}</small></td><td>${badge(e.action)}</td><td>${esc(e.entity)} · ${esc(e.entity_id)}</td><td>${esc(e.ip_address || "—")}</td><td><button class="link-button" data-event="${e.id}">View event</button></td></tr>`).join("")}</tbody></table></div>`
      : empty("No audit events found");
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
    target.querySelectorAll("[data-event]").forEach(
      (b) =>
        (b.onclick = () => {
          const e = data.items.find((e) => e.id === +b.dataset.event);
          modal(
            "Audit event #" + e.id,
            `<p>${esc(label(e.action))} · ${date(e.created_at)}</p><div class="description"><strong>Previous value</strong><pre style="white-space:pre-wrap">${esc(JSON.stringify(e.before, null, 2))}</pre><strong>New value</strong><pre style="white-space:pre-wrap">${esc(JSON.stringify(e.after, null, 2))}</pre><small>Request: ${esc(e.request_id || "—")}<br>IP: ${esc(e.ip_address || "—")}<br>User agent: ${esc(e.user_agent || "—")}</small></div>`,
            async () => {},
            "Done",
          );
        }),
    );
  }
  form.oninput = debounce(() => {
    offset = 0;
    load();
  });
  await load();
}
