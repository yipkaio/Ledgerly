"""Bounded PDF inspection, text extraction, rendering, and OCR orchestration."""

from __future__ import annotations

import math
import multiprocessing
import os
from pathlib import Path
import queue
import shutil
from tempfile import TemporaryDirectory

from pypdf import PdfReader
import pypdfium2 as pdfium

from app.ocr import OCRNoTextError, OCRResult, OCRService


MAX_TEXT_CHARACTERS = 200_000
MAX_PAGE_EDGE_POINTS = 20_000
MAX_STATEMENT_OCR_PAGES = 10


class PDFError(ValueError):
    pass


class PDFEncryptedError(PDFError):
    pass


class PDFPageLimitError(PDFError):
    pass


class PDFTimeoutError(PDFError):
    pass


class PDFOCRPageLimitError(PDFError):
    pass


def _usable(text: str) -> bool:
    return sum(character.isalnum() for character in text) >= 20


def _inspect_worker(
    source: str,
    output_dir: str,
    max_pages: int,
    max_render_pixels: int,
    password: str | None,
    result_queue,
) -> None:
    """Run parser/native rendering in an expendable process."""
    try:
        reader = PdfReader(source, strict=True)
        if reader.is_encrypted:
            if not password or not reader.decrypt(password):
                result_queue.put({"error": "encrypted"})
                return
        page_count = len(reader.pages)
        if page_count < 1 or page_count > max_pages:
            result_queue.put({"error": "pages", "count": page_count})
            return

        native: list[str | None] = []
        text_characters = 0
        for page in reader.pages:
            # Layout mode retains the statement's visual columns while still
            # providing useful receipt text. Fall back for unusual generators.
            try:
                text = (page.extract_text(extraction_mode="layout") or "").strip()
            except Exception:
                text = (page.extract_text() or "").strip()
            text_characters += len(text)
            if text_characters > MAX_TEXT_CHARACTERS:
                result_queue.put({"error": "text_limit"})
                return
            native.append(text if _usable(text) else None)

        document = pdfium.PdfDocument(source, password=password)
        if len(document) != page_count:
            result_queue.put({"error": "invalid"})
            return
        rendered: list[str | None] = [None] * page_count
        per_page_budget = max_render_pixels / page_count
        for index in range(page_count):
            # Always render page one for the protected UI preview. Render other
            # pages only when embedded text is not useful.
            if index > 0 and native[index] is not None:
                continue
            page = document[index]
            width, height = page.get_size()
            if (
                width <= 0
                or height <= 0
                or width > MAX_PAGE_EDGE_POINTS
                or height > MAX_PAGE_EDGE_POINTS
            ):
                result_queue.put({"error": "dimensions"})
                return
            scale = min(
                2.0,
                4000 / max(width, height),
                math.sqrt(per_page_budget / (width * height)),
            )
            if scale < 0.25:
                result_queue.put({"error": "dimensions"})
                return
            path = str(Path(output_dir) / f"page-{index + 1}.png")
            bitmap = page.render(scale=scale)
            try:
                bitmap.to_pil().convert("RGB").save(path, format="PNG", optimize=True)
            finally:
                bitmap.close()
                page.close()
            rendered[index] = path
        document.close()
        result_queue.put({"native": native, "rendered": rendered})
    except Exception:
        result_queue.put({"error": "invalid"})


def _inspect(
    source: Path,
    output_dir: Path,
    max_pages: int,
    max_render_pixels: int,
    timeout_seconds: int,
    password: str | None = None,
) -> dict:
    context = multiprocessing.get_context("spawn")
    result_queue = context.Queue(maxsize=1)
    process = context.Process(
        target=_inspect_worker,
        args=(str(source), str(output_dir), max_pages, max_render_pixels, password, result_queue),
        daemon=True,
    )
    process.start()
    try:
        result = result_queue.get(timeout=timeout_seconds)
    except queue.Empty:
        process.terminate()
        process.join(2)
        if process.is_alive():
            process.kill()
            process.join(2)
        raise PDFTimeoutError("PDF inspection timed out")
    finally:
        result_queue.close()
        result_queue.join_thread()
    process.join(2)
    if process.is_alive():
        process.terminate()
        process.join(2)
    error = result.get("error")
    if error == "encrypted":
        raise PDFEncryptedError("The PDF password is missing or incorrect")
    if error == "pages":
        raise PDFPageLimitError(f"PDF must contain 1 to {max_pages} pages")
    if error:
        raise PDFError("PDF is malformed or exceeds safe rendering limits")
    return result


def extract_pdf(
    source: Path,
    ocr_service: OCRService,
    preview_path: Path,
    *,
    max_pages: int,
    max_render_pixels: int,
    timeout_seconds: int,
    password: str | None = None,
) -> OCRResult:
    """Use embedded text per page, otherwise OCR a safely rendered page."""
    with TemporaryDirectory(prefix="receipt-pdf-") as directory:
        result = _inspect(
            source,
            Path(directory),
            max_pages,
            max_render_pixels,
            timeout_seconds,
            password,
        )
        page_text: list[str] = []
        confidences: list[float] = []
        engines: list[str] = []
        for index, (native, rendered) in enumerate(
            zip(result["native"], result["rendered"], strict=True), start=1
        ):
            if native is not None:
                text = native
                engine = "native"
            else:
                if rendered is None:
                    raise PDFError("PDF page rendering is unavailable")
                ocr = ocr_service.extract(Path(rendered))
                text = ocr.text
                engine = ocr.engine
                if ocr.confidence is not None:
                    confidences.append(ocr.confidence)
            engines.append(engine)
            page_text.append(f"--- Page {index} ---\n{text.strip()}")
        combined = "\n\n".join(page_text).strip()
        if not _usable(combined):
            raise OCRNoTextError("No usable receipt text")
        preview_source = result["rendered"][0]
        if preview_source is None:
            raise PDFError("PDF preview rendering is unavailable")
        temporary_preview = preview_path.with_suffix(".preview-upload")
        shutil.copyfile(preview_source, temporary_preview)
        os.replace(temporary_preview, preview_path)
    engine_names = "+".join(dict.fromkeys(engines))
    confidence = sum(confidences) / len(confidences) if confidences else None
    return OCRResult(text=combined, engine=f"pdf:{engine_names}", confidence=confidence)


def extract_pdf_text(
    source: Path,
    ocr_service: OCRService,
    *,
    max_pages: int,
    max_render_pixels: int,
    timeout_seconds: int,
    password: str | None = None,
) -> OCRResult:
    """Extract a bounded statement PDF without retaining rendered pages.

    The password is passed only to the isolated parser process and is never
    returned, persisted, or included in an exception message.
    """
    with TemporaryDirectory(prefix="statement-pdf-") as directory:
        result = _inspect(
            source,
            Path(directory),
            max_pages,
            max_render_pixels,
            timeout_seconds,
            password,
        )
        ocr_pages = sum(native is None for native in result["native"])
        if ocr_pages > MAX_STATEMENT_OCR_PAGES:
            raise PDFOCRPageLimitError(
                f"At most {MAX_STATEMENT_OCR_PAGES} scanned pages can use OCR"
            )
        page_text: list[str] = []
        confidences: list[float] = []
        engines: list[str] = []
        for index, (native, rendered) in enumerate(
            zip(result["native"], result["rendered"], strict=True), start=1
        ):
            if native is not None:
                text = native
                engine = "native"
            else:
                if rendered is None:
                    raise PDFError("PDF page rendering is unavailable")
                ocr = ocr_service.extract(Path(rendered))
                text = ocr.text
                engine = ocr.engine
                if ocr.confidence is not None:
                    confidences.append(ocr.confidence)
            engines.append(engine)
            page_text.append(f"--- Page {index} ---\n{text.strip()}")
        combined = "\n\n".join(page_text).strip()
        if not _usable(combined) or len(combined) > MAX_TEXT_CHARACTERS:
            raise OCRNoTextError("No usable bank statement text")
    engine_names = "+".join(dict.fromkeys(engines))
    confidence = sum(confidences) / len(confidences) if confidences else None
    return OCRResult(text=combined, engine=f"pdf:{engine_names}", confidence=confidence)
