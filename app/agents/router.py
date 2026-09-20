"""Authenticated API routes for the three logical AI agents."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Callable
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from app.agents.compliance import (
    ClassificationComplianceAgent,
    assess_receipt_controls,
)
from app.agents.copilot import (
    CopilotScopeError,
    FinanceCopilotAgent,
    deterministic_monthly_brief_fallback,
    deterministic_reconciliation_fallback,
    validate_copilot_question,
)
from app.agents.gateway import (
    AgentAudit,
    AgentGatewayResponseError,
    AgentGatewayTimeout,
    AgentGatewayUnavailable,
    StructuredGatewayClient,
)
from app.database import ReceiptStore
from app.statements import monthly_reconciliation


class ReconciliationScope(BaseModel):
    month: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    currency: str = Field(pattern=r"^[A-Z]{3}$")


class CopilotQuestion(ReconciliationScope):
    question: str = Field(min_length=5, max_length=500)


def _fallback_audit(task: str, context: dict) -> AgentAudit:
    canonical = json.dumps(
        context, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str
    )
    return AgentAudit(
        request_id=str(uuid4()),
        task=task,
        model="deterministic-fallback",
        prompt_version="fallback-v1",
        input_sha256=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        cached=False,
        created_at=datetime.now(timezone.utc).isoformat(),
    )


def build_agent_router(
    get_settings: Callable,
    require_api_key: Callable,
) -> APIRouter:
    """Create routes without importing app.main and creating a dependency cycle."""

    router = APIRouter(prefix="/ai", tags=["ai-agents"])
    suites: dict[tuple[str, str, str, int, int], tuple[
        ClassificationComplianceAgent, FinanceCopilotAgent
    ]] = {}

    def agent_suite(settings):
        key = (
            settings.llm_gateway_url,
            settings.llm_gateway_api_key,
            settings.llm_model,
            settings.llm_timeout_seconds,
            settings.llm_max_output_tokens,
        )
        suite = suites.get(key)
        if suite is None:
            common = {
                "base_url": settings.llm_gateway_url,
                "api_key": settings.llm_gateway_api_key,
                "model": settings.llm_model,
                "timeout_seconds": settings.llm_timeout_seconds,
            }
            compliance_gateway = StructuredGatewayClient(
                **common,
                max_output_tokens=settings.llm_max_output_tokens,
            )
            copilot_gateway = StructuredGatewayClient(
                **common,
                max_output_tokens=min(settings.llm_max_output_tokens, 500),
            )
            suite = (
                ClassificationComplianceAgent(compliance_gateway),
                FinanceCopilotAgent(copilot_gateway),
            )
            suites.clear()
            suites[key] = suite
        return suite

    def safe_agent_error(exc: Exception) -> HTTPException:
        if isinstance(exc, AgentGatewayTimeout):
            return HTTPException(
                status_code=504,
                detail="Finance Copilot took too long. Please try again.",
            )
        if isinstance(exc, AgentGatewayUnavailable):
            return HTTPException(
                status_code=503,
                detail="Finance Copilot is temporarily unavailable. Please try again.",
            )
        return HTTPException(
            status_code=502,
            detail=(
                "Finance Copilot could not format a safe answer. Try a shorter question "
                "about this month's reconciliation."
            ),
        )

    @router.get("/agents", summary="List bounded AI-agent capabilities")
    async def list_agents(
        settings=Depends(require_api_key),
    ) -> dict:
        return {
            "agents": [
                {
                    "name": "Document Intelligence",
                    "capabilities": ["receipt extraction", "bank-statement extraction"],
                    "authority": "extract_only",
                },
                {
                    "name": "Classification and Compliance",
                    "capabilities": [
                        "expense categorisation",
                        "vendor normalisation",
                        "deterministic control checks",
                        "review assistance",
                    ],
                    "authority": "recommend_only",
                },
                {
                    "name": "Finance Copilot",
                    "capabilities": [
                        "reconciliation explanations",
                        "monthly-close briefs",
                        "read-only finance Q&A",
                    ],
                    "authority": "read_only",
                },
            ],
            "guardrails": [
                "AI cannot approve or reject transactions",
                "AI cannot change payment status",
                "AI cannot post journal entries or initiate payments",
                "AI cannot override deterministic matching or duplicate checks",
                "Finance Copilot refuses unrelated and secret-seeking questions",
                "Human confirmation remains required for uncertain evidence",
            ],
        }

    @router.post(
        "/receipts/{receipt_id}/review-assistance",
        summary="Generate advisory guidance for one receipt review",
    )
    async def receipt_review_assistance(
        receipt_id: str,
        settings=Depends(require_api_key),
    ) -> dict:
        record = await run_in_threadpool(
            ReceiptStore(settings.database_path).get, receipt_id
        )
        if record is None:
            raise HTTPException(status_code=404, detail="Receipt not found")
        assessment = assess_receipt_controls(record)
        compliance, _ = agent_suite(settings)
        try:
            guidance, audit = await compliance.assist_review(record, assessment)
        except (AgentGatewayTimeout, AgentGatewayUnavailable, AgentGatewayResponseError) as exc:
            raise safe_agent_error(exc) from exc
        return {
            "receipt_id": receipt_id,
            "control_assessment": assessment.model_dump(mode="json"),
            "guidance": guidance.model_dump(mode="json"),
            "audit": audit.as_dict(),
        }

    async def reconciliation_context(scope: ReconciliationScope, settings) -> dict:
        return await run_in_threadpool(
            monthly_reconciliation,
            ReceiptStore(settings.database_path),
            scope.month,
            scope.currency,
        )

    @router.post(
        "/reconciliation/explain",
        summary="Explain deterministic reconciliation exceptions",
    )
    async def explain_reconciliation(
        body: ReconciliationScope,
        settings=Depends(require_api_key),
    ) -> dict:
        context = await reconciliation_context(body, settings)
        _, copilot = agent_suite(settings)
        fallback = False
        try:
            explanation, audit = await copilot.explain_reconciliation(context)
        except (AgentGatewayTimeout, AgentGatewayUnavailable, AgentGatewayResponseError):
            explanation = deterministic_reconciliation_fallback(context)
            audit = _fallback_audit("reconciliation_explanation", context)
            fallback = True
        return {
            "scope": body.model_dump(),
            "explanation": explanation.model_dump(mode="json"),
            "audit": audit.as_dict(),
            "fallback": fallback,
        }

    @router.post(
        "/monthly-close/brief",
        summary="Generate a read-only monthly-close brief",
    )
    async def monthly_close_brief(
        body: ReconciliationScope,
        settings=Depends(require_api_key),
    ) -> dict:
        context = await reconciliation_context(body, settings)
        _, copilot = agent_suite(settings)
        fallback = False
        try:
            brief, audit = await copilot.monthly_brief(context)
        except (AgentGatewayTimeout, AgentGatewayUnavailable, AgentGatewayResponseError):
            brief = deterministic_monthly_brief_fallback(context)
            audit = _fallback_audit("monthly_close_brief", context)
            fallback = True
        return {
            "scope": body.model_dump(),
            "brief": brief.model_dump(mode="json"),
            "audit": audit.as_dict(),
            "fallback": fallback,
        }

    @router.post(
        "/copilot/ask",
        summary="Ask a read-only question about one reconciliation period",
    )
    async def ask_copilot(
        body: CopilotQuestion,
        settings=Depends(require_api_key),
    ) -> dict:
        try:
            safe_question = validate_copilot_question(body.question)
        except CopilotScopeError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        context = await reconciliation_context(body, settings)
        _, copilot = agent_suite(settings)
        try:
            answer, audit = await copilot.answer(safe_question, context)
        except CopilotScopeError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except (AgentGatewayTimeout, AgentGatewayUnavailable, AgentGatewayResponseError) as exc:
            raise safe_agent_error(exc) from exc
        return {
            "scope": {"month": body.month, "currency": body.currency},
            "answer": answer.model_dump(mode="json"),
            "audit": audit.as_dict(),
            "fallback": False,
        }

    return router
