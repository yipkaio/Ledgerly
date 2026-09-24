<p align="center"><img src="docs/assets/screenshots/153316.png" alt="Ledgerly logo" width="120"></p>

# Ledgerly

AI-assisted receipt classification, human review and bank reconciliation for one trusted bookkeeping workspace.

**Start here:** [User guide](docs/user-guide.md) · [Documentation index](docs/index.md) · [Developer setup](docs/setup.md) · [Code health review](docs/maintenance-review.md)

## What it does

1. Upload a JPEG, PNG or bounded PDF receipt in the web app, or send one through the owner-only Telegram relay.
2. Local OCR reads the document. A text-only gateway extracts structured fields; a database vendor mapping or classifier suggests a category. Uncertain, incomplete and probable-duplicate results enter **Pending reviews**.
3. A person compares retained evidence and records an approval or rejection. Accepted receipts can be amended or voided with an audit trail. Recoverable deletions appear under **Deleted receipts**.
4. Filter receipt history and export selected or filtered records to Excel. The dashboard reports dated accepted spend in original currencies or a clearly labelled converted management view.
5. Import a bank PDF or normalized CSV into **Monthly close**, inspect a preview, confirm the rows, investigate unmatched items and record a monthly review. Source statements and payment follow-up remain available for cross-checking.

`AUTO_FILED` is an internal classification decision. It is not a human approval, payment, bank match or external accounting posting. Finance Copilot provides read-only, evidence-scoped explanations and cannot change financial records.

## Run locally

The fastest end-to-end path is Docker. Copy the example environment file, configure a strong app key and gateway key, then follow [Docker setup](docs/docker.md) for the exact Compose commands and persistence volumes. The built frontend is served at `/ui/`. OCR model files are downloaded on the first PaddleOCR request.

For Windows PowerShell development without Docker:

```powershell
git clone https://github.com/yipkaio/Ledgerly.git
cd Ledgerly
py -3.11 -m venv .venv311
$python = ".\.venv311\Scripts\python.exe"
& $python -m pip install -e ".[test,ocr-paddle]"
Copy-Item .env.example .env
# Set APP_API_KEY and LLM_GATEWAY_API_KEY in .env; never commit the file.
& $python -m uvicorn app.main:app --reload --env-file .env
```

Open `http://127.0.0.1:8000/docs` for local API exploration, using `X-API-Key`. Run the React app separately with `cd frontend`, `npm ci`, and `npm run dev`; open `http://127.0.0.1:5173/ui/`. See [developer setup](docs/setup.md) for OCR choices, gateway configuration, test commands and common failure modes.

## Architecture and safety

FastAPI stores receipts, audit events, bank statements and payment follow-up in SQLite. Retained originals live in protected upload storage. The React frontend uses Firebase email/password for one pre-approved production account; trusted integrations can use the app key in hybrid mode. The production Compose overlay places the API behind Caddy HTTPS. Back up the database **and** retained files together before migration or deployment.

Three bounded AI responsibilities are implemented:

| Responsibility | Allowed output | Decision owner |
| --- | --- | --- |
| Document Intelligence | Receipt extraction; optional consented statement-layout fallback | Deterministic validation and reviewer |
| Classification and Compliance | Category suggestion and evidence checks | Confidence gate and reviewer |
| Finance Copilot | Period-scoped explanations, briefs and answers | Reviewer |

Arithmetic, duplicate checks, vendor lookup, matching, status changes and approvals remain deterministic or human-controlled. The gateway receives OCR text, not receipt images. The optional bank-statement AI fallback requires explicit consent. See [architecture](docs/architecture.md), [AI boundaries](docs/ai-agents.md), [security](docs/security.md) and [authentication](docs/authentication.md).

## Documentation

| Goal | Document |
| --- | --- |
| Learn the app with examples | [Illustrated user guide](docs/user-guide.md) |
| Find a setup, feature or operating procedure | [Documentation index](docs/index.md) |
| Run locally and test | [Developer setup](docs/setup.md) and [frontend guide](docs/frontend.md) |
| Deploy, back up or roll back | [Docker and Lightsail operations](docs/docker.md) |
| Review release readiness | [Demo and release checklist](docs/demo-readiness.md) |
| Review the first release | [v0.1.0 release notes](docs/release-notes-v0.1.0.md) |
| Understand safe cleanup and remaining debt | [Code health review](docs/maintenance-review.md) |

Feature contracts for review, reprocessing, receipt lifecycle, PDFs, Excel exports, Telegram and monthly reconciliation are linked from the [documentation index](docs/index.md).

## Checks

```bash
python -m pytest
cd frontend
npm ci
npm run lint
npm run test:unit
npm run build
```

Backend tests mock OCR and gateway calls, so they do not consume API credits. Browser tests use Playwright; run them separately with `npm test` in an environment with browser dependencies installed. Use the [release checklist](docs/demo-readiness.md) for the live, authenticated smoke test. Current databases migrate transactionally through schema **v9** on first use; a pre-migration backup is required because older app versions cannot read the new schema.
