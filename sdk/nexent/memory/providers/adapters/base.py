"""Base adapter for external memory providers.

This module provides a base adapter class that external provider adapters
should inherit from. Adapters are responsible for converting between
Nexent's internal models and the external provider's specific format.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ...models import (
    ExternalMemoryItem,
    MemoryIngestRequest,
    MemoryIngestResult,
    MemorySearchRequest,
    MemorySearchResult,
)


class BaseMemoryAdapter:
    """Base class for external memory provider adapters.

    Adapters translate between Nexent's internal memory models and the
    specific request/response formats expected by external providers.

    Each adapter should implement the conversion methods to handle
    the specific format of its provider.
    """

    @property
    def provider_name(self) -> str:
        """Return the name of the provider this adapter supports."""
        return "base"

    def normalize_search_result(self, raw_result: Dict[str, Any]) -> MemorySearchResult:
        """Convert a raw search result to a MemorySearchResult.

        Args:
            raw_result: The raw result from the external provider.

        Returns:
            A normalized MemorySearchResult.
        """
        return MemorySearchResult(
            external_id=raw_result.get("id", ""),
            content=raw_result.get("content", raw_result.get("text", "")),
            score=raw_result.get("score", raw_result.get("relevance_score", 0.0)),
            source=self.provider_name,
            is_external=True,
            metadata=raw_result.get("metadata", {}),
        )

    def normalize_search_results(
        self,
        raw_results: List[Dict[str, Any]],
    ) -> List[MemorySearchResult]:
        """Convert a list of raw search results.

        Args:
            raw_results: List of raw results from the external provider.

        Returns:
            List of normalized MemorySearchResults.
        """
        return [self.normalize_search_result(result) for result in raw_results]

    def adapt_search_request(self, request: MemorySearchRequest) -> Dict[str, Any]:
        """Convert a MemorySearchRequest to provider-specific format.

        Args:
            request: The Nexent search request.

        Returns:
            Provider-specific request dictionary.
        """
        return {
            "query": request.query,
            "limit": request.limit,
            "filters": self._build_filters(request),
        }

    def _build_filters(self, request: MemorySearchRequest) -> Dict[str, Any]:
        """Build filter dictionary for search requests.

        Args:
            request: The search request.

        Returns:
            Filter dictionary.
        """
        filters = {}
        if request.tenant_id:
            filters["tenant_id"] = request.tenant_id
        if request.user_id:
            filters["user_id"] = request.user_id
        if request.agent_id:
            filters["agent_id"] = request.agent_id
        return filters

    def adapt_ingest_request(self, request: MemoryIngestRequest) -> Dict[str, Any]:
        """Convert a MemoryIngestRequest to provider-specific format.

        Args:
            request: The Nexent ingest request.

        Returns:
            Provider-specific request dictionary.
        """
        return {
            "tenant_id": request.tenant_id,
            "user_id": request.user_id,
            "agent_id": request.agent_id,
            "conversation_id": request.conversation_id,
            "events": [
                {
                    "event_id": unit.event_id,
                    "event_type": unit.event_type,
                    "content": unit.unit_content,
                    "type": unit.unit_type,
                    "index": unit.unit_index,
                    "metadata": unit.metadata,
                }
                for unit in request.units
            ],
            "idempotency_key": request.idempotency_key,
        }

    def adapt_ingest_response(
        self,
        response: Dict[str, Any],
        request: MemoryIngestRequest,
    ) -> MemoryIngestResult:
        """Convert a provider response to MemoryIngestResult.

        Args:
            response: The raw response from the provider.
            request: The original ingest request.

        Returns:
            A MemoryIngestResult.
        """
        accepted_count = 0
        rejected_count = 0
        unit_results = []

        for unit in request.units:
            # Try to find result for this unit
            unit_result = response.get("results", {}).get(unit.event_id, {})
            status = unit_result.get("status", "accepted")

            if status == "accepted":
                accepted_count += 1
            else:
                rejected_count += 1

            unit_results.append({
                "unit_id": unit.event_id,
                "status": status,
                "message": unit_result.get("message"),
            })

        return MemoryIngestResult(
            provider=self.provider_name,
            status=response.get("status", "ok"),
            accepted_count=accepted_count,
            rejected_count=rejected_count,
            unit_results=unit_results,  # type: ignore
            message=response.get("message"),
        )
