# Developer setup and local checks

Use [Docker setup](docker.md) for the packaged backend and frontend, persistent volumes, backups and deployment. These steps run the backend and frontend directly for development.

## Windows PowerShell

Install Python 3.11 and Node.js. PaddleOCR is the configured default; install its optional extra when you need local receipt OCR.

```powershell
git clone https://github.com/yipkaio/expense-classification-agent.git
cd expense-classification-agent
py -3.11 -m venv .venv311
$python = ".\.venv311\Scripts\python.exe"
& $python -m pip install --upgrade pip setuptools wheel
& $python -m pip install -e ".[test,ocr-paddle]"
Copy-Item .env.example .env
```

Generate an application key and set `APP_API_KEY` and the organizer-provided `LLM_GATEWAY_API_KEY` in the ignored `.env`. Do not put real keys in Git, examples, screenshots or test fixtures.

```powershell
[guid]::NewGuid().ToString("N") | Set-Clipboard
notepad .env
& $python -m uvicorn app.main:app --reload --env-file .env
```

Open `http://127.0.0.1:8000/docs` in local `api_key` mode; send the configured key in the `X-API-Key` header. The receipt endpoint accepts JPEG, PNG and bounded PDF. PDFs default to three pages and 5 MB. The backend retains the validated original behind authentication; scanned pages use OCR. PaddleOCR may download models on first use.

In a second terminal:

```powershell
cd frontend
npm ci
npm run dev
```

Open `http://127.0.0.1:5173/ui/`. Production authentication and trusted-integration keys are described in [authentication](authentication.md); do not use a shared development key as a substitute for a public multi-user identity system.

## OCR and gateway

`OCR_ENGINE=paddle` is the default. PaddleOCR gives recognition confidence; the optional `OCR_ENGINE=tesseract` needs a local Tesseract installation and returns no confidence value in this integration. Select an engine in `.env` and restart the backend. PaddlePaddle is pinned to `3.2.2` for the tested Windows CPU setup. If a previous installation of 3.3.x fails on PP-OCR inference, reinstall the pinned `ocr-paddle` extra.

The gateway receives OCR text, asks for structured JSON and validates the response with Pydantic. An exact vendor mapping avoids the classification call; unmatched vendors trigger an additional gateway call. Missing purpose or inconsistent arithmetic must reach human review rather than a guessed auto-file. Gateway errors return controlled responses; failed extraction evidence can be inspected in history.

One local, 263,222-byte receipt was processed in roughly 2–3 seconds with Tesseract and about 10 seconds with PaddleOCR; the former missed vendor/detail text and the latter reported 0.994 average recognition confidence. This single receipt is an illustrative comparison, not a benchmark or an accounting-field accuracy measure.

## Run the checks

```powershell
& $python -m pytest
cd frontend
npm run lint
npm run test:unit
npm run build
```

The backend suite mocks OCR and gateway traffic. Frontend Playwright tests require browser dependencies and a running test environment; follow [frontend testing](frontend.md) and [release checks](demo-readiness.md). Use [monthly reconciliation](monthly-reconciliation.md) and [receipt review](reviews.md) to inspect the API contracts. Back up the SQLite database and retained originals together before a schema upgrade.
