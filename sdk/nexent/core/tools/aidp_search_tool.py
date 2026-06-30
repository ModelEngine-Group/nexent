"""
AIDP Search Tool
Performs multimodal knowledge base retrieval via the AIDP FusionSearch API.
Supports hybrid, vector, and full-text search with optional reranking.
Dual-channel output: all chunks via SEARCH_CONTENT, image file_urls via PICTURE_WEB.
"""
import json
import logging
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

import httpx
from pydantic import Field
from pydantic.fields import FieldInfo
from smolagents.tools import Tool

from ..utils.observer import MessageObserver, ProcessType
from ..utils.tools_common_message import SearchResultTextMessage, ToolCategory, ToolSign
from ...utils.http_client_manager import http_client_manager

logger = logging.getLogger("aidp_search_tool")

_LIST_PATH = "/KnowledgeBase/Tenants/aidp/KnowledgeBases"
_RETRIEVE_PATH = "/KnowledgeBase/Tenants/aidp/Retrieval/FusionSearch"

_VALID_SEARCH_METHODS = {"hybrid_search", "vector_search", "full_text_search"}
_VALID_RERANK_MODES = {"performance", "high_accuracy"}
_MAX_KDS = 10


class AidpSearchError(RuntimeError):
    """Raised when the AIDP search tool cannot complete a request."""


def _resolve_field_default(value: Any, fallback: Any) -> Any:
    if isinstance(value, FieldInfo):
        return fallback if value.default is ... else value.default
    return fallback if value is None else value


def _parse_kds_list(kds_list: str) -> List[str]:
    """Parse and validate the JSON-encoded knowledge base ID list."""
    try:
        parsed_kds = json.loads(kds_list) if isinstance(kds_list, str) else kds_list
    except json.JSONDecodeError as e:
        raise ValueError(f"kds_list must be a valid JSON array: {e}") from e
    if not isinstance(parsed_kds, list) or not (1 <= len(parsed_kds) <= _MAX_KDS):
        raise ValueError(f"kds_list must be a list of 1-{_MAX_KDS} knowledge base IDs")
    return [str(k) for k in parsed_kds]


def _coerce_choice(raw: str, valid: set, default: str, label: str) -> str:
    """Coerce ``raw`` to one of ``valid`` or fall back to ``default``."""
    value = raw or default
    if value not in valid:
        logger.warning("Invalid %s '%s', defaulting to %s", label, value, default)
        return default
    return value


class AidpSearchTool(Tool):
    name = "aidp_search"
    description = (
        "Performs a multimodal search on AIDP knowledge bases using FusionSearch. "
        "Returns text, table, and image chunks with dual-channel delivery: "
        "all chunks as SEARCH_CONTENT and image file_urls as PICTURE_WEB. "
        "Use when users ask about domain-specific knowledge stored in AIDP knowledge bases."
    )
    description_zh = (
        "通过 AIDP FusionSearch 对知识库进行多模态检索，返回文本、表格和图片块。"
        "双通道输出：所有块通过 SEARCH_CONTENT 发送，图片通过 PICTURE_WEB 发送。"
        "适用于询问 AIDP 知识库中存储的领域专业知识。"
    )

    inputs = {
        "query": {
            "type": "string",
            "description": "The search query string.",
            "description_zh": "搜索查询词",
        },
        "kds_list": {
            "type": "array",
            "description": "The list of knowledge base IDs (kds_id) to search. If not provided, uses the kds_list from tool configuration.",
            "description_zh": "要检索的知识库 ID 列表，如不提供则使用工具配置中的 kds_list",
            "nullable": True,
        },
    }

    init_param_descriptions = {
        "server_url": {
            "description": "AIDP API base URL (without trailing slash)",
            "description_zh": "AIDP API 服务地址",
        },
        "api_key": {
            "description": "AIDP API key (ak_...)",
            "description_zh": "AIDP API 密钥",
        },
        "kds_list": {
            "description": "JSON string array of knowledge base IDs (kds_id) to search",
            "description_zh": "要检索的知识库 ID 列表",
        },
        "search_method": {
            "description": "Search method: hybrid_search, vector_search, full_text_search",
            "description_zh": (
                "搜索方法：hybrid_search（融合检索）/"
                "vector_search（向量检索）/"
                "full_text_search（全文检索）"
            ),
        },
        "reranking_enable": {
            "description": "Whether to enable reranking",
            "description_zh": "是否启用重排序",
        },
        "reranking_mode": {
            "description": "Reranking mode: performance or high_accuracy",
            "description_zh": "重排序模式：performance/high_accuracy",
        },
        "rewrite_enable": {
            "description": "Whether to enable query rewrite",
            "description_zh": "是否启用黑话改写",
        },
        "related_search_enable": {
            "description": "Whether to enable related chunk retrieval",
            "description_zh": "是否启用关联 Chunk 检索",
        },
        "score_threshold": {
            "description": "Similarity threshold (0-1)",
            "description_zh": "相似度阈值（0-1）",
        },
        "top_k": {
            "description": "Number of results to return (1-100)",
            "description_zh": "返回结果数量（1-100）",
        },
        "multi_modal": {
            "description": "Whether to return multimodal chunks (image/table)",
            "description_zh": "是否返回多模态块（图片/表格）",
        },
    }

    output_type = "string"
    category = ToolCategory.SEARCH.value
    tool_sign = ToolSign.AIDP_SEARCH.value

    def __init__(
        self,
        server_url: str = Field(description="AIDP API base URL"),
        api_key: str = Field(description="AIDP API key"),
        kds_list: str = Field(description="JSON string array of knowledge base IDs"),
        search_method: str = Field(default="hybrid_search", description="Search method"),
        reranking_enable: bool = Field(default=False, description="Enable reranking"),
        reranking_mode: str = Field(default="performance", description="Reranking mode"),
        rewrite_enable: bool = Field(default=False, description="Enable query rewrite"),
        related_search_enable: bool = Field(default=False, description="Enable related search"),
        score_threshold: float = Field(default=0.0, description="Score threshold 0-1"),
        top_k: int = Field(default=10, description="Top K results"),
        multi_modal: bool = Field(default=True, description="Return multimodal chunks"),
        observer: MessageObserver = Field(default=None, exclude=True),
    ):
        super().__init__()

        if not server_url or not isinstance(server_url, str):
            raise ValueError("server_url is required and must be a non-empty string")
        if not api_key or not isinstance(api_key, str):
            raise ValueError("api_key is required and must be a non-empty string")

        self.kds_list: List[str] = _parse_kds_list(kds_list)
        self.base_url = server_url.rstrip("/")
        self.api_key = api_key
        self.search_method = _coerce_choice(
            search_method, _VALID_SEARCH_METHODS, "hybrid_search", "search_method"
        )
        self.reranking_mode = _coerce_choice(
            reranking_mode, _VALID_RERANK_MODES, "performance", "reranking_mode"
        )
        self.reranking_enable = bool(_resolve_field_default(reranking_enable, False))
        self.rewrite_enable = bool(_resolve_field_default(rewrite_enable, False))
        self.related_search_enable = bool(_resolve_field_default(related_search_enable, False))
        resolved_score_threshold = _resolve_field_default(score_threshold, 0.0)
        resolved_top_k = _resolve_field_default(top_k, 10)
        resolved_multi_modal = _resolve_field_default(multi_modal, True)
        self.score_threshold = max(0.0, min(float(resolved_score_threshold), 1.0))
        self.top_k = max(1, min(int(resolved_top_k), 100))
        self.multi_modal = bool(resolved_multi_modal)
        self.observer = observer

        self._http_client = http_client_manager.get_sync_client(
            base_url=self.base_url,
            timeout=60.0,
            verify_ssl=False,
        )

        self.record_ops = 1
        self.running_prompt_zh = "AIDP 知识库检索中..."
        self.running_prompt_en = "Searching AIDP knowledge base..."

    def _build_retrieve_url(self) -> str:
        return urljoin(self.base_url, _RETRIEVE_PATH)

    def _build_retrieve_payload(self, query: str, kds_list: List[str]) -> Dict[str, Any]:
        payload = {
            "query": query,
            "kds_list": kds_list,
            "search_method": self.search_method,
            "reranking_enable": self.reranking_enable,
            "rewrite_enable": self.rewrite_enable,
            "related_search_enable": self.related_search_enable,
            "score_threshold": self.score_threshold,
            "top_k": self.top_k,
            "multi_modal": self.multi_modal,
        }
        if self.reranking_enable:
            payload["reranking_mode"] = self.reranking_mode
        return payload

    def _parse_response(self, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        records = data.get("result", [])
        if not isinstance(records, list):
            logger.error("Unexpected response format: result is not a list")
            raise ValueError("Invalid AIDP response: result field missing or not a list")
        return records

    def _emit_running_prompt(self, query: str) -> None:
        """Push the running prompt + query card to the observer if any."""
        if not self.observer:
            return
        prompt = (
            self.running_prompt_zh
            if self.observer.lang == "zh"
            else self.running_prompt_en
        )
        self.observer.add_message("", ProcessType.TOOL, prompt)
        card_content = [{"icon": "search", "text": query.strip()}]
        self.observer.add_message(
            "", ProcessType.CARD, json.dumps(card_content, ensure_ascii=False)
        )

    def _build_chunk_message(self, chunk: Dict[str, Any], idx: int):
        """Build a SearchResultTextMessage for a single record chunk."""
        chunk_type = str(chunk.get("chunk_type", "text") or "text")
        title = str(chunk.get("title") or "")
        text = str(chunk.get("text") or "")
        file_url = str(chunk.get("file_url") or "")
        chunk_id = chunk.get("id")
        score = chunk.get("score")
        pages = chunk.get("pages", [])
        metadata = chunk.get("metadata", {})
        return SearchResultTextMessage(
            title=title,
            text=text,
            source_type="file",
            url=file_url,
            filename=title,
            published_date="",
            score=str(score) if score is not None else None,
            score_details={
                "chunk_id": chunk_id,
                "chunk_type": chunk_type,
                "pages": pages,
                "file_url": file_url,
                "metadata": metadata,
            },
            cite_index=self.record_ops + idx,
            search_type=self.name,
            tool_sign=self.tool_sign,
        )

    def _process_records(self, records: List[Dict[str, Any]]):
        """Convert raw response records into dual-channel messages and return
        ``(search_results_return, images_url)``."""
        search_results_json: List[Dict[str, Any]] = []
        search_results_return: List[Dict[str, Any]] = []
        images_url: List[str] = []

        for idx, chunk in enumerate(records[: self.top_k]):
            msg = self._build_chunk_message(chunk, idx)
            search_results_json.append(msg.to_dict())
            search_results_return.append(msg.to_model_dict())
            chunk_type = str(chunk.get("chunk_type", "text") or "text")
            file_url = str(chunk.get("file_url") or "")
            if chunk_type == "image" and file_url:
                images_url.append(file_url)

        return search_results_json, search_results_return, images_url

    def _emit_results(self, search_results_json, images_url) -> None:
        """Forward the structured results to the observer if present."""
        if not self.observer:
            return
        self.observer.add_message(
            "",
            ProcessType.SEARCH_CONTENT,
            json.dumps(search_results_json, ensure_ascii=False),
        )
        if images_url:
            self.observer.add_message(
                "",
                ProcessType.PICTURE_WEB,
                json.dumps({"images_url": images_url}, ensure_ascii=False),
            )

    def _execute_request(self, query: str, kds_list: List[str]):
        """POST to the AIDP FusionSearch endpoint and return parsed records."""
        url = self._build_retrieve_url()
        payload = self._build_retrieve_payload(query.strip(), kds_list)
        resp = self._http_client.post(
            url,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            json=payload,
        )
        resp.raise_for_status()
        return self._parse_response(resp.json())

    def forward(
        self,
        query: str,
        kds_list: Optional[List[str]] = None,
    ) -> str:
        if not query or not query.strip():
            raise ValueError("query is required and must be a non-empty string")

        # Use kds_list from runtime parameters if provided, otherwise fall back to instance kds_list
        search_kds_list = self.kds_list
        if kds_list is not None and len(kds_list) > 0:
            search_kds_list = kds_list

        self._emit_running_prompt(query)

        logger.info(
            "AidpSearchTool called query='%s' kds_list=%s method=%s top_k=%d",
            query,
            search_kds_list,
            self.search_method,
            self.top_k,
        )

        if not search_kds_list:
            raise AidpSearchError(
                "No knowledge base selected. Please select at least one knowledge base."
            )

        try:
            records = self._execute_request(query, search_kds_list)
        except httpx.HTTPError as e:
            logger.exception("AIDP HTTP error: %s", e)
            raise AidpSearchError(f"AIDP HTTP error: {e}") from e
        except ValueError as e:
            logger.exception("AIDP search error: %s", e)
            raise AidpSearchError(f"AIDP search error: {e}") from e

        if not records:
            raise AidpSearchError(
                "AIDP search error: No results found! Try a less restrictive or shorter query."
            )

        search_results_json, search_results_return, images_url = self._process_records(records)
        self.record_ops += len(search_results_return)
        self._emit_results(search_results_json, images_url)
        return json.dumps(search_results_return, ensure_ascii=False)
