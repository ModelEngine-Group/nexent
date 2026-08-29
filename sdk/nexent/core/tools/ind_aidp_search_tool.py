"""Independent AIDP FusionSearch tool.

This tool deliberately owns its endpoint, credential, and default knowledge-base scope.
It does not participate in Nexent's managed AIDP permissions or conversation
knowledge-scope selection.
"""

import json
import logging
import re
import time
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urljoin, urlparse

import httpx
from pydantic import Field
from pydantic.fields import FieldInfo
from smolagents.tools import Tool

from ..utils.observer import MessageObserver, ProcessType
from ..utils.tools_common_message import SearchResultTextMessage, ToolCategory, ToolSign
from ...utils.http_client_manager import http_client_manager

logger = logging.getLogger("ind_aidp_search_tool")

_VALID_SEARCH_METHODS = {"hybrid_search", "vector_search", "full_text_search"}
_VALID_RERANK_MODES = {"performance", "high_accuracy"}
_RETRY_STATUSES = {502, 503, 504}
_MAX_ATTEMPTS = 3
_MAX_KDS = 10
_HTML_IMAGE_TAG_PATTERN = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
_IMAGE_MARKER_PATH = "/__aidp_image__/"


class IndependentAidpSearchError(RuntimeError):
    """Raised when independent AIDP retrieval cannot complete."""


def _field_default(value: Any, fallback: Any) -> Any:
    if isinstance(value, FieldInfo):
        return fallback if value.default is ... else value.default
    return fallback if value is None else value


def _parse_kds_list(value: Any) -> List[str]:
    try:
        parsed = json.loads(value) if isinstance(value, str) else value
    except json.JSONDecodeError as exc:
        raise ValueError(f"kds_list must be a valid JSON array: {exc}") from exc
    if not isinstance(parsed, list) or not 1 <= len(parsed) <= _MAX_KDS:
        raise ValueError(f"kds_list must contain 1-{_MAX_KDS} knowledge base IDs")
    result = [str(item).strip() for item in parsed]
    if any(not item for item in result):
        raise ValueError("kds_list cannot contain empty knowledge base IDs")
    return result


def _validate_base_url(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("server_url is required and must be a non-empty string")
    normalized = value.strip().rstrip("/")
    parsed = urlparse(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("server_url must be an absolute HTTP or HTTPS URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("server_url cannot contain credentials, query parameters, or a fragment")
    return normalized


class IndependentAidpSearchTool(Tool):
    """Search an independently configured AIDP knowledge-base scope."""

    name = "ind_aidp_search"
    description = (
        "Searches independently configured AIDP knowledge bases with FusionSearch. "
        "The configured knowledge bases are the default scope; callers may provide a "
        "different kds_list for one invocation. Image results include safe image markers; copy a relevant marker "
        "unchanged into the final answer and never invent or expose an AIDP image URL."
    )
    description_zh = (
        "通过独立配置的 AIDP FusionSearch 检索知识库。工具配置提供默认知识库范围，"
        "每次调用也可以传入不同的 kds_list。相关图片需原样引用结果中的安全图片标记。"
    )
    inputs = {
        "query": {
            "type": "string",
            "description": "The search query string.",
            "description_zh": "搜索查询词",
        },
        "kds_list": {
            "type": "array",
            "description": (
                "Optional knowledge base IDs for this call. When omitted, the "
                "knowledge bases configured on the tool are used."
            ),
            "description_zh": "本次调用使用的知识库 ID；不传时使用工具配置中的知识库",
            "nullable": True,
        },
    }
    init_param_descriptions = {
        "server_url": {
            "description": "Independent AIDP API base URL",
            "description_zh": "独立 AIDP API 服务地址",
        },
        "api_key": {
            "description": "Independent AIDP API key",
            "description_zh": "独立 AIDP API 密钥",
        },
        "tenant_id": {
            "description": "AIDP tenant identifier used in API paths",
            "description_zh": "AIDP API 路径中的租户标识",
        },
        "kds_list": {
            "description": "Knowledge base IDs fixed for this tool instance",
            "description_zh": "此工具实例固定检索的知识库 ID 列表",
        },
        "search_method": {"description": "FusionSearch method", "description_zh": "检索方式"},
        "reranking_enable": {"description": "Enable reranking", "description_zh": "是否启用重排"},
        "reranking_mode": {"description": "Reranking mode", "description_zh": "重排模式"},
        "rewrite_enable": {"description": "Enable query rewrite", "description_zh": "是否启用查询改写"},
        "related_search_enable": {"description": "Enable related search", "description_zh": "是否启用关联检索"},
        "score_threshold": {"description": "Similarity threshold (0-1)", "description_zh": "相似度阈值（0-1）"},
        "top_k": {"description": "Number of results (1-100)", "description_zh": "返回结果数量（1-100）"},
        "multi_modal": {"description": "Return image/table chunks", "description_zh": "是否返回图片和表格块"},
    }
    output_type = "string"
    category = ToolCategory.SEARCH.value
    tool_sign = ToolSign.INDEPENDENT_AIDP_SEARCH.value

    def __init__(
        self,
        server_url: str = Field(description="Independent AIDP API base URL"),
        api_key: str = Field(description="Independent AIDP API key"),
        tenant_id: str = Field(default="aidp", description="AIDP tenant identifier"),
        kds_list: List[str] = Field(default_factory=list, description="Knowledge base IDs"),
        search_method: str = Field(default="hybrid_search", description="Search method"),
        reranking_enable: bool = Field(default=True, description="Enable reranking"),
        reranking_mode: str = Field(default="performance", description="Reranking mode"),
        rewrite_enable: bool = Field(default=False, description="Enable query rewrite"),
        related_search_enable: bool = Field(default=False, description="Enable related search"),
        score_threshold: float = Field(default=0.0, description="Score threshold", ge=0.0, le=1.0),
        top_k: int = Field(default=10, description="Top K results", ge=1, le=100),
        multi_modal: bool = Field(default=True, description="Return multimodal chunks"),
        observer: MessageObserver = Field(default=None, exclude=True),
        image_url_builder: Optional[Callable[[str], str]] = Field(default=None, exclude=True),
    ):
        super().__init__()
        self.base_url = _validate_base_url(server_url)
        if not isinstance(api_key, str) or not api_key.strip():
            raise ValueError("api_key is required and must be a non-empty string")
        resolved_tenant_id = _field_default(tenant_id, "aidp")
        if not isinstance(resolved_tenant_id, str) or not resolved_tenant_id.strip():
            raise ValueError("tenant_id is required and must be a non-empty string")
        self.api_key = api_key.strip()
        self.tenant_id = resolved_tenant_id.strip()
        self.kds_list = _parse_kds_list(kds_list)

        self.search_method = _field_default(search_method, "hybrid_search")
        if self.search_method not in _VALID_SEARCH_METHODS:
            raise ValueError(f"search_method must be one of {sorted(_VALID_SEARCH_METHODS)}")
        self.reranking_mode = _field_default(reranking_mode, "performance")
        if self.reranking_mode not in _VALID_RERANK_MODES:
            raise ValueError(f"reranking_mode must be one of {sorted(_VALID_RERANK_MODES)}")
        self.reranking_enable = bool(_field_default(reranking_enable, True))
        self.rewrite_enable = bool(_field_default(rewrite_enable, False))
        self.related_search_enable = bool(_field_default(related_search_enable, False))
        self.score_threshold = max(0.0, min(float(_field_default(score_threshold, 0.0)), 1.0))
        self.top_k = max(1, min(int(_field_default(top_k, 10)), 100))
        self.multi_modal = bool(_field_default(multi_modal, True))
        self.observer = _field_default(observer, None)
        self.image_url_builder = _field_default(image_url_builder, None)
        self.record_ops = 1
        self._http_client = http_client_manager.get_sync_client(
            base_url=self.base_url,
            timeout=60.0,
            verify_ssl=False,
        )

    def _retrieve_url(self) -> str:
        return urljoin(
            self.base_url,
            f"/KnowledgeBase/Tenants/{self.tenant_id}/Retrieval/FusionSearch",
        )

    def _payload(self, query: str, kds_list: Optional[List[str]] = None) -> Dict[str, Any]:
        payload = {
            "query": query,
            "kds_list": kds_list if kds_list is not None else self.kds_list,
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

    def _execute_request(
        self, query: str, kds_list: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        response = None
        for attempt in range(_MAX_ATTEMPTS):
            response = self._http_client.post(
                self._retrieve_url(),
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=self._payload(query, kds_list),
            )
            if response.status_code not in _RETRY_STATUSES or attempt == _MAX_ATTEMPTS - 1:
                break
            time.sleep(0.5 * (2**attempt))
        if response is None:  # pragma: no cover - defensive
            raise IndependentAidpSearchError("AIDP request was not sent")
        try:
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPStatusError as exc:
            raise IndependentAidpSearchError(
                f"AIDP FusionSearch returned HTTP {response.status_code}"
            ) from exc
        except ValueError as exc:
            raise IndependentAidpSearchError("AIDP returned invalid JSON") from exc
        if not isinstance(data, dict) or not isinstance(data.get("result"), list):
            raise IndependentAidpSearchError("AIDP response field 'result' must be a list")
        return data["result"]

    def _emit_running_prompt(self, query: str) -> None:
        if self.observer:
            card = [{"icon": "search", "text": query}]
            self.observer.add_message("", ProcessType.CARD, json.dumps(card, ensure_ascii=False))

    def _process_records(self, records: List[Dict[str, Any]]):
        ui_results: List[Dict[str, Any]] = []
        model_results: List[Dict[str, Any]] = []
        image_urls: List[str] = []
        for idx, chunk in enumerate(records[: self.top_k]):
            chunk_type = str(chunk.get("chunk_type") or "text")
            title = str(chunk.get("title") or "")
            file_url = str(chunk.get("file_url") or "")
            message = SearchResultTextMessage(
                title=title,
                text=str(chunk.get("text") or ""),
                source_type="file",
                url=file_url,
                filename=title,
                score=str(chunk.get("score")) if chunk.get("score") is not None else None,
                score_details={
                    "chunk_id": chunk.get("id"),
                    "chunk_type": chunk_type,
                    "pages": chunk.get("pages", []),
                    "file_url": file_url,
                    "metadata": chunk.get("metadata", {}),
                },
                cite_index=self.record_ops + idx,
                search_type=self.name,
                tool_sign=self.tool_sign,
            )
            ui_result = message.to_dict()
            ui_result["text"] = _HTML_IMAGE_TAG_PATTERN.sub("", ui_result["text"])
            model_result = message.to_model_dict()
            model_result["text"] = _HTML_IMAGE_TAG_PATTERN.sub("", model_result["text"])
            if chunk_type == "image" and file_url and callable(self.image_url_builder):
                try:
                    proxy_url = self.image_url_builder(file_url)
                except Exception as exc:  # pragma: no cover - backend callback boundary
                    logger.warning("Failed to build independent AIDP image proxy URL: %s", exc)
                    proxy_url = ""
                if proxy_url:
                    image_key = f"{message.tool_sign}{message.cite_index}"
                    marker = f"![AIDP image]({_IMAGE_MARKER_PATH}{image_key})"
                    ui_result["image_key"] = image_key
                    model_result["text"] += (
                        f"\n\nImage marker: {marker}. Copy this marker unchanged into "
                        "the final answer immediately after the paragraph it illustrates."
                    )
                    image_urls.append(proxy_url)
            ui_results.append(ui_result)
            model_results.append(model_result)
        return ui_results, model_results, image_urls

    def _emit_results(self, ui_results: List[Dict[str, Any]], image_urls: List[str]) -> None:
        if not self.observer:
            return
        self.observer.add_message(
            "", ProcessType.SEARCH_CONTENT, json.dumps(ui_results, ensure_ascii=False)
        )
        if image_urls:
            self.observer.add_message(
                "",
                ProcessType.PICTURE_WEB,
                json.dumps({"images_url": image_urls}, ensure_ascii=False),
            )

    def forward(self, query: str, kds_list: Optional[List[str]] = None) -> str:
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query is required and must be a non-empty string")
        search_kds_list = self.kds_list if kds_list is None else _parse_kds_list(kds_list)
        normalized_query = query.strip()
        self._emit_running_prompt(normalized_query)
        try:
            records = self._execute_request(normalized_query, search_kds_list)
        except httpx.HTTPError as exc:
            raise IndependentAidpSearchError(f"AIDP HTTP error: {exc}") from exc
        if not records:
            return json.dumps(
                "No relevant information was found in the configured AIDP knowledge bases.",
                ensure_ascii=False,
            )
        ui_results, model_results, image_urls = self._process_records(records)
        self.record_ops += len(model_results)
        self._emit_results(ui_results, image_urls)
        return json.dumps(model_results, ensure_ascii=False)
