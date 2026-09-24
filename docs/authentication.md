# Authentication and production deployment

Ledgerly supports three authentication modes without changing the SQLite schema.
This authenticates access to the shared workspace. Names entered into receipt
or monthly-review events remain self-reported audit labels, not separate
reviewer identities or roles.

| Mode | Web UI | Trusted integrations |
|---|---|---|
| `api_key` | Shared `APP_API_KEY` form | `X-API-Key` |
| `firebase` | Firebase email/password | Disabled |
| `hybrid` | Firebase email/password | `X-API-Key` |

Use `api_key` for local development and `hybrid` for the Lightsail production
configuration. Hybrid mode keeps a separate credential for the Telegram/OpenClaw
bridge while ordinary web users sign in with Firebase. There is no registration,
password-reset or account-management UI.

## 1. Create the controlled Firebase account

1. Create or select a Firebase project.
2. In **Authentication → Sign-in method**, enable **Email/Password** only.
3. In **Authentication → Users**, add the one bookkeeper account manually.
4. Copy the project's Web API key and project ID.
5. Copy the user's Firebase UID from the Users table.
6. Do not enable public sign-up in Ledgerly and do not place service-account JSON
   in this repository or container.

Add the following to the server's ignored `.env`:

```dotenv
AUTH_MODE=hybrid
FIREBASE_WEB_API_KEY=your-public-web-api-key
FIREBASE_PROJECT_ID=your-project-id
FIREBASE_ALLOWED_UID=the-pre-created-bookkeeper-uid
FIREBASE_ALLOWED_EMAIL=bookkeeper@example.com
APP_DOMAIN=ledgerly.example.com
TLS_EMAIL=operations@example.com
API_DOCS_ENABLED=false
```

`FIREBASE_ALLOWED_UID` is mandatory in Firebase modes. The optional email is a
second check. Firebase passwords and ID tokens are never written to SQLite or logs.
The browser keeps the refresh token in memory, so reloading or closing the page
requires another sign-in.

## 2. Back up the persistent data

Before changing production configuration, complete the
[production backup procedure](docker.md#production-backup). It uses SQLite's
online backup API, copies the retained evidence, verifies integrity and creates a
checksummed archive. Keep a protected copy outside the Lightsail instance and
restore the database and evidence together.

## 3. Start HTTPS on Lightsail

Point the domain's A record to the Lightsail static IP. In the Lightsail firewall,
allow TCP 22, 80 and 443 and UDP 443; do not expose port 8000 publicly.

```bash
cd ~/Ledgerly
git switch main
git pull --ff-only origin main
chmod 600 .env
docker compose -f compose.yaml -f compose.production.yaml config --quiet
docker compose -f compose.yaml -f compose.production.yaml build api
docker compose -f compose.yaml -f compose.production.yaml up -d --wait --wait-timeout 180
docker compose -f compose.yaml -f compose.production.yaml ps
```

Caddy obtains and renews HTTPS certificates. The API remains bound to localhost on
port 8000 and is also reachable by Caddy on the private Compose network.

## 4. Verify the deployment

```bash
APP_DOMAIN=ledgerly.example.com  # Replace with the public hostname in .env.
curl -fsS http://127.0.0.1:8000/health
curl -fsS "https://$APP_DOMAIN/health"
curl -fsS "https://$APP_DOMAIN/auth/config"
docker compose -f compose.yaml -f compose.production.yaml logs --tail=100 api caddy
```

Then sign in through `https://$APP_DOMAIN/ui/` and complete one acceptance flow:
upload, review, statement import, reconciliation, Finance Copilot, source preview,
Excel export, statement removal and restore.

Expected security behavior:

- A different Firebase UID receives HTTP 401.
- The shared app key is not displayed or entered in the production UI.
- Out-of-scope Copilot questions remain blocked.
- `/docs`, `/redoc` and `/openapi.json` are disabled in production.
- Receipt and statement responses use no-store, anti-framing and referrer controls.

The exact deployment and trust boundaries are illustrated in
[Architecture and data flow](architecture.md#aws-lightsail-deployment).

## Rollback

The authentication change has no database migration. To return temporarily to the
previous local-key sign-in, set `AUTH_MODE=api_key` and restart the API. Do not
restore an older database. If data recovery is required, stop the API and restore
the database and uploads from the same backup archive.
