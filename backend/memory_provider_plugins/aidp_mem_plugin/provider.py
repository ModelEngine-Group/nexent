"""AIDP_Memorybank external memory provider plugin.

Implements SearchableMemoryProvider and IngestibleMemoryProvider protocols
against the openJiuwen MemoryBank HTTP API.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
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

logger = logging.getLogger("memory_provider_unifiedmemory")


class UnifiedMemoryProvider:
    """UnifiedMemory external memory provider."""

    def __init__(self, config: dict):
        self.base_url = (config.get("base_url") or "").rstrip("/")
        self.api_key = config.get("api_key")
        self.tenant_id = config.get("tenant_id")
        # self.default_agent_id = config.get("default_agent_id") or "default"
        self.instance_name = config.get("instance_name")
        if self.instance_name is None:
            self.instance_name = "nexent_instance"
        self.verify_ssl = str(config.get("verify_ssl", "false")).strip().lower() in {"1", "true", "yes", "on"}
        self.timeout = int(config.get("timeout_seconds", config.get("timeout", 30)))

    @property
    def provider_name(self) -> str:
        return "unifiedmemory"

    # def _resolve_instance_name(self, agent_id: Optional[str]) -> str:
    #     if agent_id:
    #         return f"{self.instance_name}"
    #     return self.default_agent_id

    def _build_headers(self) -> Dict[str, str]:
        headers: Dict[str, str] = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def search(
        self,
        request: MemorySearchRequest,
        limit: int = 5,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[MemorySearchResult]:
        instance_name = self.instance_name
        # user_id = request.user_id or ""
        top_k = int(limit or request.top_k or request.limit or 5)

        url = (
            f"{self.base_url}/MemoryBank/Tenants/{self.tenant_id}"
            f"/Instances/{instance_name}/Memories/Query"
        )
        payload = {
            "query": request.query,
            "top_k": top_k,
            "threshold": 0,
            "rerank": False,
        }
        headers = self._build_headers()

        try:
            async with httpx.AsyncClient(timeout=self.timeout, verify=self.verify_ssl) as client:
                response = await client.post(url, json=payload, headers=headers)
                self._check_response(response)
        except (NonRetryableProviderError, RetryableProviderError):
            raise
        except httpx.TimeoutException as exc:
            error = ProviderError(
                code=ProviderErrorCode.TIMEOUT,
                message=f"UnifiedMemory search timed out after {self.timeout}s",
                severity=ProviderErrorSeverity.RETRYABLE,
            )
            raise RetryableProviderError(error.message, error) from exc
        except httpx.HTTPError as exc:
            error = ProviderError(
                code=ProviderErrorCode.PROVIDER_ERROR,
                message=f"UnifiedMemory search HTTP error: {exc}",
                severity=ProviderErrorSeverity.RETRYABLE,
            )
            raise RetryableProviderError(error.message, error) from exc

        data = response.json()
        if isinstance(data, list):
            raw_results = data
        elif isinstance(data, dict):
            raw_results = data.get("value", data.get("results", []))
        else:
            raw_results = []

        results: List[MemorySearchResult] = []
        for r in raw_results:
            results.append(
                MemorySearchResult(
                    external_id=str(r.get("memory_id")),
                    content=r.get("content", ""),
                    score=float(r.get("score", 0.0)),
                    source=self.provider_name,
                    is_external=True,
                    metadata={
                        "memory_type": r.get("memory_type"),
                        "timestamp": r.get("timestamp"),
                    },
                )
            )
        return results

    async def ingest(
        self,
        request: MemoryIngestRequest,
    ) -> MemoryIngestResult:
        instance_name = self.instance_name
        # user_id = request.user_id or ""
        timestamp = datetime.now(timezone.utc).isoformat()

        messages = [
            {"role": "user", "content": unit.unit_content}
            for unit in request.units
        ]

        url = (
            f"{self.base_url}/MemoryBank/Tenants/{self.tenant_id}"
            f"/Instances/{instance_name}/Memories"
        )
        payload = {
            "messages": messages,
            "timestamp": timestamp,
        }
        headers = self._build_headers()

        try:
            async with httpx.AsyncClient(timeout=self.timeout, verify=self.verify_ssl) as client:
                response = await client.put(url, json=payload, headers=headers)
                self._check_response(response)
        except (NonRetryableProviderError, RetryableProviderError) as exc:
            provider_error = exc.error
            unit_results = [
                UnitIngestResult(
                    unit_id=unit.event_id,
                    status=UnitIngestStatus.REJECTED,
                    message=provider_error.message,
                )
                for unit in request.units
            ]
            return MemoryIngestResult(
                provider=self.provider_name,
                status="error",
                accepted_count=0,
                rejected_count=len(request.units),
                unit_results=unit_results,
                message=provider_error.message,
            )

        unit_results = [
            UnitIngestResult(
                unit_id=unit.event_id,
                status=UnitIngestStatus.ACCEPTED,
            )
            for unit in request.units
        ]
        return MemoryIngestResult(
            provider=self.provider_name,
            status="ok",
            accepted_count=len(request.units),
            rejected_count=0,
            unit_results=unit_results,
            message=f"Accepted {len(request.units)}/{len(request.units)} units",
        )

    def _check_response(self, response: httpx.Response) -> None:
        if 200 <= response.status_code < 300:
            return
        try:
            response_body = response.text
        except Exception:
            response_body = "<unable to read response>"

        if response.status_code == 401:
            error = ProviderError(
                code=ProviderErrorCode.UNAUTHORIZED,
                message=f"UnifiedMemory authentication failed: {response_body[:100]}",
                severity=ProviderErrorSeverity.NON_RETRYABLE,
            )
            raise NonRetryableProviderError(error.message, error)
        if response.status_code == 403:
            error = ProviderError(
                code=ProviderErrorCode.FORBIDDEN,
                message=f"UnifiedMemory access forbidden: {response_body[:100]}",
                severity=ProviderErrorSeverity.NON_RETRYABLE,
            )
            raise NonRetryableProviderError(error.message, error)
        if response.status_code == 429:
            retry_after = int(response.headers.get("Retry-After", 60))
            error = ProviderError(
                code=ProviderErrorCode.RATE_LIMITED,
                message="UnifiedMemory rate limited",
                severity=ProviderErrorSeverity.RETRYABLE,
                retry_after_seconds=retry_after,
            )
            raise RetryableProviderError(error.message, error)
        if response.status_code >= 500:
            error = ProviderError(
                code=ProviderErrorCode.PROVIDER_ERROR,
                message=f"UnifiedMemory server error: {response.status_code}",
                severity=ProviderErrorSeverity.RETRYABLE,
            )
            raise RetryableProviderError(error.message, error)
        code = (
            ProviderErrorCode.INVALID_PAYLOAD
            if 400 <= response.status_code < 500
            else ProviderErrorCode.UNKNOWN
        )
        error = ProviderError(
            code=code,
            message=f"UnifiedMemory HTTP {response.status_code}: {response_body[:100]}",
            severity=ProviderErrorSeverity.NON_RETRYABLE,
        )
        raise NonRetryableProviderError(error.message, error)
