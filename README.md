# Lamma | لَمّة

Bilingual Arabic/English cardboard pickup application for shops and collectors.
Read [START-HERE.md](START-HERE.md) for the local Arabic walkthrough.

## Features

- Separate accounts and server-enforced ownership/roles.
- Shared persisted data; SQLite locally, PostgreSQL connection support for hosting.
- Atomic exclusive booking; collector receipts confirmed or returned by the shop.
- Confirmation-only totals computed across all records, cursor pagination and area search.
- Optional pickup coordinates, hidden along with the address until booking; external map link.
- Email verification, single-use expiring recovery tokens, session revocation and idle timeout.
- Local development mailbox; optional queued SMTP delivery worker.
- Arabic and English, RTL/LTR, responsive layouts, labelled forms and status messages.

## Run

Python 3.12:

```sh
python -m venv .venv
# Activate .venv for your platform
pip install -r requirements-lock.txt
python server.py
```

Open http://127.0.0.1:8002. `python manage.py mailbox` displays LOCAL development emails.
The app uses Waitress (8 bounded worker threads), not Python's demonstration HTTP server.

## Verify

```sh
python -m pytest -q
node --check dist/app.js
python load_smoke.py
```

The test suite covers booking contention, permissions, private location visibility,
receipt confirmation, recovery/replay, CSRF/header defenses, throttling, pagination,
expiry/revocation, and migration from the original local database.
GitHub Actions also runs an isolated PostgreSQL booking test.

See [VERIFICATION.md](VERIFICATION.md), [DEPLOYMENT.md](DEPLOYMENT.md) and [SECURITY.md](SECURITY.md).

## Boundaries

No public deployment, real mail delivery, payments, automated route optimization,
admin dashboard or recycling verification is claimed. Browser-local prototype records
are not imported. Existing database accounts and requests are retained by an additive
migration; old sessions are invalidated and accounts must verify email.

Do not commit data/, backups/, .env, or mailbox output. Local SQLite is for a single
machine, not shared storage across replicas. The Docker/PostgreSQL package requires
validation on the intended hosting environment before launch.
