# Security model and release checklist

Ledgerly is a single-bookkeeper hackathon MVP containing financial documents. Its
security objective is to minimise public exposure, strictly authenticate data
access, bound untrusted file processing and keep AI advisory.

Firebase identifies the one approved production account; typed reviewer names
on receipt and monthly-review events are still self-reported. The
[maintenance review](maintenance-review.md) distinguishes removable code from
schema migrations and compatibility endpoints that must be retained.

## Implemented controls

| Area | Current control |
|---|---|
| Public network | Caddy exposes HTTPS; FastAPI and OpenClaw bind to loopback/private networking. Port `8000` and `18789` are not public. |
| Browser identity | Firebase ID tokens are checked with Firebase and must match the configured UID; optional email matching adds defence in depth. |
| Integration identity | OpenClaw uses a high-entropy `APP_API_KEY`; Telegram direct messages require pairing/approval and groups are disabled in the deployed MVP. |
| Secrets | `.env`, local frontend environment files, databases and uploads are ignored. Docker uses an allowlisted build context. Telegram uses a mode-`600` token file. |
| Uploads | Authentication precedes processing. Size, media type and magic bytes are checked; generated UUID filenames prevent traversal; PDF work is bounded. |
| Runtime | The API container is non-root, capability-free, no-new-privileges and read-only except for explicit volumes and bounded temporary storage. |
| Browser responses | Financial and AI routes are `no-store`, `nosniff`, anti-framing and referrer-restricted. The UI has a restrictive Content Security Policy and Permissions Policy. |
| AI authority | AI may extract, classify and explain. It cannot approve, pay, post, change payment state or override deterministic controls. |
| Persistence | Parameterised SQLite operations, foreign keys, atomic workflow writes and append-only human/audit events preserve traceability. |
| Recovery | The documented procedure creates a consistent SQLite copy, retains uploads and verifies a checksum. The operator must copy that archive off-instance; a Lightsail snapshot is an additional recommended control, not an application backup. |

## Secret inventory

Never commit or paste these values into issues, logs, screenshots or Telegram:

- `APP_API_KEY`
- `LLM_GATEWAY_API_KEY`
- Telegram bot token
- Firebase user password or ID/refresh token
- SSH private key (`.pem`)
- OpenClaw provider credentials

Firebase's web API key and project ID identify the public Firebase client and are
delivered to the browser by design. The configured Firebase UID, authentication
rules and password remain the access boundary.

## Before every production release

1. Confirm the worktree contains no `.env`, database, upload, backup or private-key files.
2. Run backend tests, frontend lint/unit tests, frontend build and dependency audits.
3. Confirm production Compose resolves with `AUTH_MODE=hybrid` and API docs disabled.
4. Confirm only ports 22, 80 and 443 are public in Lightsail.
5. Verify unauthenticated receipt, dashboard, statement and AI requests return 401.
6. Verify HTTPS, HSTS, CSP, no-store and anti-framing headers.
7. Verify OpenClaw binds to `127.0.0.1`, Telegram groups remain disabled and every paired direct-message user is expected.
8. Create and verify an application backup, copy it off-instance and, when used, confirm the Lightsail snapshot is available.
9. Protect `main`: require pull requests and passing CI, and block force pushes/deletion.
10. Tag only the reviewed commit that passed these checks.

## Accepted MVP limitations

- The service is designed for one controlled bookkeeper, not public multi-tenant use.
- There is no distributed rate limiter or web application firewall. Keep the
  deployment small, monitor logs/resources and do not broaden public exposure.
- SQLite and the upload volume are stored on the instance and are not encrypted by
  the application. Rely on AWS account security, encrypted snapshots where
  provided, strict host access and an encrypted off-instance destination for
  backups. A checksum detects corruption; it does not encrypt the archive.
- Python transitive dependencies are resolved during image builds rather than from
  a fully hashed lockfile. Rebuild and audit before releases; retain the tested image
  or snapshot for rollback.
- The `sslip.io` hostname is suitable for an MVP but not an ownership-controlled
  production identity. Move to a domain you control before broader public use.

## If a secret may have leaked

1. Revoke or rotate the affected credential immediately.
2. Restart only the service that consumes the replacement credential.
3. Search Git history and logs for the exposed value; deleting a working-tree file
   does not remove Git history.
4. Review Firebase sign-ins, Telegram bot activity, gateway use and SSH access.
5. Restore from a known-good snapshot only if host integrity is uncertain.

Do not publish real credentials in a remediation commit. Document only the rotation
date, affected service and verification result.
