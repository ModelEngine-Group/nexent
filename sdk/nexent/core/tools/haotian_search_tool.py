import json
import logging
from typing import Any, Dict, List, Optional

import httpx
from pydantic import Field
from smolagents.tools import Tool

from ..models.rerank_model import BaseRerank
from ..utils.observer import MessageObserver, ProcessType
from ..utils.tools_common_message import SearchResultTextMessage, ToolCategory, ToolSign
from ...utils.http_client_manager import http_client_manager


logger = logging.getLogger("haotian_search_tool")


class HaotianSearchTool(Tool):
    """Haotian external knowledge base search tool."""

    name = "haotian_search"
    description = (
        "Performs a search on Haotian external knowledge bases based on your query "
        "then returns the top search results."
    )
    description_zh = "基于你的查询词在 Haotian 外部知识库中进行检索，返回最相关的搜索结果。"

    inputs = {
        "query": {
            "type": "string",
            "description": "The search query to perform.",
            "description_zh": "要执行的搜索查询词",
        }
    }

    init_param_descriptions = {
        "list_url": {
            "description": "Haotian knowledge sets list URL",
            "description_zh": "Haotian 知识集/知识库列表 URL",
        },
        "retrieve_url": {
            "description": "Haotian retrieve API URL",
            "description_zh": "Haotian 检索 API URL",
        },
        "authorization": {
            "description": "Haotian Authorization header value (e.g., 'Bearer xxx')",
            "description_zh": "Haotian Authorization 头（例如：Bearer xxx）",
        },
        "dataset_ids": {
            "description": "JSON string array of selected dataset IDs (dify_dataset_id)",
            "description_zh": "选择的知识库 ID（dify_dataset_id）列表（JSON 字符串数组）",
        },
        "top_k": {
            "description": "Maximum number of search results per dataset",
            "description_zh": "返回的搜索结果最大数量",
        },
        "search_method": {
            "description": "Search method: keyword_search only (Haotian does not support semantic or hybrid search)",
            "description_zh": "搜索方法：仅支持 keyword_search（Haotian 不支持语义搜索或混合搜索）",
        },
        "reranking_enable": {
            "description": "Whether to enable reranking in retrieve API",
            "description_zh": "是否启用检索接口内置 rerank",
        },
        "reranking_provider_name": {
            "description": "Reranking provider name",
            "description_zh": "Rerank 提供方名称",
        },
        "reranking_model_name": {
            "description": "Reranking model name",
            "description_zh": "Rerank 模型名称",
        },
        "keyword_weight": {
            "description": "Keyword weight",
            "description_zh": "关键词权重",
        },
        "vector_weight": {
            "description": "Vector weight",
            "description_zh": "向量权重",
        },
        "embedding_provider_name": {
            "description": "Embedding provider name",
            "description_zh": "Embedding 提供方名称",
        },
        "embedding_model_name": {
            "description": "Embedding model name",
            "description_zh": "Embedding 模型名称",
        },
        "score_threshold_enabled": {
            "description": "Whether to enable score threshold",
            "description_zh": "是否启用 score 阈值",
        },
        "score_threshold": {
            "description": "Score threshold",
            "description_zh": "score 阈值",
        },
    }

    output_type = "string"
    category = ToolCategory.SEARCH.value
    tool_sign = ToolSign.HAOTIAN_SEARCH.value

    def __init__(
        self,
        list_url: str = Field(description="Haotian knowledge sets list URL"),
        retrieve_url: str = Field(description="Haotian retrieve API URL"),
        authorization: str = Field(
            description="Authorization header value, e.g. 'Bearer xxx'"
        ),
        dataset_ids: Any = Field(
            description="Selected dataset ids (JSON string array or list)"
        ),
        top_k: int = Field(description="Maximum number of search results", default=3),
        search_method: str = Field(
            description="Search method",
            default="keyword_search",
        ),
        reranking_enable: bool = Field(
            description="Whether to enable reranking in retrieve API",
            default=False,
        ),
        reranking_provider_name: str = Field(
            description="Reranking provider name",
            default="",
        ),
        reranking_model_name: str = Field(
            description="Reranking model name",
            default="",
        ),
        keyword_weight: float = Field(description="Keyword weight", default=0.1),
        vector_weight: float = Field(description="Vector weight", default=0.3),
        embedding_provider_name: str = Field(
            description="Embedding provider name",
            default="",
        ),
        embedding_model_name: str = Field(
            description="Embedding model name",
            default="",
        ),
        score_threshold_enabled: bool = Field(
            description="Whether to enable score threshold",
            default=False,
        ),
        score_threshold: Optional[float] = Field(
            description="Score threshold",
            default=None,
        ),
        observer: MessageObserver = Field(
            description="Message observer", default=None, exclude=True
        ),
        rerank_model: BaseRerank = Field(
            description="Optional local rerank model (not used by Haotian API)",
            default=None,
            exclude=True,
        ),
    ):
        super().__init__()

        if not retrieve_url or not isinstance(retrieve_url, str):
            raise ValueError("retrieve_url is required and must be a non-empty string")
        if not list_url or not isinstance(list_url, str):
            raise ValueError("list_url is required and must be a non-empty string")
        if not authorization or not isinstance(authorization, str):
            raise ValueError("authorization is required and must be a non-empty string")

        self.list_url = list_url.strip()
        self.retrieve_url = retrieve_url.strip()
        self.authorization = authorization.strip()

        self.dataset_ids = self._parse_dataset_ids(dataset_ids)
        self.top_k = top_k
        self.search_method = search_method
        self.reranking_enable = reranking_enable
        self.reranking_provider_name = reranking_provider_name
        self.reranking_model_name = reranking_model_name
        self.keyword_weight = keyword_weight
        self.vector_weight = vector_weight
        self.embedding_provider_name = embedding_provider_name
        self.embedding_model_name = embedding_model_name
        self.score_threshold_enabled = score_threshold_enabled
        self.score_threshold = score_threshold
        self.observer = observer
        self.rerank_model = rerank_model

        self._http_client = http_client_manager.get_sync_client(
            base_url="",
            timeout=30.0,
            verify_ssl=True,
        )

        self.record_ops = 1
        self.running_prompt_zh = "Haotian知识库检索中..."
        self.running_prompt_en = "Searching Haotian knowledge base..."

    @staticmethod
    def _parse_dataset_ids(dataset_ids: Any) -> List[str]:
        if dataset_ids is None:
            return []
        if isinstance(dataset_ids, list):
            return [str(x) for x in dataset_ids if str(x).strip()]
        if isinstance(dataset_ids, str):
            s = dataset_ids.strip()
            if not s:
                return []
            try:
                parsed = json.loads(s)
                if isinstance(parsed, list):
                    return [str(x) for x in parsed if str(x).strip()]
            except Exception:
                return [x.strip() for x in s.split(",") if x.strip()]
        return [str(dataset_ids)]

    def forward(self, query: str) -> str:
        if self.observer:
            running_prompt = (
                self.running_prompt_zh
                if self.observer.lang == "zh"
                else self.running_prompt_en
            )
            self.observer.add_message("", ProcessType.TOOL, running_prompt)
            card_content = [{"icon": "search", "text": query}]
            self.observer.add_message(
                "", ProcessType.CARD, json.dumps(card_content, ensure_ascii=False)
            )

        if not self.dataset_ids:
            return json.dumps(
                "No knowledge base selected. No relevant information found.",
                ensure_ascii=False,
            )

        payload = {
            "query": query,
            "retrieval_model": {
                "search_method": self.search_method,
                "reranking_enable": self.reranking_enable,
                "reranking_model": {
                    "reranking_provider_name": self.reranking_provider_name,
                    "reranking_model_name": self.reranking_model_name,
                },
                "weights": {
                    "keyword_setting": {"keyword_weight": self.keyword_weight},
                    "vector_setting": {
                        "vector_weight": self.vector_weight,
                        "embedding_provider_name": self.embedding_provider_name,
                        "embedding_model_name": self.embedding_model_name,
                    },
                },
                "top_k": self.top_k,
                "score_threshold_enabled": self.score_threshold_enabled,
                "score_threshold": self.score_threshold,
            },
            "dataset_ids": self.dataset_ids,
        }

        headers = {
            "Content-Type": "application/json",
            "Authorization": self.authorization,
        }

        try:
            resp = self._http_client.post(
                self.retrieve_url, headers=headers, json=payload
            )
            resp.raise_for_status()
            data = resp.json()

            records = []
            if isinstance(data, dict):
                # Try common patterns
                if isinstance(data.get("records"), list):
                    records = data.get("records", [])
                elif isinstance(data.get("data"), dict) and isinstance(
                    data["data"].get("records"), list
                ):
                    records = data["data"].get("records", [])
                elif isinstance(data.get("data"), list):
                    records = data.get("data", [])

            if not records:
                raise Exception("No results found! Try a less restrictive/shorter query.")

            search_results_json = []
            search_results_return = []

            for index, r in enumerate(records[: self.top_k]):
                # Handle Haotian API format with metadata object
                metadata = r.get("metadata", {})
                if not isinstance(metadata, dict):
                    metadata = {}

                # Extract title from various possible locations
                title = str(
                    r.get("title")
                    or metadata.get("document_name")
                    or r.get("name")
                    or ""
                )
                # Extract content
                content = str(r.get("text") or r.get("content") or "")
                # Extract score from metadata (Haotian format) or top level
                score = metadata.get("score", r.get("score"))
                # Extract URL from metadata
                url = str(r.get("url") or metadata.get("_source") or "")
                # Extract document info from metadata
                dataset_id = str(metadata.get("dataset_id") or "")
                dataset_name = str(metadata.get("dataset_name") or "")
                document_id = str(metadata.get("document_id") or "")
                document_name = str(metadata.get("document_name") or "")
                segment_id = str(metadata.get("segment_id") or "")

                # Dify-like segment format fallback
                segment = r.get("segment") if isinstance(r, dict) else None
                if isinstance(segment, dict):
                    content = str(segment.get("content") or content)
                    document = segment.get("document") or {}
                    if isinstance(document, dict):
                        title = str(document.get("name") or title)

                search_result_message = SearchResultTextMessage(
                    title=title,
                    text=content,
                    source_type="haotian",
                    url=url,
                    filename=title,
                    published_date=str(r.get("published_date") or ""),
                    score=str(score) if score is not None else None,
                    score_details={
                        "dataset_id": dataset_id,
                        "dataset_name": dataset_name,
                        "document_id": document_id,
                        "document_name": document_name,
                        "segment_id": segment_id,
                    },
                    cite_index=self.record_ops + index,
                    search_type=self.name,
                    tool_sign=self.tool_sign,
                )
                search_results_json.append(search_result_message.to_dict())
                search_results_return.append(search_result_message.to_model_dict())

            self.record_ops += len(search_results_return)

            if self.observer:
                self.observer.add_message(
                    "",
                    ProcessType.SEARCH_CONTENT,
                    json.dumps(search_results_json, ensure_ascii=False),
                )

            return json.dumps(search_results_return, ensure_ascii=False)
        except httpx.HTTPError as e:
            error_msg = f"Error searching Haotian knowledge base: {str(e)}"
            logger.error(error_msg)
            raise Exception(error_msg)
        except Exception as e:
            error_msg = f"Error searching Haotian knowledge base: {str(e)}"
            logger.error(error_msg)
            raise Exception(error_msg)

