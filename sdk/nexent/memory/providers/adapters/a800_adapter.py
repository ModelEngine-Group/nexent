"""A800 external memory provider adapter.

This adapter integrates with A800 services by adapting
Nexent's internal models to A800's API format and vice versa.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .base import BaseMemoryAdapter
from ..base import BaseMemoryProvider
from ...models import (
    MemoryIngestRequest,
    MemoryIngestResult,
    MemorySearchRequest,
    MemorySearchResult,
)
from ..retry import RetryConfig, execute_with_retry


logger = logging.getLogger("memory_adapters_a800")


class A800Adapter(BaseMemoryAdapter):
    """Adapter for A800 external services.

    This adapter translates between Nexent's internal memory models
    and A800's API format for search and ingest operations.
    """

    @property
    def provider_name(self) -> str:
        """Return the name of the provider."""
        return "a800"

    def normalize_search_result(self, raw_result: Dict[str, Any]) -> MemorySearchResult:
        """Convert an A800 search result to MemorySearchResult.

        A800 returns results in the format:
        {
            "id": "...",
            "content": "...",
            "score": 0.95,
            "metadata": {...}
        }
        """
        return MemorySearchResult(
            external_id=raw_result.get("id", ""),
            content=raw_result.get("content", raw_result.get("text", "")),
            score=raw_result.get("score", raw_result.get("relevance_score", 0.0)),
            source=self.provider_name,
            is_external=True,
            metadata=raw_result.get("metadata", {}),
        )

    def adapt_search_request(self, request: MemorySearchRequest) -> Dict[str, Any]:
        """Convert a MemorySearchRequest to A800 format."""
        return {
            "query": request.query,
            "tenant_id": request.tenant_id,
            "user_id": request.user_id,
            "agent_id": request.agent_id,
            "top_k": request.limit,
            "threshold": request.threshold or 0.65,
        }

    def adapt_ingest_request(self, request: MemoryIngestRequest) -> Dict[str, Any]:
        """Convert a MemoryIngestRequest to A800 format."""
        return {
            "tenant_id": request.tenant_id,
            "user_id": request.user_id,
            "agent_id": request.agent_id,
            "conversation_id": request.conversation_id,
            "idempotency_key": request.idempotency_key,
            "events": [
                {
                    "event_id": unit.event_id,
                    "type": unit.unit_type,
                    "content": unit.unit_content,
                }
                for unit in request.units
            ],
        }
