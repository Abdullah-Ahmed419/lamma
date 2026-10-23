# Verification record — 2026-10-23

- Python integration/security tests: **10 passed**, PostgreSQL-specific test skipped locally because no PostgreSQL service is installed.
- JavaScript syntax check: passed.
- Browser end-to-end, isolated synthetic database: shop login → create request → collector login → book → record 18 kg at EGP 5/kg → shop confirmation → history and confirmed EGP 90 total. Passed.
- Arabic/English UI switch inspected; address hidden before booking and visible after booking verified through the browser and API tests.
- Production cookie/header guard tested without sending email.
- Legacy database migration and backup/restore/non-overwrite safeguards tested.
- Existing desktop database backed up before upgrade; upgraded health endpoint returns OK.

## Local synthetic performance smoke

5,000 completed records; 200 mixed list/summary HTTP requests; concurrency 8:

- Failures: 0
- Elapsed: 1.13 seconds
- Throughput: 176.4 requests/second
- 95th-percentile latency: 91.0 ms

This uses synthetic data, local SQLite, and disabled rate limiting to isolate query/server behavior. It is not an Internet load test or a capacity/SLA guarantee. Run `python load_smoke.py` to reproduce on another machine.

## Environment-dependent verification

Real SMTP delivery, HTTPS reverse proxy and Docker deployment remain untested locally. PostgreSQL CI is configured in `.github/workflows/checks.yml`; the workflow result, not this document, is authoritative for the pushed commit.
