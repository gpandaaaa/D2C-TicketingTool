# Verification report

Verified locally on **13 September 2026** using Python 3.12, PostgreSQL 16, Chromium/Google Chrome, Docker Engine through Colima, and Docker Compose.

## Automated backend verification

| Check | Result |
| --- | --- |
| PostgreSQL suite | **40 passed** |
| SQLite suite | **39 passed, 1 skipped** (PostgreSQL-specific concurrency test) |
| Ruff checks | Passed |
| Python formatting checks | Passed |
| Runtime dependency audit | **No known vulnerabilities found** at verification time |
| Legacy schema upgrade | Original users, legacy roles, ticket references/descriptions and audit records retained; repeat upgrade is safe |

Two upstream test-library deprecation warnings remain (`httpx`/Starlette TestClient and an AnyIO alias). They do not affect application startup or test outcomes. They are not suppressed by application code.

Tests cover:

- Correct/incorrect/disabled-account login, lockout, failed-login IP throttling, successful logins behind a shared office IP, logout, expiry, CSRF/origin checks, password changes and resets.
- ADMIN/ENGINEER/USER restrictions, private-note visibility, out-of-scope reads/writes/downloads, engineer personal requests, safe profile editing and legacy roles.
- User/engineer creation and configuration, duplicate records, capacity guards, enabled/disabled states, SLA/configuration validation.
- Ticket creation, unique references, retry idempotency, controlled transitions, required resolutions, comments, resolution/closure/reopening windows and soft deletion.
- Skill matching, no match, disabled/unavailable/capacity-full engineers, workload balancing, configured round-robin, generalist fallback, scored location selection, manual reassignment and concurrent capacity enforcement.
- Atomic bulk updates and rollback, search by reference/requester/employee ID, filters, pagination, selected-ticket CSV export and long conversation paging.
- Valid and rejected uploads, oversized/empty files, spoofed formats, unsafe archives and authorized downloads.
- Immutable audit UPDATE/DELETE rejection, complete lifecycle events, actor/request context, filters and pagination.
- SLA deadline calculations, approaching/breached notifications, deduplication and notification ownership/read state.
- Preserved asset assignment/history and knowledge publishing/search APIs.

Evidence: `artifacts/postgres-tests.log`, `artifacts/sqlite-tests.log`, `artifacts/dependency-audit-final.json`.

## Real browser acceptance

The live browser script passed against the primary Docker app at `http://localhost:3000` and a separately created clean Docker app at port 3001.

Verified sequence:

1. Administrator login and dashboard; light/dark screenshots; theme persistence across reload.
2. Profile save without unintended logout; account creation; engineer/configuration/audit/analytics screens.
3. Employee login; ticket creation; description/category/priority form; real TXT upload.
4. Automatic engineer selection read back from the persisted ticket.
5. Requester comment, engineer login, start work, resolution with text.
6. Requester login, visible resolution, closure, notification read actions.
7. Mobile viewport at 390 × 844 without document-level horizontal overflow; mobile navigation.
8. Offline API reference loads and filters attachment endpoints.

No JavaScript page errors were captured. Screenshots cover dashboards, creation, ticket detail, analytics and mobile layout. Evidence: `artifacts/browser-acceptance.log`, `artifacts/docker-clean-browser.log`, `artifacts/browser-result.json`, and PNGs under `artifacts/`.

## Docker and background processing

- `docker compose up --build -d` succeeded with PostgreSQL, backend, frontend and worker.
- A separate `d2c-clean` project started with an empty volume, ran migrations from the original baseline through `0003`, loaded **1 admin, 5 engineers, 10 users and 12 tickets**, and passed live browser acceptance.
- Backend, frontend and PostgreSQL health checks passed; the worker remained running.
- The real worker delivered two `SLA_BREACHED` notifications (requester and engineer) within its polling interval. The verification ticket was then resolved and closed with audit history.
- The temporary clean project and its volume were removed. The primary application and its data remain running at **http://localhost:3000**.

Evidence: `artifacts/docker-build.log`, `artifacts/docker-clean-build.log`, `artifacts/docker-clean-seed.log`, `artifacts/docker-clean-status.log`, `artifacts/worker-acceptance.log`.

Reproduce worker verification on development seed data:

```sh
docker compose exec -T backend python < scripts/worker_acceptance.py
```

## 100,000-ticket query benchmark

A disposable PostgreSQL schema contained 100,000 synthetic tickets, 501 users and 50 engineers. Three authenticated requests were measured per endpoint on this development machine.

| Operation | Median | Maximum |
| --- | ---: | ---: |
| Ticket list, first 25 | 30.0 ms | 39.4 ms |
| Global search for a ticket reference | 205.8 ms | 206.0 ms |
| Status + priority filter | 8.8 ms | 9.8 ms |
| Deep page at offset 99,975 | 55.6 ms | 56.9 ms |
| Dashboard aggregates | 197.8 ms | 236.4 ms |
| Workload list for 50 engineers | 36.3 ms | 39.4 ms |

SLA scan with no due candidates in this dataset: 2.7 ms. Actual due-event delivery was verified separately by unit tests and the live worker check. The benchmark schema was removed afterward.

These are local API/query timings, **not** production network measurements or a test of 400 concurrent users. Use representative traffic and production-sized infrastructure for capacity planning. Evidence: `artifacts/benchmark.json` and `scripts/benchmark.py`.

## Issues found and corrected

- Incorrect pagination on the original SQLAlchemy `ScalarResult` and unrestricted ticket/user serialization.
- PostgreSQL timestamp offset handling that could extend session validity incorrectly.
- A mobile grid’s intrinsic table width causing viewport overflow.
- Missing cross-platform transitive dependencies in the first macOS-generated hash lock; the final lock is universal and builds on Linux.
- PostgreSQL extension placement in parallel disposable schemas; trigram operators are explicitly installed/referenced in `public`.
- Engineer personal requests needing requester visibility without gaining work privileges on another engineer’s ticket.
- Profile forms preserving legacy roles/routing values and avoiding unnecessary session revocation.
- Successful users sharing an office IP no longer consume the failed-login throttle.

## Deployment boundaries

The implemented local product is functional and tested. Organization-specific HTTPS ingress, restricted production database roles, backup/restore policy, observability, SSO/MFA, external notification delivery, malware scanning and business calendars are not claimed as configured. See [SECURITY.md](SECURITY.md) for the exact boundary and rollout requirements.

## Security review addendum — 13 September 2026

The security submission identified and corrected a CSRF exemption based on the presence of any Authorization header. The exemption now follows the selected Bearer authentication path. Cookie-authenticated mutations with Basic, malformed or unsupported lowercase authorization headers still require the CSRF token.

After this correction, `.runtime/bin/pytest -q` passed **42 SQLite tests**, with **1 PostgreSQL-only skip** and the same two upstream deprecation warnings. Ruff checks passed for the changed authentication dependency and tests. The PostgreSQL suite and browser acceptance were not rerun for this addendum; their earlier results above remain historical evidence. See [Security Review Submission](SECURITY_REVIEW.md) for review findings and production dependencies.
