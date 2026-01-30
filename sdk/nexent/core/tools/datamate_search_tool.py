import json
import logging
from typing import Optional, List, Union

from pydantic import Field
from smolagents.tools import Tool
from urllib.parse import urlparse

from ...vector_database import DataMateCore
from ..utils.observer import MessageObserver, ProcessType
from ..utils.tools_common_message import SearchResultTextMessage, ToolCategory, ToolSign

# Get logger instance
logger = logging.getLogger("datamate_search_tool")


def _normalize_index_names(index_names: Optional[Union[str, List[str]]]) -> List[str]:
    """Normalize index_names to list; accept single string and keep None as empty list."""
    if index_names is None:
        return []
    if isinstance(index_names, str):
        return [index_names]
    return list(index_names)


class DataMateSearchTool(Tool):
    """DataMate knowledge base search tool"""
    name = "datamate_search"
    description = (
        "Performs a DataMate knowledge base search based on your query then returns the top search results. "
        "A tool for retrieving domain-specific knowledge, documents, and information stored in the DataMate knowledge base. "
        "Use this tool when users ask questions related to specialized knowledge, technical documentation, "
        "domain expertise, or any information that has been indexed in the DataMate knowledge base. "
        "Suitable for queries requiring access to stored knowledge that may not be publicly available."
    )
    inputs = {
        "query": {
            "type": "string",
            "description": "The search query to perform.",
        },
    }
    output_type = "string"
    category = ToolCategory.SEARCH.value

    # Used to distinguish different index sources for summaries
    tool_sign = ToolSign.DATAMATE_SEARCH.value

    def __init__(
        self,
        server_url: str = Field(description="DataMate server url"),
        verify_ssl: bool = Field(
            description="Whether to verify SSL certificates for HTTPS connections", default=False),
        index_names: List[str] = Field(
            description="The list of index names to search", default=None, exclude=True),
        observer: MessageObserver = Field(
            description="Message observer", default=None, exclude=True),
        top_k: int = Field(
            description="Default maximum number of search results to return", default=3),
        threshold: float = Field(
            description="Default similarity threshold for search results", default=0.2),
        kb_page: int = Field(
            description="Page index when listing knowledge bases from DataMate", default=0),
        kb_page_size: int = Field(
            description="Page size when listing knowledge bases from DataMate", default=20),
    ):
        """Initialize the DataMateSearchTool.

        Args:
            server_url (str): DataMate server URL (e.g., 'http://192.168.1.100:8080' or 'https://datamate.example.com:8443').
            verify_ssl (bool, optional): Whether to verify SSL certificates for HTTPS connections. Defaults to False for HTTPS, True for HTTP.
            index_names (List[str], optional): The list of index names to search. Defaults to None.
            observer (MessageObserver, optional): Message observer instance. Defaults to None.
            top_k (int, optional): Default maximum number of search results to return. Defaults to 3.
            threshold (float, optional): Default similarity threshold for search results. Defaults to 0.2.
            kb_page (int, optional): Page index when listing knowledge bases from DataMate. Defaults to 0.
            kb_page_size (int, optional): Page size when listing knowledge bases from DataMate. Defaults to 20.
        """
        super().__init__()

        if not server_url:
            raise ValueError("server_url is required for DataMateSearchTool")

        # Parse the URL
        parsed_url = self._parse_server_url(server_url)

        # Store parsed components
        self.server_ip = parsed_url["host"]
        self.server_port = parsed_url["port"]
        self.use_https = parsed_url["use_https"]
        self.server_base_url = parsed_url["base_url"]
        self.index_names = [] if index_names is None else index_names
        self.top_k = top_k
        self.threshold = threshold

        # Determine SSL verification setting
        if verify_ssl is None:
            # Default: don't verify SSL for HTTPS (for self-signed certificates), always verify for HTTP
            self.verify_ssl = not self.use_https
        else:
            self.verify_ssl = verify_ssl

        # Initialize DataMate vector database core with SSL verification settings
        self.datamate_core = DataMateCore(
            base_url=self.server_base_url,
            verify_ssl=self.verify_ssl if self.use_https else True
        )

        self.kb_page = kb_page
        self.kb_page_size = kb_page_size
        self.observer = observer

        self.record_ops = 1  # To record serial number
        self.running_prompt_zh = "DataMate知识库检索中..."
        self.running_prompt_en = "Searching the DataMate knowledge base..."

    @staticmethod
    def _parse_server_url(server_url: str) -> dict:
        """Parse server URL and extract components.

        Args:
            server_url: Server URL string (e.g., 'http://192.168.1.100:8080' or 'https://example.com:8443')

        Returns:
            dict: Parsed URL components containing:
                - host: Server hostname or IP
                - port: Server port
                - use_https: Whether HTTPS is used
                - base_url: Full base URL
        """

        # Ensure URL has a scheme
        if not server_url.startswith(('http://', 'https://')):
            raise ValueError(
                f"server_url must include protocol (http:// or https://): {server_url}")

        parsed = urlparse(server_url)

        if not parsed.hostname:
            raise ValueError(f"Invalid server_url format: {server_url}")

        # Determine port
        if parsed.port:
            port = parsed.port
        else:
            # Use default ports
            port = 443 if parsed.scheme == 'https' else 80

        # Validate port range
        if not (1 <= port <= 65535):
            raise ValueError(f"Port {port} is not in valid range (1-65535)")

        use_https = parsed.scheme == 'https'
        base_url = f"{parsed.scheme}://{parsed.hostname}:{port}".rstrip('/')

        return {
            "host": parsed.hostname,
            "port": port,
            "use_https": use_https,
            "base_url": base_url
        }

    def forward(
        self,
        query: str,
    ) -> str:
        """Execute DataMate search.

        Args:
            query: Search query text.
        """

        # Send tool run message
        if self.observer:
            running_prompt = self.running_prompt_zh if self.observer.lang == "zh" else self.running_prompt_en
            self.observer.add_message("", ProcessType.TOOL, running_prompt)
            card_content = [{"icon": "search", "text": query}]
            self.observer.add_message("", ProcessType.CARD, json.dumps(
                card_content, ensure_ascii=False))

        logger.info(
            f"DataMateSearchTool called with query: '{query}', base_url: '{self.server_base_url}', "
            f"top_k: {self.top_k}, threshold: {self.threshold}, index_names: {self.index_names}"
        )

        try:
            # Step 1: Determine knowledge base IDs to search
            knowledge_base_ids = self.index_names
            if len(knowledge_base_ids) == 0:
                return json.dumps("No knowledge base selected. No relevant information found.", ensure_ascii=False)

            # Step 2: Retrieve knowledge base content using DataMateCore hybrid search
            kb_search_results = []
            for knowledge_base_id in knowledge_base_ids:
                kb_search = self.datamate_core.hybrid_search(
                    query_text=query,
                    index_names=[knowledge_base_id],
                    top_k=self.top_k,
                    weight_accurate=self.threshold,
                )
                if not kb_search:
                    raise Exception(
                        "No results found! Try a less restrictive/shorter query.")
                kb_search_results.extend(kb_search)

            # Format search results
            search_results_json = []  # Organize search results into a unified format
            search_results_return = []  # Format for input to the large model
            for index, single_search_result in enumerate(kb_search_results):
                # Extract fields from DataMate API response
                entity_data = single_search_result.get("entity", {})
                metadata = self._parse_metadata(entity_data.get("metadata"))
                dataset_id = self._extract_dataset_id(
                    metadata.get("absolute_directory_path", ""))
                file_id = metadata.get("original_file_id")
                download_url = self.datamate_core.client.build_file_download_url(
                    dataset_id, file_id)

                score_details = entity_data.get("scoreDetails", {}) or {}
                score_details.update({
                    "datamate_dataset_id": dataset_id,
                    "datamate_file_id": file_id,
                    "datamate_download_url": download_url,
                    "datamate_base_url": self.server_base_url.rstrip("/")
                })

                search_result_message = SearchResultTextMessage(
                    title=metadata.get("file_name", ""),
                    text=entity_data.get("text", ""),
                    source_type="datamate",
                    url=download_url,
                    filename=metadata.get("file_name", ""),
                    published_date=entity_data.get("createTime", ""),
                    score=entity_data.get("score", "0"),
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
            error_msg = f"Error during DataMate knowledge base search: {str(e)}"
            logger.error(error_msg)
            raise Exception(error_msg)

    @staticmethod
    def _parse_metadata(metadata_raw: Optional[str]) -> dict:
        """Parse metadata payload safely."""
        if not metadata_raw:
            return {}
        if isinstance(metadata_raw, dict):
            return metadata_raw
        try:
            return json.loads(metadata_raw)
        except (json.JSONDecodeError, TypeError):
            logger.warning(
                "Failed to parse metadata payload, falling back to empty metadata.")
            return {}

    @staticmethod
    def _extract_dataset_id(absolute_path: str) -> str:
        """Extract dataset identifier from an absolute directory path."""
        if not absolute_path:
            return ""
        segments = [segment for segment in absolute_path.strip(
            "/").split("/") if segment]
        return segments[-1] if segments else ""
