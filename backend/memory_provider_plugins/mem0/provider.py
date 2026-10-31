"""Mem0 external memory provider plugin.

Implements SearchableMemoryProvider and IngestibleMemoryProvider protocols
using the Mem0 hosted API (https://api.mem0.ai).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

import httpx

from nexent.memory.models import (
    MemoryIngestRequest,
    MemoryIngestResult,
    MemorySearchRequest,
    MemorySearchResult,
    ProviderError,
    ProviderErrorCode,
    ProviderErrorSeverity,
    UnitIngestResult,
    UnitIngestStatus,
)
from nexent.memory.providers.retry import (
    NonRetryableProviderError,
    RetryableProviderError,
)

logger = logging.getLogger("memory_provider_mem0")


class Mem0Provider:
    """Mem0 external memory provider.

    Implements both SearchableMemoryProvider and IngestibleMemoryProvider
    protocols for integration with the Nexent memory pipeline.
    """

    def __init__(self, config: dict):
        self.api_key = config.get("api_key")
        self.org_id = config.get("org_id")
        self.base_url = config.get("base_url", "https://api.mem0.ai").rstrip("/")
        # Support both "timeout" (plugin-specific) and "timeout_seconds" (provider-level)
        self.timeout = int(config.get("timeout_seconds", config.get("timeout", 30)))

    @property
    def provider_name(self) -> str:
        return "mem0"

    def _build_headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Token {self.api_key}"
        if self.org_id:
            headers["X-Org-Id"] = self.org_id
        return headers

    async def search(
        self,
        request: MemorySearchRequest,
        limit: int = 5,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[MemorySearchResult]:
        payload = self._build_search_payload(request, limit, filters)
        async def _post_search(search_payload: Dict[str, Any]) -> Any:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/v3/memories/search/",
                    json=search_payload,
                    headers=self._build_headers(),
                )
                self._check_response(response)
                return response.json()

        try:
            data = await _post_search(payload)
            raw_results = data if isinstance(data, list) else data.get("results", [])
            if not raw_results and request.agent_id and request.user_id:
                user_request = request.model_copy(update={"agent_id": None})
                user_payload = self._build_search_payload(user_request, limit, filters)
                data = await _post_search(user_payload)
        except httpx.TimeoutException as exc:
            error = ProviderError(
                code=ProviderErrorCode.TIMEOUT,
                message=f"Mem0 search timed out after {self.timeout}s",
                severity=ProviderErrorSeverity.RETRYABLE,
            )
            raise RetryableProviderError(error.message, error) from exc
        except httpx.HTTPError as exc:
            error = ProviderError(
                code=ProviderErrorCode.PROVIDER_ERROR,
                message=f"Mem0 search HTTP error: {exc}",
                severity=ProviderErrorSeverity.RETRYABLE,
            )
            raise RetryableProviderError(error.message, error) from exc

        raw_results = data if isinstance(data, list) else data.get("results", [])
        return [
            MemorySearchResult(
                external_id=r.get("id", ""),
                content=r.get("memory", r.get("content", "")),
                score=float(r.get("score", 0.0)),
                source=self.provider_name,
                is_external=True,
                metadata=r.get("metadata", {}),
            )
            for r in raw_results
        ]

    def _build_search_payload(
        self,
        request: MemorySearchRequest,
        limit: int,
        filters: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        entity_filters = []
        if request.user_id:
            entity_filters.append({"user_id": request.user_id})
        if request.agent_id:
            entity_filters.append({"agent_id": request.agent_id})
        if filters:
            entity_filters.append(filters)
        if not entity_filters:
            raise ValueError("Mem0 v3 search requires a user_id or agent_id filter")
        search_filters = (
            entity_filters[0] if len(entity_filters) == 1 else {"AND": entity_filters}
        )
        return {
            "query": request.query,
            "filters": search_filters,
            "top_k": limit,
            "threshold": 0.0,
        }

    async def ingest(
        self,
        request: MemoryIngestRequest,
    ) -> MemoryIngestResult:
        accepted_count = 0
        rejected_count = 0
        unit_results: List[UnitIngestResult] = []

        for unit in request.units:
            payload: Dict[str, Any] = {
                "messages": [{"role": "user", "content": unit.unit_content}],
                "metadata": {
                    **request.metadata,
                    **unit.metadata,
                    "event_id": unit.event_id,
                    "event_type": unit.event_type,
                    "unit_type": unit.unit_type,
                },
            }
            if request.user_id:
                payload["user_id"] = request.user_id
            if request.agent_id:
                payload["agent_id"] = request.agent_id
            if request.conversation_id:
                payload["run_id"] = request.conversation_id
            payload["infer"] = False

            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.post(
                        f"{self.base_url}/v3/memories/add/",
                        json=payload,
                        headers=self._build_headers(),
                    )
                    self._check_response(response)
                    event_id = response.json().get("event_id")
                    if event_id:
                        await self._wait_for_event(client, event_id)

                unit_results.append(
                    UnitIngestResult(
                        unit_id=unit.event_id,
                        status=UnitIngestStatus.ACCEPTED,
                    )
                )
                accepted_count += 1
            except (NonRetryableProviderError, RetryableProviderError) as exc:
                provider_error = exc.error
                logger.warning(
                    f"Mem0 ingest failed for unit {unit.event_id}: {provider_error.message}"
                )
                unit_results.append(
                    UnitIngestResult(
                        unit_id=unit.event_id,
                        status=UnitIngestStatus.REJECTED,
                        message=provider_error.message,
                    )
                )
                rejected_count += 1

        status = (
            "ok"
            if rejected_count == 0
            else ("partial" if accepted_count > 0 else "error")
        )
        return MemoryIngestResult(
            provider=self.provider_name,
            status=status,
            accepted_count=accepted_count,
            rejected_count=rejected_count,
            unit_results=unit_results,
            message=f"Accepted {accepted_count}/{len(request.units)} units",
        )

    async def _wait_for_event(self, client: httpx.AsyncClient, event_id: str) -> None:
        attempts = max(1, self.timeout // 2)
        for _ in range(attempts):
            response = await client.get(
                f"{self.base_url}/v1/event/{event_id}/",
                headers=self._build_headers(),
            )
            self._check_response(response)
            status = str(response.json().get("status", "")).upper()
            if status == "SUCCEEDED":
                return
            if status == "FAILED":
                error = ProviderError(
                    code=ProviderErrorCode.PROVIDER_ERROR,
                    message="Mem0 asynchronous ingest failed",
                    severity=ProviderErrorSeverity.NON_RETRYABLE,
                )
                raise NonRetryableProviderError(error.message, error)
            await asyncio.sleep(2)
        raise httpx.TimeoutException(
            f"Mem0 ingest event did not complete after {self.timeout}s"
        )

    def _check_response(self, response: httpx.Response) -> None:
        if 200 <= response.status_code < 300:
            return

        if response.status_code == 401:
            try:
                response_body = response.text
            except Exception:
                response_body = "<unable to read response>"
            error = ProviderError(
                code=ProviderErrorCode.UNAUTHORIZED,
                message=f"Mem0 authentication failed: {response_body[:100]}",
                severity=ProviderErrorSeverity.NON_RETRYABLE,
            )
            raise NonRetryableProviderError(error.message, error)
        if response.status_code == 403:
            error = ProviderError(
                code=ProviderErrorCode.FORBIDDEN,
                message="Mem0 access forbidden",
                severity=ProviderErrorSeverity.NON_RETRYABLE,
            )
            raise NonRetryableProviderError(error.message, error)
        if response.status_code == 429:
            retry_after = int(response.headers.get("Retry-After", 60))
            error = ProviderError(
                code=ProviderErrorCode.RATE_LIMITED,
                message="Mem0 rate limited",
                severity=ProviderErrorSeverity.RETRYABLE,
                retry_after_seconds=retry_after,
            )
            raise RetryableProviderError(error.message, error)
        if response.status_code >= 500:
            error = ProviderError(
                code=ProviderErrorCode.PROVIDER_ERROR,
                message=f"Mem0 server error: {response.status_code}",
                severity=ProviderErrorSeverity.RETRYABLE,
            )
            raise RetryableProviderError(error.message, error)
        try:
            error_data = response.json()
            message = error_data.get(
                "detail", error_data.get("message", f"HTTP {response.status_code}")
            )
        except Exception:
            message = f"HTTP {response.status_code}"
        error = ProviderError(
            code=ProviderErrorCode.UNKNOWN,
            message=message,
            severity=ProviderErrorSeverity.NON_RETRYABLE,
        )
        raise NonRetryableProviderError(error.message, error)
