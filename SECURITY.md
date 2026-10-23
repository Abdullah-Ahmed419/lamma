# Security model and operational limits

## Implemented

- PBKDF2-HMAC-SHA256 with per-password random salts and 600,000 iterations. Passwords have a bounded length; missing-user login uses the same hash verification path.
- Random session tokens stored as SHA-256 verifiers; HttpOnly, SameSite=Strict cookies; Secure in production. 24-hour absolute and 30-minute idle lifetime. Logout-all and password reset revoke sessions. A credential fingerprint rejects sessions minted concurrently against an old password.
- Single-use, hashed verification/recovery tokens with 24-hour/30-minute expiry. Generic recovery response, no automatic sign-in after reset, no tokens in HTTP query strings or request logs.
- Atomic database-backed limits for login per account/IP, recovery, registration, token consumption and API traffic. Limits work across processes using the same database.
- Same-origin custom-header JSON mutations, Origin and Fetch Metadata checks, strict configured Host, no cross-origin CORS policy.
- CSP with no inline scripts/styles, frame denial, content sniffing protection, no-referrer policy, no-store responses, HTTPS-only production cookies and HSTS.
- Bound request body size, bounded worker/connection counts, allowlisted static files, validation of finite numbers, and server-side role/ownership checks.
- Transactional conditional booking updates; no reliance on a browser's cached request state.
- Exact address/coordinates omitted from unassigned collectors' responses.
- SQL parameter binding through SQLAlchemy; HTML output escapes user content.
- HTTP error responses carry correlation IDs; logs omit request bodies, cookies, passwords and reset links.

## Deployment requirements

Production mode fails startup without HTTPS origin, SMTP configuration and mandatory
verification. TLS must terminate at a correctly configured reverse proxy. Do not expose
Waitress directly to the public Internet. Use the supplied loopback binding until this
is configured. Backups need storage access controls and encryption by the hosting
provider. SMTP uses certificate-verified STARTTLS.

The mail queue contains one-time links until sent or cleaned up and is private database
content. The local mailbox is a CLI-only development tool, disabled in production.
Run cleanup daily and run one SMTP worker. Retries are at-least-once: a crash after SMTP
acceptance can cause a duplicate email. Tokens remain single-use. There is no guarantee
that an external email provider will deliver to the inbox.

## Limits, not certifications

This work is not an independent penetration test, security certification or uptime
commitment. Rate limits are a baseline, not DDoS protection; add edge controls when hosted.
MFA, formal audit retention policy, abuse moderation and an administrator UI are not
implemented. Production database migration coordination and backup access belong to
operations. Approximate transaction totals use floating-point arithmetic and are not
payment ledgers. Do not use this application for billing without decimal money storage.

## References used

- https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html
- https://cheatsheetseries.owasp.org/cheatsheets/Forgot_Password_Cheat_Sheet.html
- https://flask.palletsprojects.com/en/stable/tutorial/deploy/
