"""
DispatcherKBClient — in-process knowledge base search client.

Replaces the HTTP round-trip (nexent API → Service
→ Adapter → platform) with a direct in-process call:

    DispatcherKBClient.search() → ExternalKnowledgeBaseService.retrieve() → Adapter.search()

This eliminates the spurious HTTP hop for ALL knowledge base searches during
agent runtime, including:
  - "local" adapter → LocalKBAdapter → ElasticSearchService (in-process)
  - "dify" / "aidp" / etc. → their respective adapter classes (outbound HTTP to platform)

The client exposes the same ``search()`` / ``retrieve()`` methods as
DispatcherKBClient so that ExternalKnowledgeSearchTool is agnostic to which client
is injected.

For multi-adapter searches (kb_refs spanning multiple adapter_ids), use
``retrieve_across()`` which fans out per adapter and merges results globally.
"""

import logging
from collections import defaultdict
from typing import Any, Dict, List

from nexent.core.knowledge_base.platform_adapters import (
    SearchRequest,
    SearchResponse,
    SearchResult,
)

logger = logging.getLogger("dispatcher_kb_client")


class DispatcherKBClient:
    """
    In-process KB search client.

    Wraps ExternalKnowledgeBaseService.retrieve() and converts the response dict
    back into a SearchResponse so ExternalKnowledgeSearchTool sees no difference
    from DispatcherKBClient.

    Usage::

        client = DispatcherKBClient(
            adapter_id=1,
            tenant_id="tenant-abc",
            user_id="user-xyz",
        )
        response = client.search(SearchRequest(query="...", kb_ids=["kb-1"], top_k=5))
    """

    def __init__(self, adapter_id: int, tenant_id: str, user_id: str):
        self.adapter_id = adapter_id
        self.tenant_id = tenant_id
        self.user_id = user_id

    def search(self, request: SearchRequest) -> SearchResponse:
        """
        Execute in-process search via ExternalKnowledgeBaseService.

        Matches the expected search() signature so the tool is client-agnostic.
        The ``request`` is passed through untouched — each adapter handles its own
        search_mode normalization (e.g. LocalKBAdapter maps V4 standard
        ``"hybrid_search"`` → local ``"hybrid"`` internally).
        """
        from services.external_kb_service import ExternalKnowledgeBaseService

        result = ExternalKnowledgeBaseService.retrieve(
            adapter_id=self.adapter_id,
            tenant_id=self.tenant_id,
            request=request,
        )

        return self._to_search_response(result, request.query)

    def retrieve(self, request: SearchRequest) -> SearchResponse:
        """Alias for search() — kept for API symmetry."""
        return self.search(request)

    def retrieve_across(
        self,
        kb_refs: List[dict],
        request: SearchRequest,
    ) -> SearchResponse:
        """
        Search across multiple adapters, merging results globally by score.

        Groups kb_refs by adapter_id, fans out one call per adapter via
        ExternalKnowledgeBaseService.retrieve(), then merges all results
        sorted by score descending (stable sort preserves adapter order on ties).
        Truncates to request.top_k.

        Partial adapter failures are logged and skipped rather than failing
        the entire search.

        Args:
            kb_refs: List of {adapter_id: int, kb_id: str, display_name: str}
            request: SearchRequest (kb_ids will be set per group)
            tenant_id: Tenant context
            user_id: User context
        """
        from services.external_kb_service import ExternalKnowledgeBaseService

        groups: Dict[int, List[dict]] = defaultdict(list)
        for ref in kb_refs:
            groups[ref["adapter_id"]].append(ref)

        adapter_id_order = list(groups.keys())
        all_results: List[SearchResult] = []
        total_adapters_ok = 0

        for adapter_id in adapter_id_order:
            group = groups[adapter_id]
            group_kb_ids = [ref["kb_id"] for ref in group]
            per_request = SearchRequest(
                query=request.query,
                kb_ids=group_kb_ids,
                top_k=request.top_k,
                search_mode=request.search_mode,
                score_threshold=request.score_threshold,
                rerank=request.rerank,
                filters=dict(request.filters) if request.filters else {},
            )
            try:
                result = ExternalKnowledgeBaseService.retrieve(
                    adapter_id=adapter_id,
                    tenant_id=self.tenant_id,
                    request=per_request,
                )
                # Service returns V4 nested structure: {records: [{segment, score}], query}
                raw_records = result.get("records", [])
                adapter_results = [
                    _record_to_search_result(record)
                    for record in raw_records
                ]
                logger.info(
                    "merge: adapter=%s results=%d", adapter_id, len(adapter_results),
                )
                all_results.extend(adapter_results)
                total_adapters_ok += 1
            except Exception as exc:
                logger.warning(
                    "retrieve_across: adapter=%s failed: %s — skipping",
                    adapter_id, exc,
                )

        all_results.sort(key=lambda r: r.score, reverse=True)
        truncated = all_results[:request.top_k] if request.top_k else all_results

        logger.info(
            "merge: total_adapters_ok=%d total_results=%d returned=%d",
            total_adapters_ok, len(all_results), len(truncated),
        )

        return SearchResponse(
            results=truncated,
            query=request.query,
        )

    # ------------------------------------------------------------------
    # Response conversion
    # ------------------------------------------------------------------

    @staticmethod
    def _to_search_response(data: Dict[str, Any], query: str) -> SearchResponse:
        """Convert Service.retrieve() V4 nested response dict back into a SearchResponse."""
        raw_records = data.get("records", [])
        return SearchResponse(
            results=[_record_to_search_result(record) for record in raw_records],
            query=data.get("query", "") or query,
        )


def _record_to_search_result(record: Dict[str, Any]) -> SearchResult:
    """
    Convert a V4 nested ``{segment: {...}, score: ...}`` record into a
    ``SearchResult``. Falls back to legacy flat keys when nested segment is
    absent, so the helper works both before and after upstream migration.
    """
    segment = record.get("segment") or {}
    score = float(record.get("score", segment.pop("score", 0.0)))
    # Fallback keys (e.g. when ``segment`` is empty but the record itself
    # carries fields) allow the helper to degrade gracefully during migration.
    source = segment if segment else record
    return SearchResult(
        content=source.get("content", ""),
        score=score,
        knowledge_base_id=source.get("knowledge_base_id", source.get("kb_id", "")),
        knowledge_base_name=source.get("knowledge_base_name", source.get("kb_name", "")),
        document_id=source.get("document_id", ""),
        document_name=source.get("document_name", ""),
        id=source.get("id", source.get("segment_id", "")),
        position=int(source.get("position", 0)),
        tokens=int(source.get("tokens", 0)),
        keywords=source.get("keywords") or [],
        index_node_id=source.get("index_node_id", ""),
        hit_count=int(source.get("hit_count", 0)),
        enabled=bool(source.get("enabled", True)),
        image_url=source.get("image_url", ""),
        table_data=source.get("table_data") or {},
    )
