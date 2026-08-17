"""Mem0 external memory provider plugin.

Implements SearchableMemoryProvider and IngestibleMemoryProvider protocols
using the Mem0 hosted API (https://api.mem0.ai).
"""

from __future__ import annotations

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
        payload: Dict[str, Any] = {
            "query": request.query,
            "limit": limit,
        }
        if request.user_id:
            payload["user_id"] = request.user_id
        if request.agent_id:
            payload["agent_id"] = request.agent_id
        if filters:
            payload["filters"] = filters

        async def _post_search(search_payload: Dict[str, Any]) -> Any:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/v1/memories/search/",
                    json=search_payload,
                    headers=self._build_headers(),
                )
                self._check_response(response)
                return response.json()

        try:
            data = await _post_search(payload)
            raw_results = data if isinstance(data, list) else data.get("results", [])
            if not raw_results and request.agent_id and request.user_id:
                user_payload = {key: value for key, value in payload.items() if key != "agent_id"}
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

    async def ingest(
        self,
        request: MemoryIngestRequest,
    ) -> MemoryIngestResult:
        accepted_count = 0
        rejected_count = 0
        unit_results: List[UnitIngestResult] = []

        for unit in request.units:
            payload: Dict[str, Any] = {
                "messages": [
                    {"role": "user", "content": unit.unit_content}
                ],
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

            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.post(
                        f"{self.base_url}/v1/memories/",
                        json=payload,
                        headers=self._build_headers(),
                    )
                    self._check_response(response)

                unit_results.append(UnitIngestResult(
                    unit_id=unit.event_id,
                    status=UnitIngestStatus.ACCEPTED,
                ))
                accepted_count += 1
            except (NonRetryableProviderError, RetryableProviderError) as exc:
                provider_error = exc.error
                logger.warning(
                    f"Mem0 ingest failed for unit {unit.event_id}: {provider_error.message}"
                )
                unit_results.append(UnitIngestResult(
                    unit_id=unit.event_id,
                    status=UnitIngestStatus.REJECTED,
                    message=provider_error.message,
                ))
                rejected_count += 1

        status = "ok" if rejected_count == 0 else ("partial" if accepted_count > 0 else "error")
        return MemoryIngestResult(
            provider=self.provider_name,
            status=status,
            accepted_count=accepted_count,
            rejected_count=rejected_count,
            unit_results=unit_results,
            message=f"Accepted {accepted_count}/{len(request.units)} units",
        )

    def _check_response(self, response: httpx.Response) -> None:
        if response.status_code == 200:
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
            message = error_data.get("detail", error_data.get("message", f"HTTP {response.status_code}"))
        except Exception:
            message = f"HTTP {response.status_code}"
        error = ProviderError(
            code=ProviderErrorCode.UNKNOWN,
            message=message,
            severity=ProviderErrorSeverity.NON_RETRYABLE,
        )
        raise NonRetryableProviderError(error.message, error)
