# Security and operations

## Implemented controls

- Argon2 password hashing; 12-character minimum for new/reset passwords.
- Cryptographically random opaque sessions, SHA-256 token hashes at rest, fixed expiry, HttpOnly/SameSite=Strict cookies, secure cookies required in production.
- CSRF tokens on cookie-authenticated mutations; trusted-origin validation on browser login; no session token in localStorage.
- Database-derived RBAC on every request and record-level ticket/attachment authorization.
- Password changes/resets, role changes and account disablement revoke sessions. Five failed attempts lock an account for 15 minutes. Database-backed IP throttling counts failed attempts for unknown and known accounts without penalizing successful users sharing an office IP; PostgreSQL serializes concurrent checks by IP.
- Validated request schemas, bounded fields/page sizes/bulk operations, parameterized queries, safe error envelopes and credential-free structured logs.
- Escaped user content, local-only scripts, CSP, frame denial and MIME sniffing protection. CSV cells beginning with spreadsheet formula prefixes are neutralized.
- File allowlist, MIME and signature/text/ZIP structure validation, safe filenames, 10 MiB limit, 100 attachments per ticket, bounded archives and authorized forced downloads. Files are never extracted or executed on the server.
- Atomic ticket/audit/notification transactions, concurrency locks for assignment/capacity, creation idempotency and unique human-readable ticket references.
- Database triggers reject audit UPDATE, DELETE and PostgreSQL TRUNCATE. There are no audit mutation APIs. A database owner/superuser can still bypass database protections; audit immutability is enforced against application operations, not an administrator controlling the entire database.
- Hashed cross-platform runtime dependency lock. Production containers run the backend as a nonroot user. Runtime dependencies exclude pytest/browser-test tooling.

## Before production deployment

1. Terminate HTTPS at your approved internal ingress. Set `ENVIRONMENT=production`, `COOKIE_SECURE=true`, and the exact trusted origin(s). Use a private network/VPN as appropriate. Local Compose publishes HTTP for development.
2. Use unique database credentials and a restricted application database role. Run migrations with a separate schema-owner identity. The development Compose database role owns its schema; it is not a hardened production database-identity configuration.
3. Grant application SELECT/INSERT/UPDATE on operational tables and sequence usage, but only SELECT/INSERT on `audit_logs`. Do not grant schema ownership, ALTER, DROP, or trigger-disabling privileges. Install `pg_trgm` in `public` using the migration identity.
4. Bootstrap the first production administrator through `python -m app.manage bootstrap-admin`; never run the development seed in production.
5. Back up PostgreSQL (including attachments), encrypt backups, define retention and test restoration. Store secrets in the approved secret manager/environment, not source control.
6. Monitor `/ready`, backend/worker logs, database capacity, failed authentication, unassigned tickets, SLA breaches and storage growth. Run the worker continuously under a process supervisor/Compose restart policy.
7. Size PostgreSQL connection pools and workers for the actual deployment, then load-test concurrent users. The 100k benchmark is a query benchmark, not a 400-concurrent-user certification.

The nginx proxy overwrites forwarded client-address headers, and the backend is not published by Compose. If adding another ingress, configure trusted proxy addresses carefully: do not expose a backend configured to trust arbitrary forwarded headers directly to untrusted networks.

## Session and logging operations

The default lifetime is eight hours. A browser reload restores the session through `/auth/me`; logout revokes it immediately. Password-reset sessions are all revoked, including any active sessions for the affected account. No refresh token or password-reset email provider is configured.

Structured application logs record action type, actor/entity IDs, error type and request ID. They do not record request bodies, password hashes, raw session tokens, passwords or database credentials. Detailed before/after values are stored in the authorized audit ledger. User-provided ticket content can contain personal information, so apply the organization’s access and retention policies to database/audit backups.

## Upload limitations

File-format validation is not malware scanning. DOCX/XLSX/ZIP/PDF files can contain unsafe content even with valid signatures. The service downloads files as `application/octet-stream` with attachment disposition and never previews executable content. Integrate your approved antivirus/quarantine system before enabling broadly untrusted uploads. Archive payloads are bounded, but nested archives are not recursively inspected.

Attachments live in PostgreSQL for transactional consistency. For larger deployments, migrate content to an authorized object-storage adapter with a metadata migration, access-controlled downloads and coordinated retention.

## SLA and delivery boundaries

SLAs use elapsed calendar time, not business calendars. Waiting states do not pause the clock. First response is recorded when staff starts work, posts a comment or resolves/requests information. Notification delivery is in-app only. Email, Slack, Teams, SSO and MFA are extension work requiring organization-specific services and configuration.

Workflow status identities are deliberately stable. Administrators can rename their display labels and change the reopen window; arbitrary new lifecycle states require a reviewed code/schema migration. SLA changes apply to new tickets, priority changes and reopened tickets rather than rewriting historic deadlines.

## Recovery

Do not delete audit records to repair application state. Correct a ticket or configuration through its normal API so a new audit event explains the correction. Take a backup before migrations. Migration downgrades that could destroy data are intentionally disabled; restore a verified database backup if rollback is required.

For development only, `docker compose down -v` removes the entire dataset and permits a clean migration/seed. Never use that command as a production recovery procedure.
