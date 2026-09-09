# Expense Classification Agent

A hackathon MVP for turning receipt images into structured, reviewable business expenses.

## Current status

The application now provides a secure FastAPI receipt-intake and OCR boundary:

- `GET /health` for service health checks.
- `POST /receipts/upload` for authenticated JPEG/PNG uploads.
- A 5 MB default size limit, file-signature checks, generated storage names, and cleanup of rejected uploads.
- PaddleOCR text detection and recognition, including orientation correction, image unwarping, and recognition confidence.
- Configurable Tesseract fallback with a bounded subprocess timeout.
- Structured receipt extraction through the organiser's text-only LLM gateway.
- Strict receipt and line-item schemas plus deterministic amount reconciliation checks.
- Automated tests that mock both OCR providers and the gateway, so tests do not download models, require OCR installation, make network calls, or consume API credits.

Vendor lookup, expense classification, confidence gating, SQLite persistence, Firebase Authentication, Telegram/OpenClaw integration, and a review UI remain TODOs.

## Confirmed pipeline

The hackathon gateway accepts text prompts but did not receive images during testing. Receipt images must therefore be processed locally before the LLM call:

1. Receive and validate a receipt image.
2. Run local PaddleOCR, or Tesseract when selected as the fallback.
3. Send OCR text to the text-only LLM gateway and validate the returned receipt JSON.
4. Apply a deterministic vendor mapping when one is safe.
5. Classify unmatched or mixed-purpose expenses with the LLM.
6. Auto-file results at or above the confidence threshold; otherwise send them to review.

Business purpose should be optional input. Missing context must lower confidence for ambiguous receipts instead of forcing a guess. The initial confidence threshold is `0.80`.

## Local setup (Windows PowerShell)

Requirements: Python 3.11. PaddleOCR is the default provider; [Tesseract OCR](https://github.com/UB-Mannheim/tesseract/wiki) is an optional fallback.

```powershell
git clone https://github.com/yipkaio/expense-classification-agent.git
cd expense-classification-agent
py -3.11 -m venv .venv311
$python = ".\.venv311\Scripts\python.exe"
& $python -m pip install --upgrade pip setuptools wheel
& $python -m pip install -e ".[test,ocr-paddle]"
Copy-Item .env.example .env
```

Set secrets only in the current shell or an ignored `.env` file. The application currently reads environment variables directly, so load them before startup:

```powershell
$apiKey = [guid]::NewGuid().ToString("N")
$env:APP_API_KEY = $apiKey
Set-Clipboard -Value $apiKey
$env:UPLOAD_DIR = "data/uploads"
$env:MAX_UPLOAD_BYTES = "5242880"
$env:OCR_ENGINE = "paddle"
$env:PADDLE_LANGUAGE = "en"
$env:PADDLE_DEVICE = "cpu"
$env:PADDLE_MIN_CONFIDENCE = "0.50"
$env:TESSERACT_CMD = "C:\Program Files\Tesseract-OCR\tesseract.exe"
$env:TESSERACT_LANGUAGE = "eng"
$env:TESSERACT_PSM = "6"
$env:OCR_TIMEOUT_SECONDS = "30"
$secureGatewayKey = Read-Host "Paste LLM gateway API key (hidden)" -AsSecureString
$env:LLM_GATEWAY_API_KEY = [System.Net.NetworkCredential]::new(
    "", $secureGatewayKey
).Password
$env:LLM_GATEWAY_URL = "https://api.softwaresystems.app"
$env:LLM_MODEL = "global.anthropic.claude-sonnet-4-5-20250929-v1:0"
$env:LLM_TIMEOUT_SECONDS = "120"
$env:LLM_MAX_OUTPUT_TOKENS = "800"

& $python -m uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000/docs`, paste the copied `APP_API_KEY` value into the `X-API-Key` request header, and submit a JPEG or PNG receipt. A successful response has status `extraction_complete` and includes `ocr_engine`, Paddle's average `ocr_confidence`, the raw `ocr_text`, and validated `extracted_data`. Each successful OCR upload now makes one paid extraction call to the organiser gateway. PaddleOCR downloads its model files on the first real OCR request and caches one pipeline instance per application process.

To use the existing Tesseract fallback instead, set `$env:OCR_ENGINE = "tesseract"` before starting Uvicorn. Tesseract does not expose a recognition confidence through this integration, so `ocr_confidence` will be `null`.

## OCR engine comparison

Both OCR engines were tested locally on the same 263,222-byte JPEG receipt using a Windows CPU environment.

| Engine | Processing time | Reported confidence | Observed result |
|---|---:|---:|---|
| Tesseract | 2–3 seconds | Not available | Faster, but it missed the vendor name and misread parts of the address, fax number, GST number, and receipt table. |
| PaddleOCR | About 10 seconds | 0.994 | It detected the vendor and produced substantially clearer identity, contact, tax, receipt, total, and line-item text. |

PaddleOCR is the default because accurate vendor and amount recognition is more important than raw OCR speed for downstream vendor lookup and structured expense extraction. Tesseract remains available as a faster, lightweight alternative and fallback.

Choose an engine before starting Uvicorn:

```powershell
$env:OCR_ENGINE = "paddle"       # Accuracy-focused default
# or
$env:OCR_ENGINE = "tesseract"    # Faster alternative

& $python -m uvicorn app.main:app --reload
```

These results are an indicative comparison from one receipt, not a comprehensive benchmark or a claim that PaddleOCR is always more accurate. PaddleOCR's value is its average recognition confidence across accepted text lines; it is not an accounting-field accuracy score and cannot be compared directly with the current Tesseract response, which does not include confidence.

Run the tests with:

```powershell
& $python -m pytest
```

### PaddleOCR Windows CPU compatibility

The project pins PaddlePaddle `3.2.2` because PaddlePaddle `3.3.x` has a CPU/oneDNN regression that can raise `ConvertPirAttribute2RuntimeAttribute not support [pir::ArrayAttribute<pir::DoubleAttribute>]` during PP-OCR inference. If `3.3.x` was previously installed in `.venv311`, stop Uvicorn and restore the pinned dependency with:

```powershell
$python = ".\.venv311\Scripts\python.exe"
& $python -m pip install --force-reinstall "paddlepaddle==3.2.2"
& $python -m pip install -e ".[test,ocr-paddle]"
```

## Gateway configuration

The confirmed endpoint is `POST https://api.softwaresystems.app/api/chat` using the `X-API-Key` header and model `global.anthropic.claude-sonnet-4-5-20250929-v1:0`. Keep these values in environment variables; never commit the real API key.

The extraction client sends only OCR text, requests deterministic JSON with an 800-token default output allowance, and validates every response against strict Pydantic models. Optional JSON Markdown fences are accepted, while empty, truncated, malformed, or schema-invalid responses are rejected. Required-field and arithmetic inconsistencies set `needs_review` without silently changing the extracted amounts.

Gateway errors use controlled API responses: `502` for invalid model output, `503` when the service is unavailable, and `504` for timeouts. The uploaded receipt image is retained when LLM extraction fails so it can be recovered once persistence and the review queue are implemented. Automated tests use a mocked HTTP transport and never call the live gateway.
