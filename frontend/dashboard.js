import { api, state } from "./api.js";
import { esc, admin, engineer, label, badge, sla, empty } from "./ui.js";
export const ticketRows = (items) =>
  items
    .map(
      (t) =>
        `<tr><td><a class="ticket-id" href="#/tickets/${t.id}">${esc(t.number)}</a><a class="ticket-title" href="#/tickets/${t.id}">${esc(t.title)}</a></td><td>${badge(t.priority)}</td><td>${badge(t.status)}</td><td>${esc(t.engineer_name || "Unassigned")}</td><td>${sla(t)}</td></tr>`,
    )
    .join("");
export function bars(items) {
  const max = Math.max(...items.map((i) => i.value), 1);
  return items.length
    ? items
        .map(
          (i) =>
            `<div class="chart-row"><div class="chart-label"><span>${esc(label(i.label))}</span><strong>${i.value}</strong></div><div class="bar-track"><div class="bar" style="width:${(i.value / max) * 100}%"></div></div></div>`,
        )
        .join("")
    : empty("No data yet");
}
export async function dashboardPage(target, analytics = false) {
  const [data, tickets] = await Promise.all([
    api("/dashboard"),
    api("/tickets?limit=6&sort=updated"),
  ]);
  const m = data.metrics;
  const cards = admin()
    ? [
        ["Total tickets", m.total, "Across your service desk", "▤"],
        ["Open tickets", m.open, `${m.unassigned} awaiting assignment`, "◷"],
        ["SLA breaches", m.sla_breaches, `${m.due_soon} tickets due soon`, "◴"],
        [
          "Resolved today",
          m.resolved_today,
          `${m.sla_compliance ?? "—"}% SLA compliance`,
          "✓",
        ],
      ]
    : engineer()
      ? [
          ["My open tickets", m.open, "Assigned to you", "▤"],
          [
            "Critical & high",
            m.critical + m.high,
            "Requires your attention",
            "!",
          ],
          ["Due soon", m.due_soon, `${m.sla_breaches} overdue tickets`, "◷"],
          [
            "Resolved today",
            m.resolved_today,
            `${m.average_resolution_hours.toFixed(1)}h average resolution`,
            "✓",
          ],
        ]
      : [
          ["My tickets", m.total, "Your support requests", "▤"],
          ["In progress", m.in_progress, "Your IT team is on it", "◷"],
          ["Waiting", m.pending, "Check for engineer updates", "◴"],
          ["Resolved", m.resolved, "Ready for your confirmation", "✓"],
        ];
  target.innerHTML = `<div class="page-head"><div><div class="eyebrow">${analytics ? "Insights & performance" : "Your workspace"}</div><h1>${analytics ? "Service analytics" : "Overview"}</h1><p>${new Date().toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long", year: "numeric" })} · Samsung D2C Service Desk</p></div><a href="#/create"><button>＋ Create ticket</button></a></div>${analytics ? "" : `<div class="welcome"><div><h2>Welcome back, ${esc(state.user.name.split(" ")[0])}.</h2><p>${admin() ? "A clear view of your IT operations. Keep your teams moving forward." : engineer() ? "Your next resolution starts here. Let’s keep D2C running smoothly." : "Good support keeps your day moving. We’re here to help."}</p></div><a href="#/tickets${admin() ? "?assignment=unassigned" : ""}"><button class="secondary">${admin() ? "Review unassigned" : "View my tickets"} →</button></a></div>`}<div class="stats">${cards.map(([title, value, foot, icon]) => `<div class="card stat"><div class="stat-top">${title}<span class="stat-icon">${icon}</span></div><div class="stat-number">${value.toLocaleString()}</div><div class="stat-foot">${foot}</div></div>`).join("")}</div><div class="grid-two"><section class="card"><div class="card-head"><h2>Ticket volume</h2><small>Last 30 days</small></div><div class="volume-chart">${data.charts.daily.length ? data.charts.daily.map((i) => `<div class="volume-column" title="${esc(i.label)}: ${i.value} tickets"><div class="volume-bar" style="height:${Math.max(3, (i.value / Math.max(...data.charts.daily.map((d) => d.value))) * 125)}px"></div><small>${esc(i.label.slice(5))}</small></div>`).join("") : empty("No ticket volume yet")}</div><div class="legend">● Tickets created · ${m.created_week} this week · ${m.created_month} this month</div></section><section class="card"><div class="card-head"><h2>Tickets by priority</h2><small>All tickets</small></div>${bars(data.charts.priority)}</section></div>${analytics ? `<div class="grid-equal">${["category", "status", "location", "engineer"].map((k) => `<section class="card"><h2>Tickets by ${k}</h2>${bars(data.charts[k])}</section>`).join("")}</div>` : ""}<div class="grid-two"><section class="card"><div class="card-head"><h2>Recently updated tickets</h2><a href="#/tickets">View all →</a></div>${tickets.items.length ? `<div class="table-wrap"><table><thead><tr><th>Ticket</th><th>Priority</th><th>Status</th><th>Engineer</th><th>SLA</th></tr></thead><tbody>${ticketRows(tickets.items)}</tbody></table></div>` : empty("Your workspace is clear", "Create a ticket whenever you need IT support.")}</section><section class="card"><div class="card-head"><h2>${data.workload.length ? "Engineer workload" : "My ticket status"}</h2>${admin() ? '<a href="#/engineers">Manage →</a>' : ""}</div>${
    data.workload.length
      ? data.workload
          .map(
            (e) =>
              `<div class="workload-row"><div class="avatar">${esc(
                e.name
                  .split(" ")
                  .map((s) => s[0])
                  .slice(0, 2)
                  .join(""),
              )}</div><div class="workload-info"><strong>${esc(e.name)}</strong><div class="bar-track"><div class="bar ${e.active / e.capacity > 0.8 ? "red" : ""}" style="width:${Math.min(100, (e.active / e.capacity) * 100)}%"></div></div></div><div class="workload-number">${e.active} / ${e.capacity}<small>${e.available ? "Available" : "Away"}</small></div></div>`,
          )
          .join("")
      : bars(data.charts.status)
  }</section></div><section class="card"><div class="card-head"><h2>Service performance</h2><small>Based on ${admin() ? "all" : "your"} tickets</small></div><div class="grid-equal"><div><div class="metric-inline"><span>Average first response</span><strong>${m.average_response_hours.toFixed(1)} hours</strong></div><div class="metric-inline"><span>Average resolution</span><strong>${m.average_resolution_hours.toFixed(1)} hours</strong></div><div class="metric-inline"><span>SLA compliance</span><strong>${m.sla_compliance === null ? "No resolved tickets" : m.sla_compliance + "%"}</strong></div></div><div><div class="metric-inline"><span>Created today</span><strong>${m.created_today}</strong></div><div class="metric-inline"><span>${admin() ? "Active users" : "Closed tickets"}</span><strong>${admin() ? m.active_users : m.closed}</strong></div><div class="metric-inline"><span>${admin() ? "Active engineers" : "Open tickets"}</span><strong>${admin() ? m.active_engineers : m.open}</strong></div></div></div></section>`;
}
