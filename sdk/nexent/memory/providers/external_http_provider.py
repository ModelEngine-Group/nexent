"""HTTP-based external memory provider.

This module provides an HTTP client for interacting with external memory
providers that expose REST APIs. It handles authentication, timeouts,
and response parsing.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import httpx

from .base import BaseMemoryProvider, IngestibleMemoryProvider, SearchableMemoryProvider
from .adapters.base import BaseMemoryAdapter
from ..models import (
    MemoryIngestRequest,
    MemoryIngestResult,
    MemorySearchRequest,
    MemorySearchResult,
)
from .retry import (
    RetryConfig,
    execute_with_retry,
    NonRetryableProviderError,
    DegradableProviderError,
    RetryableProviderError,
    ProviderError,
    ProviderErrorCode,
    ProviderErrorSeverity,
)


logger = logging.getLogger("memory_external_http_provider")


class ExternalHttpProvider(BaseMemoryProvider, SearchableMemoryProvider, IngestibleMemoryProvider):
    """HTTP-based external memory provider.

    This provider can interact with any REST API that implements the
    Nexent memory provider protocol.
    """

    def __init__(
        self,
        provider_name: str,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: int = 30,
        adapter: Optional[BaseMemoryAdapter] = None,
        retry_config: Optional[RetryConfig] = None,
    ):
        """Initialize the HTTP provider.

        Args:
            provider_name: Unique identifier for this provider.
            api_key: API key for authentication.
            base_url: Base URL for the provider API.
            timeout: Request timeout in seconds.
            adapter: Adapter for translating between formats.
            retry_config: Configuration for retry behavior.
        """
        super().__init__(
            provider_name=provider_name,
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
        )
        self.adapter = adapter
        self.retry_config = retry_config or RetryConfig()

    @property
    def provider_name(self) -> str:
        """Return the unique name of this provider."""
        return self._provider_name

    async def search(
        self,
        request: MemorySearchRequest,
        limit: int = 5,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[MemorySearchResult]:
        """Search for memories from this provider.

        Args:
            request: The search request.
            limit: Maximum results to return.
            filters: Optional search filters.

        Returns:
            List of search results.

        Raises:
            ProviderError: If the search fails.
        """
        if not self.base_url:
            logger.warning(f"Provider {self.provider_name} has no base_url configured")
            return []

        adapted_request = request
        if self.adapter:
            adapted_request = self.adapter.adapt_search_request(request)

        if hasattr(adapted_request, "model_dump"):
            adapted_request = adapted_request.model_dump()
        adapted_request["limit"] = limit

        async def _do_search():
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/search",
                    json=adapted_request,
                    headers=self._build_headers(),
                )
                self._check_response(response)
                return response.json()

        try:
            result = await execute_with_retry(
                _do_search,
                self.retry_config,
                f"provider.{self.provider_name}.search",
            )
            raw_results = result.get("results", [])
            if self.adapter:
                return self.adapter.normalize_search_results(raw_results)
            return [
                MemorySearchResult(
                    external_id=r.get("id", ""),
                    content=r.get("content", ""),
                    score=r.get("score", 0.0),
                    source=self.provider_name,
                    is_external=True,
                )
                for r in raw_results
            ]
        except NonRetryableProviderError as exc:
            logger.error(f"Provider {self.provider_name} search failed: {exc}")
            raise ProviderError(
                code=exc.error.code if exc.error else ProviderErrorCode.PROVIDER_ERROR,
                message=str(exc),
                severity=ProviderErrorSeverity.NON_RETRYABLE,
            ) from exc
        except Exception as exc:
            logger.error(f"Provider {self.provider_name} search failed: {exc}")
            raise ProviderError(
                code=ProviderErrorCode.UNKNOWN,
                message=str(exc),
                severity=ProviderErrorSeverity.RETRYABLE,
            ) from exc

    async def ingest(
        self,
        request: MemoryIngestRequest,
    ) -> MemoryIngestResult:
        """Ingest context units to this provider.

        Args:
            request: The ingest request.

        Returns:
            Ingest result.

        Raises:
            ProviderError: If the ingest fails.
        """
        if not self.base_url:
            logger.warning(f"Provider {self.provider_name} has no base_url configured")
            return MemoryIngestResult(
                provider=self.provider_name,
                status="error",
                message="Provider not configured",
            )

        adapted_request = request
        if self.adapter:
            adapted_request = self.adapter.adapt_ingest_request(request)

        async def _do_ingest():
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/ingest",
                    json=adapted_request if isinstance(adapted_request, dict) else adapted_request.model_dump(),
                    headers=self._build_headers(),
                )
                self._check_response(response)
                return response.json()

        try:
            result = await execute_with_retry(
                _do_ingest,
                self.retry_config,
                f"provider.{self.provider_name}.ingest",
            )
            if self.adapter:
                return self.adapter.adapt_ingest_response(result, request)
            return MemoryIngestResult(
                provider=self.provider_name,
                status=result.get("status", "ok"),
                accepted_count=result.get("accepted_count", 0),
                rejected_count=result.get("rejected_count", 0),
                message=result.get("message"),
            )
        except NonRetryableProviderError as exc:
            logger.error(f"Provider {self.provider_name} ingest failed: {exc}")
            raise ProviderError(
                code=exc.error.code if exc.error else ProviderErrorCode.PROVIDER_ERROR,
                message=str(exc),
                severity=ProviderErrorSeverity.NON_RETRYABLE,
            ) from exc
        except DegradableProviderError as exc:
            logger.warning(f"Provider {self.provider_name} ingest degraded: {exc}")
            raise
        except Exception as exc:
            logger.error(f"Provider {self.provider_name} ingest failed: {exc}")
            raise ProviderError(
                code=ProviderErrorCode.UNKNOWN,
                message=str(exc),
                severity=ProviderErrorSeverity.RETRYABLE,
            ) from exc

    def _check_response(self, response: httpx.Response) -> None:
        """Check HTTP response and raise appropriate errors.

        Args:
            response: The HTTP response.

        Raises:
            ProviderError: If the response indicates an error.
        """
        if response.status_code == 200:
            return
        elif response.status_code == 401:
            raise ProviderError(
                code=ProviderErrorCode.UNAUTHORIZED,
                message="Authentication failed",
                severity=ProviderErrorSeverity.NON_RETRYABLE,
            )
        elif response.status_code == 403:
            raise ProviderError(
                code=ProviderErrorCode.FORBIDDEN,
                message="Access forbidden",
                severity=ProviderErrorSeverity.NON_RETRYABLE,
            )
        elif response.status_code == 429:
            retry_after = int(response.headers.get("Retry-After", 60))
            raise ProviderError(
                code=ProviderErrorCode.RATE_LIMITED,
                message="Rate limited",
                severity=ProviderErrorSeverity.RETRYABLE,
                retry_after_seconds=retry_after,
            )
        elif response.status_code >= 500:
            raise ProviderError(
                code=ProviderErrorCode.PROVIDER_ERROR,
                message=f"Provider error: {response.status_code}",
                severity=ProviderErrorSeverity.RETRYABLE,
            )
        else:
            try:
                error_data = response.json()
                message = error_data.get("message", f"HTTP {response.status_code}")
            except Exception:
                message = f"HTTP {response.status_code}"

            raise ProviderError(
                code=ProviderErrorCode.UNKNOWN,
                message=message,
                severity=ProviderErrorSeverity.NON_RETRYABLE,
            )
