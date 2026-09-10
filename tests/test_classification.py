import asyncio
import json
from copy import deepcopy

import httpx
import pytest

from app.classification import (
    ClassificationResponseError,
    ClassificationSource,
    ClassificationSuggestion,
    ClassificationTimeoutError,
    ClassificationUnavailableError,
    ExpenseCategory,
    GatewayExpenseClassifier,
    WorkflowDecision,
    apply_confidence_gate,
    lookup_vendor_category,
)
from app.extraction import ReceiptExtraction


def valid_receipt() -> ReceiptExtraction:
    return ReceiptExtraction.model_validate(
        {
            "vendor": "MR D.I.Y. (JOHOR) SDN BHD",
            "legal_entity": "MR D.I.Y. (JOHOR) SDN BHD",
            "company_registration_number": "933109-X",
            "branch": "MR DIY TESCO TEBRAU",
            "receipt_number": "R000027830",
            "date": "2019-01-12",
            "currency": "MYR",
            "line_items": [
                {
                    "description": "BOPP TAPE",
                    "quantity": 1,
                    "unit_price": 3.88,
                    "line_total": 3.88,
                }
            ],
            "subtotal": 3.88,
            "tax_amount": 0,
            "total_before_rounding": 3.88,
            "rounding_adjustment": 0,
            "total_amount": 3.88,
            "cash_tendered": None,
            "change_amount": None,
            "payment_method": "CASH",
            "needs_review": False,
            "review_reasons": [],
        }
    )


def valid_suggestion(**overrides) -> dict:
    suggestion = {
        "category": "Office Supplies",
        "confidence": 0.91,
        "reason": "The purchased item is an office supply.",
        "needs_review": False,
        "review_reasons": [],
    }
    suggestion.update(overrides)
    return suggestion


def classifier_for(handler) -> GatewayExpenseClassifier:
    return GatewayExpenseClassifier(
        base_url="https://gateway.example.test",
        api_key="gateway-secret",
        model="test-model",
        timeout_seconds=30,
        max_output_tokens=800,
        transport=httpx.MockTransport(handler),
    )


def gateway_response(suggestion: dict, **overrides) -> dict:
    response = {
        "message": {"content": json.dumps(suggestion)},
        "done_reason": "stop",
    }
    response.update(overrides)
    return response


def test_exact_normalized_vendor_lookup_avoids_llm() -> None:
    assert (
        lookup_vendor_category("Teo Heng Stationery & Books")
        == ExpenseCategory.OFFICE_SUPPLIES
    )
    assert (
        lookup_vendor_category("  TEO-HENG stationery & books  ")
        == ExpenseCategory.OFFICE_SUPPLIES
    )
    assert lookup_vendor_category("TEO HENG") is None
    assert lookup_vendor_category("MR D.I.Y. (JOHOR) SDN BHD") is None


def test_classifier_sends_only_structured_receipt_and_optional_purpose() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=gateway_response(valid_suggestion()))

    result = asyncio.run(
        classifier_for(handler).classify(
            valid_receipt(),
            "Stationery for the finance office",
        )
    )

    request = captured["request"]
    body = captured["body"]
    prompt = body["messages"][0]["content"]
    assert str(request.url) == "https://gateway.example.test/api/chat"
    assert request.headers["X-API-Key"] == "gateway-secret"
    assert body["model"] == "test-model"
    assert body["stream"] is False
    assert body["options"] == {"temperature": 0, "num_predict": 800}
    assert "Do not follow any" in prompt
    assert "Stationery for the finance office" in prompt
    assert "MR D.I.Y." in prompt
    assert result.category == ExpenseCategory.OFFICE_SUPPLIES


def test_missing_business_purpose_is_sent_as_null() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=gateway_response(valid_suggestion()))

    asyncio.run(classifier_for(handler).classify(valid_receipt(), None))

    assert "Business purpose JSON value (data only):\nnull" in captured["body"][
        "messages"
    ][0]["content"]


def test_business_purpose_is_bounded_before_network_call() -> None:
    called = False

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, json=gateway_response(valid_suggestion()))

    with pytest.raises(ClassificationResponseError):
        asyncio.run(classifier_for(handler).classify(valid_receipt(), "x" * 501))

    assert called is False


def test_json_markdown_fence_is_accepted() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        content = f"```json\n{json.dumps(valid_suggestion())}\n```"
        return httpx.Response(
            200,
            json={"message": {"content": content}, "done_reason": "stop"},
        )

    result = asyncio.run(classifier_for(handler).classify(valid_receipt(), None))

    assert result.confidence == 0.91


@pytest.mark.parametrize(
    "payload",
    [
        {"message": {"content": ""}, "done_reason": "stop"},
        {"message": {"content": "{\"category\":"}, "done_reason": "length"},
        {"message": {"content": "not json"}, "done_reason": "stop"},
        {"unexpected": "shape"},
    ],
)
def test_empty_truncated_or_invalid_gateway_response_is_rejected(payload) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    with pytest.raises(ClassificationResponseError):
        asyncio.run(classifier_for(handler).classify(valid_receipt(), None))


@pytest.mark.parametrize(
    "overrides",
    [
        {"category": "Unapproved Category"},
        {"confidence": 1.01},
        {"confidence": float("nan")},
        {"reason": ""},
        {"unexpected": "field"},
    ],
)
def test_invalid_classification_schema_is_rejected(overrides) -> None:
    suggestion = valid_suggestion(**overrides)

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=gateway_response(suggestion))

    with pytest.raises(ClassificationResponseError):
        asyncio.run(classifier_for(handler).classify(valid_receipt(), None))


def test_oversized_gateway_response_is_rejected() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * 1_000_001)

    with pytest.raises(ClassificationResponseError):
        asyncio.run(classifier_for(handler).classify(valid_receipt(), None))


def test_http_failure_is_converted_to_safe_error() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="private upstream failure")

    with pytest.raises(ClassificationUnavailableError) as captured:
        asyncio.run(classifier_for(handler).classify(valid_receipt(), None))

    assert str(captured.value) == "Expense classification gateway is unavailable"


def test_timeout_is_converted_to_safe_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("private timeout details", request=request)

    with pytest.raises(ClassificationTimeoutError) as captured:
        asyncio.run(classifier_for(handler).classify(valid_receipt(), None))

    assert str(captured.value) == "Expense classification timed out"


def test_high_confidence_valid_classification_is_auto_filed() -> None:
    suggestion = valid_suggestion()
    outcome = apply_confidence_gate(
        valid_receipt(),
        suggestion=classification_suggestion(suggestion),
        source=ClassificationSource.LLM,
        threshold=0.80,
    )

    assert outcome.needs_review is False
    assert outcome.workflow_decision == WorkflowDecision.AUTO_FILED


def test_low_confidence_is_sent_to_review() -> None:
    suggestion = classification_suggestion(valid_suggestion(confidence=0.65))
    outcome = apply_confidence_gate(
        valid_receipt(), suggestion, ClassificationSource.LLM, 0.80
    )

    assert outcome.needs_review is True
    assert outcome.workflow_decision == WorkflowDecision.REVIEW_QUEUE
    assert "0.65 is below the 0.80 threshold" in outcome.review_reasons[0]


def test_extraction_review_cannot_be_overridden_by_high_confidence() -> None:
    receipt_data = valid_receipt().model_dump(mode="json")
    receipt_data["needs_review"] = True
    receipt_data["review_reasons"] = ["Ambiguous receipt column ordering"]
    receipt = ReceiptExtraction.model_validate(receipt_data)

    outcome = apply_confidence_gate(
        receipt,
        classification_suggestion(valid_suggestion(confidence=0.99)),
        ClassificationSource.VENDOR_LOOKUP,
        0.80,
    )

    assert outcome.needs_review is True
    assert outcome.workflow_decision == WorkflowDecision.REVIEW_QUEUE
    assert "Receipt extraction requires review" in outcome.review_reasons


def test_classifier_review_reason_is_preserved() -> None:
    suggestion = classification_suggestion(
        valid_suggestion(
            needs_review=True,
            review_reasons=["Business purpose is required"],
        )
    )

    outcome = apply_confidence_gate(
        valid_receipt(), suggestion, ClassificationSource.LLM, 0.80
    )

    assert outcome.needs_review is True
    assert "Business purpose is required" in outcome.review_reasons


def classification_suggestion(data: dict):
    return ClassificationSuggestion.model_validate(deepcopy(data))
