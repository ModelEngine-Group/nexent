"""
AIDP Search Tool
Performs multimodal knowledge base retrieval via the AIDP FusionSearch API.
Supports hybrid, vector, and full-text search with optional reranking.
"""
import json
import logging
import re
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

import httpx
from pydantic import Field
from pydantic.fields import FieldInfo
from smolagents.tools import Tool

from ...utils.observer import MessageObserver, ProcessType
from ...utils.tools_common_message import SearchResultTextMessage, ToolCategory, ToolSign
from ....utils.http_client_manager import http_client_manager

logger = logging.getLogger("aidp_search_tool")

_VALID_SEARCH_METHODS = {"hybrid_search", "vector_search", "full_text_search"}
_VALID_RERANK_MODES = {"performance", "high_accuracy"}
_MAX_KDS = 10

# Transient HTTP status codes that merit automatic retry. 502/503/504 per
# HTTP spec indicate the upstream server was temporarily unavailable; a
# short backoff and retry is the standard client-side mitigation. AIDP's
# FusionSearch endpoint is observed to return 503 intermittently (e.g. cold
# start or gateway-level instability), so this is the main consumer.
_AIDP_SEARCH_RETRY_STATUSES = {502, 503, 504}
_AIDP_SEARCH_MAX_ATTEMPTS = 3
_AIDP_SEARCH_RETRY_BACKOFF = (0.5, 1.5)  # seconds between retry 1 and 2
_HTML_IMAGE_TAG_PATTERN = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
_IMAGE_MARKER_PATH = "/__aidp_image__/"


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
    if not isinstance(parsed_kds, list) or len(parsed_kds) > _MAX_KDS:
        raise ValueError(f"kds_list must be a list of 0-{_MAX_KDS} knowledge base IDs")
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
    is_user_selectable: bool = False
    description = (
        "Performs a multimodal search on AIDP knowledge bases using FusionSearch. "
        "Returns text, table, and image chunks with title and text content. "
        "Image chunks include a safe Markdown image marker. When an image is relevant, "
        "copy that marker unchanged into the answer near the paragraph it illustrates; "
        "never invent or expose an image URL. "
        "Use when users ask about domain-specific knowledge stored in AIDP knowledge bases."
    )
    description_zh = (
        "通过 AIDP FusionSearch 对知识库进行多模态检索，返回文本、表格和图片块。"
        "每个块包含标题和文本内容。"
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
        "tenant_id": {
            "description": "AIDP tenant identifier used in API paths",
            "description_zh": "AIDP API 路径中的租户标识",
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
        server_url: str = Field(exclude=True, description="AIDP API base URL"),
        api_key: str = Field(exclude=True, description="AIDP API key"),
        tenant_id: str = Field(exclude=True, description="AIDP tenant identifier"),
        kds_name_to_id_map: dict = Field(
            default_factory=dict,
            exclude=True,
            description="Mapping from kds_name to kds_id for LLM parameter conversion",
        ),
        kds_list: str = Field(description="JSON string array of knowledge base IDs"),
        search_method: str = Field(default="hybrid_search", description="Search method"),
        reranking_enable: bool = Field(default=True, description="Enable reranking"),
        reranking_mode: str = Field(default="performance", description="Reranking mode"),
        rewrite_enable: bool = Field(default=False, description="Enable query rewrite"),
        related_search_enable: bool = Field(default=False, description="Enable related search"),
        score_threshold: float = Field(default=0.0, description="Score threshold 0-1", ge=0.0, le=1.0),
        top_k: int = Field(default=10, description="Top K results", ge=1, le=100),
        multi_modal: bool = Field(default=True, description="Return multimodal chunks"),
        observer: MessageObserver = Field(default=None, exclude=True),
    ):
        super().__init__()
        self.kds_list: List[str] = _parse_kds_list(kds_list)

        self.base_url = server_url.rstrip("/") if isinstance(server_url, str) else ""
        self.api_key = api_key if isinstance(api_key, str) else ""
        self.tenant_id = tenant_id.strip() if isinstance(tenant_id, str) else ""
        self.kds_name_to_id_map = kds_name_to_id_map

        if not self.base_url:
            raise ValueError("server_url is required and must be a non-empty string")
        if not self.api_key:
            raise ValueError("api_key is required and must be a non-empty string")
        if not self.tenant_id:
            raise ValueError("tenant_id is required and must be a non-empty string")
        self.search_method = _coerce_choice(
            search_method, _VALID_SEARCH_METHODS, "hybrid_search", "search_method"
        )
        self.reranking_mode = _coerce_choice(
            reranking_mode, _VALID_RERANK_MODES, "performance", "reranking_mode"
        )
        self.reranking_enable = bool(_resolve_field_default(reranking_enable, True))
        self.rewrite_enable = bool(_resolve_field_default(rewrite_enable, False))
        self.related_search_enable = bool(_resolve_field_default(related_search_enable, False))
        resolved_score_threshold = _resolve_field_default(score_threshold, 0.0)
        resolved_top_k = _resolve_field_default(top_k, 10)
        resolved_multi_modal = _resolve_field_default(multi_modal, True)
        self.score_threshold = max(0.0, min(float(resolved_score_threshold), 1.0))
        self.top_k = max(1, min(int(resolved_top_k), 100))
        self.multi_modal = bool(resolved_multi_modal)
        self.observer = observer
        # Runtime whitelist populated by the backend (create_agent_info).
        # When the whitelist has been explicitly installed (even as an empty
        # set), both the configured ``kds_list`` and any LLM-supplied
        # ``kds_list`` are intersected with this set so permission changes
        # take effect immediately, without ever touching the database.
        #
        # Two fields control filtering:
        #   * ``_whitelist_installed`` — True iff ``set_allowed_kds`` was
        #     called by the backend. False only in SDK unit tests or legacy
        #     code paths that never call it.
        #   * ``_allowed_kds_set``     — the actual set of permitted KB ids.
        #     An empty set means "user has access to nothing" and blocks
        #     all KBs. A non-empty set means "only these KBs".
        #
        # The distinction matters: previously an empty set was treated as
        # a no-op (preserving the SDK's unit-test mode), which meant a
        # user with zero KB permissions could still query any KB the LLM
        # passed. That was a privilege-escalation bug and is now fixed.
        self._allowed_kds_set: set[str] = set()
        self._whitelist_installed: bool = False

        self._http_client = http_client_manager.get_sync_client(
            base_url=self.base_url,
            timeout=60.0,
            verify_ssl=False,
        )

        self.record_ops = 1

    def _build_retrieve_url(self) -> str:
        path = f"/KnowledgeBase/Tenants/{self.tenant_id}/Retrieval/FusionSearch"
        return urljoin(self.base_url, path)

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
            ui_result = msg.to_dict()
            ui_result["text"] = _HTML_IMAGE_TAG_PATTERN.sub("", ui_result["text"])
            search_results_json.append(ui_result)
            result = msg.to_model_dict()
            # AIDP can embed relative ``/md_image/...`` tags in image and
            # text chunks alike. Never expose those tags to the LLM: they are
            # not valid Nexent URLs and the verified image is delivered via
            # the PICTURE_WEB observer channel instead.
            result["text"] = _HTML_IMAGE_TAG_PATTERN.sub("", result["text"])
            chunk_type = str(chunk.get("chunk_type", "text") or "text")
            file_url = str(chunk.get("file_url") or "")
            # Images require a fully-qualified URL that the image proxy can
            # fetch with a Bearer token; text/table chunks keep their raw
            # value because they aren't rendered as <img> tags.
            if chunk_type == "image" and file_url:
                full_url = self._build_image_url(file_url)
                # Do NOT expose the image URL to the LLM: the URL is an
                # AIDP endpoint that requires a Bearer token, so if the
                # model embeds it in markdown the browser will GET it
                # without credentials and get a 401. Images are delivered
                # only via the PICTURE_WEB observer channel, which goes
                # through image_service proxy (adds Bearer).
                images_url.append(full_url)
                image_key = f"{msg.tool_sign}{msg.cite_index}"
                # Keep the marker syntax independent of document titles, which
                # may contain Markdown delimiter characters such as `]`.
                image_marker = f"![AIDP image]({_IMAGE_MARKER_PATH}{image_key})"
                ui_result["image_key"] = image_key
                result["text"] = (
                    f"{result['text']}\n\n"
                    f"Image marker: {image_marker}. Copy this marker unchanged into "
                    "the final answer immediately after the paragraph that this image illustrates."
                )
            search_results_return.append(result)

        return search_results_json, search_results_return, images_url

    def _emit_results(self, search_results_json, images_url) -> None:
        """Forward the structured results to the observer if present."""
        logger.info(
            "AIDP _emit_results: %d chunks total, %d with image URL",
            len(search_results_json), len(images_url),
        )
        if not self.observer:
            logger.warning("AIDP _emit_results: observer is None, skipping emit")
            return
        self.observer.add_message(
            "",
            ProcessType.SEARCH_CONTENT,
            json.dumps(search_results_json, ensure_ascii=False),
        )
        if images_url:
            logger.info(
                "AIDP PICTURE_WEB: sending %d image URLs: %s",
                len(images_url),
                images_url,
            )
            self.observer.add_message(
                "",
                ProcessType.PICTURE_WEB,
                json.dumps({"images_url": images_url}, ensure_ascii=False),
            )

    def _execute_request(self, query: str, kds_list: List[str]):
        """POST to the AIDP FusionSearch endpoint and return parsed records.

        Retries automatically on transient HTTP statuses (502 / 503 / 504)
        with a short exponential backoff. These are the only retryable
        failures we handle — 4xx errors and other 5xx responses are raised
        immediately. Retrying 503 is the most valuable case in practice:
        AIDP's FusionSearch endpoint has been observed to return 503 on the
        first invocation after a period of inactivity and succeed on a
        quick retry.

        On a final 503 error (all retries exhausted) we surface a
        user-friendly message that explains the likely cause (AIDP
        retrieval service temporarily unavailable / KB still warming up)
        rather than the raw httpx exception string.
        """
        url = self._build_retrieve_url()
        payload = self._build_retrieve_payload(query.strip(), kds_list)

        last_status_error: Optional[httpx.HTTPStatusError] = None
        for attempt in range(1, _AIDP_SEARCH_MAX_ATTEMPTS + 1):
            resp = self._http_client.post(
                url,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.api_key}",
                },
                json=payload,
            )
            if resp.status_code not in _AIDP_SEARCH_RETRY_STATUSES:
                # Non-retryable: raise_for_status will either succeed (2xx)
                # or throw immediately for 4xx / other 5xx.
                break

            last_status_error = httpx.HTTPStatusError(
                message=f"{resp.status_code} {resp.reason_phrase}",
                request=resp.request,
                response=resp,
            )
            if attempt >= _AIDP_SEARCH_MAX_ATTEMPTS:
                break
            wait = _AIDP_SEARCH_RETRY_BACKOFF[0] * (2 ** (attempt - 1))
            logger.warning(
                "AIDP FusionSearch returned %d on attempt %d/%d for query=%r, "
                "retrying in %.1fs",
                resp.status_code, attempt, _AIDP_SEARCH_MAX_ATTEMPTS,
                query[:50], wait,
            )
            time.sleep(wait)

        # If we exhausted all retries on a transient status, surface it as
        # a domain-level AidpSearchError with a clearer message.
        if last_status_error is not None and resp.status_code in _AIDP_SEARCH_RETRY_STATUSES:
            if resp.status_code == 503:
                # AIDP 503 is almost always caused by the retrieval service
                # being temporarily down, which in turn is almost always
                # caused by the selected KB(s) having no indexed content
                # yet (empty or still processing).
                raise AidpSearchError(
                    "AIDP retrieval service is temporarily unavailable (HTTP 503). "
                    "This usually means the selected knowledge base(s) have no "
                    "searchable content yet — upload at least one document to "
                    "each KB and wait for indexing to finish, then retry. "
                    "If the problem persists, contact the AIDP operator."
                )
            raise AidpSearchError(
                f"AIDP retrieval service returned HTTP {resp.status_code} "
                f"after {_AIDP_SEARCH_MAX_ATTEMPTS} attempts. Please retry later."
            )

        resp.raise_for_status()
        return self._parse_response(resp.json())

    def _build_image_url(self, file_url: str) -> str:
        """Build a fully-qualified image URL from the relative ``file_url``
        returned in an AIDP FusionSearch chunk.

        AIDP returns ``file_url`` as a path relative to the KnowledgeBases
        prefix on the AIDP host (e.g. ``"aidp-kb-1/data/img.png"``). The
        image must be fetched via GET with a Bearer token, so we construct
        the full URL as::

            {base_url}/KnowledgeBase/Tenants/{TenantId}/KnowledgeBases/{file_url}

        If ``file_url`` is already an absolute ``http``/``https`` URL it is
        returned unchanged (defensive: avoids double-prefixing when a
        future AIDP version starts returning full URLs).
        """
        if not file_url:
            return ""
        if file_url.startswith("http://") or file_url.startswith("https://"):
            return file_url
        cleaned = file_url.lstrip("/")
        list_path = f"/KnowledgeBase/Tenants/{self.tenant_id}/KnowledgeBases"
        return f"{self.base_url}{list_path}/{cleaned}"

    def set_allowed_kds(self, allowed: Optional[List[str]]) -> None:
        """Install the runtime whitelist computed by the backend.

        Called once during agent setup so the tool never reaches a forbidden
        KB even if the LLM later crafts a ``kds_list`` that includes one.

        Semantics after v7.1:
          * ``allowed is None``  → whitelist is cleared and marked as NOT
            installed. The tool falls through to no-op filtering (legacy
            SDK unit-test compatibility).
          * ``allowed == []``    → whitelist is installed as an empty set.
            ``_filter_by_whitelist`` will block every KB. This is how the
            backend signals "user has access to nothing".
          * ``allowed`` non-empty → whitelist is installed with those ids.
            ``_filter_by_whitelist`` intersects input with the set.
        """
        if allowed is None:
            self._allowed_kds_set = set()
            self._whitelist_installed = False
            logger.debug("AidpSearchTool whitelist cleared (not installed)")
        else:
            self._allowed_kds_set = {str(k) for k in allowed if k}
            self._whitelist_installed = True
            logger.info(
                "AidpSearchTool whitelist installed with %d permitted KB(s)",
                len(self._allowed_kds_set),
            )

    def _filter_by_whitelist(self, kds: List[str]) -> List[str]:
        """Intersect ``kds`` with the runtime whitelist, preserving order.

        No-op iff ``set_allowed_kds`` was never called (whitelist not
        installed). Once installed — even as an empty set — filtering is
        strict and blocks every id that isn't in the set.
        """
        if not self._whitelist_installed:
            return list(kds)
        return [k for k in kds if k in self._allowed_kds_set]

    def _convert_to_kds_ids(self, names: List[str]) -> List[str]:
        """Convert kds_name (display name) to kds_id if a mapping exists.

        When the LLM passes a kds_name instead of the actual kds_id in the
        ``kds_list`` parameter, this method resolves it to the real ID so
        that downstream API calls receive valid identifiers.

        Args:
            names: List of values that could be either kds_name or kds_id.

        Returns:
            List of resolved kds_id values. Unknown names pass through unchanged.
        """
        kds_map = self.kds_name_to_id_map
        if isinstance(kds_map, FieldInfo):
            if kds_map.default_factory is not None:
                kds_map = kds_map.default_factory()
            else:
                kds_map = kds_map.default
        if not kds_map:
            return names

        converted_names = []
        for name in names:
            if name in kds_map:
                converted_names.append(kds_map[name])
            else:
                converted_names.append(name)
        return converted_names

    def forward(
        self,
        query: str,
        kds_list: Optional[List[str]] = None,
    ) -> str:
        if not query or not query.strip():
            raise ValueError("query is required and must be a non-empty string")

        # Always intersect with the runtime whitelist, regardless of whether
        # the LLM passed a fresh ``kds_list`` or we fall back to the
        # configured value. ``_filter_by_whitelist`` is a no-op when no
        # whitelist has been installed (e.g. SDK unit tests), so it stays
        # safe to call from anywhere.
        base_kds = (
            kds_list
            if kds_list is not None and len(kds_list) > 0
            else self.kds_list
        )
        # Resolve kds_name (display name) to kds_id before permission
        # filtering so the whitelist operates on the real ID namespace.
        base_kds = self._convert_to_kds_ids(list(base_kds))
        search_kds_list = self._filter_by_whitelist(list(base_kds))

        self._emit_running_prompt(query)

        logger.info(
            "AidpSearchTool called query='%s' kds_list=%s method=%s top_k=%d",
            query,
            search_kds_list,
            self.search_method,
            self.top_k,
        )

        if not search_kds_list:
            # Permission denial is a valid tool observation, not a transport
            # failure. Returning it lets the agent produce a complete answer
            # while still preventing any request to the AIDP endpoint.
            return json.dumps(
                "No AIDP knowledge base is accessible within the selected "
                "conversation scope. The configured knowledge bases may have "
                "been removed or your access may have been revoked.",
                ensure_ascii=False,
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
            logger.info(
                "AIDP search returned no results for query '%s' in kds_list=%s",
                query,
                search_kds_list,
            )
            return json.dumps(
                "No relevant information was found in the selected AIDP knowledge "
                "bases. Try a broader or shorter query, or explain that the selected "
                "scope does not contain enough evidence.",
                ensure_ascii=False,
            )

        search_results_json, search_results_return, images_url = self._process_records(records)
        self.record_ops += len(search_results_return)
        self._emit_results(search_results_json, images_url)
        return json.dumps(search_results_return, ensure_ascii=False)
