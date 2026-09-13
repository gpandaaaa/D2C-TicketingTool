# Samsung D2C Service Desk

A working internal IT helpdesk built on the supplied FastAPI / SQLAlchemy backend, with PostgreSQL persistence and a responsive Samsung D2C-inspired glass interface. The previously empty frontend is implemented with native JavaScript modules and CSS; nginx serves it and proxies the API through the same origin.

## Run with Docker

Requires Docker Engine/Desktop and Docker Compose v2.

```sh
cp .env.example .env
# Replace POSTGRES_PASSWORD in .env with a random alphanumeric password.
# Example generator: openssl rand -hex 24

docker compose up --build -d
docker compose run --rm seed
```

Open **http://localhost:3000**. API reference: **http://localhost:3000/api/docs**. OpenAPI: `/api/v1/openapi.json`.

The seed is explicit and only runs with `ENVIRONMENT=development`. Normal application startup runs migrations but never creates demo users. An existing database containing users is not reseeded.

| Development account | Role |
| --- | --- |
| `admin@example.local` | Administrator |
| `engineer1@example.local` … `engineer5@example.local` | Engineers |
| `user1@example.local` … `user10@example.local` | Employees |

The development password is the `SEED_PASSWORD` set **when the seed ran**. The example uses `D2C-Local-Only-2026!`. Changing this environment variable later does not reset existing passwords. Never seed a production database.

```sh
docker compose ps
docker compose logs --tail=100 backend worker
docker compose stop                 # Preserve the database
docker compose start
```

## Included functionality

- Login, logout, persistent expiring sessions, Argon2 passwords, CSRF checks, account lockout and IP rate limits. Password changes and administrator resets revoke sessions.
- Backend RBAC for ADMIN, ENGINEER and USER, with legacy role compatibility. Requesters see their own tickets; engineers work on assigned tickets and can also submit personal requests.
- Admin account creation, profile editing, enable/disable, roles, password reset, employee IDs, teams, departments, locations, phone numbers, last login, activity and ticket history.
- Engineer skills and subskills, availability, capacity, current utilization, completed tickets, SLA breaches and average resolution time.
- Ticket creation with unique `D2C-YYYY-NNNNNN` references, retry-safe creation, categories/subcategories, priorities, routing attributes and database-backed SLA deadlines.
- Controlled lifecycle, resolutions, closure, reopening windows, cancellation and soft deletion. Private staff notes stay private even when an engineer is the requester of a ticket assigned to someone else.
- Automatic assignment with category eligibility, capacity limits, configurable scoring, workload balancing, round-robin and optional generalist fallback. Manual reassignment and atomic bulk assignment, priority/status changes, selected-ticket CSV export.
- Ticket comments, paginated activity history, validated attachments, upload progress and authorized downloads.
- In-app notifications, read state, configurable warning windows and a separate SLA worker with deduplicated delivery.
- Role-specific dashboards, analytics, search, filters, SQL pagination, engineer workloads and read-only audit search with event details.
- Category, subcategory, team, location, SLA, assignment, notification and workflow-label configuration.
- Knowledge-base browsing/search and staff publishing. Existing asset and asset-history APIs retained.
- Light/dark themes, mobile navigation, responsive tables, loading/error/empty states, confirmations and feedback.

## Architecture and project structure

```text
frontend/                  Native browser modules, CSS, nginx and Dockerfile
  api.js                   Session-aware API client and upload progress
  app.js                   Login, navigation, routing and account screens
  tickets.js               Ticket list, creation, conversation and actions
  admin.js                 User/engineer/configuration/audit interfaces
  dashboard.js             Role-specific metrics and charts
backend/
  app/api/                 Auth, tickets, admin, reporting, attachments, legacy APIs
  app/services/            Transactional assignment, workflow, audit, SLA scan
  app/models/entities.py   SQLAlchemy relational entities
  app/schemas/             Validated API request schemas
  app/core/                Settings, database and password security
  app/worker.py            SLA notification worker
  app/seed.py              Explicit development dataset
  app/manage.py            First administrator bootstrap
  app/static/              Offline API reference (no external CDN)
  migrations/              Versioned baseline and additive migrations
  tests/                   Business, security and PostgreSQL concurrency tests
scripts/                   Live Chromium acceptance and isolated 100k benchmark
docs/                      Architecture, security, API and verification documents
```

See [architecture](docs/ARCHITECTURE.md), [API overview](docs/API.md), [security and operations](docs/SECURITY.md), and [verification](docs/VERIFICATION.md).

## Environment variables

| Variable | Purpose |
| --- | --- |
| `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` | Compose PostgreSQL credentials. Use an alphanumeric password or correctly URL-encode reserved characters. |
| `DATABASE_URL` | Backend SQLAlchemy DSN outside Compose. Compose supplies a `postgres` service hostname. |
| `ENVIRONMENT` | `development` or `production`. Production disables demo seeding and requires PostgreSQL plus secure cookies. |
| `COOKIE_SECURE` | `true` for HTTPS production; `false` only for local HTTP. |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Session lifetime, default 480 minutes. The legacy environment name is retained although sessions are opaque, not JWTs. |
| `CORS_ORIGINS` | Comma-separated trusted origins, default `http://localhost:3000`. |
| `MAX_UPLOAD_BYTES` | Backend upload limit, default 10 MiB. Align nginx’s request limit when changing it. |
| `APP_PORT` | Published frontend port, default 3000. |
| `SEED_PASSWORD` | Required for explicit development seeding. Minimum 12 characters. |
| `BOOTSTRAP_PASSWORD` | Optional CLI bootstrap password; otherwise entered through a hidden interactive prompt. |
| `TEST_DATABASE_URL` | Optional isolated PostgreSQL integration-test/benchmark database. |
| `APP_URL`, `CHROME_PATH` | Live browser acceptance target and Chromium/Chrome executable. |

No signing secret or hardcoded application password is required. Session tokens are generated cryptographically and only their hashes are persisted.

## Local development without Docker

Requires Python 3.12+, PostgreSQL 16+, and a database created for this application. Node is only needed for optional JavaScript formatting, not to run the frontend.

```sh
python3.12 -m venv .venv
.venv/bin/pip install -r backend/requirements-dev.txt
export DATABASE_URL='postgresql+psycopg://USER:PASSWORD@127.0.0.1:5432/helpdesk'
cd backend
../.venv/bin/alembic upgrade head
SEED_PASSWORD='D2C-Local-Only-2026!' ../.venv/bin/python -m app.seed
../.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Open http://127.0.0.1:8000. The backend serves the frontend directly in local development. Start the worker separately from `backend/` with the same environment:

```sh
../.venv/bin/python -m app.worker
```

SQLite is available for quick isolated tests and smoke development; PostgreSQL is required in production and for concurrency guarantees.

## Database migrations, seed and reset

```sh
# Docker: startup applies pending migrations automatically.
docker compose exec backend alembic current
docker compose exec backend alembic upgrade head
docker compose run --rm seed

# Local, from backend/
alembic upgrade head
python -m app.seed
```

Migrations:

1. `0001`: frozen baseline of the original users/tickets/assets/knowledge/audit schema.
2. `0002`: additive enterprise fields, role/status enum additions, engineers/skills, sessions, login attempts, subcategories, teams/locations, assignments, status history, notifications, attachments, settings, indexes and immutable audit triggers.
3. `0003`: idempotency records for retried ticket creation.

Existing databases created by the original `create_all` setup are handled by the baseline’s table checks. Back up first, test the migration on a copy, and ensure the existing schema matches the supplied baseline. Do not stamp an arbitrary unrelated schema. PostgreSQL migrations install `pg_trgm`; the migration identity needs permission to install it or it must be preinstalled in `public`.

Destructive downgrades are disabled. Restore a verified backup to roll back database changes. A **local development reset deletes all data**:

```sh
docker compose down -v
docker compose up --build -d
docker compose run --rm seed
```

For a fresh production database, bootstrap the first administrator without demo data:

```sh
docker compose exec backend python -m app.manage bootstrap-admin \
  --email admin@your-company.example --name 'Service Desk Administrator'
```

Configure categories, teams, locations and engineers in the Admin Console before accepting tickets.

## RBAC and workflow

| Role | Ticket visibility | Mutations | Administration |
| --- | --- | --- | --- |
| ADMIN | All nondeleted tickets | Edit, assign, resolve, close, reopen, cancel, soft-delete, bulk operations | Full |
| ENGINEER | Assigned tickets and their own requests | Status/resolution/internal comments on assigned tickets; requester controls on personal tickets assigned elsewhere | None |
| USER | Own requests | Create, comment, attach, close resolved tickets, reopen within policy | None |

Legacy `SUPER_ADMIN`/`IT_ADMIN` map to administrator permissions, `IT_AGENT` to engineer permissions, and `EMPLOYEE`/`MANAGER` to requester permissions. Roles come from the database on each request. Role and account-state changes revoke sessions.

New tickets start OPEN. Automatic assignment moves them to ASSIGNED. Engineers progress through IN_PROGRESS and WAITING_FOR_USER / WAITING_FOR_VENDOR to RESOLVED. Resolution text is mandatory. Requesters close resolved tickets and may reopen within the configured window. Reopening recalculates SLA and reassesses assignment. Administrators can override transition paths, but cannot put an unassigned ticket into an engineer-work state or close a ticket without a resolution timestamp. Legacy statuses remain readable.

## Assignment algorithm

Assignment runs server-side inside the ticket transaction. PostgreSQL advisory locks serialize assignment and capacity edits; concurrent requests cannot overfill an engineer. Engineers must have an enabled account, engineer role, availability and spare capacity. Category skills are required unless the administrator enables generalist fallback.

- **Least workload:** lowest active ticket count, then least recent assignment, then stable user ID.
- **Round-robin:** least recent assignment, then user ID, still respecting eligibility and capacity.
- **Scored:** weighted category/subcategory match, team/location match, free capacity and lower existing priority/SLA pressure. Urgent incoming tickets give additional weight to available urgency capacity. Every weight is configurable.

Priority pressure uses higher weight for existing critical/high tickets and adds pressure when their SLA is approaching or breached. Ties use assignment history. If no engineer qualifies, the ticket stays visible in Unassigned with a recorded reason and an administrator notification. Existing unassigned tickets are manually assigned; they are not silently rerouted when configuration changes.

## Tests and verification

```sh
.venv/bin/pytest
TEST_DATABASE_URL='postgresql+psycopg://USER:PASSWORD@localhost:5432/helpdesk_test' .venv/bin/pytest
.venv/bin/ruff check backend scripts
.venv/bin/ruff format --check backend scripts
.venv/bin/pip-audit -r backend/requirements.txt

# Requires a running, seeded app and a Chromium/Chrome executable.
APP_URL=http://localhost:3000 CHROME_PATH=/path/to/chrome \
  .venv/bin/python scripts/browser_acceptance.py

# Dedicated test database only; synthetic data exists in a disposable schema.
TEST_DATABASE_URL='postgresql+psycopg://USER:PASSWORD@localhost:5432/helpdesk_test' \
  .venv/bin/python scripts/benchmark.py
```

Integration tests use isolated schemas. The browser test creates real development records; do not point it at production. Screenshots/results go to ignored `artifacts/`.

Dependencies are pinned with cross-platform hashes. Runtime and development dependencies are separate. To regenerate locks using `uv`:

```sh
uv pip compile backend/requirements.in --universal --python-version 3.12 --generate-hashes -o backend/requirements.txt
uv pip compile backend/requirements-dev.in --universal --python-version 3.12 --generate-hashes -o backend/requirements-dev.txt
```

## Operational boundaries

The local system is implemented and exercised end-to-end. Production rollout still requires your infrastructure’s HTTPS termination, restricted database identity, backups/restore testing, monitoring, and organizational security review. SSO/MFA, email/Slack/Teams delivery, malware scanning and business-hours calendars are not connected. The in-app notification/outbox structure and worker provide extension points. Attachments are stored in PostgreSQL and use format validation; they are not antivirus-scanned. SLA targets use elapsed calendar time, including waiting states. See [security](docs/SECURITY.md) for details.

The final local verification recorded **40 passing PostgreSQL tests**, **39 passing SQLite tests** plus the PostgreSQL-only skip, successful browser and live worker acceptance, successful clean-volume Docker startup, and no known runtime dependency vulnerabilities. Full evidence and benchmark limitations are in [VERIFICATION.md](docs/VERIFICATION.md).

In this prepared workspace, the installed test tools are under `.runtime/bin/`. `make test` and `make lint` automatically use that environment (or `.venv` when present in a fresh setup). `make up`, `make seed`, and `make browser` provide shortcuts for the Docker and browser commands above.

## Hosting on the internal server

For **107.108.42.60**, use the [server deployment guide](docs/SERVER_DEPLOYMENT.md), [production Compose override](docker-compose.server.yml), and [server environment example](deploy/server.env.example). The server configuration serves HTTPS on port 5050, enforces secure sessions, and keeps the database and backend private. It requires an internal CA certificate valid for the server IP (or an internal hostname). Local development commands remain unchanged.

For Windows Server 2025 / Windows 11 installation on **https://107.108.42.60:5050**, use the [step-by-step illustrated guide](docs/WINDOWS_INSTALLATION.md).
