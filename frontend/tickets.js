import { api, send, state, upload } from "./api.js";
import {
  esc,
  admin,
  engineer,
  label,
  badge,
  date,
  sla,
  empty,
  options,
  option,
  field,
  modal,
  confirmAction,
  toast,
  pager,
  debounce,
} from "./ui.js";
const statuses = [
  "OPEN",
  "ASSIGNED",
  "IN_PROGRESS",
  "WAITING_FOR_USER",
  "WAITING_FOR_VENDOR",
  "RESOLVED",
  "CLOSED",
  "REOPENED",
  "CANCELLED",
];
const priorities = ["LOW", "MEDIUM", "HIGH", "CRITICAL"];
const selectField = (name, title, items, value) =>
  `<label>${title}<select name="${name}">${items.map((i) => option(i, label(i), value)).join("")}</select></label>`;
const activeCategories = () => state.config.categories.filter((c) => c.active);
const categoryName = (id) =>
  state.config.categories.find((c) => c.id === id)?.name || "—";
export async function ticketsPage(target, params) {
  let offset = Number(params.get("offset") || 0),
    selected = new Set(),
    request = 0;
  const engineers = admin()
    ? (await api("/admin/engineers?limit=100")).items
    : [];
  target.innerHTML = `<div class="page-head"><div><div class="eyebrow">Service operations</div><h1>${params.get("assignment") === "unassigned" ? "Unassigned tickets" : params.get("mine") ? "My tickets" : "Tickets"}</h1><p>Track requests, manage progress, and keep work moving.</p></div><a href="#/create"><button>＋ Create ticket</button></a></div><div class="card"><form id="filters"><div class="toolbar"><input name="q" value="${esc(params.get("q") || "")}" placeholder="Search tickets, people, ID…" aria-label="Search tickets"><select name="status" aria-label="Filter status">${option("", "All statuses")}${statuses.map((s) => option(s, label(s), params.get("status"))).join("")}</select><select name="priority" aria-label="Filter priority">${option("", "All priorities")}${priorities.map((s) => option(s, label(s), params.get("priority"))).join("")}</select><select name="category_id" aria-label="Filter category">${options(activeCategories(), params.get("category_id"), "All categories")}</select><select name="sla" aria-label="Filter SLA">${option("", "All SLA")}${["within", "approaching", "breached"].map((s) => option(s, label(s), params.get("sla"))).join("")}</select><span class="spacer"></span><button type="button" class="secondary" id="more">More filters</button></div><div class="filters-more" id="more-filters" hidden style="display:none">${admin() ? `<select name="assignee_id" aria-label="Filter engineer">${options(engineers, params.get("assignee_id"), "All engineers")}</select>` : ""}<select name="assignment" aria-label="Assignment status">${option("", "All assignments")}${option("unassigned", "Unassigned", params.get("assignment"))}${option("assigned", "Assigned", params.get("assignment"))}</select><select name="team" aria-label="Filter team">${option("", "All teams")}${state.config.teams.map((t) => option(t.name, t.name, params.get("team"))).join("")}</select><select name="location" aria-label="Filter location">${option("", "All locations")}${state.config.locations.map((t) => option(t.name, t.name, params.get("location"))).join("")}</select><input type="date" name="date_from" aria-label="Created from"><input type="date" name="date_to" aria-label="Created until"><select name="sort" aria-label="Sort tickets">${["newest", "oldest", "updated", "sla"].map((s) => option(s, label(s), params.get("sort") || "newest")).join("")}</select><button class="secondary" type="reset">Clear filters</button></div></form>${admin() ? '<div class="bulk" id="bulk" hidden style="display:none"><span id="selected-count"></span><button data-bulk="assign">Assign</button><button data-bulk="priority">Priority</button><button data-bulk="status">Status</button><button class="secondary" id="export">Export CSV</button></div>' : ""}<div id="results"></div><div id="pagination" class="pagination"></div></div>`;
  const form = target.querySelector("#filters");
  form.onsubmit = (e) => e.preventDefault();
  target.querySelector("#more").onclick = () => {
    const el = target.querySelector("#more-filters");
    el.style.display = el.style.display === "none" ? "flex" : "none";
  };
  async function load() {
    const version = ++request;
    const search = new URLSearchParams();
    for (const [k, v] of new FormData(form)) if (v) search.set(k, v);
    if (params.get("mine")) search.set("mine", "true");
    if (params.get("requester_id"))
      search.set("requester_id", params.get("requester_id"));
    search.set("offset", offset);
    const data = await api("/tickets?" + search);
    if (version !== request) return;
    selected.clear();
    showBulk();
    target.querySelector("#results").innerHTML = data.items.length
      ? `<div class="table-wrap"><table><thead><tr>${admin() ? '<th><input type="checkbox" id="select-all" aria-label="Select page"></th>' : ""}<th>Ticket</th><th>Priority</th><th>Status</th><th>Category</th><th>Requester</th><th>Engineer</th><th>SLA</th><th>Created</th></tr></thead><tbody>${data.items.map((t) => `<tr>${admin() ? `<td><input type="checkbox" data-select="${t.id}" aria-label="Select ${esc(t.number)}"></td>` : ""}<td><a class="ticket-id" href="#/tickets/${t.id}">${esc(t.number)}</a><a class="ticket-title" href="#/tickets/${t.id}">${esc(t.title)}</a></td><td>${badge(t.priority)}</td><td>${badge(t.status)}</td><td>${esc(categoryName(t.category_id))}</td><td>${esc(t.requester_name)}</td><td>${esc(t.engineer_name || "Unassigned")}</td><td>${sla(t)}</td><td>${date(t.created_at)}</td></tr>`).join("")}</tbody></table></div>`
      : empty(
          "No tickets found",
          "Try another search or create a new support request.",
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
    if (admin()) {
      target.querySelectorAll("[data-select]").forEach(
        (c) =>
          (c.onchange = () => {
            c.checked
              ? selected.add(+c.dataset.select)
              : selected.delete(+c.dataset.select);
            showBulk();
          }),
      );
      const all = target.querySelector("#select-all");
      if (all)
        all.onchange = () => {
          target.querySelectorAll("[data-select]").forEach((c) => {
            c.checked = all.checked;
            c.checked
              ? selected.add(+c.dataset.select)
              : selected.delete(+c.dataset.select);
          });
          showBulk();
        };
    }
  }
  function showBulk() {
    if (!admin()) return;
    target.querySelector("#bulk").style.display = selected.size
      ? "flex"
      : "none";
    target.querySelector("#selected-count").textContent =
      selected.size + " selected";
  }
  form.oninput = debounce(() => {
    offset = 0;
    load();
  });
  form.onreset = () =>
    setTimeout(() => {
      params = new URLSearchParams();
      offset = 0;
      load();
    }, 0);
  if (admin()) {
    target.querySelectorAll("[data-bulk]").forEach(
      (b) =>
        (b.onclick = () => {
          const action = b.dataset.bulk;
          let body =
            action === "assign"
              ? `<label>Engineer<select name="engineer_id">${options(engineers, "", "Leave unassigned")}</select></label>`
              : selectField(
                  action,
                  label(action),
                  action === "priority" ? priorities : statuses,
                );
          modal(
            "Bulk " + label(action),
            body +
              (action === "status"
                ? '<label>Resolution (required to resolve)<textarea name="resolution" maxlength="10000"></textarea></label>'
                : "") +
              field("reason", "Reason", "Bulk update"),
            async (fd) => {
              const values = Object.fromEntries(fd);
              if (action === "assign")
                values.engineer_id = values.engineer_id
                  ? +values.engineer_id
                  : null;
              await send("/tickets/bulk", {
                ids: [...selected],
                action,
                ...values,
              });
              toast("Tickets updated");
              await load();
            },
          );
        }),
    );
    target.querySelector("#export").onclick = () => {
      window.location.href =
        "/api/v1/tickets/export?ids=" + [...selected].join(",");
    };
  }
  await load();
}
function dropzone() {
  return `<label class="dropzone" id="dropzone">↑<br><strong>Drop files here or browse</strong><br><small>PNG, JPG, PDF, TXT, LOG, CSV, DOCX, XLSX, ZIP · up to 10 MB each</small><input type="file" id="files" multiple accept=".png,.jpg,.jpeg,.pdf,.txt,.log,.csv,.docx,.xlsx,.zip"></label><div id="file-list"></div>`;
}
function wireFiles(target) {
  let files = [],
    completed = new Set();
  const input = target.querySelector("#files"),
    zone = target.querySelector("#dropzone");
  function add(incoming) {
    for (const file of incoming) {
      if (file.size > 10 * 1024 * 1024) {
        toast(file.name + " exceeds 10 MB", true);
        continue;
      }
      files.push(file);
    }
    render();
  }
  function render() {
    target.querySelector("#file-list").innerHTML = files
      .map(
        (f, i) =>
          `<div class="file-row"><span>${esc(f.name)} <small>${(f.size / 1024).toFixed(0)} KB</small></span><small id="progress-${i}">Ready</small><button type="button" class="secondary" data-remove="${i}" aria-label="Remove ${esc(f.name)}">×</button></div>`,
      )
      .join("");
    target.querySelectorAll("[data-remove]").forEach(
      (b) =>
        (b.onclick = () => {
          files.splice(+b.dataset.remove, 1);
          render();
        }),
    );
  }
  input.onchange = () => add(input.files);
  zone.ondragover = (e) => {
    e.preventDefault();
    zone.classList.add("drag");
  };
  zone.ondragleave = () => zone.classList.remove("drag");
  zone.ondrop = (e) => {
    e.preventDefault();
    zone.classList.remove("drag");
    add(e.dataTransfer.files);
  };
  return {
    get: () => files,
    clear: () => {
      files = [];
      input.value = "";
      render();
    },
    send: async (id) => {
      for (let i = 0; i < files.length; i++) {
        if (completed.has(files[i])) continue;
        await upload(id, files[i], (p) => {
          const el = target.querySelector("#progress-" + i);
          if (el) el.textContent = p + "%";
        });
        completed.add(files[i]);
      }
    },
  };
}
export async function createPage(target) {
  target.innerHTML = `<div class="page-head"><div><div class="eyebrow">We’re here to help</div><h1>Create a ticket</h1><p>Tell us what you need. We’ll connect you with the right engineer.</p></div><a href="#/tickets">← Back to tickets</a></div><div class="detail-grid"><form id="create-form"><section class="card"><div class="card-head"><h2>01 · Request details</h2><small>Required fields are marked *</small></div>${field("title", "Ticket title *", "", "text", 'required minlength="3" maxlength="255" placeholder="A short summary of the issue"')}<label>Description *<div class="rich-toolbar"><button type="button" data-format="bold"><b>Bold</b></button><button type="button" data-format="list">• List</button><button type="button" id="preview">Preview</button></div><textarea name="description" required maxlength="10000" rows="7" placeholder="What happened? When did it start? Include any error messages and troubleshooting you’ve tried."></textarea><small>Supports **bold** and bullet lists. Do not include passwords or authentication codes.</small><div id="rich-preview" class="rich-preview" hidden></div></label></section><section class="card"><h2>02 · Classification</h2><div class="form-grid"><label>Category *<select name="category_id" required>${options(activeCategories(), "", "Choose a category")}</select></label><label>Subcategory<select name="subcategory_id">${option("", "Optional")}</select></label>${selectField("priority", "Priority *", priorities, "MEDIUM")}<label>Location<select name="location">${option("", "Use profile location")}${state.config.locations
    .filter((l) => l.active)
    .map((l) => option(l.name, l.name, state.user.location))
    .join(
      "",
    )}</select></label><label>Team<select name="team">${option("", "Use profile team")}${state.config.teams
    .filter((t) => t.active)
    .map((t) => option(t.name, t.name, state.user.team))
    .join(
      "",
    )}</select></label></div></section><section class="card"><h2>03 · Supporting files</h2>${dropzone()}</section><p class="form-error" role="alert"></p><div class="form-actions"><a href="#/tickets"><button type="button" class="secondary">Cancel</button></a><button type="submit">Submit ticket →</button></div></form><aside><section class="card"><div class="eyebrow">What happens next</div><h2>You’re in good hands.</h2><div class="timeline"><div class="event"><strong>Request received</strong><small>Your ticket gets a unique reference number.</small></div><div class="event"><strong>Engineer matched</strong><small>We find an available engineer with the right skills.</small></div><div class="event"><strong>Stay informed</strong><small>Follow updates and chat with your engineer.</small></div></div></section><section class="card"><h3>Expected resolution</h3><p id="sla-preview" class="muted"></p><small>Targets follow your IT team’s configured SLA policy.</small></section></aside></div>`;
  const form = target.querySelector("form"),
    files = wireFiles(target),
    requestKey = crypto.randomUUID();
  const updateSLA = () => {
    const policy = state.config.sla.find(
      (p) => p.priority === form.priority.value,
    );
    target.querySelector("#sla-preview").textContent = policy
      ? `${policy.resolution_minutes / 60} hours · first response within ${policy.response_minutes} minutes`
      : "No SLA configured. Contact an administrator.";
  };
  form.priority.onchange = updateSLA;
  updateSLA();
  form.category_id.onchange = () =>
    (form.subcategory_id.innerHTML = options(
      state.config.subcategories.filter(
        (s) => s.active && s.category_id === +form.category_id.value,
      ),
      "",
      "Optional",
    ));
  target.querySelectorAll("[data-format]").forEach(
    (b) =>
      (b.onclick = () => {
        const t = form.description,
          start = t.selectionStart,
          end = t.selectionEnd,
          selected = t.value.slice(start, end);
        t.setRangeText(
          b.dataset.format === "bold"
            ? "**" + (selected || "text") + "**"
            : "\n- " + (selected || "List item"),
          start,
          end,
          "select",
        );
        t.focus();
      }),
  );
  target.querySelector("#preview").onclick = () => {
    const el = target.querySelector("#rich-preview");
    el.hidden = !el.hidden;
    el.innerHTML = esc(form.description.value).replace(
      /\*\*(.*?)\*\*/g,
      "<strong>$1</strong>",
    );
  };
  form.onsubmit = async (e) => {
    e.preventDefault();
    const button = e.submitter;
    button.disabled = true;
    button.textContent = "Creating ticket…";
    try {
      const data = Object.fromEntries(new FormData(form));
      data.category_id = +data.category_id;
      data.subcategory_id = data.subcategory_id ? +data.subcategory_id : null;
      data.location = data.location || null;
      data.team = data.team || null;
      const t = await api("/tickets", {
        method: "POST",
        body: data,
        headers: { "Idempotency-Key": requestKey },
      });
      try {
        await files.send(t.id);
      } catch (err) {
        toast(
          "Ticket created, but an attachment failed: " +
            err.message +
            ". Retry on the ticket page.",
          true,
        );
      }
      toast(t.number + " created successfully");
      location.hash = "/tickets/" + t.id;
    } catch (err) {
      target.querySelector(".form-error").textContent = err.message;
      button.disabled = false;
      button.textContent = "Submit ticket →";
    }
  };
}
export async function detailPage(target, id) {
  const data = await api("/tickets/" + id),
    t = data.ticket,
    people = data.people;
  const person = (uid) => people[uid]?.name || "System";
  const operator = admin() || (engineer() && t.assignee_id === state.user.id);
  const permitted = admin()
    ? statuses
    : operator
      ? data.transitions.filter((s) => !["NEW", "PENDING", "OPEN"].includes(s))
      : t.status === "RESOLVED"
        ? ["CLOSED", "REOPENED"]
        : t.status === "CLOSED"
          ? ["REOPENED"]
          : [];
  target.innerHTML = `<div class="page-head"><div><div class="eyebrow"><a href="#/tickets">Tickets</a> / ${esc(t.number)}</div><h1>${esc(t.title)}</h1><p>Created ${date(t.created_at)} · Updated ${date(t.updated_at)}</p><div class="detail-meta">${badge(t.priority)}${badge(t.status)}${sla(t)}</div></div>${admin() ? '<button class="secondary" id="edit-ticket">Edit ticket</button>' : ""}</div>${t.assignment_reason ? `<div class="card"><strong>Awaiting assignment</strong><p class="muted" style="margin:8px 0 0">${esc(t.assignment_reason)}</p></div>` : ""}<div class="detail-grid"><div><section class="card"><h2>Description</h2><div class="description">${esc(t.description).replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>")}</div></section>${t.resolution ? `<section class="card"><h2>Resolution</h2><p class="description">${esc(t.resolution)}</p></section>` : ""}<section class="card"><div class="card-head"><h2>Conversation</h2><small>${data.comment_total} comments</small></div>${data.comments.length ? data.comments.map((c) => `<div class="comment ${c.internal ? "internal" : ""}"><div class="avatar">${esc(person(c.author_id)[0])}</div><div class="comment-body"><strong>${esc(person(c.author_id))}</strong><small>${date(c.created_at)} ${c.internal ? "· Internal note" : ""}</small><p>${esc(c.body)}</p></div></div>`).join("") : empty("Start the conversation", "Share an update or ask your engineer a question.")}${data.comment_total > data.comments.length ? '<button class="secondary" id="more-comments">Load more comments</button>' : ""}<form id="comment-form" style="margin-top:22px"><label>Add a comment<textarea name="body" required maxlength="10000" placeholder="Write your message…"></textarea></label>${operator ? '<label class="check-label"><input type="checkbox" name="internal">Internal note (IT team only)</label>' : ""}<div class="form-actions"><button type="submit">Send comment</button></div></form></section><section class="card"><h2>Attachments</h2>${data.attachments.map((a) => `<a class="file-row" href="/api/v1/tickets/${id}/attachments/${a.id}"><span>↧ ${esc(a.name)}</span><small>${(a.size / 1024).toFixed(0)} KB · ${date(a.created_at)}</small></a>`).join("") || '<p class="muted">No attachments yet.</p>'}${dropzone()}<button id="upload-files" class="secondary">Upload files</button></section><section class="card"><h2>Activity timeline</h2><div class="timeline" id="ticket-timeline">${data.activity.map((a) => `<div class="event"><strong>${esc(label(a.action))}</strong><small>${esc(person(a.actor_id))} · ${date(a.created_at)}</small>${a.before || a.after ? `<details><summary>View details</summary><pre>${esc(JSON.stringify({ before: a.before, after: a.after }, null, 2))}</pre></details>` : ""}</div>`).join("")}</div>${data.activity_total > data.activity.length ? '<button class="secondary" id="more-activity">Load more activity</button>' : ""}</section></div><aside><section class="card"><h2>Ticket details</h2><dl class="definition">${[
    ["Requester", person(t.requester_id)],
    ["Email", people[t.requester_id]?.email],
    ["Department", people[t.requester_id]?.department],
    ["Engineer", t.assignee_id ? person(t.assignee_id) : "Unassigned"],
    ["Category", categoryName(t.category_id)],
    [
      "Subcategory",
      state.config.subcategories.find((s) => s.id === t.subcategory_id)?.name,
    ],
    ["Team", t.team],
    ["Location", t.location],
    ["First response due", date(t.response_due_at)],
    ["Acknowledged", date(t.acknowledged_at)],
    ["Resolution due", date(t.sla_due_at)],
    ["Resolved", date(t.resolved_at)],
    ["Closed", date(t.closed_at)],
  ]
    .map(([k, v]) => `<div><dt>${k}</dt><dd>${esc(v || "—")}</dd></div>`)
    .join("")}</dl></section>${
    permitted.length
      ? `<section class="card"><h2>Update status</h2><form id="status-form"><label>Next status<select name="status">${permitted
          .filter((s) => s !== t.status)
          .map((s) => option(s, label(s)))
          .join(
            "",
          )}</select></label><label>Resolution<textarea name="resolution" placeholder="Describe how the issue was resolved…">${esc(t.resolution || "")}</textarea><small>Required when resolving a ticket.</small></label><button type="submit">Update status</button></form></section>`
      : ""
  }${admin() ? '<section class="card"><h2>Assignment</h2><button id="assign-ticket">Assign / reassign</button><hr style="border:0;border-top:1px solid var(--line);margin:24px 0"><button id="delete-ticket" class="secondary">Delete ticket</button></section>' : ""}</aside></div>`;
  let commentsOffset = data.comments.length,
    activityOffset = data.activity.length;
  if (target.querySelector("#more-comments"))
    target.querySelector("#more-comments").onclick = async (e) => {
      e.target.disabled = true;
      try {
        const next = await api(
          `/tickets/${id}/conversation?offset=${commentsOffset}`,
        );
        e.target.insertAdjacentHTML(
          "beforebegin",
          next.items
            .map(
              (c) =>
                `<div class="comment ${c.internal ? "internal" : ""}"><div class="avatar">${esc(c.author_name[0])}</div><div class="comment-body"><strong>${esc(c.author_name)}</strong><small>${date(c.created_at)} ${c.internal ? "· Internal" : ""}</small><p>${esc(c.body)}</p></div></div>`,
            )
            .join(""),
        );
        commentsOffset += next.items.length;
        e.target.hidden = commentsOffset >= next.total;
      } finally {
        e.target.disabled = false;
      }
    };
  if (target.querySelector("#more-activity"))
    target.querySelector("#more-activity").onclick = async (e) => {
      e.target.disabled = true;
      try {
        const next = await api(
          `/tickets/${id}/activity?offset=${activityOffset}`,
        );
        target
          .querySelector("#ticket-timeline")
          .insertAdjacentHTML(
            "beforeend",
            next.items
              .map(
                (a) =>
                  `<div class="event"><strong>${esc(label(a.action))}</strong><small>${esc(a.actor_name)} · ${date(a.created_at)}</small><details><summary>View details</summary><pre>${esc(JSON.stringify({ before: a.before, after: a.after }, null, 2))}</pre></details></div>`,
              )
              .join(""),
          );
        activityOffset += next.items.length;
        e.target.hidden = activityOffset >= next.total;
      } finally {
        e.target.disabled = false;
      }
    };
  target.querySelector("#comment-form").onsubmit = async (e) => {
    e.preventDefault();
    e.submitter.disabled = true;
    try {
      await send("/tickets/" + id + "/comments", {
        body: e.target.body.value,
        internal: !!e.target.internal?.checked,
      });
      toast("Comment added");
      await detailPage(target, id);
    } catch (err) {
      toast(err.message, true);
      e.submitter.disabled = false;
    }
  };
  if (target.querySelector("#status-form"))
    target.querySelector("#status-form").onsubmit = (e) => {
      e.preventDefault();
      const payload = { status: e.target.status.value };
      if (operator) payload.resolution = e.target.resolution.value;
      confirmAction(
        "Update ticket status",
        `Change ${t.number} to ${label(payload.status)}?`,
        async () => {
          await send("/tickets/" + id, payload, "PATCH");
          toast("Status updated");
          await detailPage(target, id);
        },
      );
    };
  const files = wireFiles(target);
  target.querySelector("#upload-files").onclick = async (e) => {
    if (!files.get().length) {
      toast("Choose at least one file", true);
      return;
    }
    e.target.disabled = true;
    try {
      await files.send(id);
      toast("Files uploaded");
      await detailPage(target, id);
    } catch (err) {
      toast(err.message, true);
      e.target.disabled = false;
    }
  };
  if (admin()) {
    target.querySelector("#assign-ticket").onclick = async () => {
      const engineers = (await api("/admin/engineers?limit=100")).items;
      modal(
        "Assign engineer",
        `<label>Engineer<select name="engineer_id">${option("", "Leave unassigned")}${engineers.map((e) => option(e.id, `${e.name} · ${e.active_tickets}/${e.capacity} active · ${e.available && e.active ? "Available" : "Unavailable"}`, t.assignee_id)).join("")}</select></label>${field("reason", "Reason", "", "text", "required")}`,
        async (fd) => {
          await send("/tickets/" + id + "/assign", {
            engineer_id: fd.get("engineer_id") ? +fd.get("engineer_id") : null,
            reason: fd.get("reason"),
          });
          toast("Assignment updated");
          await detailPage(target, id);
        },
        "Assign ticket",
      );
    };
    target.querySelector("#delete-ticket").onclick = () =>
      confirmAction(
        "Delete ticket",
        "This cancels and removes the ticket from active views. Its audit history is retained.",
        async () => {
          await send("/tickets/" + id, {}, "DELETE");
          toast("Ticket deleted");
          location.hash = "/tickets";
        },
      );
    target.querySelector("#edit-ticket").onclick = () =>
      modal(
        "Edit ticket",
        `${field("title", "Title", t.title, "text", 'required minlength="3"')}<label>Description<textarea name="description" required>${esc(t.description)}</textarea></label>${selectField("priority", "Priority", priorities, t.priority)}<label>Category<select name="category_id">${options(activeCategories(), t.category_id)}</select></label>${field("team", "Team", t.team || "")}`,
        async (fd) => {
          const values = Object.fromEntries(fd);
          values.category_id = +values.category_id;
          if (values.category_id !== t.category_id)
            values.subcategory_id = null;
          await send("/tickets/" + id, values, "PATCH");
          toast("Ticket saved");
          await detailPage(target, id);
        },
      );
  }
}
