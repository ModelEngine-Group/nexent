import json
import logging
from typing import Dict, List, Optional, Any
import httpx
from urllib.parse import urlencode

from pydantic import Field
from smolagents.tools import Tool

from ..utils.observer import MessageObserver, ProcessType
from ..utils.pydantic_utils import unwrap_field_info
from ..utils.tools_common_message import SearchResultTextMessage, ToolCategory, ToolSign
from ...utils.http_client_manager import http_client_manager


# Get logger instance
logger = logging.getLogger("idata_search_tool")


class IdataSearchTool(Tool):
    """iData knowledge base search tool"""

    name = "idata_search"
    description = (
        "Performs a search on an iData knowledge base based on your query then returns the top search results. "
        "A tool for retrieving domain-specific knowledge, documents, and information stored in iData knowledge bases. "
        "Use this tool when users ask questions related to specialized knowledge, technical documentation, "
        "domain expertise, or any information that has been indexed in iData knowledge bases. "
        "Suitable for queries requiring access to stored knowledge that may not be publicly available."
    )
    description_zh = (
        "基于你的查询词在 iData 知识库中进行搜索，返回最相关的搜索结果。"
        "适用于检索 iData 知识库中存储的领域专业知识、文档和信息。"
        "当用户询问与专业知识、技术文档、领域专长或任何已在 iData 知识库中建立索引的信息相关的问题时，请使用此工具。"
        "特别适合需要访问可能无法公开获取的存储知识的查询。"
    )
    inputs = {
        "question": {
            "type": "string",
            "description": "The search query to perform.",
            "description_zh": "要执行的搜索查询词"
        }
    }
    init_param_descriptions = {
        "server_url": {
            "description": "iData API base URL",
            "description_zh": "iData API 基础 URL"
        },
        "api_key": {
            "description": "iData API key with Bearer token",
            "description_zh": "iData API 密钥（带 Bearer token）"
        },
        "user_id": {
            "description": "iData user ID",
            "description_zh": "iData 用户 ID"
        },
        "knowledge_space_id": {
            "description": "iData knowledge space ID",
            "description_zh": "iData 知识空间 ID"
        },
        "dataset_ids": {
            "description": "JSON string array of iData knowledge base IDs",
            "description_zh": "iData 知识库 ID 的 JSON 字符串数组"
        },
        "rerank_model_id": {
            "description": "Rerank model ID",
            "description_zh": "Rerank 模型 ID"
        },
        "top_k": {
            "description": "Maximum number of search results",
            "description_zh": "最大返回搜索结果数量"
        },
        "similarity_threshold": {
            "description": "Rerank similarity threshold score",
            "description_zh": "Rerank 相似度阈值"
        },
        "keyword_similarity_weight": {
            "description": "Keyword similarity weight",
            "description_zh": "关键词相似度权重"
        },
        "vector_similarity_weight": {
            "description": "Vector similarity weight",
            "description_zh": "向量相似度权重"
        },
    }
    output_type = "string"
    category = ToolCategory.SEARCH.value
    tool_sign = ToolSign.IDATA_SEARCH.value

    def __init__(
        self,
        server_url: str = Field(description="iData API base URL"),
        api_key: str = Field(description="iData API key with Bearer token"),
        user_id: str = Field(description="iData user ID"),
        knowledge_space_id: str = Field(
            description="iData knowledge space ID"),
        dataset_ids: str = Field(
            description="JSON string array of iData knowledge base IDs"),
        rerank_model_id: str = Field(description="Rerank model ID"),
        top_k: int = Field(
            description="Maximum number of search results", default=10, ge=1, le=100),
        similarity_threshold: float = Field(
            description="Rerank similarity threshold score", default=-10.0, le=1.0),
        keyword_similarity_weight: float = Field(
            description="Keyword similarity weight", default=0.10, ge=0.0, le=1.0),
        vector_similarity_weight: float = Field(
            description="Vector similarity weight", default=0.3, ge=0.0, le=1.0),
        observer: MessageObserver = Field(
            description="Message observer", default=None, exclude=True),
    ):
        """Initialize the IdataSearchTool.

        Args:
            server_url (str): iData API base URL
            api_key (str): iData API key with Bearer token
            user_id (str): iData user ID
            knowledge_space_id (str): iData knowledge space ID
            dataset_ids (str): JSON string array of iData knowledge base IDs, e.g., '["kb_id_1", "kb_id_2"]'
            rerank_model_id (str): Rerank model ID
            top_k (int, optional): Number of results to return. Defaults to 10.
            similarity_threshold (float, optional): Rerank similarity threshold. Defaults to -10.0.
            keyword_similarity_weight (float, optional): Keyword similarity weight. Defaults to 0.10.
            vector_similarity_weight (float, optional): Vector similarity weight. Defaults to 0.3.
            observer (MessageObserver, optional): Message observer instance. Defaults to None.
        """
        super().__init__()

        top_k = unwrap_field_info(top_k)
        similarity_threshold = unwrap_field_info(similarity_threshold)
        keyword_similarity_weight = unwrap_field_info(keyword_similarity_weight)
        vector_similarity_weight = unwrap_field_info(vector_similarity_weight)

        # Validate server_url
        if not server_url or not isinstance(server_url, str):
            raise ValueError(
                "server_url is required and must be a non-empty string")

        # Validate api_key
        if not api_key or not isinstance(api_key, str):
            raise ValueError(
                "api_key is required and must be a non-empty string")

        # Validate user_id
        if not user_id or not isinstance(user_id, str):
            raise ValueError(
                "user_id is required and must be a non-empty string")

        # Validate knowledge_space_id
        if not knowledge_space_id or not isinstance(knowledge_space_id, str):
            raise ValueError(
                "knowledge_space_id is required and must be a non-empty string")

        # Validate rerank_model_id
        if not rerank_model_id or not isinstance(rerank_model_id, str):
            raise ValueError(
                "rerank_model_id is required and must be a non-empty string")

        # Parse and validate dataset_ids from string or list
        if not dataset_ids:
            raise ValueError(
                "dataset_ids is required and must be a non-empty JSON string array or list")
        try:
            # Handle both JSON string array and plain list
            if isinstance(dataset_ids, str):
                parsed_ids = json.loads(dataset_ids)
            else:
                parsed_ids = dataset_ids
            if not isinstance(parsed_ids, list) or not parsed_ids:
                raise ValueError(
                    "dataset_ids must be a non-empty array of strings")
            self.dataset_ids = [str(item) for item in parsed_ids]
        except (json.JSONDecodeError, TypeError) as e:
            raise ValueError(
                f"dataset_ids must be a valid JSON string array or list: {str(e)}")

        self.server_url = server_url.rstrip("/")
        self.api_key = api_key
        self.user_id = user_id
        self.knowledge_space_id = knowledge_space_id
        self.rerank_model_id = rerank_model_id
        self.top_k = max(1, min(int(top_k or 10), 100))
        self.similarity_threshold = min(float(similarity_threshold if similarity_threshold is not None else -10.0), 1.0)
        self.keyword_similarity_weight = max(0.0, min(float(keyword_similarity_weight if keyword_similarity_weight is not None else 0.10), 1.0))
        self.vector_similarity_weight = max(0.0, min(float(vector_similarity_weight if vector_similarity_weight is not None else 0.3), 1.0))
        self.observer = observer

        # Cache HTTP client for reuse (uses shared HttpClientManager internally)
        # Note: ssl_verify is set to False as per requirement (self-signed certificate)
        self._http_client = http_client_manager.get_sync_client(
            base_url=self.server_url,
            timeout=30.0,
            verify_ssl=False
        )

        self.record_ops = 1  # To record serial number

    def forward(
        self,
        question: str
    ) -> str:
        # Tool running chunk is emitted by the SDK tool-call bridge in
        # core_agent.py so it is consistent across direct and code_action
        # invocations. We only emit the search card from inside the tool.
        if self.observer:
            card_content = [{"icon": "search", "text": question}]
            self.observer.add_message("", ProcessType.CARD, json.dumps(
                card_content, ensure_ascii=False))

        # Log the search parameters
        logger.info(
            f"IdataSearchTool called with question: '{question}', top_k: {self.top_k}"
        )

        search_results_json = []  # Organize search results into a unified format
        search_results_return = []  # Format for input to the large model

        try:
            # Build knowledge base filter
            knowledge_base_filter = []
            for kb_id in self.dataset_ids:
                knowledge_base_filter.append({
                    "knowledgeBaseId": kb_id,
                    "metas": []
                })

            # Build request payload
            payload = {
                "userId": self.user_id,
                "knowledgeBaseFilter": knowledge_base_filter,
                "question": question,
                "rankTopN": self.top_k,
                "rerankModelId": self.rerank_model_id,
                "similarityThreshold": self.similarity_threshold,
                "keywordSimilarityWeight": self.keyword_similarity_weight,
                "vectorSimilarityWeight": self.vector_similarity_weight
            }

            # Perform search
            result = self._search_idata_knowledge_base(payload)

            # Parse response
            data = result.get("data", {})
            retrieval_data = data.get("retrievalData", [])

            if not retrieval_data:
                raise Exception(
                    "No results found! Try a less restrictive/shorter query.")

            # Extract chunks from the first retrieval data entry
            chunks = retrieval_data[0].get("chunks", [])

            if not chunks:
                raise Exception(
                    "No chunks found in search results! Try a different query.")

            # Process all chunks
            for index, chunk in enumerate(chunks):
                # Extract chunk information
                document_id = chunk.get("documentId", "")
                document_name = chunk.get("documentName", "")
                content = chunk.get("content", "")
                dataset_id = chunk.get("datasetId", "")
                create_time = chunk.get("createTime", 0)
                re_rank_score = chunk.get("reRankScore", 0)
                vs_score = chunk.get("vsScore", 0)
                es_score = chunk.get("esScore", 0)
                title = chunk.get("title", document_name)

                # Build download URL
                download_url = self._build_download_url(
                    document_id, dataset_id)

                # Build score details
                score_details = {
                    "reRankScore": re_rank_score,
                    "vsScore": vs_score,
                    "esScore": es_score
                }

                # Convert create_time from milliseconds to ISO format string
                published_date = ""
                if create_time:
                    try:
                        from datetime import datetime
                        # Convert milliseconds to seconds
                        timestamp = create_time / 1000
                        published_date = datetime.fromtimestamp(
                            timestamp).isoformat()
                    except Exception:
                        published_date = ""

                # Build the search result message
                search_result_message = SearchResultTextMessage(
                    title=title or document_name,
                    text=content,
                    source_type="idata",  # iData knowledge base source type
                    url=download_url,
                    filename=document_name,
                    published_date=published_date,
                    score=str(re_rank_score) if re_rank_score else None,
                    score_details=score_details,
                    cite_index=self.record_ops + index,
                    search_type=self.name,
                    tool_sign=self.tool_sign,
                )

                search_results_json.append(search_result_message.to_dict())
                search_results_return.append(
                    search_result_message.to_model_dict())

            self.record_ops += len(search_results_return)

            # Record the detailed content of this search
            if self.observer:
                search_results_data = json.dumps(
                    search_results_json, ensure_ascii=False)
                self.observer.add_message(
                    "", ProcessType.SEARCH_CONTENT, search_results_data)

            return json.dumps(search_results_return, ensure_ascii=False)

        except Exception as e:
            error_msg = f"Error searching iData knowledge base: {str(e)}"
            logger.error(error_msg)
            raise Exception(error_msg)

    def _build_download_url(self, document_id: str, dataset_id: str) -> str:
        """Build download URL for a document from iData API.

        Args:
            document_id (str): Document ID from search results
            dataset_id (str): Dataset/Knowledge base ID from chunk

        Returns:
            str: Download URL for the document
        """
        if not document_id:
            return ""

        # If dataset_id is empty, try to use the first knowledge base ID as fallback
        knowledge_base_id = dataset_id
        if not knowledge_base_id and self.dataset_ids:
            knowledge_base_id = self.dataset_ids[0]

        if not knowledge_base_id:
            return ""

        # Build URL with query parameters
        params = {
            "userId": self.user_id,
            "knowledgeBaseId": knowledge_base_id,
            "documentId": document_id
        }
        query_string = urlencode(params)
        url = f"{self.server_url}/apiaccess/modelmate/north/machine/v1/documents/download?{query_string}"

        return url

    def _search_idata_knowledge_base(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Perform search on iData knowledge base via API.

        Args:
            payload (Dict[str, Any]): Request payload

        Returns:
            Dict: Search results with retrievalData
        """
        url = f"{self.server_url}/apiaccess/modelmate/north/machine/v1/retrievals"

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }

        try:
            # Use cached HTTP client for requests
            # Note: All requests use self._http_client which was configured with verify_ssl=False
            # to support self-signed certificates (see __init__ method)
            response = self._http_client.post(
                url, headers=headers, json=payload)
            response.raise_for_status()

            result = response.json()

            # Validate response format
            code = result.get("code", "")
            if code != "1":
                msg = result.get("msg", "Unknown error")
                raise Exception(f"iData API error: {msg}")

            # Validate that required keys are present
            if "data" not in result:
                raise Exception(
                    "Unexpected iData API response format: missing 'data' key")

            data = result.get("data", {})
            if "retrievalData" not in data:
                raise Exception(
                    "Unexpected iData API response format: missing 'retrievalData' key")

            return result

        except httpx.RequestError as e:
            raise Exception(f"iData API request failed: {str(e)}")
        except httpx.HTTPStatusError as e:
            raise Exception(f"iData API HTTP error: {str(e)}")
        except json.JSONDecodeError as e:
            raise Exception(f"Failed to parse iData API response: {str(e)}")
        except KeyError as e:
            raise Exception(
                f"Unexpected iData API response format: missing key {str(e)}")
