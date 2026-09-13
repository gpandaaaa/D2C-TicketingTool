import { api, send } from "./api.js";
import { esc, date, toast } from "./ui.js";

export async function engineerActivityPage(target) {
  target.innerHTML = `<div class="page-head"><div><div class="eyebrow">Admin console</div><h1>Engineer activity tracker</h1><p>Historical assignments and completions. Completed means resolved by the recorded actor; date filters use UTC.</p></div></div>
  <section class="card"><form id="activity-filters" class="toolbar">
  <input name="search" aria-label="Search engineer or ticket" placeholder="Engineer name, email or ticket">
  <select name="event" aria-label="Event"><option value="all">All events</option><option value="assigned">Assigned</option><option value="completed">Completed (resolved)</option></select>
  <label>From (UTC)<input name="date_from" type="date"></label><label>To (UTC)<input name="date_to" type="date"></label>
  <button>Apply filters</button><button type="button" id="download-activity" class="secondary">Download CSV</button></form>
  <p>Assignment rows identify the receiving engineer; completion rows identify who resolved the ticket, including administrator resolutions. Reopened tickets may have multiple completion events.</p>
  <div id="activity-results"></div></section>
  <section class="card"><h2>Assignment email delivery</h2><p id="email-state"></p><div id="email-results"></div></section>`;
  let offset = 0, emailOffset = 0, filters = new URLSearchParams();
  const form = target.querySelector("#activity-filters");
  async function load() {
    const el = target.querySelector("#activity-results");
    el.textContent = "Loading activity…";
    try {
      const data = await api(`/admin/engineer-activity?${filters}&offset=${offset}`);
      el.innerHTML = `<p>${data.total} matching events</p><div class="table-wrap"><table><thead><tr><th>Time</th><th>Event</th><th>Ticket</th><th>Engineer / resolver</th><th>Performed by</th><th>Current status</th><th>Details</th></tr></thead><tbody>${data.items.map(r => `<tr><td>${date(r.occurred_at)}</td><td>${esc(r.event)}</td><td><a href="#/tickets/${r.ticket_id}">${esc(r.number)}</a><br>${esc(r.title)}</td><td>${esc(r.engineer)}<br>${esc(r.engineer_email)}</td><td>${esc(r.actor || "System")}</td><td>${esc(r.current_status)}</td><td>${esc(r.details)}</td></tr>`).join("") || '<tr><td colspan="7">No matching activity.</td></tr>'}</tbody></table></div><div class="pagination"><button id="activity-prev" ${offset === 0 ? "disabled" : ""}>Previous</button><button id="activity-next" ${offset + 25 >= data.total ? "disabled" : ""}>Next</button></div>`;
      el.querySelector("#activity-prev").onclick = () => { offset -= 25; load(); };
      el.querySelector("#activity-next").onclick = () => { offset += 25; load(); };
    } catch (e) { el.textContent = e.message; }
  }
  form.onsubmit = e => {
    e.preventDefault(); filters = new URLSearchParams();
    for (const [k,v] of new FormData(form)) if (v) filters.set(k,v);
    offset = 0; load();
  };
  target.querySelector("#download-activity").onclick = async e => {
    const button = e.currentTarget; button.disabled = true;
    try {
      const response = await fetch(`/api/v1/admin/engineer-activity?${filters}&export=true`, { credentials: "same-origin" });
      if (!response.ok) throw new Error((await response.json()).error?.message || "Download failed");
      const url = URL.createObjectURL(await response.blob());
      const a = document.createElement("a"); a.href = url; a.download = "engineer-activity.csv"; a.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000); toast("Report downloaded");
    } catch (err) { toast(err.message); } finally { button.disabled = false; }
  };
  async function emails() {
    const el = target.querySelector("#email-results");
    try {
      const data = await api(`/admin/email-deliveries?offset=${emailOffset}`);
      target.querySelector("#email-state").textContent = data.enabled ? "Email enabled. Sent means accepted by SMTP, not confirmed inbox delivery." : "Email is disabled. Configure the SMTP relay to enable assignment emails.";
      el.innerHTML = `<div class="table-wrap"><table><thead><tr><th>Ticket</th><th>Recipient</th><th>Status</th><th>Attempts</th><th>Error type</th><th>Action</th></tr></thead><tbody>${data.items.map(r => `<tr><td>${esc(r.ticket)}</td><td>${esc(r.recipient)}</td><td>${esc(r.status)}</td><td>${r.attempts}</td><td>${esc(r.last_error || "—")}</td><td>${r.status === "failed" ? `<button data-retry="${r.id}">Retry</button>` : "—"}</td></tr>`).join("") || '<tr><td colspan="6">No email deliveries yet.</td></tr>'}</tbody></table></div><div class="pagination"><button id="email-prev" ${emailOffset === 0 ? "disabled" : ""}>Previous</button><button id="email-next" ${emailOffset + 25 >= data.total ? "disabled" : ""}>Next</button><button id="email-refresh">Refresh</button></div>`;
      el.querySelector("#email-prev").onclick = () => {emailOffset -= 25; emails();};
      el.querySelector("#email-next").onclick = () => {emailOffset += 25; emails();};
      el.querySelector("#email-refresh").onclick = emails;
      el.querySelectorAll("[data-retry]").forEach(b => b.onclick = async () => {
        b.disabled = true;
        try {await send(`/admin/email-deliveries/${b.dataset.retry}/retry`, {}); toast("Delivery queued for retry"); await emails();}
        catch (e) {toast(e.message); b.disabled = false;}
      });
    } catch (e) {el.textContent = e.message;}
  }
  await Promise.all([load(), emails()]);
}
