"""Mem0 external memory provider adapter.

This adapter integrates with Mem0 services by adapting Nexent's internal models
to Mem0's API format and vice versa.

The adapter is referenced in the Memory Architecture design doc (§12.2 SDK layer)
as the translation layer between Nexent protocol models and external provider
responses.
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


logger = logging.getLogger("memory_adapters_mem0")


class Mem0Adapter(BaseMemoryAdapter):
    """Adapter for Mem0 external services.

    This adapter translates between Nexent's internal memory models
    and Mem0's API format for search and ingest operations.
    """

    @property
    def provider_name(self) -> str:
        """Return the name of the provider."""
        return "mem0"

    def normalize_search_result(self, raw_result: Dict[str, Any]) -> MemorySearchResult:
        """Convert a Mem0 search result to MemorySearchResult.

        Mem0 returns results in the format:
        {
            "id": "...",
            "text": "...",
            "score": 0.95,
            "metadata": {...}
        }
        """
        return MemorySearchResult(
            external_id=raw_result.get("id", ""),
            content=raw_result.get("text", raw_result.get("content", "")),
            score=raw_result.get("score", raw_result.get("relevance_score", 0.0)),
            source=self.provider_name,
            is_external=True,
            metadata=raw_result.get("metadata", {}),
        )

    def adapt_search_request(self, request: MemorySearchRequest) -> Dict[str, Any]:
        """Convert a MemorySearchRequest to Mem0 format.

        Mem0 search API expects:
        {
            "query": str,
            "user_id": str,
            "agent_id": str (optional),
            "top_k": int,
            "filter": dict (optional)
        }
        """
        filter_dict: Dict[str, Any] = {}
        if request.tenant_id:
            filter_dict["tenant_id"] = request.tenant_id
        if request.agent_id:
            filter_dict["agent_id"] = request.agent_id

        return {
            "query": request.query,
            "user_id": request.user_id,
            "top_k": request.limit,
            "filter": filter_dict if filter_dict else None,
        }

    def adapt_ingest_request(self, request: MemoryIngestRequest) -> Dict[str, Any]:
        """Convert a MemoryIngestRequest to Mem0 format.

        Mem0 add API expects:
        {
            "user_id": str,
            "agent_id": str (optional),
            "memory": [
                {
                    "role": str,
                    "content": str,
                    "metadata": dict
                }
            ]
        }
        """
        memories = []
        for unit in request.units:
            role = unit.metadata.get("role", "system")
            memories.append({
                "role": role,
                "content": unit.unit_content,
                "metadata": {
                    "event_id": unit.event_id,
                    "event_type": unit.event_type,
                    "unit_type": unit.unit_type,
                    "conversation_id": request.conversation_id,
                    "tenant_id": request.tenant_id,
                    **unit.metadata,
                },
            })

        return {
            "user_id": request.user_id,
            "agent_id": request.agent_id,
            "memory": memories,
            "idempotency_key": request.idempotency_key,
        }

    def adapt_ingest_response(
        self,
        response: Dict[str, Any],
        request: MemoryIngestRequest,
    ) -> MemoryIngestResult:
        """Convert a Mem0 response to MemoryIngestResult.

        Mem0 add API returns:
        {
            "status": "success" | "partial",
            "memory_ids": [str, ...],
            "failed_count": int
        }
        """
        status = response.get("status", "ok")
        memory_ids = response.get("memory_ids", [])
        failed_count = response.get("failed_count", 0)
        accepted_count = len(memory_ids)

        unit_results = []
        for i, unit in enumerate(request.units):
            if i < len(memory_ids):
                unit_results.append({
                    "unit_id": unit.event_id,
                    "status": "accepted",
                    "memory_id": memory_ids[i],
                })
            else:
                unit_results.append({
                    "unit_id": unit.event_id,
                    "status": "rejected",
                })

        return MemoryIngestResult(
            provider=self.provider_name,
            status=status,
            accepted_count=accepted_count,
            rejected_count=failed_count,
            unit_results=unit_results,  # type: ignore
            message=response.get("message"),
        )
