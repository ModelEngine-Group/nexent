import json
import logging
from typing import Optional

from pydantic import Field
from smolagents.tools import Tool

from ...datamate import DataMateClient
from ..utils.observer import MessageObserver, ProcessType
from ..utils.tools_common_message import SearchResultTextMessage, ToolCategory, ToolSign

# Get logger instance
logger = logging.getLogger("datamate_search_tool")


class DataMateSearchTool(Tool):
    """DataMate knowledge base search tool"""
    name = "datamate_search_tool"
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
        "top_k": {
            "type": "integer",
            "description": "Maximum number of search results to return.",
            "default": 10,
            "nullable": True,
        },
        "threshold": {
            "type": "number",
            "description": "Similarity threshold for search results.",
            "default": 0.2,
            "nullable": True,
        },
        "kb_page": {
            "type": "integer",
            "description": "Page index when listing knowledge bases from DataMate.",
            "default": 0,
            "nullable": True,
        },
        "kb_page_size": {
            "type": "integer",
            "description": "Page size when listing knowledge bases from DataMate.",
            "default": 20,
            "nullable": True,
        },
    }
    output_type = "string"
    category = ToolCategory.SEARCH.value

    # Used to distinguish different index sources for summaries
    tool_sign = ToolSign.DATAMATE_KNOWLEDGE_BASE.value

    def __init__(
        self,
        server_ip: str = Field(description="DataMate server IP or hostname"),
        server_port: int = Field(description="DataMate server port"),
        observer: MessageObserver = Field(description="Message observer", default=None, exclude=True),
    ):
        """Initialize the DataMateSearchTool.

        Args:
            server_ip (str): DataMate server IP or hostname (without scheme).
            server_port (int): DataMate server port (1-65535).
            observer (MessageObserver, optional): Message observer instance. Defaults to None.
        """
        super().__init__()

        if not server_ip:
            raise ValueError("server_ip is required for DataMateSearchTool")

        if not isinstance(server_port, int) or not (1 <= server_port <= 65535):
            raise ValueError("server_port must be an integer between 1 and 65535")

        # Store raw host and port
        self.server_ip = server_ip.strip()
        self.server_port = server_port

        # Build base URL: http://host:port
        self.server_base_url = f"http://{self.server_ip}:{self.server_port}".rstrip("/")

        # Initialize DataMate SDK client
        self.datamate_client = DataMateClient(base_url=self.server_base_url)

        self.kb_page = 0
        self.kb_page_size = 20
        self.observer = observer

        self.record_ops = 1  # To record serial number
        self.running_prompt_zh = "DataMate知识库检索中..."
        self.running_prompt_en = "Searching the DataMate knowledge base..."

    def forward(
        self,
        query: str,
        top_k: int = 10,
        threshold: float = 0.2,
        kb_page: int = 0,
        kb_page_size: int = 20,
    ) -> str:
        """Execute DataMate search.

        Args:
            query: Search query text.
            top_k: Optional override for maximum number of search results.
            threshold: Optional override for similarity threshold.
            kb_page: Optional override for knowledge base list page index.
            kb_page_size: Optional override for knowledge base list page size.
        """

        self.kb_page = kb_page
        self.kb_page_size = kb_page_size

        # Send tool run message
        if self.observer:
            running_prompt = self.running_prompt_zh if self.observer.lang == "zh" else self.running_prompt_en
            self.observer.add_message("", ProcessType.TOOL, running_prompt)
            card_content = [{"icon": "search", "text": query}]
            self.observer.add_message("", ProcessType.CARD, json.dumps(card_content, ensure_ascii=False))

        logger.info(
            f"DataMateSearchTool called with query: '{query}', base_url: '{self.server_base_url}', "
            f"top_k: {top_k}, threshold: {threshold}"
        )

        try:
            # Step 1: Get knowledge base list using SDK
            knowledge_bases = self.datamate_client.list_knowledge_bases(
                page=self.kb_page,
                size=self.kb_page_size
            )

            # Extract knowledge base IDs
            knowledge_base_ids = []
            for kb in knowledge_bases:
                kb_id = kb.get("id")
                chunk_count = kb.get("chunkCount")
                if kb_id and chunk_count:
                    knowledge_base_ids.append(str(kb_id))

            if not knowledge_base_ids:
                return json.dumps("No knowledge base found. No relevant information found.", ensure_ascii=False)

            # Step 2: Retrieve knowledge base content using SDK
            kb_search_results = []
            for knowledge_base_id in knowledge_base_ids:

                kb_search = self.datamate_client.retrieve_knowledge_base(
                    query=query,
                    knowledge_base_ids=[knowledge_base_id],
                    top_k=top_k,
                    threshold=threshold
                )

                if not kb_search:
                    raise Exception("No results found! Try a less restrictive/shorter query.")
                kb_search_results.extend(kb_search)

            # Format search results
            search_results_json = []  # Organize search results into a unified format
            search_results_return = []  # Format for input to the large model
            for index, single_search_result in enumerate(kb_search_results):
                # Extract fields from DataMate API response
                entity_data = single_search_result.get("entity", {})
                metadata = self._parse_metadata(entity_data.get("metadata"))
                dataset_id = self._extract_dataset_id(metadata.get("absolute_directory_path", ""))
                file_id = metadata.get("original_file_id")
                download_url = self.datamate_client.build_file_download_url(dataset_id, file_id)

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
                search_results_return.append(search_result_message.to_model_dict())

            self.record_ops += len(search_results_return)

            # Record the detailed content of this search
            if self.observer:
                search_results_data = json.dumps(search_results_json, ensure_ascii=False)
                self.observer.add_message("", ProcessType.SEARCH_CONTENT, search_results_data)
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
            logger.warning("Failed to parse metadata payload, falling back to empty metadata.")
            return {}

    @staticmethod
    def _extract_dataset_id(absolute_path: str) -> str:
        """Extract dataset identifier from an absolute directory path."""
        if not absolute_path:
            return ""
        segments = [segment for segment in absolute_path.strip("/").split("/") if segment]
        return segments[-1] if segments else ""