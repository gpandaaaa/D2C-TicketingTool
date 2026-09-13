import { state } from "./api.js";
export const esc = (v) =>
  String(v ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
export const admin = () =>
  ["ADMIN", "SUPER_ADMIN", "IT_ADMIN"].includes(state.user?.role);
export const engineer = () =>
  ["ENGINEER", "IT_AGENT"].includes(state.user?.role);
export const label = (v) =>
  state.config?.settings?.workflow?.labels?.[v] ||
  String(v || "")
    .replaceAll("_", " ")
    .toLowerCase()
    .replace(/\b\w/g, (c) => c.toUpperCase());
export const date = (v) =>
  v
    ? new Date(
        v.endsWith("Z") || /[+-]\d\d:\d\d$/.test(v) ? v : v + "Z",
      ).toLocaleString(undefined, {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      })
    : "—";
export const badge = (v, type = "") =>
  `<span class="badge ${esc(type || v?.toLowerCase())}"><span class="dot"></span>${esc(label(v))}</span>`;
export const option = (v, text, selected) =>
  `<option value="${esc(v)}" ${String(v) === String(selected) ? "selected" : ""}>${esc(text)}</option>`;
export const options = (items, selected, blank = "Select…") =>
  option("", blank, selected) +
  items.map((i) => option(i.id, i.name, selected)).join("");
export function toast(message, error = false) {
  const el = document.createElement("div");
  el.className = "toast " + (error ? "error" : "");
  el.textContent = (error ? "!  " : "✓  ") + message;
  document.querySelector("#toasts").append(el);
  setTimeout(() => el.remove(), 6000);
}
export function empty(
  title,
  detail = "Try changing your filters or come back later.",
) {
  return `<div class="empty"><div class="empty-icon">◇</div><h3>${esc(title)}</h3><p>${esc(detail)}</p></div>`;
}
export const loading = () =>
  `<div class="skeleton"></div><div class="skeleton short"></div><div class="skeleton tall"></div>`;
export function errorView(err) {
  return `<div class="card empty"><h3>We couldn’t load this page</h3><p>${esc(err.message)}</p><button id="retry">Try again</button></div>`;
}
export function modal(title, body, onSubmit, submitLabel = "Save changes") {
  const dialog = document.querySelector("#modal");
  dialog.innerHTML = `<form id="dialog-form"><div class="modal-head"><h2>${esc(title)}</h2><button type="button" class="icon-button" id="modal-close" aria-label="Close dialog">×</button></div>${body}<p class="form-error" role="alert"></p><div class="modal-foot"><button type="button" class="secondary" id="modal-cancel">Cancel</button><button type="submit">${esc(submitLabel)}</button></div></form>`;
  dialog.querySelector("#modal-close").onclick = dialog.querySelector(
    "#modal-cancel",
  ).onclick = () => dialog.close();
  dialog.querySelector("form").onsubmit = async (e) => {
    e.preventDefault();
    const button = e.submitter;
    button.disabled = true;
    try {
      await onSubmit(new FormData(e.target), e.target);
      dialog.close();
    } catch (err) {
      dialog.querySelector(".form-error").textContent = err.message;
    } finally {
      button.disabled = false;
    }
  };
  dialog.showModal();
}
export function confirmAction(title, message, action) {
  modal(title, `<p>${esc(message)}</p>`, action, "Confirm");
}
export function pager(total, offset, limit, onPage, root = document) {
  const target = root.querySelector("#pagination");
  if (!target) return;
  target.innerHTML = `<span>${total ? offset + 1 : 0}–${Math.min(offset + limit, total)} of ${total.toLocaleString()}</span><div><button class="secondary" id="prev" ${offset === 0 ? "disabled" : ""}>← Previous</button> <button class="secondary" id="next" ${offset + limit >= total ? "disabled" : ""}>Next →</button></div>`;
  target.querySelector("#prev").onclick = () =>
    onPage(Math.max(0, offset - limit));
  target.querySelector("#next").onclick = () => onPage(offset + limit);
}
export function debounce(fn, ms = 300) {
  let timer;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), ms);
  };
}
export const field = (name, title, value = "", type = "text", extra = "") =>
  `<label>${esc(title)}<input name="${name}" type="${type}" value="${esc(value)}" ${extra}></label>`;
export function sla(t) {
  if (["RESOLVED", "CLOSED", "CANCELLED"].includes(t.status))
    return badge(
      t.resolved_at && new Date(t.resolved_at) > new Date(t.sla_due_at)
        ? "BREACHED"
        : "COMPLETE",
      t.resolved_at && new Date(t.resolved_at) > new Date(t.sla_due_at)
        ? "critical"
        : "resolved",
    );
  if (!t.sla_due_at) return '<span class="muted">No deadline</span>';
  const warning =
    (state.config?.settings?.notifications?.sla_warning_minutes || 60) / 60;
  const due = new Date(
      t.sla_due_at.endsWith("Z") || /[+-]\d\d:\d\d$/.test(t.sla_due_at)
        ? t.sla_due_at
        : t.sla_due_at + "Z",
    ),
    hours = (due - Date.now()) / 3600000;
  return `<span class="sla ${hours < 0 ? "late" : hours < warning ? "soon" : "good"}">${hours < 0 ? "Overdue" : hours < warning ? "Due soon" : "Within SLA"}<small>${Math.abs(hours) < 24 ? Math.abs(hours).toFixed(1) + "h" : Math.round(Math.abs(hours) / 24) + "d"} ${hours < 0 ? "ago" : "remaining"}</small></span>`;
}
