# PDF receipt ingestion

PDF upload uses the same authenticated `POST /receipts/upload` endpoint, duplicate
controls, extraction, classification, SQLite persistence and review workflow as
JPEG/PNG. The original `.pdf` is retained in the private receipt-data volume.

## Processing path

1. Stream at most `MAX_UPLOAD_BYTES` and require both `application/pdf` and `%PDF-`.
2. Block an exact SHA-256 duplicate before parsing, OCR, or gateway calls.
3. Inspect the PDF in a time-bounded worker process. Reject encryption, malformed
   structure, unsafe page dimensions, and documents outside `PDF_MAX_PAGES`.
4. Extract usable embedded text per page. Render pages without usable text and run
   those PNGs through `OCR_ENGINE`. A first-page PNG is retained for UI preview.
5. Join page text with explicit page markers and send text—not PDF bytes—to the
   existing LLM extraction/classification pipeline.

The default limits are:

```dotenv
MAX_UPLOAD_BYTES=5242880
PDF_MAX_PAGES=3
PDF_TIMEOUT_SECONDS=30
PDF_MAX_RENDER_PIXELS=30000000
```

Keep these limits for the MVP unless measurements justify a change. Raising them
increases CPU, memory and denial-of-service risk, especially on a small Lightsail
instance. The PDF timeout covers parsing and rendering; OCR uses its existing engine
limits. One uploaded PDF must contain one receipt. Split files containing several
invoices before upload.

## Responses and review

- 202: processing completed; `ocr_engine` begins with `pdf:` and identifies native
  text, OCR, or a per-page mixture.
- 409: exact original bytes were already uploaded; use `existing_receipt_id`.
- 415: media type or `%PDF-` signature did not match.
- 422: encrypted, malformed, excessive-page, unsafe-dimension, or textless PDF.
- 504: PDF inspection/rendering or OCR exceeded its timeout.

Use `GET /receipts/{id}/image` for the authenticated original and
`GET /receipts/{id}/preview` for the first-page image. A high OCR confidence or
native-text result still requires evidence review when classification or receipt
fields are ambiguous.

## Deployment check

After pulling the commit, rebuild the image because PDF libraries are new runtime
dependencies. Do not use `down -v`; the receipt-data volume contains the database,
original files and generated previews.

```bash
sudo docker compose build api
sudo docker compose up -d --wait --wait-timeout 120
sudo docker compose ps
curl --fail http://127.0.0.1:8000/health
```

Through the existing SSH tunnel, upload one native-text PDF and one scanned PDF,
open both originals/previews, and confirm the expected `pdf:` engine. Review logs
and memory during the first PaddleOCR request before increasing traffic.
