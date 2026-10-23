# Deployment and scaling

## Configuration

| Variable | Local default | Hosting requirement |
|---|---|---|
| DATABASE_URL | sqlite:///.../data/lamma.db | postgresql+psycopg://... with TLS configured for managed DB |
| PUBLIC_ORIGIN | http://127.0.0.1:8002 | Exact https:// domain, no trailing path |
| LAMMA_ENV | development | production |
| MAIL_MODE | local | smtp |
| REQUIRE_VERIFICATION | 1 | Must remain 1 |
| SMTP_HOST / SMTP_FROM | none | Required in production |
| SMTP_PORT | 587 | STARTTLS port |
| SMTP_USER / SMTP_PASSWORD | none | Provider credentials, through secrets manager |
| PORT / BIND_HOST | 8002 / 127.0.0.1 | Container uses 0.0.0.0 behind a reverse proxy |

Python does not automatically load .env. Set environment variables before starting.
Docker Compose reads .env. Never commit secrets.

## Local Docker + PostgreSQL

1. Install Docker, copy .env.example to .env and replace POSTGRES_PASSWORD with a random URL-safe value.
2. Stop the local Python server using port 8002.
3. Run `docker compose up --build -d`.
4. Check `docker compose ps` and open http://127.0.0.1:8002.
5. Local mail: `docker compose exec web python manage.py mailbox`.

This creates a separate PostgreSQL database. It does not migrate existing SQLite records.
Do not discard the local data directory. A real database migration needs a separately
validated export/import and row-count checks before cutover.

## Hosting preparation

- Put the app behind an HTTPS reverse proxy with request/time/connection limits.
- Preserve the configured public Host header. Do not forward arbitrary client-supplied proxy headers.
- Current Waitress configuration clears untrusted forwarding headers; IP throttling sees the
  direct peer. At a proxy, add client-IP throttling at the edge and tune application global
  limits for the shared proxy address before launch. Do not claim per-client IP limiting
  behind a proxy until trusted forwarding has been configured and tested.
- Configure SMTP secrets, run `python manage.py mail-worker` as one managed worker.
- Schedule `python manage.py cleanup` daily through the hosting platform.
- Probe `/api/health` with the configured Host. It checks database connectivity without exposing details.
- Apply schema changes once during a controlled rollout before scaling replicas. Initial
  create_app performs additive bootstrap migrations; concurrent first-start migrations are not supported.
- Use PostgreSQL before multiple app replicas; SQLite stays single-host. Database pool:
  up to 20 connections per replica, so size replica count against the database connection budget.
- Sessions and rate counters are shared in the DB; no sticky browser sessions are required.
- Orders have owner/status indexes, bounded keyset pagination, and SQL aggregate summaries.
  Substring area search is intentionally simple; at larger volume benchmark PostgreSQL
  trigram indexes or normalized areas rather than promising unbounded scale.

## Backups and recovery

SQLite: `python manage.py backup backups/name.db` uses SQLite online backup and validates
integrity. Restore to a new file: `python manage.py restore backups/name.db backups/check.db`.
Stop the app before changing DATABASE_URL. Never overwrite the only live database.

PostgreSQL: use managed daily snapshots/PITR or `pg_dump -Fc` with credentials from the
operator environment. Restore with pg_restore into a fresh test database, verify counts,
log in, and exercise a full pickup before cutover. Automate encrypted off-host retention;
local disk copies alone are not disaster recovery.

## Not yet verified here

Docker is not installed on the current machine. Container build, PostgreSQL integration,
real SMTP delivery and TLS hosting require their respective environments. CI is configured
to verify PostgreSQL automatically; inspect its actual result after pushing.
