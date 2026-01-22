from dataclasses import dataclass
from typing import Optional, Dict, Any
from enum import Enum


class ToolSign(Enum):
    """Tool identifier enum for distinguishing different search sources in summaries"""
    KNOWLEDGE_BASE = "a"      # Knowledge base search tool identifier
    EXA_SEARCH = "b"  # Exa search tool identifier
    LINKUP_SEARCH = "c"       # Linkup search tool identifier
    TAVILY_SEARCH = "d"  # Tavily search tool identifier
    DATAMATE_SEARCH = "e"  # DataMate search tool identifier
    DIFY_SEARCH = "g"  # Dify search tool identifier
    FILE_OPERATION = "f"      # File operation tool identifier
    TERMINAL_OPERATION = "t"  # Terminal operation tool identifier
    MULTIMODAL_OPERATION = "m" # Multimodal operation tool identifier


# Tool sign mapping for backward compatibility
TOOL_SIGN_MAPPING = {
    "knowledge_base_search": ToolSign.KNOWLEDGE_BASE.value,
    "tavily_search": ToolSign.TAVILY_SEARCH.value,
    "linkup_search": ToolSign.LINKUP_SEARCH.value,
    "exa_search": ToolSign.EXA_SEARCH.value,
    "datamate_search": ToolSign.DATAMATE_SEARCH.value,
    "dify_search": ToolSign.DIFY_SEARCH.value,
    "file_operation": ToolSign.FILE_OPERATION.value,
    "terminal_operation": ToolSign.TERMINAL_OPERATION.value,
    "multimodal_operation": ToolSign.MULTIMODAL_OPERATION.value,
}

# Reverse mapping for lookup
REVERSE_TOOL_SIGN_MAPPING = {v: k for k, v in TOOL_SIGN_MAPPING.items()}


class ToolCategory(Enum):
    """Enumeration for MCP tool categories"""
    SEARCH = "search"
    FILE = "file"
    EMAIL = "email"
    TERMINAL = "terminal"
    MULTIMODAL = "multimodal"


@dataclass
class SearchResultTextMessage:
    """
    Unified search result message class, containing all fields for search and FinalAnswerFormat tools.
    """

    def __init__(self, title: str, url: str, text: str, published_date: Optional[str] = None,
                 source_type: Optional[str] = None, filename: Optional[str] = None, score: Optional[str] = None,
                 score_details: Optional[Dict[str, Any]] = None, cite_index: Optional[int] = None,
                 search_type: Optional[str] = None, tool_sign: Optional[str] = None):
        self.title = title
        self.url = url
        self.text = text
        self.published_date = published_date
        self.source_type = source_type
        self.filename = filename
        self.score = score
        self.score_details = score_details
        self.cite_index = cite_index
        self.search_type = search_type
        self.tool_sign = tool_sign

    def to_dict(self) -> Dict[str, Any]:
        """Convert SearchResult object to dictionary format to save all data."""
        return {"title": self.title, "url": self.url, "text": self.text, "published_date": self.published_date,
            "source_type": self.source_type, "filename": self.filename, "score": self.score,
            "score_details": self.score_details, "cite_index": self.cite_index, "search_type": self.search_type,
            "tool_sign": self.tool_sign}

    def to_model_dict(self) -> Dict[str, Any]:
        """Format for input to the large model summary."""
        return {"title": self.title, "text": self.text, "index": f"{self.tool_sign}{self.cite_index}"}
