"""Shared, bounded structured-output gateway for advisory AI tasks."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TypeVar
from uuid import uuid4

import httpx
from pydantic import BaseModel, ValidationError

MAX_GATEWAY_RESPONSE_BYTES = 1_000_000
SchemaT = TypeVar("SchemaT", bound=BaseModel)


class AgentGatewayError(RuntimeError):
    """Base class for safe advisory-agent failures."""


class AgentGatewayUnavailable(AgentGatewayError):
    """The configured model gateway could not serve the request."""


class AgentGatewayTimeout(AgentGatewayError):
    """The advisory request exceeded its configured timeout."""


class AgentGatewayResponseError(AgentGatewayError):
    """The gateway returned an invalid or schema-incompatible response."""


@dataclass(frozen=True)
class AgentAudit:
    request_id: str
    task: str
    model: str
    prompt_version: str
    input_sha256: str
    cached: bool
    created_at: str

    def as_dict(self) -> dict[str, str | bool]:
        return {
            "request_id": self.request_id,
            "task": self.task,
            "model": self.model,
            "prompt_version": self.prompt_version,
            "input_sha256": self.input_sha256,
            "cached": self.cached,
            "created_at": self.created_at,
        }


@dataclass
class _CacheEntry:
    expires_at: datetime
    value: BaseModel


class StructuredGatewayClient:
    """Call the existing text gateway with strict schemas and a small TTL cache."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        timeout_seconds: int,
        max_output_tokens: int,
        *,
        cache_ttl_seconds: int = 900,
        cache_limit: int = 128,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._endpoint = f"{base_url.rstrip('/')}/api/chat"
        self._api_key = api_key
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._max_output_tokens = max_output_tokens
        self._cache_ttl = timedelta(seconds=cache_ttl_seconds)
        self._cache_limit = cache_limit
        self._transport = transport
        self._cache: dict[str, _CacheEntry] = {}

    async def run(
        self,
        *,
        task: str,
        prompt_version: str,
        prompt: str,
        input_data: object,
        schema: type[SchemaT],
    ) -> tuple[SchemaT, AgentAudit]:
        canonical_input = json.dumps(
            input_data, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str
        )
        input_sha = hashlib.sha256(canonical_input.encode("utf-8")).hexdigest()
        cache_key = hashlib.sha256(
            f"{self._model}\n{task}\n{prompt_version}\n{schema.__name__}\n{prompt}".encode("utf-8")
        ).hexdigest()
        now = datetime.now(timezone.utc)
        self._prune(now)
        cached = self._cache.get(cache_key)
        if cached is not None:
            value = schema.model_validate(cached.value.model_dump(mode="json"))
            return value, self._audit(task, prompt_version, input_sha, True, now)

        body = {
            "model": self._model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "options": {"temperature": 0, "num_predict": self._max_output_tokens},
        }
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout_seconds, transport=self._transport
            ) as client:
                response = await client.post(
                    self._endpoint,
                    headers={"X-API-Key": self._api_key},
                    json=body,
                )
                response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise AgentGatewayTimeout("AI advisory request timed out") from exc
        except httpx.HTTPError as exc:
            raise AgentGatewayUnavailable("AI advisory gateway is unavailable") from exc

        if len(response.content) > MAX_GATEWAY_RESPONSE_BYTES:
            raise AgentGatewayResponseError("AI advisory response was too large")
        try:
            envelope = response.json()
            content = envelope["message"]["content"]
            done_reason = envelope.get("done_reason")
            if not isinstance(content, str) or not content.strip():
                raise TypeError
            if done_reason is not None and done_reason != "stop":
                raise AgentGatewayResponseError("AI advisory response was truncated")
            parsed = json.loads(self._strip_fence(content))
            value = schema.model_validate(parsed)
        except AgentGatewayResponseError:
            raise
        except (
            json.JSONDecodeError,
            UnicodeError,
            KeyError,
            TypeError,
            AttributeError,
            ValidationError,
        ) as exc:
            raise AgentGatewayResponseError("AI advisory response was invalid") from exc

        if len(self._cache) >= self._cache_limit:
            oldest = min(self._cache, key=lambda key: self._cache[key].expires_at)
            self._cache.pop(oldest, None)
        self._cache[cache_key] = _CacheEntry(now + self._cache_ttl, value)
        return value, self._audit(task, prompt_version, input_sha, False, now)

    def _prune(self, now: datetime) -> None:
        expired = [key for key, entry in self._cache.items() if entry.expires_at <= now]
        for key in expired:
            self._cache.pop(key, None)

    def _audit(
        self, task: str, prompt_version: str, input_sha: str, cached: bool, now: datetime
    ) -> AgentAudit:
        return AgentAudit(
            request_id=str(uuid4()),
            task=task,
            model=self._model,
            prompt_version=prompt_version,
            input_sha256=input_sha,
            cached=cached,
            created_at=now.isoformat(),
        )

    @staticmethod
    def _strip_fence(content: str) -> str:
        cleaned = content.strip()
        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]
        elif cleaned.startswith("```"):
            cleaned = cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        return cleaned.strip()
