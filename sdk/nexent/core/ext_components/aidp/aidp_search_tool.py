# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""
AIDP Search Tool
Performs multimodal knowledge base retrieval via the AIDP FusionSearch API.
Supports vector, full-text, graph and combined retrieval with optional reranking.
"""
import json
import logging
import re
from typing import Any, Dict, List, Optional
from urllib.parse import quote, urljoin

from pydantic import Field
from pydantic.fields import FieldInfo
from smolagents.tools import Tool

from .constants import AIDP_SEARCH_TOOL_NAME

from ...utils.observer import MessageObserver, ProcessType
from ...utils.pydantic_utils import unwrap_field_info
from ...utils.tools_common_message import (
    SearchResultTextMessage,
    ToolCategory,
    ToolSign,
    build_knowledge_search_response,
    resolve_knowledge_search_scope,
)
from ....utils.http_client_manager import http_client_manager
from .retrieval_client import AidpRetrievalError, post_retrieval
from .retrieval_config import (
    ALL_CHANNELS,
    CONFIG_KEYS,
    DEFAULTS,
    active_channels,
    build_payload,
    resolve_config,
)
from . import metadata_filter as metadata_filter_rules


logger = logging.getLogger("aidp_search_tool")

AidpSearchError = AidpRetrievalError

_MAX_KDS = 10

_HTML_IMAGE_TAG_PATTERN = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
_IMAGE_MARKER_PATH = "/__aidp_image__/"


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


def _normalize_identity_value(value: Any) -> str:
    """Return a non-empty string identifier, or ``""`` for a missing value."""
    if not isinstance(value, str):
        return ""
    return value.strip()


def extract_aidp_file_identity(metadata: Any) -> tuple[str, str]:
    """Read the AIDP original-file locator from one hit's ``metadata``.

    AIDP returns both identifiers in ``metadata``; either one missing means the
    hit cannot address an original file, and nothing may be inferred from the
    filename, ``file_url`` or chunk id.
    """
    if not isinstance(metadata, dict):
        return "", ""
    kds_id = _normalize_identity_value(metadata.get("kds_id"))
    file_uuid = _normalize_identity_value(metadata.get("file_uuid"))
    if not kds_id or not file_uuid:
        return "", ""
    return kds_id, file_uuid


class AidpSearchTool(Tool):
    name = AIDP_SEARCH_TOOL_NAME
    is_user_selectable: bool = False
    description = (
        "Searches AIDP knowledge bases using configured vector, full-text, graph or combined retrieval. "
        "Returns text, table, and image chunks with title and text content. "
        "Image chunks include a safe Markdown image marker. When an image is relevant, "
        "copy that marker unchanged into the answer near the paragraph it illustrates; "
        "never invent or expose an image URL. "
        "Use when users ask about domain-specific knowledge stored in AIDP knowledge bases."
    )
    description_zh = (
        "按已配置的向量、全文、图谱或组合方式检索 AIDP 知识库，返回可引用的文本、表格和图片结果。"
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
            "description_zh": "检索方式：向量、全文、图谱或使用竖线分隔的组合",
        },
        "reranking_enable": {
            "description": "Whether to enable reranking",
            "description_zh": "是否启用重排序",
        },
        "reranking_mode": {
            "description_zh": "重排策略：性能优先、精度优先或术语覆盖",
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
        "vector_candidates": {"description_zh": "向量初步检索条数；固定整数，1–500"},
        "full_text_candidates": {"description_zh": "全文初步检索条数；固定整数，1–500"},
        "hybrid_top_k": {"description_zh": "向量／全文部分返回上限；固定整数，最小为 1（0 会被 AIDP 拒绝），最终仍受总返回上限约束"},
        "graph_top_k": {"description_zh": "图谱返回上限；0 表示不单独限制，最终仍受总返回上限约束"},
        "vector_score_threshold": {"description_zh": "向量检索分数阈值，范围 0–1"},
        "full_text_score_threshold": {"description_zh": "全文检索分数阈值，范围 0–1"},
        "graph_score_threshold": {"description_zh": "图谱检索分数阈值，范围 0–1"},
        "graph_reranking_enable": {"description_zh": "图谱是否参与统一重排；固定布尔值"},
        "query_expansion_enable": {"description_zh": "是否启用查询扩展"},
        "ontology_enhance_enable": {
            "description": "Use the bound ontology's entities and relations to enhance retrieval",
            "description_zh": "使用已关联本体库的实体及同义、上位、下位关系增强检索",
        },
        "rule_enable": {
            "description": "Use enabled ontology rules to adjust candidate scores",
            "description_zh": "使用本体库中已启用的规则调整候选结果分数",
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
        search_method: str = Field(default=ALL_CHANNELS, description="Retrieval channels: vector_search, full_text_search, graph_search or a pipe-separated combination"),
        reranking_enable: bool = Field(default=True, description="Enable reranking"),
        reranking_mode: str = Field(default="performance", description="Reranking strategy: performance, high_accuracy or jargon_coverage"),
        rewrite_enable: bool = Field(default=False, description="Enable query rewrite"),
        related_search_enable: bool = Field(default=False, description="Enable related search"),
        score_threshold: float = Field(default=0.0, description="Score threshold 0-1", ge=0.0, le=1.0),
        top_k: int = Field(default=10, description="Top K results", ge=1, le=100),
        multi_modal: bool = Field(default=True, description="Return multimodal chunks"),
        vector_candidates: int = Field(default=10, ge=1, le=500, description="Vector candidates"),
        full_text_candidates: int = Field(default=10, ge=1, le=500, description="Full-text candidates"),
        hybrid_top_k: Optional[int] = Field(default=None, ge=0, le=100, description="Vector/full-text cap; real AIDP rejects 0 (ge=1), so zero is normalized to the total cap"),
        graph_top_k: int = Field(default=0, ge=0, le=100, description="Graph cap; zero means no separate cap, still bounded by top_k"),
        vector_score_threshold: float = Field(default=0.0, ge=0.0, le=1.0, description="Vector threshold"),
        full_text_score_threshold: float = Field(default=0.0, ge=0.0, le=1.0, description="Full-text threshold"),
        graph_score_threshold: float = Field(default=0.0, ge=0.0, le=1.0, description="Graph threshold"),
        graph_reranking_enable: bool = Field(default=True, description="Include graph results in unified reranking"),
        query_expansion_enable: bool = Field(default=False, description="Enable query expansion"),
        ontology_enhance_enable: bool = Field(default=False, description="Enable ontology entity enhancement"),
        rule_enable: bool = Field(default=False, description="Enable ontology rule enhancement"),
        metadata_filter: dict = Field(
            default_factory=dict,
            exclude=True,
            description="Server-installed conversation metadata filter: {enabled, match, conditions}",
        ),
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
        config = {
            "search_method": search_method,
            "reranking_mode": reranking_mode,
            "reranking_enable": reranking_enable,
            "rewrite_enable": rewrite_enable,
            "related_search_enable": related_search_enable,
            "score_threshold": score_threshold,
            "top_k": top_k,
            "multi_modal": multi_modal,
            "vector_candidates": vector_candidates,
            "full_text_candidates": full_text_candidates,
            "hybrid_top_k": hybrid_top_k,
            "graph_top_k": graph_top_k,
            "vector_score_threshold": vector_score_threshold,
            "full_text_score_threshold": full_text_score_threshold,
            "graph_score_threshold": graph_score_threshold,
            "graph_reranking_enable": graph_reranking_enable,
            "query_expansion_enable": query_expansion_enable,
            "ontology_enhance_enable": ontology_enhance_enable,
            "rule_enable": rule_enable,
        }
        config = {key: _resolve_field_default(value, DEFAULTS[key]) for key, value in config.items()}
        resolved = resolve_config(config)
        for key, value in resolved.items():
            setattr(self, key, value)
        self.metadata_filter = metadata_filter_rules.normalize_metadata_filter(
            unwrap_field_info(metadata_filter)
        )
        self.observer = _resolve_field_default(observer, None)
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

        # Request-scoped northbound download link settings. Only the runtime's
        # internal northbound entrypoint may install these through tool
        # configuration; the default page-created tool never exposes the field.
        self._northbound_download_base_url: str = ""

        self.record_ops = 1

    def set_northbound_download(
        self, external_url: Optional[str] = None
    ) -> None:
        """Enable original-file download links for a northbound run.

        ``external_url`` is the configured Nexent northbound base URL. It is
        deliberately supplied by the backend instead of being read from the
        environment here. Passing an empty or non-HTTP value disables the
        field again so a misconfigured run degrades to the page contract.
        """
        normalized = str(external_url or "").strip().rstrip("/")
        if not normalized.lower().startswith(("http://", "https://")):
            self._northbound_download_base_url = ""
            return
        self._northbound_download_base_url = normalized

    def _build_northbound_download_url(self, kds_id: str, file_uuid: str) -> str:
        """Build the API-key protected download URL for one original file."""
        if not self._northbound_download_base_url:
            return ""
        return (
            f"{self._northbound_download_base_url}/nb/v1/knowledge-bases/"
            f"{quote(kds_id, safe='')}/files/{quote(file_uuid, safe='')}/download"
        )

    def _build_retrieve_url(self) -> str:
        path = f"/KnowledgeBase/Tenants/{self.tenant_id}/Retrieval/FusionSearch"
        return urljoin(self.base_url, path)

    def _build_retrieve_payload(
        self,
        query: str,
        kds_list: List[str],
        metadata_condition: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return build_payload(
            {key: getattr(self, key) for key in CONFIG_KEYS},
            query,
            kds_list,
            metadata_condition,
        )

    def _emit_running_prompt(self, query: str) -> None:
        """Push the running prompt + query card to the observer if any."""
        if not self.observer:
            return
        card_content = [{"icon": "search", "text": query.strip()}]
        self.observer.add_message(
            "", ProcessType.CARD, json.dumps(card_content, ensure_ascii=False)
        )

    def _build_chunk_message(self, chunk: Dict[str, Any], idx: int, citation_start: Optional[int] = None):
        """Build a SearchResultTextMessage for a single record chunk."""
        chunk_type = str(chunk.get("chunk_type", "text") or "text")
        title = str(chunk.get("title") or "")
        text = str(chunk.get("text") or "")
        file_url = str(chunk.get("file_url") or "")
        chunk_id = chunk.get("id") if chunk.get("id") is not None else chunk.get("text_id")
        score = chunk.get("score")
        pages = chunk.get("pages", [])
        metadata = chunk.get("metadata", {})
        score_details = {
            "chunk_id": chunk_id,
            "chunk_type": chunk_type,
            "pages": pages,
            "file_url": file_url,
            "metadata": metadata,
            "retrieval_source": chunk.get("retrieval_source"),
        }
        kds_id, file_uuid = extract_aidp_file_identity(metadata)
        if kds_id and file_uuid:
            # Structured technical locator for the page source card. It is
            # never written to ``url`` and never inferred from the file name,
            # image URL or chunk id.
            score_details["kds_id"] = kds_id
            score_details["file_uuid"] = file_uuid
        return SearchResultTextMessage(
            title=title,
            text=text,
            source_type="file",
            url=file_url,
            filename=title,
            published_date="",
            score=str(score) if score is not None else None,
            score_details=score_details,
            cite_index=(self.record_ops if citation_start is None else citation_start) + idx,
            search_type=self.name,
            tool_sign=self.tool_sign,
        )

    def _process_records(self, records: List[Dict[str, Any]]):
        """Convert raw response records into dual-channel messages and return
        ``(search_results_return, images_url)``."""
        search_results_json: List[Dict[str, Any]] = []
        search_results_return: List[Dict[str, Any]] = []
        images_url: List[str] = []

        chunks = records[: self.top_k]
        citation_start = (
            self.observer.reserve_citations(self.tool_sign, len(chunks))
            if self.observer else self.record_ops
        )
        for idx, chunk in enumerate(chunks):
            msg = self._build_chunk_message(chunk, idx, citation_start)
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
                ui_result["url"] = full_url
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
            kds_id, file_uuid = extract_aidp_file_identity(chunk.get("metadata"))
            if kds_id and file_uuid:
                northbound_url = self._build_northbound_download_url(
                    kds_id, file_uuid
                )
                if northbound_url:
                    # Model-facing only: the page source card keeps the
                    # structured locator and never receives this API-key URL.
                    result["northbound_api_download_url"] = northbound_url
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

    def _execute_request(
        self,
        query: str,
        kds_list: List[str],
        metadata_condition: Optional[Dict[str, Any]] = None,
    ):
        """Retrieve records through the shared transport and response boundary."""
        return post_retrieval(
            self._http_client, self._build_retrieve_url(), self.api_key,
            self._build_retrieve_payload(query.strip(), kds_list, metadata_condition),
        )

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

    def _resolve_search_scope(
        self, kds_list: Optional[List[str]]
    ):
        configured_scope = self._convert_to_kds_ids(list(self.kds_list))
        requested_scope = (
            None
            if kds_list is None or len(kds_list) == 0
            else self._convert_to_kds_ids(list(kds_list))
        )
        return resolve_knowledge_search_scope(
            configured_scope=configured_scope,
            available_scope=self._filter_by_whitelist(configured_scope),
            requested_scope=requested_scope,
            permission_tracking_enabled=self._whitelist_installed,
        )

    def _get_kds_name_to_id_map(self) -> Dict[str, str]:
        kds_map = unwrap_field_info(self.kds_name_to_id_map)
        return kds_map if isinstance(kds_map, dict) else {}

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
        kds_map = self._get_kds_name_to_id_map()
        if not kds_map:
            return names

        converted_names = []
        for name in names:
            if name in kds_map:
                converted_names.append(kds_map[name])
            else:
                converted_names.append(name)
        return converted_names

    def _convert_to_kds_names(self, kds_ids: List[str]) -> List[str]:
        """Convert internal KDS IDs to display names for model-facing metadata."""
        kds_map = self._get_kds_name_to_id_map()
        if not kds_map:
            return list(kds_ids)

        id_to_name = {str(kds_id): str(name) for name, kds_id in kds_map.items()}
        return [id_to_name.get(str(kds_id), str(kds_id)) for kds_id in kds_ids]

    def _build_scope_response(
        self,
        results: List[Dict[str, Any]],
        used_scope: List[str],
        permission_denied_scope: List[str],
        unavailable_scope: List[str],
        fallback_to_all: bool,
        scope_was_specified: bool,
    ) -> str:
        """Serialize search results with display names in the model-facing notice."""
        return build_knowledge_search_response(
            results,
            self._convert_to_kds_names(used_scope),
            self._convert_to_kds_names(permission_denied_scope),
            self._convert_to_kds_names(unavailable_scope),
            fallback_to_all,
            scope_was_specified,
        )

    def forward(
        self,
        query: str,
        kds_list: Optional[List[str]] = None,
    ) -> str:
        if not query or not query.strip():
            raise ValueError("query is required and must be a non-empty string")

        scope = self._resolve_search_scope(kds_list)
        search_kds_list = scope.used_scope

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
            return self._build_scope_response(
                [],
                search_kds_list,
                scope.permission_denied_scope,
                scope.unavailable_scope,
                scope.fallback_to_all,
                scope.scope_was_specified,
            )

        metadata_condition = None
        if self.metadata_filter.get("enabled"):
            if "graph_search" in active_channels(self.search_method):
                # Graph retrieval does not consume metadata_condition. The
                # conversation filter is ignored for graph-enabled methods so
                # the retrieval still runs; the assistant UI hides the filter
                # entry for these Agents.
                logger.info(
                    "AIDP metadata filter ignored because graph retrieval is enabled"
                )
            else:
                metadata_condition = metadata_filter_rules.build_metadata_condition(
                    self.metadata_filter
                )

        self._emit_running_prompt(query)

        records = self._execute_request(query, search_kds_list, metadata_condition)

        if not records:
            logger.info(
                "AIDP search returned no results for query '%s' in kds_list=%s",
                query,
                search_kds_list,
            )
            return self._build_scope_response(
                [],
                search_kds_list,
                scope.permission_denied_scope,
                scope.unavailable_scope,
                scope.fallback_to_all,
                scope.scope_was_specified,
            )

        search_results_json, search_results_return, images_url = self._process_records(records)
        self.record_ops += len(search_results_return)
        self._emit_results(search_results_json, images_url)
        return self._build_scope_response(
            search_results_return,
            search_kds_list,
            scope.permission_denied_scope,
            scope.unavailable_scope,
            scope.fallback_to_all,
            scope.scope_was_specified,
        )
