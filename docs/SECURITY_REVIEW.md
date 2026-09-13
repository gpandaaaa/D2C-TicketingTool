# Samsung D2C IT Service Desk — Security Review Submission

**Classification:** Proposed Internal Confidential; confirm with the data owner.

| Document control | Value |
|---|---|
| Prepared | 13 September 2026 |
| Purpose | Architecture and application security review before production deployment |
| Target | Ubuntu Server 24.04 LTS, `https://107.108.42.60:5050` |
| Source repository | Private repository: [gpandaaaa/D2C-TicketingTool](https://github.com/gpandaaaa/D2C-TicketingTool) |
| Baseline reviewed | `f4ebea9`, with the accompanying CSRF correction and regression tests in this submission |
| Status | Submitted for review; **not approved for production** |
| Business / technical owners | To be assigned by Samsung D2C |
| Security reviewer / decision date | To be recorded by the security team |

## 1. Executive assessment

The platform supports employee IT requests, engineer assignment and resolution, administrative configuration, attachments, notifications and audit history. Core controls include database-enforced ticket scoping, server-side roles, hashed passwords and session tokens, CSRF validation, bounded uploads and application-level immutable audit records.

Local functional testing is recorded in [VERIFICATION.md](VERIFICATION.md). This is not an independent penetration test, a compliance certification or evidence that the target Ubuntu server is deployed securely. Security approval should address the open items in section 9 before employee production data is introduced.

The principal unresolved risks are the schema-owner database identity used by Compose, missing attachment malware scanning, absent SSO/MFA integration, and unconfigured operational controls for encryption at rest, backup recovery, monitoring and retention. Their priorities below are proposed engineering assessments; the security team owns final severity and acceptance.

## 2. Scope and intended use

**In scope:** browser frontend; Nginx TLS proxy; FastAPI APIs; authentication and authorization; PostgreSQL and stored attachments; SLA worker; migrations; Docker deployment; configuration/secrets; audit history; repository and dependency handling.

**Deployment assumption:** Ubuntu directly owns `107.108.42.60`. Employees reach TCP 5050 over approved corporate routes. The address alone does not prove network isolation; infrastructure must demonstrate the actual access controls.

**Outside implemented scope:** enterprise identity federation, MFA, antivirus/quarantine, SIEM integration, high availability, external email/Slack/Teams delivery, managed secret rotation and automated retention. These are review dependencies, not controls claimed by this submission.

## 3. Architecture and trust boundaries

![Ubuntu service architecture](images/ubuntu-network.png)

| Boundary / flow | Data and protection | Review note |
|---|---|---|
| Employee browser → Ubuntu:5050 | Credentials, session cookie, ticket content and files over TLS 1.2/1.3 | Approved CA; certificate SAN `IP:107.108.42.60`; client trust required |
| Host:5050 → Nginx:443 | Docker port mapping; Nginx terminates TLS | No HTTP endpoint is published by the server override |
| Nginx → FastAPI:8000 | Internal HTTP carrying authenticated requests | Private Docker network; no backend host port; no internal mTLS |
| FastAPI / worker → PostgreSQL:5432 | SQL, tickets, identities, audit and attachment bytes | Private Docker network; database TLS is not configured by this stack |
| Operator → Ubuntu / Docker | SSH and privileged administration | Host administrators and Docker operators can access service secrets/data |
| Backup/export → authorized storage | Database dumps or selected CSV records | Encryption, destination control and retention must be configured operationally |

Nginx overwrites forwarded client-address headers. Uvicorn currently trusts forwarded headers from all sources, relying on the unpublished backend network boundary. Do not publish backend port 8000. Reassess trust configuration if introducing another proxy, unrelated containers on this network, or remote backend access.

The direct Ubuntu design avoids the original-client-IP loss associated with Windows TCP portproxy. Any infrastructure NAT/proxy still needs verification of the actual recorded client address.

Runtime dependencies are PostgreSQL 16, Python 3.12/FastAPI/SQLAlchemy, Nginx, native JavaScript and a separate worker. Build-time egress includes GitHub, package repositories and container registries. No external notification or telemetry integration is configured in application code; infrastructure services may generate their own operational traffic.

## 4. Data inventory and handling

| Data class | Examples / location | Access and retention considerations |
|---|---|---|
| Employee identity | Name, employee ID, email, department, team, phone, location, role | PostgreSQL; authorized user/admin API responses; classification and retention need approval |
| Authentication | Password hashes, session-token hashes, session CSRF values, login counters | PostgreSQL; passwords and raw session tokens are not returned in normal account responses |
| Ticket/conversation | Issue text, requester, assignment, priority, resolution, comments, internal notes | Requester/assigned engineer/admin scoping; internal notes have restricted visibility |
| Attachments | IT evidence including possible personal or business information | PostgreSQL binary content; authorized download; no malware scanner |
| Audit | Actor, action, entity, before/after values, timestamp, IP, user agent and metadata | Admin audit view; may contain personal/business information |
| Notifications | Recipient and ticket activity | Recipient-specific reads; in-app only |
| Backups/exports | Database dumps and selected-ticket CSV | Copies remain sensitive and require controlled access and disposal |

Users must not submit passwords, access tokens or unnecessary customer/payment information in tickets. The application does not provide automated DLP or content redaction. Ticket deletion is soft deletion, not erasure of all associated data. Retention schedules, legal holds, account lifecycle and deletion procedures require a documented data-owner decision.

Disk, database-volume and backup encryption are **not configured by this repository**. TLS at the browser boundary does not provide encryption at rest or protect against a privileged host administrator.

## 5. Authentication, sessions and authorization

| Control | Implemented behavior | Evidence |
|---|---|---|
| Password storage | Argon2 via password-hashing library; minimum 12 characters on new/reset passwords | `backend/app/core/security.py`, `backend/app/schemas/enterprise.py` |
| Session storage | Cryptographically random opaque token; SHA-256 digest persisted; fixed expiry | `backend/app/api/auth.py`, `backend/app/api/deps.py` |
| Browser cookie | HttpOnly, SameSite=Strict; Secure required in production | `backend/app/api/auth.py`, `backend/app/core/config.py` |
| Lifetime | Default eight hours; configured through environment; no sliding/refresh-token system | `ACCESS_TOKEN_EXPIRE_MINUTES` |
| Revocation | Logout, password change/reset, account disablement and actual role changes revoke affected sessions | Auth/admin routes and tests |
| Failed-login controls | Five account failures lock for 15 minutes; 30 failed attempts per IP in 15 minutes are throttled | `backend/app/api/auth.py` |
| CSRF | Cookie-authenticated mutations require session-bound X-CSRF-Token | `backend/app/api/deps.py`; correction described below |
| Origin validation | Browser login origin validation and configured CORS origins | `backend/app/main.py` |
| Backend roles | Roles loaded from the database rather than frontend claims | `backend/app/api/deps.py` |
| Record authorization | Ticket, comment, internal-note, attachment and notification ownership/scope checks | API modules and authorization tests |

The API also accepts an opaque session token through `Authorization: Bearer ...`; it is not a separate JWT or integration credential. Valid bearer-authenticated mutations do not require cookie CSRF protection. Frontend authentication uses cookies and does not persist the session token in localStorage. Theme preference is stored locally.

**Correction accompanying this review:** the original CSRF exemption tested whether any Authorization header was present. An unrelated header could therefore skip CSRF validation while retaining cookie authentication. The exemption now follows the selected Bearer authentication path; regression cases cover Basic, malformed and unsupported lowercase header forms. This correction must be deployed before approval. It is not evidence that no other vulnerabilities exist.

| Role | Ticket scope | Privileged operations |
|---|---|---|
| USER | Own requests | Create, comment, attach, close resolved tickets, reopen within policy |
| ENGINEER | Assigned tickets plus own requests | Work/status/resolution on assigned tickets; requester controls on personal requests |
| ADMIN | All nondeleted tickets | User/engineer/configuration management, assignment, audit review and bulk operations |

Legacy administrative/engineer/requester role names map to centralized permission gates. The application has no independent approval workflow for privileged administrative changes. Admin password reset is available; self-service reset email, SSO and MFA are not configured.

## 6. Application, attachment and audit controls

| Area | Implemented protection | Residual limitation |
|---|---|---|
| Input and SQL | Typed validation, bounded fields/pages/batches and parameterized ORM queries | Independent injection testing still required |
| Browser rendering | User-content escaping, CSP, frame denial, MIME sniff protection | CSP permits inline styles; no claim of browser hardening certification |
| Uploads | Allowlist, MIME/signature/text/archive checks, 10 MiB per file and 100 attachments per ticket | No antivirus, sandbox or quarantine; nested archive contents not recursively inspected |
| Downloads | Record authorization, safe filename, forced attachment disposition and octet-stream response | Downloaded documents may still harm client applications |
| CSV export | Formula-prefix neutralization; bounded selected-ticket export | Authorized export can still copy sensitive data outside the platform |
| Workflow integrity | Backend transition rules, required resolution, assignment/capacity locks and transaction boundaries | Admins can override permitted workflow paths |
| Idempotency | Requester-scoped ticket-creation idempotency keys and conflict checks | Not a blanket replay-prevention system for every API |
| Audit records | No mutation API; DB triggers reject UPDATE/DELETE and PostgreSQL TRUNCATE | Schema owner/superuser can bypass triggers; no external WORM ledger or signing |
| Application logs | Structured events, request IDs and safe error envelopes; no intended credential/body logging | Audit metadata and URL/request context still need retention/access review |

Allowed attachment extensions include PNG/JPG/JPEG, PDF, TXT/LOG/CSV, DOCX/XLSX and ZIP. Files are stored rather than extracted or executed by the service. Format validation is not a malware-free guarantee.

## 7. Deployment and operations

The server configuration uses `PUBLIC_ORIGIN=https://107.108.42.60:5050`, secure cookies, PostgreSQL persistence and a TLS Nginx listener. See [Ubuntu installation guide](UBUNTU_INSTALLATION.md), [Compose override](../docker-compose.server.yml) and [TLS configuration](../deploy/nginx.conf).

- Only TCP 5050 is published by the server override. Access must be limited to approved employee routes; management SSH must be restricted separately. Docker-published ports need upstream or Docker-aware firewall enforcement, not reliance on UFW alone.
- Backend runs as a nonroot container user. This is not a claim that every container process is nonroot, that filesystems are read-only, or that capabilities have been minimized.
- Runtime Python dependencies have version/hash locks. Container base images are version-tagged, not digest-pinned; a Python dependency audit does not scan the OS/container layers.
- `.env.server`, certificate private keys, local databases and artifacts are ignored by Git. Docker/host administrators can inspect runtime secrets. A managed secret store and rotation workflow are not integrated.
- Migrations run at backend startup using the same database credentials. Separating migration and runtime identities requires a deployment change; it is not achieved simply by changing a username.
- PostgreSQL data and attachments share a named volume. This is a single-host deployment, with no implemented failover or availability SLA.
- Health checks verify frontend/backend/database availability; the worker has a restart policy. Continuous worker liveness alerting, SIEM forwarding and alert ownership require infrastructure setup.

## 8. Verification evidence and limits

The historical verification on 13 September 2026 recorded 40 PostgreSQL tests passing, 39 SQLite tests passing with one PostgreSQL-specific skip, clean-volume Docker startup, browser ticket lifecycle acceptance, real-worker notification delivery and no known runtime Python dependency vulnerabilities at that time. See [VERIFICATION.md](VERIFICATION.md) for scope and commands.

That evidence predates the CSRF correction accompanying this document. Its new test run is recorded in the review addendum in VERIFICATION.md. Local evidence files under `artifacts/` are intentionally excluded from GitHub; reviewers need a controlled evidence transfer or a reproduced CI/staging run. Historical counts are not a claim of a current vulnerability-free release.

The 100,000-ticket measurement is a local query benchmark, not a 400-user concurrency, denial-of-service or disaster-recovery test. No independent penetration-test report, container vulnerability scan, target-host hardening report, production certificate validation, approved firewall evidence or production restore exercise is supplied by this repository.

## 9. Open risks and requested dispositions

Proposed priorities are qualitative and are not CVSS scores. Each item needs a named owner, due date, evidence and security disposition.

| ID | Proposed priority | Gap / consequence | Required action or explicit acceptance | Suggested owner |
|---|---|---|---|---|
| SEC-01 | High | Runtime DB role owns schema; compromise may bypass audit protections | Separate schema-owner migration identity from least-privilege runtime role; prove audit privilege restrictions | DBA / platform |
| SEC-02 | High | Valid-format attachments may contain malware | Integrate approved scanning/quarantine; restrict upload use until an approved control exists | Security / engineering |
| SEC-03 | High | Privileged access relies on local passwords without MFA | Integrate approved SSO/MFA or document time-bound compensating controls and acceptance | IAM / security |
| SEC-04 | High | Target TLS and network restrictions not verified | Install trusted certificate, validate SAN/expiry, prove allowed/denied network tests | Network / platform |
| SEC-05 | High | Backup, encryption and recovery operations unverified | Configure protected off-host backups and storage encryption; approve RPO/RTO and prove restore | Platform / DBA |
| SEC-06 | Medium | Internal HTTP/DB connections unencrypted | Assess single-host trust boundary; use approved transport protection if services span hosts | Platform / security |
| SEC-07 | Medium | No independent VAPT, container scan or current release-wide assessment | Perform authenticated role-based testing and dependency/container/host scans | AppSec |
| SEC-08 | Medium | Audit/log retention, SIEM and tamper-resistant external archive absent | Approve retention, alerts, access and independent audit export/storage | SOC / data owner |
| SEC-09 | Medium | Host and Docker admins control secrets/data; image/container hardening incomplete | Apply host baseline, restricted administration, patching, digest policy and secret rotation | Platform |
| SEC-10 | Medium | No automated DLP/retention or comprehensive erasure workflow | Classify data, define acceptable content and lifecycle procedures | Data owner / privacy |
| SEC-11 | Medium | Single-host outage and limited abuse/capacity evidence | Approve availability design, load/abuse tests and storage/worker monitoring | Operations |
| SEC-12 | Medium | Forwarded-header trust relies on private backend network | Verify isolation and trusted proxy topology; reassess on ingress changes | Platform / engineering |

## 10. Security validation requested before release

Use an isolated staging deployment containing synthetic data. Assign identifiers and preserve sanitized requests/responses, screenshots, timestamps and deployed commit for each result.

1. Verify TLS trust/protocols, exact origin, cookie attributes, expiry, logout and session revocation.
2. Test login guessing/lockouts and shared-IP behavior; review privileged account recovery.
3. Exercise USER, ENGINEER and ADMIN roles against unauthorized ticket/comment/attachment reads and mutations, including modified object identifiers.
4. Test CSRF with absent/wrong tokens and unrelated Authorization headers; test invalid bearer tokens and login origins.
5. Test stored/reflected content, CSV formulas, query injection, oversized inputs and safe error responses.
6. Exercise disallowed/spoofed/oversized/archive uploads and authorized downloads; verify the approved malware-control outcome once integrated.
7. Attempt audit changes with the restricted runtime DB identity; confirm privileged DBA actions have independent oversight.
8. Verify network denial from unauthorized sources and that backend/database ports are not reachable from employee networks.
9. Reproduce container/host/dependency scans, backup restore, restart/persistence, worker alerting and representative concurrent load.
10. Reconcile all findings with section 9 and document approved exceptions before production data is loaded.

## 11. Approval record

| Decision field | To be completed by reviewers |
|---|---|
| Business owner and data classification | Pending |
| Technical/platform and DBA owners | Pending |
| AppSec / IAM / network / SOC reviewers | Pending |
| Evidence location and exact release commit | Pending |
| Open findings, owners and closure dates | Pending |
| Accepted exceptions, compensating controls and expiry | Pending |
| Decision: approved / conditional / rejected | Pending security-team decision |
| Sign-off names and date | Pending |

Preparation of this document does not grant approval. Retain the completed review and evidence in the organization's approved security review system.

## Assignment email change addendum

The subsequent [Email and Engineer Reports extension](EMAIL_AND_ENGINEER_REPORTS.md) adds configurable SMTP assignment emails and administrative historical report export. Its outbound data flow, secret configuration, delivery semantics and approval dependencies supersede the earlier statement that no external email transport exists. SMTP remains disabled until configured; corporate mailbox delivery has not been verified. Review this additional transport before production enablement.
