# Expense Classification Agent

A hackathon MVP for turning receipt images into structured, reviewable business expenses.

## Current status

The application now provides a secure FastAPI receipt-processing pipeline:

- `GET /health` for service health checks.
- `POST /receipts/upload` for authenticated JPEG/PNG uploads.
- A 5 MB default size limit, file-signature checks, generated storage names, and cleanup of rejected uploads.
- PaddleOCR text detection and recognition, including orientation correction, image unwarping, and recognition confidence.
- Configurable Tesseract fallback with a bounded subprocess timeout.
- Structured receipt extraction through the organiser's text-only LLM gateway.
- Strict receipt and line-item schemas, optional explicit discounts, and deterministic amount reconciliation checks.
- Exact vendor-to-category lookup before AI classification.
- A fixed-category expense classifier for unmatched vendors, with optional business purpose and a configurable confidence gate.
- Automated tests that mock both OCR providers and both gateway agents, so tests do not download models, require OCR installation, make network calls, or consume API credits.

SQLite persistence, Firebase Authentication, Telegram/OpenClaw integration, and a review UI remain TODOs.

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

Store local secrets in the ignored `.env` file created above. Generate `APP_API_KEY` once, paste it into `.env`, add the organiser-provided `LLM_GATEWAY_API_KEY`, and never commit either value:

```powershell
[guid]::NewGuid().ToString("N") | Set-Clipboard
notepad .env

& $python -m uvicorn app.main:app --reload --env-file .env
```

Open `http://127.0.0.1:8000/docs`, paste the saved `APP_API_KEY` value into the `X-API-Key` request header, and submit a JPEG or PNG receipt. `business_purpose` is optional. A successful response has status `processing_complete` and includes OCR evidence, validated `extracted_data`, and a confidence-gated `classification`. Each successful upload makes one extraction call; only unmatched vendors make an additional classification call. PaddleOCR downloads its model files on the first real OCR request and caches one pipeline instance per application process.

To use the existing Tesseract fallback instead, change `OCR_ENGINE=tesseract` in `.env` and restart Uvicorn. Tesseract does not expose a recognition confidence through this integration, so `ocr_confidence` will be `null`.

## OCR engine comparison

Both OCR engines were tested locally on the same 263,222-byte JPEG receipt using a Windows CPU environment.

| Engine | Processing time | Reported confidence | Observed result |
|---|---:|---:|---|
| Tesseract | 2–3 seconds | Not available | Faster, but it missed the vendor name and misread parts of the address, fax number, GST number, and receipt table. |
| PaddleOCR | About 10 seconds | 0.994 | It detected the vendor and produced substantially clearer identity, contact, tax, receipt, total, and line-item text. |

PaddleOCR is the default because accurate vendor and amount recognition is more important than raw OCR speed for downstream vendor lookup and structured expense extraction. Tesseract remains available as a faster, lightweight alternative and fallback.

Choose an engine in `.env` before starting Uvicorn:

```dotenv
OCR_ENGINE=paddle       # Accuracy-focused default
# or
OCR_ENGINE=tesseract    # Faster alternative
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

The extraction client sends only OCR text, requests deterministic JSON with an 800-token default output allowance, and validates every response against strict Pydantic models. Line-item `discount_percent` and `discount_amount` values are optional and remain `null` unless printed on the receipt. If OCR column order causes `unit_price` and `discount_percent` to be reversed, the application swaps them only when the original calculation fails and the swapped calculation uniquely reconciles within the two-cent tolerance. Every such correction sets `needs_review` and records an audit reason. Optional JSON Markdown fences are accepted, while empty, truncated, malformed, or schema-invalid responses are rejected. Required-field, discount, and arithmetic inconsistencies set `needs_review` without silently changing the extracted amounts.

Gateway errors use controlled API responses: `502` for invalid model output, `503` when the service is unavailable, and `504` for timeouts. The uploaded receipt image is retained when LLM extraction fails so it can be recovered once persistence and the review queue are implemented. Automated tests use a mocked HTTP transport and never call the live gateway.

## Expense classification

The backend first checks a small set of manually validated, exact vendor mappings. Vendor names are normalized for case and punctuation, but substring matches are prohibited so broad retailers such as MR D.I.Y. are not mapped accidentally. Unmatched vendors are sent to the classification agent with the extracted receipt and optional business purpose.

The agent must select one fixed category and return a confidence score from zero to one. `CLASSIFICATION_CONFIDENCE_THRESHOLD` defaults to `0.80`. Extraction-review flags, classifier-review flags, or confidence below the threshold produce `REVIEW_QUEUE`; only a clean result at or above the threshold produces `AUTO_FILED`. Invalid or unavailable classification responses also produce a safe review decision rather than losing the accepted receipt.
