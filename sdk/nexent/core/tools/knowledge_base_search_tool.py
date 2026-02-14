import json
import logging
from typing import List

from pydantic import Field
from smolagents.tools import Tool

from ...vector_database.base import VectorDatabaseCore
from ..models.embedding_model import BaseEmbedding
from ..utils.observer import MessageObserver, ProcessType
from ..utils.tools_common_message import SearchResultTextMessage, ToolCategory, ToolSign


# Get logger instance
logger = logging.getLogger("knowledge_base_search_tool")


class KnowledgeBaseSearchTool(Tool):
    """Knowledge base search tool"""

    name = "knowledge_base_search"
    description = (
        "Performs a local knowledge base search based on your query then returns the top search results. "
        "A tool for retrieving domain-specific knowledge, documents, and information stored in the local knowledge base. "
        "Use this tool when users ask questions related to specialized knowledge, technical documentation, "
        "domain expertise, personal notes, or any information that has been indexed in the knowledge base. "
        "Suitable for queries requiring access to stored knowledge that may not be publicly available."
    )

    description_zh = "基于你的查询词在本地知识库中进行搜索，返回最相关的搜索结果。适用于检索本地知识库中存储的领域专业知识、文档和信息。当用户询问与专业知识、技术文档、领域专长、个人笔记或任何已在知识库中建立索引的信息相关的问题时，请使用此工具。适合需要访问非公开存储知识的查询。"

    inputs = {
        "query": {
            "type": "string",
            "description": "The search query to perform.",
            "description_zh": "要执行的搜索查询词"
        },
    }

    init_param_descriptions = {
        "top_k": {
            "description": "Maximum number of search results",
            "description_zh": "返回搜索结果的最大数量"
        },
        "index_names": {
            "description": "The list of index names to search",
            "description_zh": "要搜索的索引名称列表"
        },
        "search_mode": {
            "description": "The search mode, optional values: hybrid, accurate, semantic",
            "description_zh": "搜索模式，可选值：hybrid（混合）、accurate（精确）、semantic（语义）"
        }
    }
    output_type = "string"
    category = ToolCategory.SEARCH.value

    # Used to distinguish different index sources for summaries
    tool_sign = ToolSign.KNOWLEDGE_BASE.value

    def __init__(
        self,
        top_k: int = Field(
            description="Maximum number of search results", default=3),
        index_names: List[str] = Field(
            description="The list of index names to search"),
        search_mode: str = Field(
            description="the search mode, optional values: hybrid, accurate, semantic",
            default="hybrid",
        ),
        observer: MessageObserver = Field(
            description="Message observer", default=None, exclude=True),
        embedding_model: BaseEmbedding = Field(
            description="The embedding model to use", default=None, exclude=True),
        vdb_core: VectorDatabaseCore = Field(
            description="Vector database client", default=None, exclude=True),
    ):
        """Initialize the KBSearchTool.

        Args:
            top_k (int, optional): Number of results to return. Defaults to 3.
            observer (MessageObserver, optional): Message observer instance. Defaults to None.

        Raises:
            ValueError: If language is not supported
        """
        super().__init__()
        self.top_k = top_k
        self.observer = observer
        self.vdb_core = vdb_core
        self.index_names = [] if index_names is None else index_names
        self.search_mode = search_mode
        self.embedding_model = embedding_model

        self.record_ops = 1  # To record serial number
        self.running_prompt_zh = "知识库检索中..."
        self.running_prompt_en = "Searching the knowledge base..."


    def forward(self, query: str) -> str:
        # Send tool run message
        if self.observer:
            running_prompt = self.running_prompt_zh if self.observer.lang == "zh" else self.running_prompt_en
            self.observer.add_message("", ProcessType.TOOL, running_prompt)
            card_content = [{"icon": "search", "text": query}]
            self.observer.add_message("", ProcessType.CARD, json.dumps(
                card_content, ensure_ascii=False))

        # Use the instance index_names and search_mode
        search_index_names = self.index_names
        search_mode = self.search_mode

        # Log the index_names being used for this search
        logger.info(
            f"KnowledgeBaseSearchTool called with query: '{query}', search_mode: '{search_mode}', index_names: {search_index_names}"
        )

        if len(search_index_names) == 0:
            return json.dumps("No knowledge base selected. No relevant information found.", ensure_ascii=False)

        if search_mode == "hybrid":
            kb_search_data = self.search_hybrid(
                query=query, index_names=search_index_names)
        elif search_mode == "accurate":
            kb_search_data = self.search_accurate(
                query=query, index_names=search_index_names)
        elif search_mode == "semantic":
            kb_search_data = self.search_semantic(
                query=query, index_names=search_index_names)
        else:
            raise Exception(
                f"Invalid search mode: {search_mode}, only support: hybrid, accurate, semantic")

        kb_search_results = kb_search_data["results"]

        if not kb_search_results:
            raise Exception(
                "No results found! Try a less restrictive/shorter query.")

        search_results_json = []  # Organize search results into a unified format
        search_results_return = []  # Format for input to the large model
        for index, single_search_result in enumerate(kb_search_results):
            # Temporarily correct the source_type stored in the knowledge base
            source_type = single_search_result.get("source_type", "")
            source_type = "file" if source_type in [
                "local", "minio"] else source_type
            title = single_search_result.get("title")
            if not title:
                title = single_search_result.get("filename", "")
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

            search_results_json.append(search_result_message.to_dict())
            search_results_return.append(search_result_message.to_model_dict())

        self.record_ops += len(search_results_return)

        # Record the detailed content of this search
        if self.observer:
            search_results_data = json.dumps(
                search_results_json, ensure_ascii=False)
            self.observer.add_message(
                "", ProcessType.SEARCH_CONTENT, search_results_data)
        return json.dumps(search_results_return, ensure_ascii=False)

    def search_hybrid(self, query, index_names):
        try:
            results = self.vdb_core.hybrid_search(
                index_names=index_names, query_text=query, embedding_model=self.embedding_model, top_k=self.top_k
            )

            # Format results
            formatted_results = []
            for result in results:
                doc = result["document"]
                doc["score"] = result["score"]
                # Include source index in results
                doc["index"] = result["index"]
                formatted_results.append(doc)

            return {
                "results": formatted_results,
                "total": len(formatted_results),
            }
        except Exception as e:
            raise Exception(f"Error during semantic search: {str(e)}")

    def search_accurate(self, query, index_names):
        try:
            results = self.vdb_core.accurate_search(
                index_names=index_names, query_text=query, top_k=self.top_k)

            # Format results
            formatted_results = []
            for result in results:
                doc = result["document"]
                doc["score"] = result["score"]
                # Include source index in results
                doc["index"] = result["index"]
                formatted_results.append(doc)

            return {
                "results": formatted_results,
                "total": len(formatted_results),
            }
        except Exception as e:
            raise Exception(detail=f"Error during accurate search: {str(e)}")

    def search_semantic(self, query, index_names):
        try:
            results = self.vdb_core.semantic_search(
                index_names=index_names, query_text=query, embedding_model=self.embedding_model, top_k=self.top_k
            )

            # Format results
            formatted_results = []
            for result in results:
                doc = result["document"]
                doc["score"] = result["score"]
                # Include source index in results
                doc["index"] = result["index"]
                formatted_results.append(doc)

            return {
                "results": formatted_results,
                "total": len(formatted_results),
            }
        except Exception as e:
            raise Exception(detail=f"Error during semantic search: {str(e)}")
