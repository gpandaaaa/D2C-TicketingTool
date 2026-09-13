# Assignment email and engineer activity reports

## Assignment email

Automatic and manual assignments/reassignments to a different engineer queue an email for the new engineer when `SMTP_ENABLED=true`. The sender defaults to **itecom.d2c@samsung.com**. In-app notifications continue independently. Unassignment and unchanged-assignee operations do not send mail. Enabling SMTP does not retroactively email earlier assignments.

The ticket transaction writes a durable `email_deliveries` row. The worker sends after commit; SMTP downtime does not block ticket creation. Failed messages retry up to five attempts with increasing delays. Admin Console → **Engineer activity** shows pending/sent/failed/cancelled deliveries and permits an audited retry of failed deliveries. Disabled recipients and assignments that are no longer current are cancelled before delivery.

“Sent” means accepted by the SMTP relay, not confirmed delivery to an inbox. Delivery is at-least-once: a worker crash after SMTP acceptance but before database commit can cause a duplicate. Each delivery has a stable Message-ID. No bounce processing, incoming-mail replies or mailbox integration is implemented. Email includes the ticket reference, priority and authenticated ticket link; it omits descriptions, attachments and internal notes.

### Configure the Ubuntu server

Ask your mail administrator for the approved SMTP host/port, TLS mode and send-as permission for `itecom.d2c@samsung.com`. Confirm whether credentials or IP-based relay authorization is required. An email address alone is not sufficient to send through Samsung's mail infrastructure.

In `/opt/d2c-helpdesk/.env.server`, set:

```dotenv
SMTP_ENABLED=true
SMTP_FROM=itecom.d2c@samsung.com
SMTP_HOST=YOUR_APPROVED_SMTP_RELAY
SMTP_PORT=587
SMTP_SECURITY=starttls
SMTP_USERNAME=
SMTP_PASSWORD=
PUBLIC_ORIGIN=https://107.108.42.60:5050
```

Use `starttls` for mandatory STARTTLS, `tls` for implicit TLS (commonly port 465), or `none` only for an explicitly approved unauthenticated internal relay. Certificate verification is enabled; there is no insecure certificate bypass. Authenticated SMTP requires TLS. For a private relay CA, install that CA in the backend image trust store using your approved image process. Username/password must both be set when authentication is required; otherwise leave both empty. Never commit real credentials.

Apply the configuration and migration:

```bash
cd /opt/d2c-helpdesk
dc() { sudo docker compose --env-file .env.server -p d2c-helpdesk -f docker-compose.yml -f docker-compose.server.yml "$@"; }
dc up -d --build --wait --wait-timeout 300
dc logs --tail=100 worker
```

Allow worker egress to the approved relay port. Create/assign a test ticket to an engineer with a real authorized mailbox, refresh the delivery view, confirm SMTP acceptance and verify receipt in that mailbox. Reassign to a second authorized engineer and repeat. Corporate relay testing has not been performed without the actual configuration.

## Engineer activity tracker

Admin Console → **Engineer activity** provides a historical event table, search by engineer name/email or ticket, event filters, inclusive UTC date filters and pagination. **Download CSV** exports all matching events (up to 10,000); apply narrower filters for larger results. Click Apply filters before downloading to use edited filter values.

- **Assigned:** engineer receiving an assignment at that event, with actor and reason. Includes reassignments, even if the ticket is later assigned elsewhere.
- **Completed:** the person who performed a RESOLVED transition. Administrator resolutions are attributed to the administrator, not falsely credited to the current engineer.
- Closing a ticket is not another completion. Reopening and resolving again creates another completion event. Counts are events, not unique tasks.
- Current status is shown separately from event type. Soft-deleted tickets remain in historical reporting, but their detail link may no longer open.
- Historical ticket titles/user names reflect current values; assignment/completion actor IDs and event timestamps are historical records. This is not a signed external audit archive.

CSV contains event time/type, ticket reference/title, engineer/resolver name/email, actor, current ticket status and assignment detail. Spreadsheet formula prefixes are neutralized. Every export creates `ENGINEER_REPORT_EXPORTED` in Audit Logs. USER and ENGINEER accounts cannot access the report or email delivery APIs.

### API additions

- `GET /api/v1/admin/engineer-activity`: `engineer_id`, `event=all|assigned|completed`, `search`, `date_from`, `date_to`, `offset`, `limit`, `export=true`.
- `GET /api/v1/admin/email-deliveries`: paginated delivery status, no SMTP credentials or server response text.
- `POST /api/v1/admin/email-deliveries/{id}/retry`: retry failed delivery; CSRF and administrator authorization required.

Migration **0004** creates the email queue with ticket/user foreign keys and indexes. Existing assignment/status history is reused for reporting. No historical assignment data is rewritten and no old emails are backfilled.

## Security review impact

Assignment email adds outbound transfer of ticket references and priority to the configured engineer mailbox, plus SMTP credentials when required. Obtain relay/send-as authorization, approve mail retention and include the mail server in the deployment data-flow review. Descriptions/attachments are not sent. The earlier security submission predates this transport; treat this document as its extension, not as approval for email delivery.
