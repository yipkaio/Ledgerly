# Run the backend with Docker

This packages the existing backend for local testing and a private Lightsail
trial. It does not create AWS resources or add the UI, Telegram, or HTTPS.
The initial packaging was prepared in a workspace without Docker: host tests and
YAML checks passed, but image build, native container tests and container recreation
must still be verified using the commands below before deployment.
Use Docker Desktop with **Linux containers** on Windows, or Docker Engine with
the Compose plugin on an x86-64 Ubuntu host. Compose targets `linux/amd64`.
Paddle's memory needs must be measured on the target machine; a passing health
check does not prove that OCR models fit in RAM.

## First local run (PowerShell)

Stop the existing Uvicorn process with Ctrl+C. Keep your existing `.env` and keys;
do not replace it with the empty example. New users can copy `.env.example` once
and fill its keys. Docker gets keys at runtime; neither keys nor `.env` enter the
image. Ensure Docker Desktop is running, then from the repository directory:

```powershell
docker version
docker compose version
docker compose config --quiet
docker compose build api
docker compose up -d --wait --wait-timeout 120
docker compose ps
```

Avoid plain `docker compose config` when sharing output: it can expand secrets.
Builds download Python packages, Linux packages and base images. Both PaddleOCR
and Tesseract are installed. The initial build is substantial and needs network
access. Existing dependency ranges are retained; this image is not yet a fully
locked/reproducible release. Keep known-good images until replacements pass tests.

Visit `http://127.0.0.1:8000/docs`, supply the saved `APP_API_KEY`, and upload as
before. `OCR_ENGINE=paddle` remains the default; switch to `tesseract` in `.env`
and recreate the service with `docker compose up -d --force-recreate api`.
Compose overrides `TESSERACT_CMD`, `DATABASE_PATH`, `UPLOAD_DIR`, and
`PADDLE_DEVICE` with Linux paths/CPU settings, so Windows paths in `.env` are safe.
Do not change them to Windows paths inside the container.

Add `API_PORT=8001` to `.env` if you need your old local server running too; use
port 8001 in the browser. Set `API_DOCS_ENABLED=false` to disable `/docs`, `/redoc`
and `/openapi.json`. Recreate the container after environment changes. This only
hides documentation; every protected API still requires the application key.

## What persists

Compose creates named volumes `expense-agent_receipt-data` and
`expense-agent_paddle-cache`. They hold `/app/data` (SQLite and receipt uploads)
and `/home/expense` (Paddle/PaddleX and other OCR caches). New volumes inherit the
image's directory ownership for UID/GID 10001. Do not change the Compose project
name or volume definitions casually; a different project name uses new volumes.

**Your existing Windows `data/` directory is not automatically imported.** The
container begins with a new database. Keep the original files. This avoids
overwriting existing receipts. A deliberate migration can be performed later.

`docker compose down` stops/removes containers but keeps these volumes.
Do not use `docker compose down -v` or prune volumes containing receipts: those
operations delete the database, uploads and caches. Volumes survive container
replacement, not deletion of the Lightsail disk/instance. Back up separately.

For a simple consistent backup, stop API writes with `docker compose stop api`,
copy `/app/data` out of the stopped container with `docker compose cp` into a new
protected backup directory, then start it with `docker compose start api`.
Back up the entire directory. On Windows, avoid piping binary tar archives
through PowerShell text redirection. Keep an off-instance copy for AWS recovery.

## Automated checks without gateway credits

The standard test suite runs in a dedicated test image, with no real keys,
no access to your receipt volumes, and no network while the tests run:

```powershell
docker compose -f compose.test.yaml up --build --abort-on-container-exit --exit-code-from tests
docker compose -f compose.test.yaml down
```

The exit code of the first command is the test result. This includes native
Paddle imports/tensor computation and a real Tesseract upload using a generated
PNG. LLM calls are mocked. Full Paddle OCR inference is not tested here because
it requires downloading model weights; test that separately with one receipt.

After building the runtime image, test container recreation and persistent data:

```powershell
python scripts/container_smoke.py --image expense-agent:local
```

This needs only Python's standard library and Docker on the host (your activated
`.venv311` is fine). It creates random, disposable containers and volumes, binds
no ports, disables networking, and uses temporary test keys. It verifies HTTP
health, authentication, hidden Swagger, UID 10001, and SQLite/image/cache survival
across container recreation. It removes only its own test resources afterward.
The stored receipt is a synthetic failure fixture, not an LLM result.

For a real workflow check, upload through `/docs`, copy the ID, run
`docker compose up -d --force-recreate api`, and retrieve the same ID again. A real
upload uses the normal paid extraction/classification calls. The first Paddle
request downloads model weights and can be much slower than later requests.

## Runtime checks and security

- The process runs as UID/GID 10001 with all Linux capabilities dropped,
  no new privileges, a read-only root filesystem and a bounded temporary area.
- The API is published only at `127.0.0.1`; keep port 8000 closed in Lightsail's
  public firewall. Use SSH tunnelling for the private trial.
- One Uvicorn worker is used, with no development reload. Docker forwards signals
  through an init process and allows 330 seconds before forced shutdown; Uvicorn
  gets 300 seconds for graceful shutdown. Very long/hung Paddle inference can
  still be interrupted and leave a record `PROCESSING`.
- Startup validates required configuration, OCR package/executable presence and
  writable receipt/database/cache storage. It does not download models or call
  the LLM. Paddle initialization failures return a controlled 503.
- `/health` is a liveness check. It does not continuously verify the database,
  gateway connectivity or Paddle readiness. Docker health status alone does not
  automatically restart an unhealthy process; `unless-stopped` restarts exits.
- Access logs are disabled to avoid logging receipt IDs in request URLs. Docker
  logs rotate at 10 MB with three files. Native OCR libraries may still emit
  diagnostics; inspect logs before sharing them.
- Shared-key authentication is still one trusted workspace. HTTPS and individual
  user authorization are required before opening this to general users. Hiding
  Swagger is not an authentication replacement. Do not mount the Docker socket.

Useful commands:

```powershell
docker compose ps
docker compose logs --tail=100 api
docker stats --no-stream
docker compose stop api
docker compose start api
```

## Lightsail trial and subsequent updates

Provision Ubuntu x86-64, attach a static IP, install Docker Engine and Compose,
and clone this private repository using read-only deploy credentials. Add `.env`
on the server with restricted permissions (`chmod 600 .env`). Use the same Compose
commands. The Python 3.11 interpreter is in the image; Ubuntu's host Python version
does not need changing. Never copy a Windows `.venv311` into the server or image.

For private access, use your configured SSH key to open a tunnel from Windows:

```powershell
ssh -L 18000:127.0.0.1:8000 ubuntu@YOUR_STATIC_IP
```

Visit `http://127.0.0.1:18000/docs` while that SSH session stays open. This keeps the
remote API private. Use a separate HTTPS reverse-proxy deployment when the public
UI is ready; no public HTTP endpoint or TLS certificate is installed by this commit.

Before an update, back up data and preserve the old image under a unique tag:

```bash
docker image tag expense-agent:local expense-agent:before-update-YYYYMMDD
git pull --ff-only
docker compose build api
docker compose up -d --wait --wait-timeout 120
```

Replace the date placeholder with a unique tag. Run smoke checks after updating.
For an application-only rollback with a compatible database schema, retag the
saved image as `expense-agent:local` and run `docker compose up -d --no-build
--force-recreate api`. If a later release changes the schema, use that release's
migration/restore procedure; an old image alone is not a safe database rollback.

Official references: [Docker on Ubuntu](https://docs.docker.com/engine/install/ubuntu/),
[Compose services](https://docs.docker.com/reference/compose-file/services/),
[Docker volumes](https://docs.docker.com/engine/storage/volumes/).
