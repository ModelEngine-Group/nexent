import json
import logging
from typing import Dict, List, Optional, Any, Tuple
import httpx

from pydantic import Field
from smolagents.tools import Tool

from ..utils.observer import MessageObserver, ProcessType
from ..utils.tools_common_message import SearchResultTextMessage, ToolCategory, ToolSign


# Get logger instance
logger = logging.getLogger("dify_search_tool")


class DifySearchTool(Tool):
    """Dify knowledge base search tool"""

    name = "dify_search"
    description = (
        "Performs a search on a Dify knowledge base based on your query then returns the top search results. "
        "A tool for retrieving domain-specific knowledge, documents, and information stored in Dify knowledge bases. "
        "Use this tool when users ask questions related to specialized knowledge, technical documentation, "
        "domain expertise, or any information that has been indexed in Dify knowledge bases. "
        "Suitable for queries requiring access to stored knowledge that may not be publicly available."
    )
    inputs = {
        "query": {"type": "string", "description": "The search query to perform."},
    }
    output_type = "string"
    category = ToolCategory.SEARCH.value
    tool_sign = ToolSign.DIFY_SEARCH.value

    def __init__(
        self,
        server_url: str = Field(description="Dify API base URL"),
        api_key: str = Field(description="Dify API key with Bearer token"),
        dataset_ids: str = Field(
            description="JSON string array of Dify dataset IDs"),
        top_k: int = Field(
            description="Maximum number of search results per dataset", default=3),
        search_method: str = Field(
            description="Search method: keyword_search, semantic_search, full_text_search, hybrid_search",
            default="semantic_search",
        ),
        observer: MessageObserver = Field(
            description="Message observer", default=None, exclude=True),
    ):
        """Initialize the DifySearchTool.

        Args:
            server_url (str): Dify API base URL
            api_key (str): Dify API key with Bearer token
            dataset_ids (str): JSON string array of Dify dataset IDs, e.g., '["dataset_id_1", "dataset_id_2"]'
            top_k (int, optional): Number of results to return per dataset. Defaults to 3.
            search_method (str, optional): Search method. Options: keyword_search, semantic_search, full_text_search, hybrid_search. Defaults to "semantic_search".
            observer (MessageObserver, optional): Message observer instance. Defaults to None.
        """
        super().__init__()

        # Validate server_url
        if not server_url or not isinstance(server_url, str):
            raise ValueError(
                "server_url is required and must be a non-empty string")

        # Validate api_key
        if not api_key or not isinstance(api_key, str):
            raise ValueError(
                "api_key is required and must be a non-empty string")

        # Parse and validate dataset_ids from JSON string
        if not dataset_ids or not isinstance(dataset_ids, str):
            raise ValueError(
                "dataset_ids is required and must be a non-empty JSON string array")
        try:
            parsed_ids = json.loads(dataset_ids)
            if not isinstance(parsed_ids, list) or not parsed_ids:
                raise ValueError(
                    "dataset_ids must be a non-empty JSON array of strings")
            self.dataset_ids = [str(item) for item in parsed_ids]
        except (json.JSONDecodeError, TypeError) as e:
            raise ValueError(
                f"dataset_ids must be a valid JSON string array: {str(e)}")

        self.server_url = server_url.rstrip("/")
        self.api_key = api_key
        self.top_k = top_k
        self.search_method = search_method
        self.observer = observer

        self.record_ops = 1  # To record serial number
        self.running_prompt_zh = "Dify知识库检索中..."
        self.running_prompt_en = "Searching Dify knowledge base..."

    def forward(
        self,
        query: str
    ) -> str:
        # Send tool run message
        if self.observer:
            running_prompt = self.running_prompt_zh if self.observer.lang == "zh" else self.running_prompt_en
            self.observer.add_message("", ProcessType.TOOL, running_prompt)
            card_content = [{"icon": "search", "text": query}]
            self.observer.add_message("", ProcessType.CARD, json.dumps(
                card_content, ensure_ascii=False))

        # Use instance default top_k and search_method
        search_top_k = self.top_k
        search_method = self.search_method

        # Log the search parameters
        logger.info(
            f"DifySearchTool called with query: '{query}', top_k: {search_top_k}, search_method: '{search_method}'"
        )

        # Perform searches across all datasets
        all_search_results = []
        search_results_json = []  # Organize search results into a unified format
        search_results_return = []  # Format for input to the large model

        try:
            # Store results with their dataset_id for URL generation
            all_search_results = []
            for dataset_id in self.dataset_ids:
                search_results_data = self._search_dify_knowledge_base(
                    query, search_top_k, search_method, dataset_id)
                search_results = search_results_data.get("records", [])
                # Add dataset_id to each result for URL generation
                for result in search_results:
                    result["dataset_id"] = dataset_id
                all_search_results.extend(search_results)

            if not all_search_results:
                raise Exception(
                    "No results found! Try a less restrictive/shorter query.")

            # Collect all document info for batch URL fetching
            document_dataset_pairs = []
            for result in all_search_results:
                segment = result.get("segment", {})
                document = segment.get("document", {})
                document_id = document.get("id", "")
                dataset_id = result.get("dataset_id")
                if document_id:  # Only collect non-empty document_ids
                    document_dataset_pairs.append((document_id, dataset_id))

            # Batch get download URLs
            download_url_map = self._batch_get_download_urls(
                document_dataset_pairs)

            # Process all results
            for index, result in enumerate(all_search_results):
                # Extract segment information
                segment = result.get("segment", {})

                # Build title from document name or segment content
                document = segment.get("document", {})
                title = document.get("name", "")
                document_id = document.get("id", "")

                # Get download URL from the batch result
                download_url = download_url_map.get(document_id, "")

                # Build the search result message
                search_result_message = SearchResultTextMessage(
                    title=title,
                    text=segment.get("content", ""),
                    source_type="dify",  # Dify knowledge base source type
                    url=download_url,  # Use the actual download URL from Dify API
                    filename=document.get("name", ""),
                    published_date="",  # Dify doesn't provide creation time in a standard format
                    score=result.get("score", 0),
                    score_details={},  # No additional score details from Dify
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
            error_msg = f"Error searching Dify knowledge base: {str(e)}"
            logger.error(error_msg)
            raise Exception(error_msg)

    def _get_document_download_url(self, document_id: str, dataset_id: str = None) -> str:
        """Get download URL for a document from Dify API.

        Args:
            document_id (str): Document ID from search results
            dataset_id (str, optional): Dataset ID. If not provided, uses the first dataset_id from the list.

        Returns:
            str: Download URL for the document
        """
        if not document_id:
            return ""

        # Use provided dataset_id or fall back to first one in the list
        targetdataset_id = dataset_id if dataset_id is not None else self.dataset_ids[0]
        url = f"{self.server_url}/datasets/{targetdataset_id}/documents/{document_id}/upload-file"

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }

        try:
            with httpx.Client(timeout=30) as client:
                response = client.get(url, headers=headers)
                response.raise_for_status()

                result = response.json()
                return result.get("download_url", "")

        except httpx.RequestError as e:
            logger.warning(
                f"Failed to get download URL for document {document_id}: {str(e)}")
            return ""
        except httpx.HTTPStatusError as e:
            logger.warning(
                f"HTTP error getting download URL for document {document_id}: {str(e)}")
            return ""
        except json.JSONDecodeError as e:
            logger.warning(
                f"Failed to parse download URL response for document {document_id}: {str(e)}")
            return ""
        except KeyError as e:
            logger.warning(
                f"Unexpected download URL response format for document {document_id}: missing key {str(e)}")
            return ""

    def _batch_get_download_urls(self, document_dataset_pairs: List[Tuple[str, str]]) -> Dict[str, str]:
        """Batch get download URLs for multiple documents.

        Args:
            document_dataset_pairs: List of (document_id, dataset_id) tuples

        Returns:
            Dict mapping document_id to download_url
        """
        url_map = {}

        for document_id, dataset_id in document_dataset_pairs:
            if document_id:  # Only process non-empty document_ids
                download_url = self._get_document_download_url(
                    document_id, dataset_id)
                url_map[document_id] = download_url
            else:
                url_map[document_id] = ""

        return url_map

    def _search_dify_knowledge_base(self, query: str, top_k: int, search_method: str, dataset_id: str) -> Dict[str, Any]:
        """Perform search on Dify knowledge base via API.

        Args:
            query (str): Search query
            top_k (int): Number of results to return
            search_method (str): Search method (keyword_search, semantic_search, full_text_search, hybrid_search)
            dataset_id (str): Dataset ID to search in

        Returns:
            Dict: Search results with records
        """
        url = f"{self.server_url}/datasets/{dataset_id}/retrieve"

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }

        payload = {
            "query": query,
            "retrieval_model": {
                "search_method": search_method,
                "reranking_enable": False,
                "reranking_mode": None,
                "reranking_model": {
                    "reranking_provider_name": "",
                    "reranking_model_name": ""
                },
                "weights": None,
                "top_k": top_k,
                "score_threshold_enabled": False,
                "score_threshold": None
            }
        }

        try:
            with httpx.Client(timeout=30) as client:
                response = client.post(url, headers=headers, json=payload)
                response.raise_for_status()

                result = response.json()

                # Validate that required keys are present
                if "records" not in result:
                    raise Exception(
                        "Unexpected Dify API response format: missing 'records' key")

                return result

        except httpx.RequestError as e:
            raise Exception(f"Dify API request failed: {str(e)}")
        except httpx.HTTPStatusError as e:
            raise Exception(f"Dify API HTTP error: {str(e)}")
        except json.JSONDecodeError as e:
            raise Exception(f"Failed to parse Dify API response: {str(e)}")
        except KeyError as e:
            raise Exception(
                f"Unexpected Dify API response format: missing key {str(e)}")
