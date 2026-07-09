"""
ExternalKnowledgeSearchTool

SDK-level tool for searching knowledge bases via registered adapters.

The search client is injected at runtime by create_agent_info.py.  Two client
implementations are supported:

  * ``DispatcherKBClient`` (default) — in-process client that delegates directly
    to ``ExternalKnowledgeBaseService.retrieve()``.  No HTTP hop.  Works for
    both local (LocalKBAdapter → ElasticSearch) and external adapters
    (DifyAdapter / AIDPAdapter → platform HTTP).

  * ``DispatcherKBClient`` — process-local call to dispatcher_kb_client.
    Kept for backward compatibility; no longer injected by default.

The tool never touches the DB or Docker directly.
"""
import json
import logging
from typing import Any, Dict, List, Optional

from pydantic import Field
from pydantic.fields import FieldInfo
from smolagents.tools import Tool

from ..knowledge_base import (
    EmbeddingModelConfig,
    SearchRequest,
    SearchResponse,
)
from ..utils.constants import RERANK_OVERSEARCH_MULTIPLIER
from ..utils.observer import MessageObserver, ProcessType
from ..utils.tools_common_message import (
    SearchResultTextMessage,
    ToolCategory,
    ToolSign,
    TOOL_SIGN_MAPPING,
)

logger = logging.getLogger("external_kb_search_tool")


def _unwrap_field_info(value):
    """Resolve a value that may be wrapped in a Pydantic FieldInfo."""
    if isinstance(value, FieldInfo):
        if value.default_factory is not None:
            return value.default_factory()
        return value.default
    return value


class ExternalKnowledgeSearchTool(Tool):
    """
    Search knowledge bases via a registered adapter.

    The search client is injected by ``create_agent_info.py`` — typically a
    ``DispatcherKBClient`` that calls the adapter in-process (no HTTP hop).
    Supports both local (LocalKBAdapter) and external (Dify, AIDP, etc.)
    platforms transparently.
    """

    name = "external_kb_search"
    description = (
        "Performs a knowledge base search on local or external platforms via a registered adapter. "
        "Use this tool when users ask questions that require searching knowledge stored in "
        "the local knowledge base or external systems such as Dify, RAGFlow, AIDP, or other "
        "connected knowledge platforms. "
        "Returns the most relevant document segments ranked by similarity score."
    )
    description_zh = "通过已注册的适配器在知识库中执行检索，返回最相关的文档片段。支持本地和外部知识库。"

    inputs = {
        "query": {
            "type": "string",
            "description": "The search query to perform.",
            "description_zh": "要执行的搜索查询词",
        }
    }
    output_type = "string"
    category = ToolCategory.SEARCH.value
    # Use next available letter after existing signs; "k" is free
    tool_sign = "k"

    def __init__(
        self,
        adapter_id: int = Field(default=None, description="Adapter ID from external_kb_adapter_t"),
        kb_ids: str = Field(default=None, description="JSON string array of KB IDs to search"),
        kb_display_names: str = Field(
            default=None,
            description="JSON string array of KB display names (for LLM prompt context)",
        ),
        kb_refs: str = Field(
            default="[]",
            description='JSON string array of {adapter_id, kb_id, display_name} refs',
        ),
        top_k: int = Field(default=5, description="Maximum number of results to return"),
        search_mode: str = Field(
            default="hybrid",
            description="Search mode: hybrid / semantic / keyword",
        ),
        score_threshold: float = Field(default=0.0, description="Minimum similarity score threshold"),
        rerank: bool = Field(default=False, description="Whether to enable reranking"),
        observer: MessageObserver = Field(default=None, exclude=True),
        client: Optional[Any] = Field(default=None, exclude=True),
        embedding_model_config: EmbeddingModelConfig = Field(default=None, exclude=True),
    ):
        super().__init__()
        raw_kb_refs = _unwrap_field_info(kb_refs)
        if isinstance(raw_kb_refs, str):
            raw_kb_refs = json.loads(raw_kb_refs) if raw_kb_refs else []

        if raw_kb_refs:
            self.kb_refs: List[dict] = raw_kb_refs
            self.adapter_id = None
            self.kb_ids: List[str] = []
            self.kb_display_names: List[str] = []
        else:
            adp = _unwrap_field_info(adapter_id)
            raw_old_ids = _unwrap_field_info(kb_ids)
            old_ids = json.loads(raw_old_ids) if isinstance(raw_old_ids, str) else (raw_old_ids or [])
            raw_names = _unwrap_field_info(kb_display_names)
            old_names = json.loads(raw_names) if isinstance(raw_names, str) else (raw_names or [])

            self.adapter_id = adp
            self.kb_ids = old_ids
            self.kb_display_names = old_names
            self.kb_refs = [
                {"adapter_id": adp, "kb_id": kb_id, "display_name": old_names[i] if i < len(old_names) else kb_id}
                for i, kb_id in enumerate(old_ids)
            ]

        self.top_k = _unwrap_field_info(top_k)
        self.search_mode = _unwrap_field_info(search_mode)
        self.score_threshold = _unwrap_field_info(score_threshold)
        self.rerank = _unwrap_field_info(rerank)
        self.observer = _unwrap_field_info(observer)
        self.client: Optional[Any] = _unwrap_field_info(client)
        self.embedding_model_config: Optional[EmbeddingModelConfig] = _unwrap_field_info(
            embedding_model_config
        )
        self.record_ops = 1
        self.running_prompt_zh = "知识库检索中..."
        self.running_prompt_en = "Searching knowledge base..."

    # ------------------------------------------------------------------
    # search_mode → V4 search_method mapping
    # ------------------------------------------------------------------

    _SEARCH_MODE_MAP = {
        "hybrid": "hybrid_search",
        "semantic": "semantic_search",
        "keyword": "keyword_search",
        # accept V4 names directly too
        "hybrid_search": "hybrid_search",
        "semantic_search": "semantic_search",
        "keyword_search": "keyword_search",
    }

    def _to_v4_method(self, mode: str) -> str:
        return self._SEARCH_MODE_MAP.get(mode, "hybrid_search")

    # ------------------------------------------------------------------
    # Tool entry point
    # ------------------------------------------------------------------

    def forward(self, query: str) -> str:
        if not self.client:
            raise RuntimeError(
                "Search client not injected into ExternalKnowledgeSearchTool. "
                "Ensure create_agent_info.py sets tool_config.metadata['client']."
            )
        if not self.kb_refs:
            return json.dumps(
                "No external knowledge base selected. No relevant information found.",
                ensure_ascii=False,
            )

        self._notify_search_start(query)

        effective_top_k = self.top_k
        if self.rerank:
            effective_top_k = effective_top_k * RERANK_OVERSEARCH_MULTIPLIER

        request = SearchRequest(
            query=query,
            top_k=effective_top_k,
            search_mode=self._to_v4_method(self.search_mode),
            score_threshold=self.score_threshold,
            rerank=self.rerank,
            filters={},
        )

        logger.info(
            "ExternalKnowledgeSearchTool: query=%r kb_refs=%s top_k=%d mode=%s",
            query,
            self.kb_refs,
            effective_top_k,
            request.search_mode,
        )

        try:
            response: SearchResponse = self.client.retrieve_across(self.kb_refs, request)
        except Exception as exc:
            logger.error("ExternalKnowledgeSearchTool: retrieve_across failed: %s", exc, exc_info=True)
            raise RuntimeError(f"External KB search failed: {exc}") from exc

        if not response.results:
            raise Exception("No results found! Try a less restrictive/shorter query.")

        search_results_json, search_results_return = self._build_results(response)
        self.record_ops += len(search_results_return)
        self._publish_results(search_results_json)

        return json.dumps(search_results_return, ensure_ascii=False)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _notify_search_start(self, query: str) -> None:
        if not self.observer:
            return
        running_prompt = (
            self.running_prompt_zh
            if getattr(self.observer, "lang", "en") == "zh"
            else self.running_prompt_en
        )
        self.observer.add_message("", ProcessType.TOOL, running_prompt)
        card_content = [{"icon": "search", "text": query}]
        self.observer.add_message("", ProcessType.CARD, json.dumps(card_content, ensure_ascii=False))

    def _build_results(self, response: SearchResponse):
        search_results_json = []
        search_results_return = []

        # Build a kb_id → adapter_id lookup from self.kb_refs so we can
        # resolve the correct adapter for lazy download URL generation.
        kb_to_adapter: Dict[str, int] = {
            ref["kb_id"]: int(ref["adapter_id"])
            for ref in (self.kb_refs or [])
        }

        for idx, result in enumerate(response.results):
            msg = SearchResultTextMessage(
                # Use spec field ``document_name`` for display; downstream
                # consumers (taskWindow.tsx, chatRightPanel.tsx) will use it as
                # the title/filename when no richer metadata is available.
                title=result.document_name,
                url="",  # No direct-URL in the standard spec; download goes through GET /download-url lazily.
                text=result.content,
                filename=result.document_name,
                score=result.score,
                cite_index=self.record_ops + idx,
                search_type=self.name,
                tool_sign=self.tool_sign,
                source_type="external",
                # Spec-based lazy download refs — the frontend calls
                # GET /adapters/{adapter_id}/knowledge-bases/{kb_id}/documents/{doc_id}/download-url
                # when the user clicks download.
                adapter_id=kb_to_adapter.get(result.knowledge_base_id, self.adapter_id),
                knowledge_base_id=result.knowledge_base_id,
                document_id=result.document_id,
            )
            search_results_json.append(msg.to_dict())
            search_results_return.append(msg.to_model_dict())

        return search_results_json, search_results_return

    def _publish_results(self, search_results_json: list) -> None:
        if not self.observer:
            return
        self.observer.add_message(
            "", ProcessType.SEARCH_CONTENT, json.dumps(search_results_json, ensure_ascii=False)
        )
