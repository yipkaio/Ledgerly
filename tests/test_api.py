from pathlib import Path

from fastapi.testclient import TestClient

import pytest

from app.classification import (
    ClassificationResponseError,
    ClassificationSuggestion,
    ClassificationTimeoutError,
    ClassificationUnavailableError,
    ExpenseCategory,
)
from app.extraction import (
    ExtractionResponseError,
    ExtractionTimeoutError,
    ExtractionUnavailableError,
    ReceiptExtraction,
)
from app.main import (
    create_app,
    get_expense_classifier,
    get_ocr_service,
    get_receipt_extractor,
)
from app.ocr import OCRResult, OCRTimeoutError

TEST_KEY = "test-key-that-is-longer-than-32-characters"


class StubOCRService:
    def __init__(self, text: str = "MR DIY\nTOTAL RM 33.90") -> None:
        self.text = text
        self.paths: list[Path] = []

    def extract(self, image_path: Path) -> OCRResult:
        self.paths.append(image_path)
        return OCRResult(text=self.text, engine="stub", confidence=0.95)


class StubReceiptExtractor:
    def __init__(self) -> None:
        self.inputs: list[str] = []
        self.error: Exception | None = None
        self.vendor = "MR DIY"
        self.legal_entity: str | None = None
        self.needs_review = False
        self.review_reasons: list[str] = []

    async def extract(self, ocr_text: str) -> ReceiptExtraction:
        self.inputs.append(ocr_text)
        if self.error is not None:
            raise self.error
        return ReceiptExtraction.model_validate(
            {
                "vendor": self.vendor,
                "legal_entity": self.legal_entity,
                "company_registration_number": None,
                "branch": None,
                "receipt_number": None,
                "date": "2019-01-12",
                "currency": "MYR",
                "line_items": [],
                "subtotal": 33.92,
                "tax_amount": 0.00,
                "total_before_rounding": 33.92,
                "rounding_adjustment": -0.02,
                "total_amount": 33.90,
                "cash_tendered": 50.00,
                "change_amount": 16.10,
                "payment_method": "CASH",
                "needs_review": self.needs_review,
                "review_reasons": self.review_reasons,
            }
        )


class StubExpenseClassifier:
    def __init__(self) -> None:
        self.inputs: list[tuple[ReceiptExtraction, str | None]] = []
        self.error: Exception | None = None
        self.suggestion = ClassificationSuggestion(
            category=ExpenseCategory.OFFICE_SUPPLIES,
            confidence=0.91,
            reason="The purchased items are office supplies.",
            needs_review=False,
            review_reasons=[],
        )

    async def classify(
        self,
        receipt: ReceiptExtraction,
        business_purpose: str | None,
    ) -> ClassificationSuggestion:
        self.inputs.append((receipt, business_purpose))
        if self.error is not None:
            raise self.error
        return self.suggestion


def configured_client(
    monkeypatch, tmp_path: Path, max_bytes: int = 1024
) -> tuple[
    TestClient,
    StubOCRService,
    StubReceiptExtractor,
    StubExpenseClassifier,
]:
    monkeypatch.setenv("APP_API_KEY", TEST_KEY)
    monkeypatch.setenv("LLM_GATEWAY_API_KEY", "test-gateway-key")
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path))
    monkeypatch.setenv("MAX_UPLOAD_BYTES", str(max_bytes))
    app = create_app()
    ocr_service = StubOCRService()
    receipt_extractor = StubReceiptExtractor()
    expense_classifier = StubExpenseClassifier()
    app.dependency_overrides[get_ocr_service] = lambda: ocr_service
    app.dependency_overrides[get_receipt_extractor] = lambda: receipt_extractor
    app.dependency_overrides[get_expense_classifier] = lambda: expense_classifier
    return TestClient(app), ocr_service, receipt_extractor, expense_classifier


def test_health_is_public() -> None:
    response = TestClient(create_app()).get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_upload_requires_authentication(monkeypatch, tmp_path: Path) -> None:
    client, _, receipt_extractor, expense_classifier = configured_client(
        monkeypatch, tmp_path
    )

    response = client.post(
        "/receipts/upload",
        files={"receipt": ("receipt.jpg", b"\xff\xd8\xffdata", "image/jpeg")},
    )

    assert response.status_code == 401
    assert list(tmp_path.iterdir()) == []
    assert receipt_extractor.inputs == []
    assert expense_classifier.inputs == []


def test_valid_jpeg_is_saved_with_generated_name(monkeypatch, tmp_path: Path) -> None:
    client, ocr_service, receipt_extractor, expense_classifier = configured_client(
        monkeypatch, tmp_path
    )
    image = b"\xff\xd8\xffreceipt-data"

    response = client.post(
        "/receipts/upload",
        headers={"X-API-Key": TEST_KEY},
        files={"receipt": ("../../unsafe.jpg", image, "image/jpeg")},
    )

    assert response.status_code == 202
    payload = response.json()
    stored_files = list(tmp_path.iterdir())
    assert payload["status"] == "processing_complete"
    assert payload["size_bytes"] == len(image)
    assert payload["ocr_engine"] == "stub"
    assert payload["ocr_confidence"] == 0.95
    assert payload["ocr_text"] == "MR DIY\nTOTAL RM 33.90"
    assert payload["extracted_data"]["vendor"] == "MR DIY"
    assert payload["extracted_data"]["total_amount"] == 33.90
    assert payload["business_purpose"] is None
    assert payload["classification"]["category"] == "Office Supplies"
    assert payload["classification"]["source"] == "llm"
    assert payload["classification"]["workflow_decision"] == "AUTO_FILED"
    assert len(stored_files) == 1
    assert stored_files[0].name == f"{payload['receipt_id']}.jpg"
    assert stored_files[0].read_bytes() == image
    assert ocr_service.paths == [stored_files[0]]
    assert receipt_extractor.inputs == ["MR DIY\nTOTAL RM 33.90"]
    assert len(expense_classifier.inputs) == 1
    assert expense_classifier.inputs[0][0].vendor == "MR DIY"
    assert expense_classifier.inputs[0][1] is None


def test_declared_type_must_match_file_signature(monkeypatch, tmp_path: Path) -> None:
    client, _, receipt_extractor, expense_classifier = configured_client(
        monkeypatch, tmp_path
    )

    response = client.post(
        "/receipts/upload",
        headers={"X-API-Key": TEST_KEY},
        files={"receipt": ("receipt.jpg", b"not-an-image", "image/jpeg")},
    )

    assert response.status_code == 415
    assert list(tmp_path.iterdir()) == []
    assert receipt_extractor.inputs == []
    assert expense_classifier.inputs == []


def test_oversized_upload_is_rejected_and_removed(monkeypatch, tmp_path: Path) -> None:
    client, _, receipt_extractor, expense_classifier = configured_client(
        monkeypatch, tmp_path, max_bytes=5
    )

    response = client.post(
        "/receipts/upload",
        headers={"X-API-Key": TEST_KEY},
        files={"receipt": ("receipt.jpg", b"\xff\xd8\xfftoo-large", "image/jpeg")},
    )

    assert response.status_code == 413
    assert list(tmp_path.iterdir()) == []
    assert receipt_extractor.inputs == []
    assert expense_classifier.inputs == []


def test_ocr_failure_returns_safe_error_and_removes_upload(
    monkeypatch, tmp_path: Path
) -> None:
    client, ocr_service, receipt_extractor, expense_classifier = configured_client(
        monkeypatch, tmp_path
    )

    def time_out(_: Path) -> str:
        raise OCRTimeoutError("internal timeout information")

    ocr_service.extract = time_out
    response = client.post(
        "/receipts/upload",
        headers={"X-API-Key": TEST_KEY},
        files={"receipt": ("receipt.jpg", b"\xff\xd8\xffdata", "image/jpeg")},
    )

    assert response.status_code == 504
    assert response.json() == {"detail": "Receipt OCR timed out"}
    assert list(tmp_path.iterdir()) == []
    assert receipt_extractor.inputs == []
    assert expense_classifier.inputs == []


@pytest.mark.parametrize(
    ("error", "expected_status", "expected_detail"),
    [
        (
            ExtractionTimeoutError("private gateway details"),
            504,
            "Receipt extraction timed out",
        ),
        (
            ExtractionUnavailableError("private gateway details"),
            503,
            "Receipt extraction service is unavailable",
        ),
        (
            ExtractionResponseError("private model output"),
            502,
            "Receipt extraction returned an invalid response",
        ),
    ],
)
def test_extraction_failure_returns_safe_error_and_retains_upload(
    monkeypatch,
    tmp_path: Path,
    error: Exception,
    expected_status: int,
    expected_detail: str,
) -> None:
    client, _, receipt_extractor, expense_classifier = configured_client(
        monkeypatch, tmp_path
    )
    receipt_extractor.error = error

    response = client.post(
        "/receipts/upload",
        headers={"X-API-Key": TEST_KEY},
        files={"receipt": ("receipt.jpg", b"\xff\xd8\xffdata", "image/jpeg")},
    )

    assert response.status_code == expected_status
    assert response.json() == {"detail": expected_detail}
    assert "private" not in response.text
    stored_files = list(tmp_path.iterdir())
    assert len(stored_files) == 1
    assert stored_files[0].suffix == ".jpg"
    assert expense_classifier.inputs == []


def test_optional_business_purpose_is_trimmed_and_sent_to_classifier(
    monkeypatch,
    tmp_path: Path,
) -> None:
    client, _, _, expense_classifier = configured_client(monkeypatch, tmp_path)

    response = client.post(
        "/receipts/upload",
        headers={"X-API-Key": TEST_KEY},
        files={"receipt": ("receipt.jpg", b"\xff\xd8\xffdata", "image/jpeg")},
        data={"business_purpose": "  Stationery for finance office  "},
    )

    assert response.status_code == 202
    assert response.json()["business_purpose"] == "Stationery for finance office"
    assert expense_classifier.inputs[0][1] == "Stationery for finance office"


def test_exact_vendor_lookup_skips_classifier(monkeypatch, tmp_path: Path) -> None:
    client, _, receipt_extractor, expense_classifier = configured_client(
        monkeypatch, tmp_path
    )
    receipt_extractor.vendor = "TEO HENG STATIONERY & BOOKS"

    response = client.post(
        "/receipts/upload",
        headers={"X-API-Key": TEST_KEY},
        files={"receipt": ("receipt.jpg", b"\xff\xd8\xffdata", "image/jpeg")},
    )

    assert response.status_code == 202
    classification = response.json()["classification"]
    assert classification["category"] == "Office Supplies"
    assert classification["confidence"] == 1
    assert classification["source"] == "vendor_lookup"
    assert classification["workflow_decision"] == "AUTO_FILED"
    assert expense_classifier.inputs == []


def test_extraction_review_forces_vendor_match_into_review_queue(
    monkeypatch,
    tmp_path: Path,
) -> None:
    client, _, receipt_extractor, expense_classifier = configured_client(
        monkeypatch, tmp_path
    )
    receipt_extractor.vendor = "TEO HENG STATIONERY & BOOKS"
    receipt_extractor.needs_review = True
    receipt_extractor.review_reasons = ["Receipt columns were normalized"]

    response = client.post(
        "/receipts/upload",
        headers={"X-API-Key": TEST_KEY},
        files={"receipt": ("receipt.jpg", b"\xff\xd8\xffdata", "image/jpeg")},
    )

    classification = response.json()["classification"]
    assert classification["workflow_decision"] == "REVIEW_QUEUE"
    assert "Receipt extraction requires review" in classification["review_reasons"]
    assert expense_classifier.inputs == []


def test_low_confidence_llm_classification_enters_review_queue(
    monkeypatch,
    tmp_path: Path,
) -> None:
    client, _, _, expense_classifier = configured_client(monkeypatch, tmp_path)
    expense_classifier.suggestion = ClassificationSuggestion(
        category=ExpenseCategory.OFFICE_SUPPLIES,
        confidence=0.65,
        reason="The retailer sells products for several possible business purposes.",
        needs_review=True,
        review_reasons=["Business purpose is required"],
    )

    response = client.post(
        "/receipts/upload",
        headers={"X-API-Key": TEST_KEY},
        files={"receipt": ("receipt.jpg", b"\xff\xd8\xffdata", "image/jpeg")},
    )

    classification = response.json()["classification"]
    assert classification["source"] == "llm"
    assert classification["workflow_decision"] == "REVIEW_QUEUE"
    assert "Business purpose is required" in classification["review_reasons"]
    assert any("0.65 is below" in reason for reason in classification["review_reasons"])


@pytest.mark.parametrize(
    ("error", "expected_reason"),
    [
        (
            ClassificationTimeoutError("private timeout details"),
            "Expense classification timed out",
        ),
        (
            ClassificationUnavailableError("private upstream details"),
            "Expense classification service is unavailable",
        ),
        (
            ClassificationResponseError("private model response"),
            "Expense classification returned an invalid response",
        ),
    ],
)
def test_classification_failure_returns_safe_review_decision_and_retains_upload(
    monkeypatch,
    tmp_path: Path,
    error: Exception,
    expected_reason: str,
) -> None:
    client, _, _, expense_classifier = configured_client(monkeypatch, tmp_path)
    expense_classifier.error = error

    response = client.post(
        "/receipts/upload",
        headers={"X-API-Key": TEST_KEY},
        files={"receipt": ("receipt.jpg", b"\xff\xd8\xffdata", "image/jpeg")},
    )

    assert response.status_code == 202
    classification = response.json()["classification"]
    assert classification["category"] is None
    assert classification["confidence"] == 0
    assert classification["workflow_decision"] == "REVIEW_QUEUE"
    assert classification["review_reasons"] == [expected_reason]
    assert "private" not in response.text
    assert len(list(tmp_path.iterdir())) == 1


def test_business_purpose_length_is_bounded_before_processing(
    monkeypatch,
    tmp_path: Path,
) -> None:
    client, ocr_service, receipt_extractor, expense_classifier = configured_client(
        monkeypatch, tmp_path
    )

    response = client.post(
        "/receipts/upload",
        headers={"X-API-Key": TEST_KEY},
        files={"receipt": ("receipt.jpg", b"\xff\xd8\xffdata", "image/jpeg")},
        data={"business_purpose": "x" * 501},
    )

    assert response.status_code == 422
    assert list(tmp_path.iterdir()) == []
    assert ocr_service.paths == []
    assert receipt_extractor.inputs == []
    assert expense_classifier.inputs == []
