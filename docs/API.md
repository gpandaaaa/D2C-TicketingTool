# API overview

The live, offline reference at `/api/docs` is generated from `/api/v1/openapi.json`. It lists exact current request schemas and parameters. This document explains the endpoint groups and authorization model.

## Authentication

| Method | Path (under `/api/v1`) | Behavior |
| --- | --- | --- |
| POST | `/auth/login` | Email/password login; sets HttpOnly session cookie and returns user profile plus CSRF token |
| GET | `/auth/me`, `/me` | Current profile and CSRF token; requires active, unexpired session |
| POST | `/auth/logout` | Revokes the current session and clears cookie |
| POST | `/auth/password` | Verifies current password, changes password, revokes all sessions |

Browser requests use cookies. State-changing requests include `X-CSRF-Token`. There is no role claim accepted from the browser. The login route has account lockout after five failed attempts and a 30-failed-attempt/15-minute limit per client IP.

## Tickets and related data

| Method | Path | Authorization / behavior |
| --- | --- | --- |
| GET | `/tickets` | Scoped list with search, status, priority, category, requester, engineer, team/location, dates, SLA and assignment filters |
| POST | `/tickets` | Authenticated creation; optional `Idempotency-Key`; calculates SLA and assigns in the same transaction |
| GET | `/tickets/{id}` | Scoped details, first 100 comments/activity events, totals and attachment metadata |
| PATCH | `/tickets/{id}` | Administrator edits; assigned engineer workflow/resolution; requester closure/reopening |
| DELETE | `/tickets/{id}` | Administrator cancellation and soft deletion |
| POST | `/tickets/{id}/comments` | Scoped comment; internal notes only for administrators/assigned engineer |
| GET | `/tickets/{id}/conversation` | Paginated comments, including author names and internal-note filtering |
| GET | `/tickets/{id}/activity` | Paginated, requester-safe ticket activity |
| POST | `/tickets/{id}/assign`, `/reassign` | Administrator assignment/reassignment with reason; availability/capacity enforced |
| POST | `/tickets/{id}/attachments` | Scoped multipart upload using field `file` |
| GET | `/tickets/{id}/attachments/{attachment_id}` | Authorized forced download |
| POST | `/tickets/bulk` | Administrator atomic updates, at most 100 distinct selected records |
| GET | `/tickets/export?ids=1,2` | Administrator CSV export, up to 100 selected tickets; spreadsheet formula neutralization |

Ticket list sorting: `newest`, `oldest`, `updated`, `sla`. `offset` is nonnegative and `limit` is 1–100. Default page size is 25. All searches use parameterized SQL. Date-only upper bounds include the selected day.

Creation example:

```json
{
  "title": "VPN connection keeps dropping",
  "description": "Connection drops after a few minutes. Error code 100.",
  "category_id": 4,
  "subcategory_id": null,
  "priority": "HIGH",
  "location": "Bengaluru",
  "team": "Infrastructure"
}
```

Use category IDs returned by `/configuration`; IDs in this example are illustrative, not a fixed contract. The returned ticket contains its reference, status, assignee, response deadline and resolution deadline.

## Administration

| Method | Path | Behavior |
| --- | --- | --- |
| GET/POST | `/admin/users` | Paginated account search / create |
| GET/PATCH/DELETE | `/admin/users/{id}` | View / edit / deactivate |
| POST | `/admin/users/{id}/password` | Reset password, unlock and revoke sessions |
| GET/POST | `/admin/engineers` | Workload/skills search / create engineer |
| PATCH | `/admin/engineers/{id}` | Availability, capacity, category and subcategory skills |
| POST | `/admin/config/{resource}` | Create categories, subcategories, teams or locations |
| PATCH | `/admin/config/{resource}/{id}` | Rename or enable/disable configuration record |
| PUT | `/admin/sla/{priority}` | Response/resolution target minutes |
| PUT | `/admin/settings/assignment` | Assignment enablement, fallback, strategy and scoring weights |
| PUT | `/admin/settings/workflow` | Reopen window and display labels for stable statuses/priorities |
| PUT | `/admin/settings/notifications` | In-app delivery and SLA warning window |
| GET | `/admin/audit-logs` | Search, actor/action/entity/ticket/date filtering, sorting and pagination |
| GET | `/admin/dashboard` | Administrator metrics |

Disabling/deleting a user is deactivation. Administrator self-demotion/self-disable is blocked. Engineers must have active tickets reassigned before role removal/deactivation. Reducing capacity below current workload is rejected.

## Shared reporting and configuration

- `GET /dashboard` and `/reports/dashboard`: role-scoped metrics, daily volume, priority/category/status/location/engineer charts and workload.
- `GET /configuration`: categories/subcategories, teams/locations, SLA policies, labels and business-rule configuration.
- `GET /categories`: active categories.
- `GET /notifications`: paginated own notifications and unread count.
- `PATCH /notifications/{id}`: mark own notification read.
- `POST /notifications/read-all`: mark all own notifications read.
- Legacy aliases `/users` and `/audit-logs` remain administrator-protected.

## Preserved APIs

- `GET/POST /assets`: scoped assets / staff asset creation.
- `POST /assets/{id}/assign`: staff assignment.
- `GET /assets/{id}/history`: asset-authorized history.
- `GET/POST /knowledge`: published article search / staff publishing.

These existing list endpoints return bounded arrays rather than the new paginated envelope.

## Errors

Errors do not expose passwords, SQL, tokens, or stack traces:

```json
{
  "success": false,
  "error": {
    "code": "CONFLICT",
    "message": "Engineer is at capacity"
  }
}
```

Typical statuses: 401 unauthenticated, 403 forbidden, 404 missing/out-of-scope entity, 409 invalid transition/conflict, 413 too large, 422 validation, 429 rate limit. Request IDs are returned in `X-Request-ID`. API request bodies and credentials are not written to application logs.
