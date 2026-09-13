"""FastAPI entry point and secure receipt-ingestion boundary."""

from __future__ import annotations

import os
import secrets
from functools import lru_cache
from pathlib import Path
from typing import Annotated
from uuid import UUID, uuid4
from typing import Literal

from fastapi import Body, Depends, FastAPI, File, Form, Header, HTTPException, UploadFile, Query, status
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from fastapi.responses import JSONResponse
from app.database import DatabaseError, ReceiptStore
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

CHUNK_SIZE = 64 * 1024
IMAGE_TYPES = {
    "image/jpeg": (".jpg", (b"\xff\xd8\xff",)),
    "image/png": (".png", (b"\x89PNG\r\n\x1a\n",)),
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
    status: str = "processing_complete"


def get_settings() -> Settings:
    try:
        return Settings.from_environment()
    except ConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Application configuration is unavailable",
        ) from exc


def require_api_key(
    settings: Annotated[Settings, Depends(get_settings)],
    supplied_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> Settings:
    if supplied_key is None or not secrets.compare_digest(
        supplied_key, settings.app_api_key
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
        )
    return settings


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


def has_expected_signature(content_type: str, prefix: bytes) -> bool:
    return any(
        prefix.startswith(signature) for signature in IMAGE_TYPES[content_type][1]
    )


def create_app() -> FastAPI:
    docs_enabled = api_docs_enabled()
    api = FastAPI(
        title="Expense Classification Agent",
        version="0.1.0",
        description="Receipt intake for the OCR and expense-classification pipeline.",
        docs_url="/docs" if docs_enabled else None,
        redoc_url="/redoc" if docs_enabled else None,
        openapi_url="/openapi.json" if docs_enabled else None,
    )

    @api.exception_handler(DatabaseError)
    async def database_error_handler(request, exc):
        return JSONResponse(status_code=503, content={"detail": "Receipt database is unavailable"})

    @api.exception_handler(ReviewConflict)
    async def review_conflict_handler(request, exc):
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @api.exception_handler(ReviewNotFound)
    async def review_missing_handler(request, exc):
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @api.exception_handler(ReviewInvalid)
    async def review_invalid_handler(request, exc):
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @api.get("/reviews", tags=["reviews"], summary="1. List receipts awaiting human review",
             description="Read only. Copy a receipt_id, then use GET /receipts/{receipt_id}. Empty items means no pending receipts on THIS server. Local port 8000 and the AWS tunnel port 18000 use separate databases. Finalized, AUTO_FILED, FAILED and PROCESSING receipts are excluded.")
    async def reviews(settings: Annotated[Settings, Depends(require_api_key)],
                      limit: Annotated[int, Query(ge=1, le=100)] = 20,
                      offset: Annotated[int, Query(ge=0)] = 0) -> dict:
        return await run_in_threadpool(pending_reviews, ReceiptStore(settings.database_path), limit, offset)

    @api.post("/receipts/{receipt_id}/review", tags=["reviews"],
              summary="3. Finalize approval or rejection (writes data)",
              description="""**Final decisions cannot currently be undone or reopened. Use disposable records for testing.**

1. First GET the receipt detail and check `review` is null and `review_version` is 0.
2. Compare the original image with vendor, date, currency, EVERY line item, discounts, tax and totals. The image is not served by this API; use your original upload.
3. Read all extraction AND classification reasons. Establish business purpose; explain the category and any corrections in `note`. If uncertain, leave it pending rather than approving.
4. Generate a new request UUID in PowerShell: `[guid]::NewGuid().ToString()`. It is not the receipt ID or an API key.
5. Choose an example below and replace ALL REPLACE_ values. For approval replace `corrected_data: null` with the COMPLETE `extracted_data` object from GET, editing only verified fields. Choose the justified category. For rejection omit corrections, category and override.
6. Set `evidence_confirmed` to true only after inspection. Click Execute ONCE and read **Server response**, not Curl (which includes your secret key).
7. Verify GET receipt detail, GET receipt reviews, and GET /reviews. Finalized receipts leave the pending queue; original processing_status stays historical. `review.decision` is the human result.

Review currencies currently supported: SGD, MYR, USD, EUR, GBP, AUD. Unknown optional values remain null; never invent zero or discounts. Vendor, date, currency and total are required for approval. Zero totals are allowed when verified. `override_reason` is only for a documented remaining arithmetic discrepancy, not a way to bypass missing fields, unsupported currency or placeholders. Arithmetic uses a 0.02 tolerance and cannot establish business purpose or truth of the receipt.

On timeout, GET the receipt first, then retry the SAME UUID and identical payload if needed. A new UUID does not reopen a finalized receipt. Existing invalid approvals are not repaired by this update. Review names are self-reported under the shared app key; no vendor rule is learned and no payment/accounting posting occurs.""",
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

    @api.get("/receipts", tags=["receipts"])
    async def list_receipts(
        settings: Annotated[Settings, Depends(require_api_key)],
        decision: Literal["AUTO_FILED", "REVIEW_QUEUE"] | None = None,
        processing_status: Literal["PROCESSING", "COMPLETED", "REVIEW_QUEUE", "FAILED"] | None = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 20,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> dict:
        return await run_in_threadpool(
            ReceiptStore(settings.database_path).list, decision, processing_status, limit, offset
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
        receipt: Annotated[UploadFile, File(description="JPEG or PNG receipt")],
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
        if content_type not in IMAGE_TYPES:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail="Only JPEG and PNG receipts are supported",
            )

        receipt_id = str(uuid4())
        extension = IMAGE_TYPES[content_type][0]
        temporary_path = settings.upload_dir / f".{receipt_id}.upload"
        final_path = settings.upload_dir / f"{receipt_id}{extension}"
        size = 0
        prefix = b""

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
            )
        except DatabaseError:
            final_path.unlink(missing_ok=True)
            raise

        async def process() -> ReceiptProcessed:
            try:
                ocr_result: OCRResult = await run_in_threadpool(
                    ocr_service.extract, final_path
                )
            except OCRUnavailableError as exc:
                final_path.unlink(missing_ok=True)
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="OCR service is unavailable",
                ) from exc
            except OCRTimeoutError as exc:
                final_path.unlink(missing_ok=True)
                raise HTTPException(
                    status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                    detail="Receipt OCR timed out",
                ) from exc
            except (OCRProcessingError, OCRNoTextError) as exc:
                final_path.unlink(missing_ok=True)
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

    return api


app = create_app()
