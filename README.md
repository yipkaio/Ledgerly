# Expense Classification Agent

A hackathon MVP for turning receipt images into structured, reviewable business expenses.

## Current status

The first milestone provides a secure FastAPI receipt-intake boundary:

- `GET /health` for service health checks.
- `POST /receipts/upload` for authenticated JPEG/PNG uploads.
- A 5 MB default size limit, file-signature checks, generated storage names, and cleanup of rejected uploads.
- Automated tests for health, authentication, unsafe filenames, invalid content, and oversized files.

OCR, LLM extraction, vendor lookup, classification, confidence gating, SQLite persistence, Firebase Authentication, Telegram/OpenClaw integration, and a review UI remain TODOs.

## Confirmed pipeline

The hackathon gateway accepts text prompts but did not receive images during testing. Receipt images must therefore be processed locally before the LLM call:

1. Receive and validate a receipt image.
2. Run local Tesseract OCR.
3. Send OCR text to the text-only LLM gateway for structured extraction.
4. Apply a deterministic vendor mapping when one is safe.
5. Classify unmatched or mixed-purpose expenses with the LLM.
6. Auto-file results at or above the confidence threshold; otherwise send them to review.

Business purpose should be optional input. Missing context must lower confidence for ambiguous receipts instead of forcing a guess. The initial confidence threshold is `0.80`.

## Local setup (Windows PowerShell)

Requirements: Python 3.11+ and [Tesseract OCR](https://github.com/UB-Mannheim/tesseract/wiki).

```powershell
git clone https://github.com/yipkaio/expense-classification-agent.git
cd expense-classification-agent
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[test]"
Copy-Item .env.example .env
```

Set secrets only in the current shell or an ignored `.env` file. The application currently reads environment variables directly, so load them before startup:

```powershell
$env:APP_API_KEY = "replace-with-a-random-value-at-least-32-characters"
$env:UPLOAD_DIR = "data/uploads"
$env:MAX_UPLOAD_BYTES = "5242880"

uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000/docs`, authorize an upload by adding the `X-API-Key` request header, and submit a JPEG or PNG receipt.

Run the tests with:

```powershell
python -m pytest
```

## Gateway configuration

The confirmed endpoint is `POST https://api.softwaresystems.app/api/chat` using the `X-API-Key` header and model `global.anthropic.claude-sonnet-4-5-20250929-v1:0`. Keep these values in environment variables; never commit the real API key.

The gateway integration is deliberately not implemented in this first milestone. The next milestone will add Tesseract execution, validated structured extraction, and tests using mocked gateway responses before any real credits are consumed.
