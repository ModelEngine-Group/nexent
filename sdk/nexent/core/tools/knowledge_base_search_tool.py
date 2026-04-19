import json
import logging
import os
from typing import List, Optional

from pydantic import Field
from pydantic.fields import FieldInfo
from smolagents.tools import Tool

from ...vector_database.base import VectorDatabaseCore
from ..models.embedding_model import BaseEmbedding
from ..models.rerank_model import BaseRerank
from ..utils.constants import RERANK_OVERSEARCH_MULTIPLIER
from ..utils.observer import MessageObserver, ProcessType
from ..utils.tools_common_message import (
    SearchResultTextMessage,
    ToolCategory,
    ToolSign,
)

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
    description_zh = "执行本地知识库检索并返回最相关的结果。"

    inputs = {
        "query": {
            "type": "string",
            "description": "The search query to perform.",
            "description_zh": "要执行的搜索查询。",
        },
    }

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
            description="Maximum number of search results", default=3
        ),
        index_names: List[str] = Field(
            description="The list of index names to search"
        ),
        search_mode: str = Field(
            description="the search mode, optional values: hybrid, accurate, semantic",
            default="hybrid",
        ),
        rerank: bool = Field(
            description="Whether to enable reranking for search results",
            default=False,
        ),
        rerank_model_name: str = Field(
            description="The name of the rerank model to use", default=""
        ),
        observer: MessageObserver = Field(
            description="Message observer", default=None, exclude=True
        ),
        embedding_model: BaseEmbedding = Field(
            description="The embedding model to use", default=None, exclude=True
        ),
        rerank_model: BaseRerank = Field(
            description="The rerank model to use", default=None, exclude=True
        ),
        vdb_core: VectorDatabaseCore = Field(
            description="Vector database client", default=None, exclude=True
        ),
    ):
        super().__init__()
        self.top_k = top_k
        self.observer = observer
        self.vdb_core = vdb_core
        self.index_names = [] if index_names is None else index_names
        self.search_mode = search_mode
        self.embedding_model = embedding_model
        self.rerank = rerank
        self.rerank_model_name = rerank_model_name
        self.rerank_model = rerank_model
        self.data_process_service = os.getenv("DATA_PROCESS_SERVICE")

        self.record_ops = 1
        self.running_prompt_zh = "知识库检索中..."
        self.running_prompt_en = "Searching the knowledge base..."

    @staticmethod
    def _resolve_field_value(value, default):
        if isinstance(value, FieldInfo):
            return value.default if value.default is not None else default
        return default if value is None else value

    def _resolve_index_names(self) -> List[str]:
        raw_index_names = self._resolve_field_value(self.index_names, None)
        if raw_index_names is None:
            return []
        if isinstance(raw_index_names, str):
            return [name.strip() for name in raw_index_names.split(",") if name.strip()]
        if isinstance(raw_index_names, list):
            return [str(name).strip() for name in raw_index_names if str(name).strip()]
        return []

    def forward(self, query: str) -> str:
        # index_names is configured in tool init params, not runtime inputs
        search_index_names = self._resolve_index_names()

        # Use the instance search_mode
        search_mode = self.search_mode

        self._notify_search_start(query)

        logger.info(
            "KnowledgeBaseSearchTool called with query: '%s', search_mode: '%s', index_names: %s",
            query,
            search_mode,
            search_index_names,
        )

        if not search_index_names:
            return json.dumps(
                "No knowledge base selected. No relevant information found.",
                ensure_ascii=False,
            )

        top_k = int(self._resolve_field_value(self.top_k, 3))
        rerank_enabled = bool(self._resolve_field_value(self.rerank, False))
        effective_top_k = (
            top_k * RERANK_OVERSEARCH_MULTIPLIER if rerank_enabled else top_k
        )

        kb_search_data = self._run_search(
            query=query,
            index_names=search_index_names,
            search_mode=search_mode,
            top_k=effective_top_k,
        )
        kb_search_results = kb_search_data["results"]

        if not kb_search_results:
            raise Exception("No results found! Try a less restrictive/shorter query.")

        if rerank_enabled and self.rerank_model and kb_search_results:
            kb_search_results = self._apply_rerank(
                query=query,
                kb_search_results=kb_search_results,
                top_k=top_k,
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

        return json.dumps(search_results_return, ensure_ascii=False)

    def _notify_search_start(self, query: str) -> None:
        if not self.observer:
            return
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

    def _run_search(self, query: str, index_names: List[str], search_mode: str, top_k: int):
        search_handlers = {
            "hybrid": self.search_hybrid,
            "accurate": self.search_accurate,
            "semantic": self.search_semantic,
        }
        handler = search_handlers.get(search_mode)
        if not handler:
            raise Exception(
                f"Invalid search mode: {search_mode}, only support: hybrid, accurate, semantic"
            )
        return handler(query=query, index_names=index_names, top_k=top_k)

    def _apply_rerank(
        self,
        query: str,
        kb_search_results: List[dict],
        top_k: int,
    ) -> List[dict]:
        try:
            documents = [result.get("content", "") for result in kb_search_results]
            reranked_results = self.rerank_model.rerank(
                query=query,
                documents=documents,
                top_n=len(documents),
            )
            if not reranked_results:
                return kb_search_results

            original_results_map = {
                i: kb_search_results[i] for i in range(len(kb_search_results))
            }
            reranked_top_results = []
            for reranked_item in reranked_results[:top_k]:
                orig_idx = reranked_item.get("index")
                if orig_idx is None or orig_idx not in original_results_map:
                    continue
                result = original_results_map[orig_idx]
                result["score"] = reranked_item.get(
                    "relevance_score", result.get("score", 0)
                )
                reranked_top_results.append(result)

            if reranked_top_results:
                logger.info(
                    "Reranking applied: selected top %s from %s candidates",
                    top_k,
                    len(documents),
                )
                return reranked_top_results
            return kb_search_results
        except Exception as e:
            logger.warning("Reranking failed, using original results: %s", str(e))
            return kb_search_results

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

            search_results_json.append(search_result_message.to_dict())
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
        image_filter = getattr(self, "_filter_images", None)
        if callable(image_filter):
            try:
                maybe_filtered = image_filter(images_list_url, query)
                if maybe_filtered:
                    filtered_images = maybe_filtered
            except Exception as e:
                logger.warning("Image filtering failed, using original list: %s", str(e))

        if filtered_images:
            search_images_list_json = json.dumps(
                {"images_url": filtered_images}, ensure_ascii=False
            )
            self.observer.add_message(
                "", ProcessType.PICTURE_WEB, search_images_list_json
            )

    def search_hybrid(self, query, index_names, top_k):
        try:
            results = self.vdb_core.hybrid_search(
                index_names=index_names,
                query_text=query,
                embedding_model=self.embedding_model,
                top_k=top_k,
            )

            formatted_results = []
            for result in results:
                doc = result["document"]
                doc["score"] = result["score"]
                doc["index"] = result["index"]
                formatted_results.append(doc)

            return {
                "results": formatted_results,
                "total": len(formatted_results),
            }
        except Exception as e:
            raise Exception(f"Error during hybrid search: {str(e)}")

    def search_accurate(self, query, index_names, top_k):
        try:
            results = self.vdb_core.accurate_search(
                index_names=index_names,
                query_text=query,
                top_k=top_k,
            )

            formatted_results = []
            for result in results:
                doc = result["document"]
                doc["score"] = result["score"]
                doc["index"] = result["index"]
                formatted_results.append(doc)

            return {
                "results": formatted_results,
                "total": len(formatted_results),
            }
        except Exception as e:
            raise Exception(f"Error during accurate search: {str(e)}")

    def search_semantic(self, query, index_names, top_k):
        try:
            results = self.vdb_core.semantic_search(
                index_names=index_names,
                query_text=query,
                embedding_model=self.embedding_model,
                top_k=top_k,
            )

            formatted_results = []
            for result in results:
                doc = result["document"]
                doc["score"] = result["score"]
                doc["index"] = result["index"]
                formatted_results.append(doc)

            return {
                "results": formatted_results,
                "total": len(formatted_results),
            }
        except Exception as e:
            raise Exception(f"Error during semantic search: {str(e)}")
        
    def _filter_images(self, images_list_url, query) -> list:
        # kerry
        """
        Execute image filtering operation directly using the data processing service
        :param images_list_url: List of image URLs to filter
        :param query: Search query, used to filter images related to the query
        """
        import asyncio
        import aiohttp

        final_filtered_images = []
        try:
            # Define positive and negative prompts
            positive_prompt = query
            negative_prompt = "logo or banner or background or advertisement or icon or avatar"

            # Define the async function to perform the filtering
            async def process_images():
                # Maximum number of concurrent requests
                semaphore = asyncio.Semaphore(10)  # Limit concurrent requests

                # Create a ClientSession
                connector = aiohttp.TCPConnector(limit=0)
                timeout = aiohttp.ClientTimeout(total=2)

                async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
                    # Create a function to process a single image
                    async def process_single_image(img_url):
                        async with semaphore:
                            try:
                                api_url = f"{self.data_process_service}/tasks/filter_important_image"
                                data = {
                                    'image_url': img_url,
                                    'positive_prompt': positive_prompt,
                                    'negative_prompt': negative_prompt
                                }
                                async with session.post(api_url, data=data) as response:
                                    if response.status != 200:
                                        logger.info(
                                            f"API error for {img_url}: {response.status}")
                                        return None
                                    result = await response.json()
                                    if result.get("is_important", False):
                                        logger.info(
                                            f"Important image: {img_url}")
                                        return img_url
                                    return None
                            except Exception as e:
                                logger.info(
                                    f"Error processing image {img_url}: {str(e)}")
                                return None
                    tasks = [process_single_image(url)
                             for url in images_list_url]
                    results = await asyncio.gather(*tasks)
                    filtered_images = [
                        url for url in results if url is not None]

                    # Return the filtered list from the inner async function
                    return filtered_images

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                # Capture the return value from the async execution
                final_filtered_images = loop.run_until_complete(
                    process_images())
            finally:
                loop.close()
        except Exception as e:
            logger.info(f"Image filtering error: {str(e)}")
            return []

        # Return the final list to the caller
        return final_filtered_images

