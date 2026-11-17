# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import json
import logging
from typing import List, Optional

from contracts.knowledge_tool import knowledge_tool_info
from nexent.core.utils.observer import MessageObserver, ProcessType
from nexent.core.utils.pydantic_utils import unwrap_field_info
from nexent.core.utils.tools_common_message import (
    SearchResultTextMessage,
    ToolCategory,
    ToolSign,
    build_knowledge_search_response,
    resolve_knowledge_search_scope,
)
from pydantic import Field
from smolagents.tools import Tool

logger = logging.getLogger("knowledge_base_search_tool")


class KnowledgeBaseSearchTool(Tool):
    """Knowledge base search tool"""

    _definition = knowledge_tool_info()
    name = _definition.name
    is_user_selectable = False
    description = _definition.description
    description_zh = _definition.description_zh
    inputs = json.loads(_definition.inputs)

    init_param_descriptions = {
        "top_k": {
            "description": "Maximum number of search results",
            "description_zh": "返回搜索结果的最大数量。",
        },
        "search_mode": {
            "description": "The search mode, optional values: hybrid, accurate, semantic",
            "description_zh": "搜索模式，可选：hybrid、accurate、semantic。",
        },
    }

    output_type = "string"
    category = ToolCategory.SEARCH.value
    tool_sign = ToolSign.KNOWLEDGE_BASE.value

    def __init__(
        self,
        top_k: int = Field(
            description="Maximum number of search results", default=3, ge=1, le=100
        ),
        index_names: List[str] = Field(
            description="The list of index names to search"
        ),
        search_mode: str = Field(
            description="the search mode, optional values: hybrid, accurate, semantic",
            default="hybrid",
        ),
        observer: MessageObserver = Field(
            description="Message observer", default=None, exclude=True
        ),
        display_name_to_index_map: dict = Field(
            description="Mapping from display_name (knowledge_name) to index_name",
            default_factory=dict, exclude=True),
        # Defense-in-depth whitelist populated by the backend when it builds the ToolConfig.
        # If set, forward() will silently drop any index_name not in this list so that even
        # a fabricated LLM argument cannot reach a KB the chatting user is not allowed to read.
        allowed_index_names: Optional[List[str]] = Field(
            description="Internal: read-permission whitelist for index_names", default=None, exclude=True,
        ),
    ):
        """Initialize the KBSearchTool.

        Args:
            top_k (int, optional): Number of results to return. Defaults to 3.
            observer (MessageObserver, optional): Message observer instance. Defaults to None.
            display_name_to_index_map (dict, optional): Mapping from display_name to index_name.
                When LLM passes display_name as index_names parameter, it will be converted
                to the actual index_name for ES queries.

        Raises:
            ValueError: If language is not supported
        """
        super().__init__()
        self.top_k = max(1, min(int(unwrap_field_info(top_k) or 3), 100))
        self.observer = unwrap_field_info(observer)
        self.index_names = list(unwrap_field_info(index_names) or [])
        self.search_mode = unwrap_field_info(search_mode)
        self.image_filterer = None
        self.cancellation_scope = None
        self.searcher = None
        self.display_name_to_index_map = unwrap_field_info(display_name_to_index_map) or {}
        # `allowed_index_names` is `exclude=True`; unwrap in case smolagents passed FieldInfo.
        raw_allowed = unwrap_field_info(allowed_index_names)
        self._allowed_index_names: Optional[set] = (
            set(raw_allowed) if isinstance(raw_allowed, list) else None
        )

        self.record_ops = 1

    def set_allowed_index_names(self, index_names: Optional[List[str]]) -> None:
        """Install the backend-computed execution whitelist.

        An empty list is an installed deny-all whitelist. The standard backend
        independently authorizes every selected knowledge resource.
        """
        self._allowed_index_names = (
            None if index_names is None else {str(name) for name in index_names}
        )

    def _convert_to_index_names(self, names: List[str]) -> List[str]:
        """Convert display names (knowledge_name) to index names if necessary.

        When LLM passes display_name as the index_names parameter,
        this method converts it to the actual index_name for ES queries.

        Args:
            names: List of names that could be either display_name or index_name

        Returns:
            List of actual index_names for ES queries
        """
        display_map = self._get_display_name_to_index_map()
        if not display_map:
            return names

        converted_names = []
        for name in names:
            if name in display_map:
                converted_names.append(display_map[name])
            else:
                converted_names.append(name)
        return converted_names

    def _get_display_name_to_index_map(self) -> dict:
        display_map = unwrap_field_info(self.display_name_to_index_map)
        return display_map if isinstance(display_map, dict) else {}

    def _convert_to_display_names(self, index_names: List[str]) -> List[str]:
        """Convert internal index names to display names for response metadata."""
        display_map = self._get_display_name_to_index_map()
        if not display_map:
            return list(index_names)

        index_to_display = {
            str(index_name): str(display_name)
            for display_name, index_name in display_map.items()
        }
        return [
            index_to_display.get(str(index_name), str(index_name))
            for index_name in index_names
        ]

    def _build_scope_response(
        self,
        results: List[dict],
        used_scope: List[str],
        permission_denied_scope: List[str],
        unavailable_scope: List[str],
        fallback_to_all: bool,
        scope_was_specified: bool,
    ) -> str:
        """Serialize search results with display names in the model-facing notice."""
        return build_knowledge_search_response(
            results,
            self._convert_to_display_names(used_scope),
            self._convert_to_display_names(permission_denied_scope),
            self._convert_to_display_names(unavailable_scope),
            fallback_to_all,
            scope_was_specified,
        )

    def _resolve_search_scope(
        self, index_names: Optional[List[str]]
    ):
        configured_scope = self._convert_to_index_names(list(self.index_names))
        if self._allowed_index_names is not None:
            available_scope = [
                name for name in configured_scope if name in self._allowed_index_names
            ]
        else:
            available_scope = configured_scope

        requested_scope = (
            None
            if index_names is None or len(index_names) == 0
            else self._convert_to_index_names(list(index_names))
        )
        return resolve_knowledge_search_scope(
            configured_scope=configured_scope,
            available_scope=available_scope,
            requested_scope=requested_scope,
            permission_tracking_enabled=self._allowed_index_names is not None,
        )

    def forward(self, query: str, index_names: Optional[List[str]] = None) -> str:
        scope = self._resolve_search_scope(index_names)
        search_index_names = scope.used_scope

        # Guard: if no knowledge bases are accessible after permission filtering,
        # return a clear denial message so the LLM can inform the user instead of
        # retrying against a non-existent tool.
        if not search_index_names:
            logger.warning(
                "KnowledgeBaseSearchTool called with query '%s' but no accessible "
                "knowledge bases after permission filtering",
                query,
            )
            return self._build_scope_response(
                [],
                search_index_names,
                scope.permission_denied_scope,
                scope.unavailable_scope,
                scope.fallback_to_all,
                scope.scope_was_specified,
            )

        # Use the instance search_mode
        search_mode = self.search_mode

        self._notify_search_start(query)

        logger.info(
            "KnowledgeBaseSearchTool called with query: '%s', search_mode: '%s', index_names: %s",
            query,
            search_mode,
            search_index_names,
        )

        kb_search_data = self._run_search(query=query, index_names=search_index_names,
                                          search_mode=search_mode, top_k=self.top_k)
        kb_search_results = kb_search_data["results"]

        if not kb_search_results:
            logger.info(
                "Knowledge base search returned no results for query '%s' in indexes %s",
                query,
                search_index_names,
            )
            return self._build_scope_response(
                [],
                search_index_names,
                scope.permission_denied_scope,
                scope.unavailable_scope,
                scope.fallback_to_all,
                scope.scope_was_specified,
            )

        (
            search_results_json,
            search_results_return,
            images_list_url,
        ) = self._build_search_results(kb_search_results)

        self.record_ops += len(search_results_return)

        self._record_search_results(
            search_results_json=search_results_json,
            images_list_url=images_list_url,
            query=query,
        )

        return self._build_scope_response(
            search_results_return,
            search_index_names,
            scope.permission_denied_scope,
            scope.unavailable_scope,
            scope.fallback_to_all,
            scope.scope_was_specified,
        )

    def _notify_search_start(self, query: str) -> None:
        if not self.observer:
            return
        card_content = [{"icon": "search", "text": query}]
        self.observer.add_message(
            "", ProcessType.CARD, json.dumps(card_content, ensure_ascii=False)
        )

    def _run_search(self, query: str, index_names: List[str], search_mode: str, top_k: int):
        if not callable(self.searcher):
            raise RuntimeError("Runtime knowledge search requires its bound standard backend")
        return self.searcher(query=query, index_names=index_names, search_mode=search_mode, top_k=top_k,
                             cancellation_scope=self.cancellation_scope)

    @staticmethod
    def _normalize_source_type(source_type: str) -> str:
        return "file" if source_type in ["local", "minio"] else source_type

    def _build_search_results(self, kb_search_results):
        search_results_json = []
        search_results_return = []
        images_list_url = []

        for index, single_search_result in enumerate(kb_search_results):
            source_type = self._normalize_source_type(
                single_search_result.get("source_type", "")
            )
            title = single_search_result.get("title") or single_search_result.get(
                "filename", ""
            )
            search_result_message = SearchResultTextMessage(
                title=title,
                text=single_search_result.get("content", ""),
                source_type=source_type,
                url=single_search_result.get("path_or_url", ""),
                filename=single_search_result.get("filename", ""),
                published_date=single_search_result.get("create_time", ""),
                score=single_search_result.get("score", 0),
                score_details=single_search_result.get("score_details", {}),
                cite_index=self.record_ops + index,
                search_type=self.name,
                tool_sign=self.tool_sign,
            )

            image_url = self._extract_image_url(single_search_result)
            if image_url:
                images_list_url.append(image_url)

            stored = search_result_message.to_dict()
            for field in ("file_ref", "image_ref", "location"):
                if field in single_search_result:
                    stored[field] = single_search_result[field]
            search_results_json.append(stored)
            search_results_return.append(search_result_message.to_model_dict())

        return search_results_json, search_results_return, images_list_url

    @staticmethod
    def _extract_image_url(single_search_result):
        if single_search_result.get("process_source") != "UniversalImageExtractor":
            return None
        try:
            meta_data = json.loads(single_search_result.get("content"))
        except (json.JSONDecodeError, TypeError):
            logger.error("Failed to parse image metadata")
            return None
        return meta_data.get("image_url", None)

    def _record_search_results(
        self,
        search_results_json: List[dict],
        images_list_url: List[str],
        query: str,
    ) -> None:
        if not self.observer:
            return

        search_results_data = json.dumps(search_results_json, ensure_ascii=False)
        self.observer.add_message("", ProcessType.SEARCH_CONTENT, search_results_data)

        if not images_list_url:
            return

        filtered_images = images_list_url
        image_filter = self.image_filterer
        if callable(image_filter):
            try:
                maybe_filtered = image_filter(images_list_url, query, cancellation_scope=self.cancellation_scope)
                if maybe_filtered:
                    filtered_images = maybe_filtered
            except Exception as e:
                logger.warning("knowledge_image_filter_failed exception_type=%s", type(e).__name__)

        if filtered_images:
            search_images_list_json = json.dumps(
                {"images_url": filtered_images}, ensure_ascii=False
            )
            self.observer.add_message(
                "", ProcessType.PICTURE_WEB, search_images_list_json
            )
