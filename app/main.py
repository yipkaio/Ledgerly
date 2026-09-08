"""FastAPI entry point and secure receipt-ingestion boundary."""

from __future__ import annotations

import os
import secrets
from functools import lru_cache
from pathlib import Path
from typing import Annotated
from uuid import uuid4

from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from app.config import ConfigurationError, Settings
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
    status: str = "ocr_complete"


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
        return get_paddle_ocr_service(
            settings.paddle_language,
            settings.paddle_device,
            settings.paddle_min_confidence,
        )

    return TesseractOCRService(
        executable=settings.tesseract_cmd,
        language=settings.tesseract_language,
        page_segmentation_mode=settings.tesseract_psm,
        timeout_seconds=settings.ocr_timeout_seconds,
    )


def has_expected_signature(content_type: str, prefix: bytes) -> bool:
    return any(
        prefix.startswith(signature) for signature in IMAGE_TYPES[content_type][1]
    )


def create_app() -> FastAPI:
    api = FastAPI(
        title="Expense Classification Agent",
        version="0.1.0",
        description="Receipt intake for the OCR and expense-classification pipeline.",
    )

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
    ) -> ReceiptProcessed:
        content_type = (receipt.content_type or "").lower()
        if content_type not in IMAGE_TYPES:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail="Only JPEG and PNG receipts are supported",
            )

        receipt_id = str(uuid4())
        extension = IMAGE_TYPES[content_type][0]
        settings.upload_dir.mkdir(parents=True, exist_ok=True)
        temporary_path = settings.upload_dir / f".{receipt_id}.upload"
        final_path = settings.upload_dir / f"{receipt_id}{extension}"
        size = 0
        prefix = b""

        try:
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

        return ReceiptProcessed(
            receipt_id=receipt_id,
            content_type=content_type,
            size_bytes=size,
            ocr_engine=ocr_result.engine,
            ocr_confidence=ocr_result.confidence,
            ocr_text=ocr_result.text,
        )

    return api


app = create_app()
