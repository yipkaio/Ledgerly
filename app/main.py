"""FastAPI entry point and secure receipt-ingestion boundary."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import logging
import os
import re
import secrets
import hashlib
import json
from datetime import date
from functools import lru_cache
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Annotated
from uuid import UUID, uuid4
from typing import Literal

from fastapi import Body, Depends, FastAPI, File, Form, Header, HTTPException, UploadFile, Query, status
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field, ValidationError
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from app.auth import (
    FirebaseAuthError,
    FirebaseAuthUnavailable,
    verify_firebase_token,
)
from app.images import receipt_image, receipt_preview
from app.agents.router import build_agent_router
from app.lifecycle import LifecycleRequest, apply_lifecycle, purge_expired
from app.reprocessing import ReprocessRequest, reprocess
from app.statements import (
    MonthlyExportRequest,
    StatementLifecycleRequest,
    change_statement_state,
    PaymentUpdate,
    StatementDuplicate,
    StatementInvalid,
    build_monthly_export,
    import_statement,
    import_previewed_statement,
    list_periods,
    monthly_reconciliation,
    create_preview_token,
    statement_preview,
    statement_source,
    update_payment_state,
    verify_preview_token,
)
from app.statement_extraction import (
    GatewayStatementExtractor,
    StatementExtractionError,
    StatementExtractionUnavailable,
    StatementExtractor,
    deterministic_statement_extract,
    redact_statement_text_for_ai,
)
from app.database import DatabaseError, DuplicateReceiptError, ReceiptStore
from app.amendments import AmendmentRequest, amendment_history, submit_amendment
from app.exporting import ExportInvalid, ExportRequest, build_export
from app.history import HistoryFilters
from app.dashboard import dashboard_summary
from app.fx import (
    ECBRateProvider,
    FXUnavailable,
    WorkspaceCurrency,
    latest_snapshot,
    set_workspace_currency,
    workspace_currency,
)
from app.review import (ReviewRequest, ReviewConflict, ReviewNotFound, ReviewInvalid,
                        pending_reviews, review_history, submit_review)

from app.classification import (
    ClassificationOutcome,
    ClassificationResponseError,
    ClassificationSource,
    ClassificationSuggestion,
    ClassificationTimeoutError,
    ClassificationUnavailableError,
    ExpenseClassifier,
    GatewayExpenseClassifier,
    apply_confidence_gate,
    failed_classification_outcome,
    WorkflowDecision,
)
from app.config import ConfigurationError, Settings, api_docs_enabled
from app.extraction import (
    ExtractionResponseError,
    ExtractionTimeoutError,
    ExtractionUnavailableError,
    GatewayReceiptExtractor,
    ReceiptExtraction,
    ReceiptExtractor,
)
from app.ocr import (
    OCRNoTextError,
    OCRProcessingError,
    OCRResult,
    OCRService,
    OCRTimeoutError,
    OCRUnavailableError,
    PaddleOCRService,
    TesseractOCRService,
)
from app.pdf import (
    PDFEncryptedError,
    PDFError,
    PDFPageLimitError,
    PDFOCRPageLimitError,
    PDFTimeoutError,
    extract_pdf,
    extract_pdf_text,
    render_pdf_first_page,
)

CHUNK_SIZE = 64 * 1024
RECEIPT_TYPES = {
    "image/jpeg": (".jpg", (b"\xff\xd8\xff",)),
    "image/png": (".png", (b"\x89PNG\r\n\x1a\n",)),
    "application/pdf": (".pdf", (b"%PDF-",)),
}


class ReceiptProcessed(BaseModel):
    receipt_id: str
    content_type: str
    size_bytes: int
    ocr_engine: str
    ocr_confidence: float | None
    ocr_text: str
    extracted_data: ReceiptExtraction
    business_purpose: str | None
    classification: ClassificationOutcome
    duplicate_candidates: list[str] = Field(default_factory=list)
    status: str = "processing_complete"


def get_settings() -> Settings:
    try:
        return Settings.from_environment()
    except ConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Application configuration is unavailable",
        ) from exc


async def require_api_key(
    settings: Annotated[Settings, Depends(get_settings)],
    supplied_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> Settings:
    """Authorize the UI with Firebase or trusted integrations with the app key."""

    if (
        settings.auth_mode in {"api_key", "hybrid"}
        and supplied_key is not None
        and secrets.compare_digest(supplied_key, settings.app_api_key)
    ):
        return settings

    if settings.auth_mode in {"firebase", "hybrid"} and authorization is not None:
        scheme, separator, token = authorization.partition(" ")
        if separator and scheme.casefold() == "bearer":
            try:
                await verify_firebase_token(token.strip(), settings)
                return settings
            except FirebaseAuthUnavailable as exc:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Authentication service is temporarily unavailable",
                ) from exc
            except FirebaseAuthError:
                pass

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication is required",
        headers={"WWW-Authenticate": "Bearer"},
    )


@lru_cache(maxsize=1)
def get_paddle_ocr_service(
    language: str, device: str, minimum_confidence: float
) -> PaddleOCRService:
    return PaddleOCRService.create(
        language=language,
        device=device,
        minimum_confidence=minimum_confidence,
    )


def get_ocr_service(
    settings: Annotated[Settings, Depends(get_settings)],
) -> OCRService:
    if settings.ocr_engine == "paddle":
        try:
            return get_paddle_ocr_service(
                settings.paddle_language,
                settings.paddle_device,
                settings.paddle_min_confidence,
            )
        except OCRUnavailableError as exc:
            raise HTTPException(status_code=503, detail="OCR service is unavailable") from exc

    return TesseractOCRService(
        executable=settings.tesseract_cmd,
        language=settings.tesseract_language,
        page_segmentation_mode=settings.tesseract_psm,
        timeout_seconds=settings.ocr_timeout_seconds,
    )


def get_receipt_extractor(
    settings: Annotated[Settings, Depends(get_settings)],
) -> ReceiptExtractor:
    return GatewayReceiptExtractor(
        base_url=settings.llm_gateway_url,
        api_key=settings.llm_gateway_api_key,
        model=settings.llm_model,
        timeout_seconds=settings.llm_timeout_seconds,
        max_output_tokens=settings.llm_max_output_tokens,
    )


def get_expense_classifier(
    settings: Annotated[Settings, Depends(get_settings)],
) -> ExpenseClassifier:
    return GatewayExpenseClassifier(
        base_url=settings.llm_gateway_url,
        api_key=settings.llm_gateway_api_key,
        model=settings.llm_model,
        timeout_seconds=settings.llm_timeout_seconds,
        max_output_tokens=settings.llm_max_output_tokens,
    )


def get_statement_extractor(
    settings: Annotated[Settings, Depends(get_settings)],
) -> StatementExtractor:
    return GatewayStatementExtractor(
        base_url=settings.llm_gateway_url,
        api_key=settings.llm_gateway_api_key,
        model=settings.llm_model,
        timeout_seconds=settings.llm_timeout_seconds,
        max_output_tokens=settings.statement_llm_max_output_tokens,
    )


def get_fx_rate_provider() -> ECBRateProvider:
    return ECBRateProvider()


def has_expected_signature(content_type: str, prefix: bytes) -> bool:
    return any(
        prefix.startswith(signature) for signature in RECEIPT_TYPES[content_type][1]
    )


@asynccontextmanager
async def lifespan(api):
    async def cleanup():
        while True:
            try:
                settings = get_settings()
                await run_in_threadpool(purge_expired, ReceiptStore(settings.database_path), settings.upload_dir)
            except Exception:
                logging.getLogger(__name__).warning("Receipt retention cleanup failed; will retry")
            await asyncio.sleep(3600)
    task = asyncio.create_task(cleanup())
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


def create_app() -> FastAPI:
    docs_enabled = api_docs_enabled()
    api = FastAPI(
        lifespan=lifespan,
        title="Expense Classification Agent",
        version="0.1.0",
        description="Receipt intake for the OCR and expense-classification pipeline.",
        docs_url="/docs" if docs_enabled else None,
        redoc_url="/redoc" if docs_enabled else None,
        openapi_url="/openapi.json" if docs_enabled else None,
    )

    api.include_router(build_agent_router(get_settings, require_api_key))

    @api.get(
        "/auth/config",
        tags=["authentication"],
        summary="Return the public web authentication mode",
    )
    async def authentication_config(
        settings: Annotated[Settings, Depends(get_settings)],
    ):
        if settings.auth_mode == "api_key":
            return {"mode": "api_key"}
        return {
            "mode": "firebase",
            "firebase_web_api_key": settings.firebase_web_api_key,
            "firebase_project_id": settings.firebase_project_id,
        }

    @api.exception_handler(DatabaseError)
    async def database_error_handler(request, exc):
        return JSONResponse(status_code=503, content={"detail": "Receipt database is unavailable"})

    @api.exception_handler(DuplicateReceiptError)
    async def duplicate_receipt_handler(request, exc):
        return JSONResponse(
            status_code=409,
            content={
                "detail": "This exact receipt file was already uploaded",
                "existing_receipt_id": exc.receipt_id,
            },
            headers={"X-Receipt-ID": exc.receipt_id},
        )

    @api.exception_handler(ReviewConflict)
    async def review_conflict_handler(request, exc):
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @api.exception_handler(ReviewNotFound)
    async def review_missing_handler(request, exc):
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @api.exception_handler(ReviewInvalid)
    async def review_invalid_handler(request, exc):
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @api.exception_handler(ExportInvalid)
    async def export_invalid_handler(request, exc):
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @api.exception_handler(StatementInvalid)
    async def statement_invalid_handler(request, exc):
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @api.exception_handler(StatementDuplicate)
    async def statement_duplicate_handler(request, exc):
        return JSONResponse(status_code=409, content={
            "detail": str(exc), "statement_id": exc.statement_id,
        })

    @api.post("/bank-statements/upload", tags=["reconciliation"],
              summary="Import a normalized monthly bank statement CSV")
    async def upload_bank_statement(
        statement: Annotated[UploadFile, File()],
        statement_month: Annotated[str, Form(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")],
        currency: Annotated[str, Form(pattern=r"^[A-Z]{3}$")],
        account_label: Annotated[str, Form(min_length=2, max_length=100)],
        settings: Annotated[Settings, Depends(require_api_key)],
        imported_by: Annotated[str, Form(min_length=2, max_length=100)] = "Shared workspace user",
    ) -> dict:
        filename = statement.filename or "statement.csv"
        if not filename.lower().endswith(".csv"):
            raise HTTPException(status_code=415, detail="Bank statement must be a CSV file")
        content = await statement.read(2 * 1024 * 1024 + 1)
        return await run_in_threadpool(
            import_statement, ReceiptStore(settings.database_path), content, filename,
            statement_month, currency, account_label, imported_by,
        )

    @api.post("/bank-statements/preview", tags=["reconciliation"],
              summary="Safely preview a PDF bank statement before import")
    async def preview_bank_statement(
        statement: Annotated[UploadFile, File()],
        statement_month: Annotated[str, Form(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")],
        currency: Annotated[str, Form(pattern=r"^[A-Z]{3}$")],
        account_label: Annotated[str, Form(min_length=2, max_length=100)],
        settings: Annotated[Settings, Depends(require_api_key)],
        ocr_service: Annotated[OCRService, Depends(get_ocr_service)],
        statement_extractor: Annotated[StatementExtractor, Depends(get_statement_extractor)],
        password: Annotated[str | None, Form(max_length=200)] = None,
        allow_ai: Annotated[bool, Form()] = False,
        imported_by: Annotated[str, Form(min_length=2, max_length=100)] = "Shared workspace user",
    ) -> dict:
        filename = statement.filename or "statement.pdf"
        if not filename.lower().endswith(".pdf"):
            raise HTTPException(status_code=415, detail="Statement preview requires a PDF file")
        content = await statement.read(settings.statement_pdf_max_bytes + 1)
        await statement.close()
        if len(content) > settings.statement_pdf_max_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"Bank statement PDF must be no larger than {settings.statement_pdf_max_bytes // (1024 * 1024)} MB",
            )
        if not content.startswith(b"%PDF-"):
            raise HTTPException(status_code=415, detail="Bank statement file is not a valid PDF")
        try:
            with TemporaryDirectory(prefix="ledgerly-statement-") as directory:
                source = Path(directory) / "statement.pdf"
                source.write_bytes(content)
                ocr_result = await run_in_threadpool(
                    extract_pdf_text,
                    source,
                    ocr_service,
                    max_pages=settings.statement_pdf_max_pages,
                    max_render_pixels=settings.statement_pdf_max_render_pixels,
                    timeout_seconds=settings.statement_pdf_timeout_seconds,
                    password=password,
                )
        except PDFEncryptedError as exc:
            raise HTTPException(
                status_code=422, detail="This PDF is encrypted; enter its password and try again"
            ) from exc
        except PDFPageLimitError as exc:
            raise HTTPException(
                status_code=422,
                detail=f"Bank statement PDF must contain 1 to {settings.statement_pdf_max_pages} pages",
            ) from exc
        except PDFOCRPageLimitError as exc:
            raise HTTPException(
                status_code=422,
                detail="Scanned statements are limited to 10 OCR pages; use the bank's text PDF or CSV export",
            ) from exc
        except PDFTimeoutError as exc:
            raise HTTPException(status_code=504, detail="Bank statement PDF timed out") from exc
        except PDFError as exc:
            raise HTTPException(status_code=422, detail="Bank statement PDF could not be processed") from exc
        except OCRTimeoutError as exc:
            raise HTTPException(status_code=504, detail="Bank statement OCR timed out") from exc
        except OCRUnavailableError as exc:
            raise HTTPException(status_code=503, detail="OCR service is unavailable") from exc
        except (OCRProcessingError, OCRNoTextError) as exc:
            raise HTTPException(status_code=422, detail="Bank statement text could not be extracted") from exc

        method = "deterministic"
        try:
            extraction = await run_in_threadpool(
                deterministic_statement_extract, ocr_result.text, statement_month
            )
        except StatementExtractionError:
            if not allow_ai:
                raise StatementInvalid(
                    "This PDF layout needs the optional AI fallback. Review the privacy notice and retry with AI enabled, or upload a normalized CSV."
                )
            method = "ai"
            try:
                extraction = await statement_extractor.extract(
                    redact_statement_text_for_ai(ocr_result.text)
                )
            except StatementExtractionUnavailable as exc:
                raise HTTPException(status_code=503, detail=str(exc)) from exc
            except StatementExtractionError as exc:
                raise HTTPException(
                    status_code=502, detail="Bank statement AI extraction returned an invalid result"
                ) from exc
        preview = statement_preview(
            extraction, statement_month, currency, account_label, method, ocr_result.engine,
            imported_by,
        )
        return {
            "preview": preview,
            "confirmation_token": create_preview_token(settings.app_api_key, content, preview),
            "expires_in_seconds": 30 * 60,
        }

    @api.post("/bank-statements/confirm", tags=["reconciliation"],
              summary="Confirm and retain an exact PDF statement preview")
    async def confirm_bank_statement(
        statement: Annotated[UploadFile, File()],
        preview_json: Annotated[str, Form(max_length=2_000_000)],
        confirmation_token: Annotated[str, Form(min_length=20, max_length=1000)],
        evidence_confirmed: Annotated[bool, Form()],
        settings: Annotated[Settings, Depends(require_api_key)],
    ) -> dict:
        if not evidence_confirmed:
            raise StatementInvalid("Confirm that the extracted rows were checked against the PDF")
        filename = statement.filename or "statement.pdf"
        if not filename.lower().endswith(".pdf"):
            raise HTTPException(status_code=415, detail="Statement confirmation requires the same PDF")
        content = await statement.read(settings.statement_pdf_max_bytes + 1)
        await statement.close()
        if len(content) > settings.statement_pdf_max_bytes:
            raise HTTPException(status_code=413, detail="Bank statement PDF is too large")
        if not content.startswith(b"%PDF-"):
            raise HTTPException(status_code=415, detail="Bank statement file is not a valid PDF")
        try:
            preview = json.loads(preview_json)
        except (json.JSONDecodeError, TypeError) as exc:
            raise StatementInvalid("Statement preview is invalid; preview the file again") from exc
        verify_preview_token(
            settings.app_api_key, confirmation_token, content, preview
        )
        return await run_in_threadpool(
            import_previewed_statement,
            ReceiptStore(settings.database_path),
            content,
            filename,
            "application/pdf",
            preview,
        )

    @api.post("/bank-statements/{statement_id}/lifecycle", tags=["reconciliation"])
    async def statement_lifecycle(
        statement_id: UUID,
        body: StatementLifecycleRequest,
        settings: Annotated[Settings, Depends(require_api_key)],
    ):
        try:
            return await run_in_threadpool(
                change_statement_state, ReceiptStore(settings.database_path), str(statement_id), body
            )
        except StatementInvalid as exc:
            raise HTTPException(status_code=404 if "not found" in str(exc) else 409,
                                detail=str(exc)) from exc

    @api.get("/bank-statements/periods", tags=["reconciliation"],
             summary="List imported statement months")
    async def bank_statement_periods(
        settings: Annotated[Settings, Depends(require_api_key)],
    ) -> dict:
        return {"items": await run_in_threadpool(list_periods, ReceiptStore(settings.database_path))}

    @api.get("/bank-statements/{statement_id}/source", tags=["reconciliation"],
             summary="Download the retained original bank statement PDF or CSV")
    async def download_bank_statement(
        statement_id: UUID,
        settings: Annotated[Settings, Depends(require_api_key)],
    ) -> Response:
        filename, media_type, content = await run_in_threadpool(
            statement_source, ReceiptStore(settings.database_path), str(statement_id),
        )
        safe_name = re.sub(r"[^A-Za-z0-9._-]+", "-", filename) or "statement.csv"
        response_type = "text/csv; charset=utf-8" if media_type == "text/csv" else media_type
        return Response(content=content, media_type=response_type,
                        headers={"Content-Disposition": f'attachment; filename="{safe_name}"'})

    @api.get(
        "/bank-statements/{statement_id}/source-preview",
        tags=["reconciliation"],
        summary="Render a safe first-page PNG preview of a retained bank statement PDF",
    )
    async def preview_bank_statement_source(
        statement_id: UUID,
        settings: Annotated[Settings, Depends(require_api_key)],
    ) -> Response:
        _, media_type, content = await run_in_threadpool(
            statement_source, ReceiptStore(settings.database_path), str(statement_id),
        )
        if media_type != "application/pdf" and not content.startswith(b"%PDF-"):
            raise HTTPException(status_code=404, detail="Statement preview is available for PDF sources only")
        try:
            preview = await run_in_threadpool(
                render_pdf_first_page,
                content,
                max_pages=settings.statement_pdf_max_pages,
                max_render_pixels=settings.statement_pdf_max_render_pixels,
                timeout_seconds=settings.statement_pdf_timeout_seconds,
            )
        except PDFTimeoutError as exc:
            raise HTTPException(status_code=504, detail="Statement preview timed out") from exc
        except PDFError as exc:
            raise HTTPException(status_code=422, detail="Statement preview could not be rendered") from exc
        return Response(
            content=preview,
            media_type="image/png",
            headers={
                "Content-Disposition": f'inline; filename="{statement_id}-preview.png"',
                "Content-Security-Policy": "default-src 'none'; sandbox",
            },
        )

    @api.get("/reconciliation", tags=["reconciliation"],
             summary="Compare accepted receipts with imported bank debits")
    async def reconciliation(
        month: Annotated[str, Query(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")],
        currency: Annotated[str, Query(pattern=r"^[A-Z]{3}$")],
        settings: Annotated[Settings, Depends(require_api_key)],
    ) -> dict:
        return await run_in_threadpool(
            monthly_reconciliation, ReceiptStore(settings.database_path), month, currency,
        )

    @api.post("/receipts/{receipt_id}/payment-state", tags=["reconciliation"],
              summary="Record an audited payable or payment-issue status")
    async def payment_state(
        receipt_id: UUID,
        body: PaymentUpdate,
        settings: Annotated[Settings, Depends(require_api_key)],
    ) -> dict:
        return await run_in_threadpool(
            update_payment_state, ReceiptStore(settings.database_path), str(receipt_id), body,
        )

    @api.post("/reconciliation/export", tags=["reconciliation"],
              summary="Export a monthly reconciliation workbook")
    async def export_reconciliation(
        body: MonthlyExportRequest,
        settings: Annotated[Settings, Depends(require_api_key)],
    ) -> Response:
        content = await run_in_threadpool(
            build_monthly_export, ReceiptStore(settings.database_path), body.month, body.currency,
        )
        filename = f"ledgerly-reconciliation-{body.month}-{body.currency}.xlsx"
        return Response(content=content,
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": f'attachment; filename="{filename}"'})

    @api.post("/receipts/{receipt_id}/reprocess", tags=["receipts"],
              summary="Create a review draft from saved OCR (may incur AI cost)")
    async def reprocess_receipt(receipt_id: UUID, body: ReprocessRequest,
                                settings: Annotated[Settings, Depends(require_api_key)],
                                extractor: Annotated[ReceiptExtractor, Depends(get_receipt_extractor)]) -> dict:
        return await reprocess(ReceiptStore(settings.database_path), str(receipt_id), body,
                               extractor, settings.llm_model)

    @api.post("/receipts/{receipt_id}/lifecycle", tags=["receipts"],
              summary="Move to deleted receipts, restore within 30 days, or void a finalized receipt")
    async def lifecycle(receipt_id: UUID, body: LifecycleRequest,
                        settings: Annotated[Settings, Depends(require_api_key)]) -> dict:
        return await run_in_threadpool(apply_lifecycle, ReceiptStore(settings.database_path), str(receipt_id), body)

    @api.get("/reviews", tags=["reviews"], summary="1. List receipts awaiting human review",
             description="Read only. Copy a receipt_id, then use GET /receipts/{receipt_id}. Empty items means no pending receipts on THIS server. Local port 8000 and the AWS tunnel port 18000 use separate databases. Finalized, AUTO_FILED, FAILED and PROCESSING receipts are excluded.")
    async def reviews(settings: Annotated[Settings, Depends(require_api_key)],
                      limit: Annotated[int, Query(ge=1, le=100)] = 20,
                      offset: Annotated[int, Query(ge=0)] = 0) -> dict:
        return await run_in_threadpool(pending_reviews, ReceiptStore(settings.database_path), limit, offset)

    @api.post("/receipts/{receipt_id}/review", tags=["reviews"],
              summary="3. Finalize approval or rejection (writes data)",
              description="""**Approval/rejection is final. Approved records can later receive audited amendments; rejected records cannot be reopened. Use disposable records for testing.**

1. First GET the receipt detail and check `review` is null and `review_version` is 0.
2. Compare the original image with vendor, date, currency, EVERY line item, discounts, tax and totals. Use the authenticated GET /receipts/{receipt_id}/image endpoint or the /ui/ receipt workspace.
3. Read all extraction AND classification reasons. Establish business purpose; explain the category and any corrections in `note`. If uncertain, leave it pending rather than approving.
4. Generate a new request UUID in PowerShell: `[guid]::NewGuid().ToString()`. It is not the receipt ID or an API key.
5. Choose an example below and replace ALL REPLACE_ values. For approval replace `corrected_data: null` with the COMPLETE `extracted_data` object from GET, editing only verified fields. Choose the justified category. For rejection omit corrections, category and override.
6. Set `evidence_confirmed` to true only after inspection. Click Execute ONCE and read **Server response**, not Curl (which includes your secret key).
7. Verify GET receipt detail, GET receipt reviews, and GET /reviews. Finalized receipts leave the pending queue; original processing_status stays historical. `review.decision` is the human result.

Review currencies currently supported: SGD, MYR, USD, EUR, GBP, AUD. Unknown optional values remain null; never invent zero or discounts. Vendor, date, currency and total are required for approval. Zero totals are allowed when verified. `override_reason` is only for a documented remaining arithmetic discrepancy, not a way to bypass missing fields, unsupported currency or placeholders. Arithmetic uses a 0.02 tolerance and cannot establish business purpose or truth of the receipt.

On timeout, GET the receipt first, then retry the SAME UUID and identical payload if needed. A new UUID does not create a second review. Correct an approved record through the amendment endpoint; do not overwrite its audit history. Review names are self-reported under the shared app key; no vendor rule is learned and no payment/accounting posting occurs.""",
              responses={200: {"description": "Decision saved, or identical retry returned; inspect decision and review_version."},
                         401: {"description": "Missing/wrong APP_API_KEY for this server; do not use the gateway key."},
                         404: {"description": "Receipt not found on this server."},
                         409: {"description": "Not pending, already finalized, stale version, or request ID reused with different content. GET detail before retrying."},
                         422: {"description": "Invalid request or unresolved validation issues; correct the request, do not blindly override."},
                         503: {"description": "Database unavailable or authentication not configured. Inspect detail; GET receipt before retrying."}})
    async def review(receipt_id: UUID, body: Annotated[ReviewRequest, Body(openapi_examples={
        "approve": {"summary": "Approval template: replace UUID, text, category and complete extraction",
                    "value": {"request_id": "REPLACE_WITH_NEW_UUID", "expected_version": 0, "decision": "APPROVED",
                              "reviewer": "REPLACE_WITH_YOUR_NAME", "note": "REPLACE_WITH_EVIDENCE_AND_BUSINESS_PURPOSE",
                              "evidence_confirmed": False, "corrected_data": None, "category": "Office Supplies"}},
        "reject": {"summary": "Rejection template: replace UUID and text; inspect image first",
                   "value": {"request_id": "REPLACE_WITH_NEW_UUID", "expected_version": 0, "decision": "REJECTED",
                             "reviewer": "REPLACE_WITH_YOUR_NAME", "note": "REPLACE_WITH_REJECTION_REASON",
                             "evidence_confirmed": False}}
    })],
                     settings: Annotated[Settings, Depends(require_api_key)]) -> dict:
        return await run_in_threadpool(submit_review, ReceiptStore(settings.database_path), str(receipt_id), body)

    @api.get("/receipts/{receipt_id}/reviews", tags=["reviews"], summary="4. Inspect saved review audit (read only)",
             description="Empty items means no review yet. A saved event includes before (original AI evidence), final_data, decision, reviewer and timestamp. Rejection has no final_data. History cannot be edited or deleted through this API.")
    async def history(receipt_id: UUID,
                      settings: Annotated[Settings, Depends(require_api_key)]) -> dict:
        return await run_in_threadpool(review_history, ReceiptStore(settings.database_path), str(receipt_id))

    @api.post(
        "/receipts/{receipt_id}/amendments",
        tags=["reviews"],
        summary="Amend an auto-filed or approved receipt (append-only)",
        description="Creates a new effective version without changing original OCR, AI extraction, review, or earlier amendments. Copy record_version from GET receipt detail, verify the original evidence, provide the complete corrected data and category, and use a new request UUID. Stale versions and rejected/pending/failed receipts are rejected.",
        responses={
            200: {"description": "Amendment saved, or identical retry returned."},
            409: {"description": "Stale version, ineligible receipt, or request UUID conflict."},
            422: {"description": "Invalid fields or unresolved arithmetic issues."},
        },
    )
    async def amend(
        receipt_id: UUID,
        body: AmendmentRequest,
        settings: Annotated[Settings, Depends(require_api_key)],
    ) -> dict:
        return await run_in_threadpool(
            submit_amendment,
            ReceiptStore(settings.database_path),
            str(receipt_id),
            body,
        )

    @api.get(
        "/receipts/{receipt_id}/amendments",
        tags=["reviews"],
        summary="Inspect immutable receipt amendment history",
    )
    async def amendments(
        receipt_id: UUID,
        settings: Annotated[Settings, Depends(require_api_key)],
    ) -> dict:
        return await run_in_threadpool(
            amendment_history, ReceiptStore(settings.database_path), str(receipt_id)
        )

    @api.get('/dashboard', tags=['dashboard'], summary='Workspace counts and accepted expense totals',
             description='Read only and authenticated. Human decisions take precedence. Native amounts include APPROVED and AUTO_FILED receipts only and remain grouped by currency. Optional inclusive date_from and date_to filters use effective receipt dates and apply to accepted counts, totals, categories and trends. dated_only=true includes all dated accepted receipts, including any added since the last request; undated receipts are excluded from dated reporting. Workspace workflow counts remain unfiltered. When a default currency is configured, a separately labelled management estimate converts accepted amounts with a dated ECB reference-rate snapshot; original amounts are unchanged and receipt-to-bank matching never uses converted values. These are workflow estimates, not accounting postings or transaction rates.',
             responses={401: {'description': 'Missing or wrong app key'}, 503: {'description': 'Database or configuration unavailable'}})
    async def dashboard(
        settings: Annotated[Settings, Depends(require_api_key)],
        fx_provider: Annotated[ECBRateProvider, Depends(get_fx_rate_provider)],
        date_from: date | None = None,
        date_to: date | None = None,
        dated_only: bool = False,
    ) -> dict:
        if date_from is not None and date_to is not None and date_from > date_to:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="date_from must be on or before date_to",
            )
        store = ReceiptStore(settings.database_path)
        default = await run_in_threadpool(workspace_currency, store)
        snapshot = None
        if default:
            try:
                snapshot = await latest_snapshot(store, fx_provider)
            except FXUnavailable:
                pass
        return await run_in_threadpool(
            dashboard_summary, store, snapshot, date_from, date_to, dated_only
        )

    @api.get('/workspace/settings', tags=['dashboard'], summary='Read workspace reporting settings')
    async def read_workspace_settings(
        settings: Annotated[Settings, Depends(require_api_key)],
    ) -> dict:
        return {'default_currency': await run_in_threadpool(
            workspace_currency, ReceiptStore(settings.database_path)
        )}

    @api.put('/workspace/settings', tags=['dashboard'], summary='Choose the default reporting currency')
    async def update_workspace_settings(
        body: WorkspaceCurrency,
        settings: Annotated[Settings, Depends(require_api_key)],
    ) -> dict:
        return await run_in_threadpool(
            set_workspace_currency, ReceiptStore(settings.database_path), body.default_currency
        )

    @api.get("/receipts", tags=["receipts"])
    async def list_receipts(
        settings: Annotated[Settings, Depends(require_api_key)],
        decision: Literal["AUTO_FILED", "REVIEW_QUEUE"] | None = None,
        processing_status: Literal["PROCESSING", "COMPLETED", "REVIEW_QUEUE", "FAILED"] | None = None,
        query: Annotated[str | None, Query(max_length=100)] = None,
        vendor: Annotated[str | None, Query(max_length=100)] = None,
        category: Annotated[list[str] | None, Query()] = None,
        currency: Annotated[list[str] | None, Query()] = None,
        state: Annotated[list[str] | None, Query()] = None,
        date_from: date | None = None,
        date_to: date | None = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 20,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> dict:
        try:
            filters = HistoryFilters(query=query, vendor=vendor, category=category,
                                     currency=currency, state=state,
                                     date_from=date_from, date_to=date_to)
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail="Invalid receipt history filters") from exc
        return await run_in_threadpool(
            ReceiptStore(settings.database_path).list,
            decision,
            processing_status,
            limit,
            offset,
            filters,
        )

    @api.post(
        "/receipts/export",
        tags=["receipts"],
        summary="Export selected or filtered receipt history to Excel",
        description="Authenticated, read-only export using the latest effective receipt values and one SQLite snapshot. Supply 1-500 receipt_ids for selected rows, or omit receipt_ids and supply filters to export up to 1000 matching rows. The workbook contains Overview, Receipts, Line items and Review audit sheets. It never runs OCR or the LLM.",
        responses={200: {"content": {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": {}}},
                   422: {"description": "Invalid selection, missing selected record, or filtered result too large."}},
    )
    async def export_receipts(
        body: ExportRequest,
        settings: Annotated[Settings, Depends(require_api_key)],
    ) -> Response:
        content, count = await run_in_threadpool(
            build_export, ReceiptStore(settings.database_path), body
        )
        return Response(
            content=content,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": 'attachment; filename="receipt-history.xlsx"',
                "X-Receipt-Count": str(count),
            },
        )

    @api.get("/receipts/{receipt_id}", tags=["receipts"], summary="2. View receipt and copy extraction (read only)",
             description="This GET has no JSON request body and does not approve anything. Enter receipt_id and APP_API_KEY. Copy extracted_data from Server response for an approval, not the whole response or Curl. Check review and review_version before submitting. Original processing_status/classification remain historical; review.decision is the saved human decision.")
    async def get_receipt(
        receipt_id: UUID,
        settings: Annotated[Settings, Depends(require_api_key)],
    ) -> dict:
        result = await run_in_threadpool(ReceiptStore(settings.database_path).get, str(receipt_id))
        if result is None:
            raise HTTPException(status_code=404, detail="Receipt not found")
        return result

    @api.get("/health", tags=["system"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @api.post(
        "/receipts/upload",
        response_model=ReceiptProcessed,
        status_code=status.HTTP_202_ACCEPTED,
        tags=["receipts"],
    )
    async def upload_receipt(
        receipt: Annotated[UploadFile, File(description="JPEG, PNG, or PDF receipt")],
        settings: Annotated[Settings, Depends(require_api_key)],
        ocr_service: Annotated[OCRService, Depends(get_ocr_service)],
        receipt_extractor: Annotated[
            ReceiptExtractor, Depends(get_receipt_extractor)
        ],
        expense_classifier: Annotated[
            ExpenseClassifier, Depends(get_expense_classifier)
        ],
        business_purpose: Annotated[
            str | None,
            Form(
                max_length=500,
                description="Optional business reason or project for this expense",
            ),
        ] = None,
    ) -> ReceiptProcessed:
        content_type = (receipt.content_type or "").lower()
        if content_type not in RECEIPT_TYPES:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail="Only JPEG, PNG, and PDF receipts are supported",
            )

        receipt_id = str(uuid4())
        extension = RECEIPT_TYPES[content_type][0]
        temporary_path = settings.upload_dir / f".{receipt_id}.upload"
        final_path = settings.upload_dir / f"{receipt_id}{extension}"
        preview_path = settings.upload_dir / f"{receipt_id}.preview.png"
        size = 0
        prefix = b""
        digest = hashlib.sha256()

        try:
            settings.upload_dir.mkdir(parents=True, exist_ok=True)
            with temporary_path.open("xb") as destination:
                while chunk := await receipt.read(CHUNK_SIZE):
                    size += len(chunk)
                    if size > settings.max_upload_bytes:
                        raise HTTPException(
                            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                            detail="Receipt exceeds the configured upload limit",
                        )
                    if len(prefix) < 16:
                        prefix += chunk[: 16 - len(prefix)]
                    digest.update(chunk)
                    destination.write(chunk)

            if size == 0 or not has_expected_signature(content_type, prefix):
                raise HTTPException(
                    status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                    detail="File content does not match its declared image type",
                )

            os.replace(temporary_path, final_path)
        except HTTPException:
            temporary_path.unlink(missing_ok=True)
            raise
        except OSError as exc:
            temporary_path.unlink(missing_ok=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Receipt could not be stored",
            ) from exc
        finally:
            await receipt.close()

        store = ReceiptStore(settings.database_path)
        try:
            await run_in_threadpool(
                store.start, receipt_id, content_type, size, str(final_path.resolve()),
                (business_purpose.strip() if business_purpose else None) or None,
                digest.hexdigest(),
            )
        except DuplicateReceiptError:
            final_path.unlink(missing_ok=True)
            raise
        except DatabaseError:
            final_path.unlink(missing_ok=True)
            raise

        async def process() -> ReceiptProcessed:
            try:
                if content_type == "application/pdf":
                    ocr_result = await run_in_threadpool(
                        extract_pdf,
                        final_path,
                        ocr_service,
                        preview_path,
                        max_pages=settings.pdf_max_pages,
                        max_render_pixels=settings.pdf_max_render_pixels,
                        timeout_seconds=settings.pdf_timeout_seconds,
                    )
                else:
                    ocr_result = await run_in_threadpool(ocr_service.extract, final_path)
            except PDFEncryptedError as exc:
                final_path.unlink(missing_ok=True)
                preview_path.unlink(missing_ok=True)
                raise HTTPException(
                    status_code=422, detail="Encrypted PDFs are not supported"
                ) from exc
            except PDFPageLimitError as exc:
                final_path.unlink(missing_ok=True)
                preview_path.unlink(missing_ok=True)
                raise HTTPException(
                    status_code=422,
                    detail=f"PDF must contain 1 to {settings.pdf_max_pages} pages",
                ) from exc
            except PDFTimeoutError as exc:
                final_path.unlink(missing_ok=True)
                preview_path.unlink(missing_ok=True)
                raise HTTPException(status_code=504, detail="Receipt PDF timed out") from exc
            except PDFError as exc:
                final_path.unlink(missing_ok=True)
                preview_path.unlink(missing_ok=True)
                raise HTTPException(
                    status_code=422, detail="Receipt PDF could not be processed"
                ) from exc
            except OCRUnavailableError as exc:
                final_path.unlink(missing_ok=True)
                preview_path.unlink(missing_ok=True)
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="OCR service is unavailable",
                ) from exc
            except OCRTimeoutError as exc:
                final_path.unlink(missing_ok=True)
                preview_path.unlink(missing_ok=True)
                raise HTTPException(
                    status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                    detail="Receipt OCR timed out",
                ) from exc
            except (OCRProcessingError, OCRNoTextError) as exc:
                final_path.unlink(missing_ok=True)
                preview_path.unlink(missing_ok=True)
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail="Receipt text could not be extracted",
                ) from exc

            await run_in_threadpool(store.save_ocr, receipt_id, ocr_result.text, ocr_result.engine, ocr_result.confidence)

            try:
                extracted_data = await receipt_extractor.extract(ocr_result.text)
            except ExtractionTimeoutError as exc:
                raise HTTPException(
                    status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                    detail="Receipt extraction timed out",
                ) from exc
            except ExtractionUnavailableError as exc:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Receipt extraction service is unavailable",
                ) from exc
            except ExtractionResponseError as exc:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="Receipt extraction returned an invalid response",
                ) from exc

            normalized_business_purpose = (
                business_purpose.strip() if business_purpose else None
            ) or None
            duplicate_candidates = await run_in_threadpool(
                store.probable_duplicates,
                receipt_id,
                extracted_data.model_dump(mode="json"),
            )
            await run_in_threadpool(
                store.save_duplicate_candidates, receipt_id, duplicate_candidates
            )
            lookup_category = await run_in_threadpool(store.lookup_vendor, extracted_data.vendor)
            if lookup_category is None:
                lookup_category = await run_in_threadpool(store.lookup_vendor, extracted_data.legal_entity)

            if lookup_category is not None:
                suggestion = ClassificationSuggestion(
                    category=lookup_category,
                    confidence=1,
                    reason="Matched a validated exact vendor-to-category rule",
                    needs_review=False,
                    review_reasons=[],
                )
                classification = apply_confidence_gate(
                    extracted_data,
                    suggestion,
                    ClassificationSource.VENDOR_LOOKUP,
                    settings.classification_confidence_threshold,
                )
            else:
                try:
                    suggestion = await expense_classifier.classify(
                        extracted_data,
                        normalized_business_purpose,
                    )
                    classification = apply_confidence_gate(
                        extracted_data,
                        suggestion,
                        ClassificationSource.LLM,
                        settings.classification_confidence_threshold,
                    )
                except ClassificationTimeoutError:
                    classification = failed_classification_outcome(
                        "Expense classification timed out"
                    )
                except ClassificationUnavailableError:
                    classification = failed_classification_outcome(
                        "Expense classification service is unavailable"
                    )
                except ClassificationResponseError:
                    classification = failed_classification_outcome(
                        "Expense classification returned an invalid response"
                    )

            if duplicate_candidates:
                duplicate_reason = (
                    "Possible duplicate of receipt " + duplicate_candidates[0]
                )
                reasons = list(dict.fromkeys(
                    [*classification.review_reasons, duplicate_reason]
                ))[:20]
                classification = classification.model_copy(
                    update={
                        "needs_review": True,
                        "review_reasons": reasons,
                        "workflow_decision": WorkflowDecision.REVIEW_QUEUE,
                    }
                )

            return ReceiptProcessed(
                receipt_id=receipt_id,
                content_type=content_type,
                size_bytes=size,
                ocr_engine=ocr_result.engine,
                ocr_confidence=ocr_result.confidence,
                ocr_text=ocr_result.text,
                extracted_data=extracted_data,
                business_purpose=normalized_business_purpose,
                classification=classification,
                duplicate_candidates=duplicate_candidates,
            )

        try:
            result = await process()
            await run_in_threadpool(store.complete, result.model_dump(mode="json"))
            return result
        except HTTPException as exc:
            await run_in_threadpool(store.fail, receipt_id, str(exc.detail))
            exc.headers = {**(exc.headers or {}), "X-Receipt-ID": receipt_id}
            raise
        except DatabaseError as exc:
            # Best effort only: the disk may still be unavailable.
            try:
                await run_in_threadpool(store.fail, receipt_id, "Receipt persistence failed")
            except DatabaseError:
                pass
            raise HTTPException(
                status_code=503, detail="Receipt database is unavailable",
                headers={"X-Receipt-ID": receipt_id},
            ) from exc
        except Exception as exc:
            await run_in_threadpool(store.fail, receipt_id, "Receipt processing failed")
            raise HTTPException(
                status_code=500, detail="Receipt processing failed",
                headers={"X-Receipt-ID": receipt_id},
            ) from exc

    @api.get('/receipts/{receipt_id}/image', tags=['receipts'], summary='View original receipt file (authenticated)',
             response_class=Response,
             description='Read only. Use the app key and saved receipt UUID. Returns the retained JPEG, PNG, or PDF, never a database-supplied file path. Missing or invalid files return 404; do not approve without checking original evidence. The /ui/ workspace handles authenticated loading for you.',
             responses={200: {'description': 'Original JPEG, PNG, or PDF', 'content': {'image/jpeg': {}, 'image/png': {}, 'application/pdf': {}}},
                        401: {'description': 'Missing or wrong app key'},
                        404: {'description': 'Receipt or retained image unavailable'},
                        503: {'description': 'Database or app configuration unavailable'}})
    async def image(receipt_id: UUID, settings: Annotated[Settings, Depends(require_api_key)]):
        return await run_in_threadpool(receipt_image, ReceiptStore(settings.database_path),
                                       settings.upload_dir, str(receipt_id), settings.max_upload_bytes)

    @api.get('/receipts/{receipt_id}/preview', tags=['receipts'], summary='View receipt preview image (authenticated)',
             response_class=Response,
             description='Returns the original JPEG/PNG or a bounded generated PNG of the first PDF page. It never reruns OCR or the LLM.',
             responses={200: {'description': 'Preview image', 'content': {'image/jpeg': {}, 'image/png': {}}},
                        401: {'description': 'Missing or wrong app key'},
                        404: {'description': 'Receipt or preview unavailable'}})
    async def preview(receipt_id: UUID, settings: Annotated[Settings, Depends(require_api_key)]):
        return await run_in_threadpool(receipt_preview, ReceiptStore(settings.database_path),
                                       settings.upload_dir, str(receipt_id), settings.max_upload_bytes)

    @api.middleware('http')
    async def privacy_headers(request, call_next):
        response = await call_next(request)
        protected_prefixes = (
            '/ai', '/auth', '/bank-statements', '/dashboard', '/receipts',
            '/reconciliation', '/reviews', '/ui', '/workspace',
        )
        if request.url.path.startswith(protected_prefixes):
            response.headers['X-Content-Type-Options'] = 'nosniff'
            response.headers['X-Frame-Options'] = 'DENY'
            response.headers['Referrer-Policy'] = 'no-referrer'
            response.headers['Permissions-Policy'] = (
                'camera=(), geolocation=(), microphone=(), payment=(), usb=()'
            )
            if not request.url.path.startswith('/ui/assets/'):
                response.headers['Cache-Control'] = 'no-store'
        if request.url.path.startswith('/ui'):
            response.headers['Content-Security-Policy'] = (
                "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
                "img-src 'self' blob:; connect-src 'self' https://identitytoolkit.googleapis.com https://securetoken.googleapis.com; base-uri 'none'; "
                "frame-src blob:; frame-ancestors 'none'; object-src 'none'"
            )
        return response

    frontend_dist = Path(__file__).resolve().parent.parent / 'frontend' / 'dist'
    if frontend_dist.is_dir():
        api.mount('/ui', StaticFiles(directory=frontend_dist, html=True), name='ui')
    return api


app = create_app()
