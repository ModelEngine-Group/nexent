import json
import logging
from typing import Any, Dict, List, Union

import httpx
from pydantic import Field
from pydantic.fields import FieldInfo
from smolagents.tools import Tool

from ..utils.observer import MessageObserver, ProcessType
from ..utils.tools_common_message import SearchResultTextMessage, ToolCategory, ToolSign
from ...utils.http_client_manager import http_client_manager

logger = logging.getLogger("ragflow_search_tool")


def _resolve_default(value: Any) -> Any:
    """Extract the actual default value from a FieldInfo object.

    smolagents.Tool does not resolve FieldInfo defaults passed as __init__
    parameter defaults — Python passes the FieldInfo object itself. This
    helper extracts the underlying .default value so the attribute stores
    a usable Python primitive instead of a FieldInfo descriptor.
    """
    if isinstance(value, FieldInfo):
        return value.default
    return value


class RAGFlowSearchTool(Tool):
    name = "ragflow_search"
    description = (
        "Performs a search on a RAGFlow knowledge base based on your query then returns the top search results. "
        "A tool for retrieving domain-specific knowledge, documents, and information stored in RAGFlow knowledge bases. "
        "Use this tool when users ask questions related to specialized knowledge, technical documentation, "
        "domain expertise, or any information that has been indexed in RAGFlow datasets. "
        "Suitable for queries requiring access to stored knowledge that may not be publicly available."
    )

    description_zh = (
        "基于你的查询词在 RAGFlow 知识库中进行搜索，返回最相关的搜索结果。"
        "适用于检索 RAGFlow 知识库中存储的领域专业知识、文档和信息。"
        "当用户询问与专业知识、技术文档、领域专长或任何已在 RAGFlow 知识库中建立索引的信息相关的问题时，请使用此工具。"
    )

    inputs = {
        "query": {
            "type": "string",
            "description": "The search query to perform.",
            "description_zh": "要执行的搜索查询词",
        },
        "doc_id": {
            "type": "string",
            "description": "Optional. Restrict search to a specific document ID. Pass a single document ID string, or a JSON array of document IDs. Leave empty to search across all documents in the selected datasets.",
            "description_zh": "可选。限定搜索到特定文档 ID。可传入单个文档 ID 字符串，或 JSON 数组格式的多个文档 ID。留空则在整个选定知识库中搜索。",
            "nullable": True,
        },
        "dataset_ids": {
            "type": "string",
            "description": "Optional. JSON string array of RAGFlow dataset IDs to override the configured datasets for this search. When provided, only these datasets are searched instead of the configured ones.",
            "description_zh": "可选。用于覆盖本次搜索配置的 RAGFlow 知识库 ID 列表（JSON 字符串数组）。传入时，只搜索此处指定的知识库，替换配置中的知识库列表。",
            "nullable": True,
        },
    }

    init_param_descriptions = {
        "server_url": {
            "description": "RAGFlow API base URL",
            "description_zh": "RAGFlow API 基础 URL",
        },
        "api_key": {
            "description": "RAGFlow API key",
            "description_zh": "RAGFlow API 密钥",
        },
        "dataset_ids": {
            "description": "JSON string array of RAGFlow dataset IDs",
            "description_zh": "要检索的 RAGFlow 知识库 ID 列表",
        },
        "top_k": {
            "description": "Maximum number of search results to return to the LLM",
            "description_zh": "返回给 LLM 的搜索结果最大数量",
        },
        "similarity_threshold": {
            "description": "Minimum similarity score threshold for results",
            "description_zh": "结果的最小相似度阈值",
        },
        "vector_similarity_weight": {
            "description": "Weight of vector similarity in hybrid search (0.0-1.0)",
            "description_zh": "混合搜索中向量相似度的权重 (0.0-1.0)",
        },
        "keyword": {
            "description": "Whether to enable keyword search in hybrid mode",
            "description_zh": "是否在混合搜索中启用关键词搜索",
        },
        "highlight": {
            "description": "Whether to enable highlight in search results",
            "description_zh": "是否在搜索结果中启用高亮",
        },
    }
    output_type = "string"
    category = ToolCategory.SEARCH.value
    tool_sign = ToolSign.RAGFLOW_SEARCH.value

    def __init__(
        self,
        server_url: str = Field(description="RAGFlow API base URL (e.g., 'http://localhost:9380')"),
        api_key: str = Field(description="RAGFlow API key"),
        dataset_ids: str = Field(description="JSON string array of RAGFlow dataset IDs", default="[]"),
        top_k: int = Field(description="Maximum number of search results to return to the LLM", default=3),
        similarity_threshold: float = Field(
            description="Minimum similarity score threshold for results", default=0.2
        ),
        vector_similarity_weight: float = Field(
            description="Weight of vector similarity in hybrid search (0.0-1.0)", default=0.3
        ),
        keyword: bool = Field(description="Whether to enable keyword search in hybrid mode", default=False),
        highlight: bool = Field(description="Whether to enable highlight in search results", default=True),
        observer: MessageObserver = Field(description="Message observer", default=None, exclude=True),
    ):
        super().__init__()

        # Resolve FieldInfo defaults — smolagents.Tool wraps __init__ but
        # does not extract .default from FieldInfo objects. Without this
        # step, optional params (top_k, keyword, etc.) retain their FieldInfo
        # descriptors and fail on JSON serialization in _search_ragflow().
        server_url = _resolve_default(server_url)
        api_key = _resolve_default(api_key)
        dataset_ids = _resolve_default(dataset_ids)
        top_k = _resolve_default(top_k)
        similarity_threshold = _resolve_default(similarity_threshold)
        vector_similarity_weight = _resolve_default(vector_similarity_weight)
        keyword = _resolve_default(keyword)
        highlight = _resolve_default(highlight)
        observer = _resolve_default(observer)

        if not server_url or not isinstance(server_url, str):
            raise ValueError("server_url is required and must be a non-empty string")

        if not api_key or not isinstance(api_key, str):
            raise ValueError("api_key is required and must be a non-empty string")

        if not dataset_ids:
            raise ValueError("dataset_ids is required and must be a non-empty JSON string array or list")
        logger.info(f"Validating RAGFlowSearchTool with dataset_ids: {dataset_ids}")

        try:
            if isinstance(dataset_ids, str):
                parsed_ids = json.loads(dataset_ids)
            else:
                parsed_ids = dataset_ids
            if not isinstance(parsed_ids, list) or not parsed_ids:
                raise ValueError("dataset_ids must be a non-empty array of strings")
            self.dataset_ids = [str(item) for item in parsed_ids]
        except (json.JSONDecodeError, TypeError) as e:
            raise ValueError(f"dataset_ids must be a valid JSON string array or list: {str(e)}")

        self.server_url = server_url.rstrip("/")
        self.api_key = api_key
        self.top_k = top_k
        self.similarity_threshold = similarity_threshold
        self.vector_similarity_weight = vector_similarity_weight
        self.keyword = keyword
        self.highlight = highlight
        self.observer = observer

        self._http_client = http_client_manager.get_sync_client(
            base_url=self.server_url,
            timeout=30.0,
            verify_ssl=True,
        )

        self.record_ops = 1
        self.running_prompt_zh = "RAGFlow知识库检索中..."
        self.running_prompt_en = "Searching RAGFlow knowledge base..."

    def _resolve_effective_dataset_ids(self, dataset_ids: Union[str, List[str]]) -> List[str]:
        """Resolve effective dataset IDs, preferring runtime override over configured value.

        Accepts both a JSON string array and a native list (e.g. from form-based
        validation flows that pass KB selections directly as lists).
        """
        if not dataset_ids:
            return self.dataset_ids

        if isinstance(dataset_ids, list):
            return [str(d) for d in dataset_ids]

        dataset_ids = dataset_ids.strip()
        try:
            if dataset_ids.startswith("["):
                return [str(d) for d in json.loads(dataset_ids)]
            return [dataset_ids]
        except (json.JSONDecodeError, TypeError) as e:
            logger.warning(
                f"Failed to parse runtime dataset_ids as JSON array: {e}, "
                f"falling back to configured datasets"
            )
            return self.dataset_ids

    @staticmethod
    def _parse_doc_ids(doc_id: Union[str, List[str]]) -> List[str]:
        """Parse a doc_id into a list of document IDs.

        Accepts a single document ID string, a JSON array string, or a
        native list (e.g. from form-based validation flows).
        """
        if not doc_id:
            return []

        if isinstance(doc_id, list):
            return [str(d) for d in doc_id]

        doc_id = doc_id.strip()
        if doc_id.startswith("["):
            try:
                return [str(d) for d in json.loads(doc_id)]
            except (json.JSONDecodeError, TypeError) as e:
                logger.warning(f"Failed to parse doc_id as JSON array: {e}")
                return []

        return [doc_id]

    def _build_result_messages(
        self, chunks: List[dict]
    ) -> tuple:
        """Build SearchResultTextMessage objects from API response chunks."""
        search_results_json = []
        search_results_return = []

        for index, chunk in enumerate(chunks):
            content = chunk.get("content_with_weight", "") or chunk.get("content_ltks", "")
            doc_name = chunk.get("docnm_kwd", "") or chunk.get("doc_id", "")
            important_words = chunk.get("important_kwd", [])

            title = doc_name
            if important_words:
                title = f"{doc_name} [{', '.join(important_words[:3])}]"

            message = SearchResultTextMessage(
                title=title,
                text=content,
                url="",
                source_type="ragflow",
                filename=doc_name,
                published_date="",
                score=str(chunk.get("similarity", 0)),
                score_details={
                    "term_similarity": chunk.get("term_similarity"),
                    "vector_similarity": chunk.get("vector_similarity"),
                },
                cite_index=self.record_ops + index,
                search_type=self.name,
                tool_sign=self.tool_sign,
            )

            search_results_json.append(message.to_dict())
            search_results_return.append(message.to_model_dict())

        return search_results_json, search_results_return

    def forward(self, query: str, doc_id: Union[str, List[str]] = "", dataset_ids: Union[str, List[str]] = "") -> str:
        if self.observer:
            running_prompt = self.running_prompt_zh if self.observer.lang == "zh" else self.running_prompt_en
            self.observer.add_message("", ProcessType.TOOL, running_prompt)
            card_content = [{"icon": "search", "text": query}]
            self.observer.add_message("", ProcessType.CARD, json.dumps(card_content, ensure_ascii=False))

        effective_dataset_ids = self._resolve_effective_dataset_ids(dataset_ids)
        doc_ids_list = self._parse_doc_ids(doc_id)

        logger.info(
            f"RAGFlowSearchTool called with query: '{query}', top_k: {self.top_k}, "
            f"datasets: {effective_dataset_ids}, doc_id: '{doc_id}'"
        )

        try:
            search_results_data = self._search_ragflow(query, effective_dataset_ids, doc_ids_list)
            chunks = search_results_data.get("chunks", [])

            if not chunks:
                raise ValueError("No results found! Try a less restrictive/shorter query.")

            # Sort by similarity descending and take top_k
            chunks.sort(key=lambda c: c.get("similarity", 0), reverse=True)
            chunks = chunks[:self.top_k]

            search_results_json, search_results_return = self._build_result_messages(chunks)
            self.record_ops += len(search_results_return)

            if self.observer:
                self.observer.add_message(
                    "", ProcessType.SEARCH_CONTENT,
                    json.dumps(search_results_json, ensure_ascii=False)
                )

            return json.dumps(search_results_return, ensure_ascii=False)

        except ValueError:
            raise
        except Exception as e:
            error_msg = f"Error searching RAGFlow knowledge base: {str(e)}"
            logger.error(error_msg)
            raise RuntimeError(error_msg) from e

    def _search_ragflow(self, query: str, dataset_ids: List[str], doc_ids: List[str] = None) -> Dict[str, Any]:
        """Send a single multi-dataset search request to RAGFlow API.

        RAGFlow supports passing multiple dataset_ids in one request
        and handles reranking internally.

        Args:
            query: The search query string.
            dataset_ids: List of dataset IDs to search.
            doc_ids: Optional list of document IDs to restrict the search to.
        """
        url = f"{self.server_url}/api/v1/datasets/search"

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

        payload: Dict[str, Any] = {
            "question": query,
            "top_k": self.top_k,
            "similarity_threshold": self.similarity_threshold,
            "vector_similarity_weight": self.vector_similarity_weight,
            "use_kg": False,
            "keyword": self.keyword,
            "highlight": self.highlight,
        }

        if len(dataset_ids) >= 1:
            payload["dataset_ids"] = dataset_ids
        if doc_ids:
            payload["doc_ids"] = doc_ids
        logger.info(f"RAGFlow search payload: {payload}")

        try:
            response = self._http_client.post(url, headers=headers, json=payload)
            response.raise_for_status()

            result = response.json()

            if result.get("code") != 0:
                raise RuntimeError(
                    f"RAGFlow API returned error code {result.get('code')}: "
                    f"{result.get('message', 'Unknown error')}"
                )

            data = result.get("data", {})
            total = data.get("total", 0)
            logger.info(f"RAGFlow search returned {total} chunks from {len(dataset_ids)} dataset(s)")
            return data

        except httpx.RequestError as e:
            raise ConnectionError(f"RAGFlow API request failed: {str(e)}") from e
        except httpx.HTTPStatusError as e:
            raise RuntimeError(f"RAGFlow API HTTP error: {str(e)}") from e
        except json.JSONDecodeError as e:
            raise ValueError(f"Failed to parse RAGFlow API response: {str(e)}") from e
