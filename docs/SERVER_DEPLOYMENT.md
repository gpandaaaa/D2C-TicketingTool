# Internal server deployment: 107.108.42.60:5050

For Windows Server 2025 or Windows 11, follow the **[illustrated step-by-step Windows installation guide](WINDOWS_INSTALLATION.md)**. The instructions below cover the Linux application host.

Target URL: **https://107.108.42.60:5050**. This configuration adds TLS to the existing stack, enforces production settings and secure cookies, and publishes only port 5050. Local development is unchanged. Remote installation has not yet been performed.

## Prerequisites

- Linux server with Docker Engine and Docker Compose **2.24.4 or newer** (`docker compose version`). On Windows Server use a supported Linux VM for these Linux containers.
- SSH access and permission to run Docker; port 5050 available and permitted from the intended employee network. Keep PostgreSQL/8000/3000 closed externally.
- A certificate issued by your organization's trusted CA. For the IP URL, its Subject Alternative Name must contain **IP:107.108.42.60**. Every employee device must trust that CA. Alternatively use an internal DNS hostname, a certificate for that hostname, and change `PUBLIC_ORIGIN` accordingly.
- Server access to download the container images and Python packages during the first build, or an approved internal registry/package mirror.

## Install

Copy the source repository to `/opt/d2c-helpdesk` on the server. Exclude local `.env`, `.env.server`, `.local`, `.runtime`, `.venv`, `.python`, `.cache`, `artifacts`, databases and private keys. Do not copy the development database or run the development seed.

Run from the repository root on the server:

```sh
cp deploy/server.env.example .env.server
chmod 600 .env.server
openssl rand -hex 32
```

Set `POSTGRES_PASSWORD` in `.env.server` to the generated value. Keep it private. Use a hexadecimal password to avoid URL-escaping issues. Set `PUBLIC_ORIGIN` to the actual HTTPS URL with no trailing slash.

Install the CA-issued PEM certificate chain and private key:

```sh
mkdir -p deploy/tls
chmod 700 deploy/tls
# Install certificate chain as deploy/tls/fullchain.pem
# Install its matching private key as deploy/tls/privkey.pem
chmod 600 deploy/tls/privkey.pem
```

Define a convenience function for this shell. Always use this configuration for server operations; plain `docker compose up` uses the development configuration.

```sh
dc() { docker compose --env-file .env.server -p d2c-helpdesk -f docker-compose.yml -f docker-compose.server.yml "$@"; }
dc config --quiet
dc up -d --build --wait
dc ps
dc exec frontend nginx -t
```

Migrations run automatically before the backend starts. PostgreSQL persists in the `d2c-helpdesk_postgres_data` named volume. **Do not run `down -v`**, which deletes that data. Never change an initialized database password only in the environment file: PostgreSQL must be rotated as well.

Create the first real administrator (replace the email/name with your own):

```sh
dc exec backend python -m app.manage bootstrap-admin --email admin@example.local --name 'D2C Administrator'
```

The command prompts privately for a password of at least 12 characters. No default production accounts are created. Open the target URL and configure categories, teams, locations, engineers, skills, capacities, assignment rules and SLA policies in the Admin Console.

## Verify

```sh
curl --fail https://107.108.42.60:5050/
curl --fail https://107.108.42.60:5050/api/v1/openapi.json
dc logs --tail=100 backend worker frontend
```

If the server's command-line trust store needs the internal CA, pass `--cacert /path/to/company-ca.pem`; do not disable certificate verification. Verify login from an employee workstation, then create a ticket with a matching available engineer. Check assignment, notification, engineer resolution, requester closure and the admin audit timeline. Also verify USER and ENGINEER accounts cannot open Admin Console APIs. A running container alone does not establish acceptance.

## Updates, certificates and backups

Before upgrades, take an access-restricted database backup and test restoration in an isolated environment:

```sh
umask 077
mkdir -p /var/backups/d2c-helpdesk
dc exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "/var/backups/d2c-helpdesk/helpdesk-$(date +%Y%m%d-%H%M%S).dump"
```

Backups include attachment contents and user data. Store encrypted copies according to your organization's retention policy. To restore, provision an isolated PostgreSQL database and use `pg_restore --no-owner` with its credentials; do not overwrite a live database as a backup test.

After copying an approved source update, run `dc up -d --build --wait`. Review migrations before upgrades; rolling back code may require restoring the corresponding database backup. Renew the PEM files before expiry, then run `dc exec frontend nginx -t && dc exec frontend nginx -s reload`.

The bundled database account owns the application schema. Separate migration and runtime database identities, backup automation, monitoring, certificate renewal, and your organization's access controls remain deployment responsibilities; see [Security](SECURITY.md). Production seeding is disabled.
