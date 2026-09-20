import asyncio
import json

import httpx

from app.agents.compliance import assess_receipt_controls
from app.agents.copilot import FinanceCopilotAgent
from app.agents.gateway import StructuredGatewayClient


def gateway_response(content: dict) -> dict:
    return {"message": {"content": json.dumps(content)}, "done_reason": "stop"}


def test_control_assessment_normalizes_vendor_and_flags_missing_evidence() -> None:
    result = assess_receipt_controls({
        "receipt_id": "receipt-1",
        "extracted_data": {
            "vendor": "  Téo-Heng Stationery & Books ",
            "date": None,
            "currency": "SGD",
            "total_amount": 20.0,
            "needs_review": False,
        },
        "classification": {
            "needs_review": False,
            "workflow_decision": "AUTO_FILED",
        },
    })

    assert result.normalized_vendor == "T O HENG STATIONERY BOOKS"
    assert result.requires_review is True
    assert result.flags[0].code == "MISSING_CORE_EVIDENCE"
    assert result.flags[0].evidence == ["date"]


def test_control_assessment_does_not_invent_company_policy() -> None:
    result = assess_receipt_controls({
        "extracted_data": {
            "vendor": "Example Vendor",
            "date": "2026-09-20",
            "currency": "SGD",
            "total_amount": 99999.0,
            "needs_review": False,
        },
        "classification": {
            "needs_review": False,
            "workflow_decision": "AUTO_FILED",
        },
    })

    assert result.requires_review is False
    assert result.flags == []


def test_structured_gateway_validates_and_caches_identical_calls() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=gateway_response({
            "answer": "One unmatched debit needs evidence.",
            "evidence": ["transaction-1"],
            "limitations": [],
            "advisory_only": True,
        }))

    gateway = StructuredGatewayClient(
        "https://gateway.example",
        "secret",
        "model",
        10,
        500,
        transport=httpx.MockTransport(handler),
    )
    copilot = FinanceCopilotAgent(gateway)
    context = {"summary": {"unmatched_bank_count": 1}}

    first, first_audit = asyncio.run(copilot.answer("What needs attention?", context))
    second, second_audit = asyncio.run(copilot.answer("What needs attention?", context))

    assert first.answer == second.answer
    assert first_audit.cached is False
    assert second_audit.cached is True
    assert first_audit.input_sha256 == second_audit.input_sha256
    assert len(calls) == 1


def test_copilot_prompt_enforces_read_only_authority() -> None:
    prompts = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        prompts.append(body["messages"][0]["content"])
        return httpx.Response(200, json=gateway_response({
            "executive_summary": "Review the unmatched debit.",
            "exceptions": [],
            "limitations": ["No original receipt was supplied."],
            "advisory_only": True,
        }))

    gateway = StructuredGatewayClient(
        "https://gateway.example",
        "secret",
        "model",
        10,
        500,
        transport=httpx.MockTransport(handler),
    )
    copilot = FinanceCopilotAgent(gateway)

    asyncio.run(copilot.explain_reconciliation({"summary": {"unmatched_bank_count": 1}}))

    assert "Never approve transactions" in prompts[0]
    assert "Never recompute or override deterministic matching" in prompts[0]
