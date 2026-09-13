import json
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence


class ToolSign(Enum):
    """Tool identifier enum for distinguishing different search sources in summaries"""
    KNOWLEDGE_BASE = "a"      # Knowledge base search tool identifier
    EXA_SEARCH = "b"  # Exa search tool identifier
    LINKUP_SEARCH = "c"       # Linkup search tool identifier
    TAVILY_SEARCH = "d"  # Tavily search tool identifier
    DATAMATE_SEARCH = "e"  # DataMate search tool identifier
    FILE_OPERATION = "f"      # File operation tool identifier
    DIFY_SEARCH = "g"  # Dify search tool identifier
    IDATA_SEARCH = "h"  # iData search tool identifier
    HAOTIAN_SEARCH = "i"  # Haotian search tool identifier
    RAGFLOW_SEARCH = "k"  # RAGFlow search tool identifier
    AIDP_SEARCH = "j"  # AIDP search tool identifier
    INDEPENDENT_AIDP_SEARCH = "l"  # Independent AIDP search tool identifier
    MEMORY_OPERATION = "n"      # Memory operation tool identifier
    SKILL_OPERATION = "s"     # Skill script / file tool identifier
    TERMINAL_OPERATION = "t"  # Terminal operation tool identifier
    MULTIMODAL_OPERATION = "m"  # Multimodal operation tool identifier
    PLAN_OPERATION = "p"       # Plan / step-state tool identifier (v1.4)
    DATABASE_OPERATION = "z"  # Database operation tool identifier


# Tool sign mapping for backward compatibility
TOOL_SIGN_MAPPING = {
    "knowledge_base_search": ToolSign.KNOWLEDGE_BASE.value,
    "tavily_search": ToolSign.TAVILY_SEARCH.value,
    "linkup_search": ToolSign.LINKUP_SEARCH.value,
    "exa_search": ToolSign.EXA_SEARCH.value,
    "datamate_search": ToolSign.DATAMATE_SEARCH.value,
    "dify_search": ToolSign.DIFY_SEARCH.value,
    "idata_search": ToolSign.IDATA_SEARCH.value,
    "haotian_search": ToolSign.HAOTIAN_SEARCH.value,
    "ragflow_search": ToolSign.RAGFLOW_SEARCH.value,
    "aidp_search": ToolSign.AIDP_SEARCH.value,
    "ind_aidp_search": ToolSign.INDEPENDENT_AIDP_SEARCH.value,
    "file_operation": ToolSign.FILE_OPERATION.value,
    "terminal_operation": ToolSign.TERMINAL_OPERATION.value,
    "multimodal_operation": ToolSign.MULTIMODAL_OPERATION.value,
    "database_operation": ToolSign.DATABASE_OPERATION.value,
    "memory_operation": ToolSign.MEMORY_OPERATION.value,
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
    DATABASE = "database"
    MEMORY = "memory"
    SKILL = "skill"
    PLANNING = "planning"


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
        index = f"{self.tool_sign}{self.cite_index}"
        return {
            "title": self.title,
            "text": self.text,
            "index": index,
            "reference_mark": f"[[{index}]]",
        }


@dataclass(frozen=True)
class KnowledgeSearchScope:
    """Resolved knowledge-base scope for search tools."""

    used_scope: List[str]
    permission_denied_scope: List[str]
    unavailable_scope: List[str]
    fallback_to_all: bool
    scope_was_specified: bool


def _unique_scope(scope: Sequence[str]) -> List[str]:
    return list(dict.fromkeys(str(item) for item in scope))


def resolve_knowledge_search_scope(
    configured_scope: Sequence[str],
    available_scope: Sequence[str],
    requested_scope: Optional[Sequence[str]],
    *,
    permission_tracking_enabled: bool = True,
) -> KnowledgeSearchScope:
    """Resolve requested, configured, and permission-filtered knowledge-base scopes."""
    configured = _unique_scope(configured_scope)
    available_set = set(_unique_scope(available_scope))
    available = [item for item in configured if item in available_set]

    if requested_scope is None or len(requested_scope) == 0:
        return KnowledgeSearchScope(
            used_scope=available,
            permission_denied_scope=[],
            unavailable_scope=[],
            fallback_to_all=False,
            scope_was_specified=False,
        )

    requested = _unique_scope(requested_scope)
    configured_set = set(configured)
    used_scope = [item for item in requested if item in available_set]
    permission_denied_scope = (
        [item for item in requested if item in configured_set and item not in available_set]
        if permission_tracking_enabled
        else []
    )
    unavailable_scope = [item for item in requested if item not in configured_set]
    fallback_to_all = bool(requested and not used_scope and available)
    if fallback_to_all:
        used_scope = available

    return KnowledgeSearchScope(
        used_scope=used_scope,
        permission_denied_scope=permission_denied_scope,
        unavailable_scope=unavailable_scope,
        fallback_to_all=fallback_to_all,
        scope_was_specified=True,
    )


def build_knowledge_search_response(
    results: List[Dict[str, Any]],
    used_scope: List[str],
    permission_denied_scope: List[str],
    unavailable_scope: List[str],
    fallback_to_all: bool,
    scope_was_specified: bool,
) -> str:
    """Build a concise model-facing response for a knowledge-base search."""

    def format_scope(scope: List[str]) -> str:
        return json.dumps(scope, ensure_ascii=False)

    filtered_messages = []
    if permission_denied_scope:
        filtered_messages.append(
            f"no read permission: {format_scope(permission_denied_scope)}"
        )
    if unavailable_scope:
        filtered_messages.append(
            f"not configured or unavailable: {format_scope(unavailable_scope)}"
        )
    filtered_notice = "; ".join(filtered_messages)

    if not used_scope:
        if filtered_notice:
            notice = (
                f"NOTICE: Requested knowledge bases were filtered ({filtered_notice}). "
                "No accessible knowledge bases remained, so search was not executed."
            )
        else:
            notice = (
                "NOTICE: No configured knowledge bases are accessible, so search was "
                "not executed."
            )
    elif filtered_notice and fallback_to_all:
        notice = (
            f"NOTICE: Requested knowledge bases were filtered ({filtered_notice}). "
            f"Search was broadened to all available configured knowledge bases {format_scope(used_scope)}. "
            "Do not retry the filtered knowledge bases."
        )
    elif filtered_notice:
        notice = (
            f"NOTICE: Requested knowledge bases were filtered ({filtered_notice}). "
            f"Search was executed in the remaining available knowledge bases {format_scope(used_scope)}. "
            "Do not retry the filtered knowledge bases."
        )
    elif scope_was_specified:
        notice = "NOTICE: Search was executed in the requested knowledge bases."
    else:
        notice = (
            "NOTICE: No knowledge-base scope was specified. Search was executed "
            "using the agent's configured accessible knowledge bases."
        )

    if not results and used_scope:
        notice += " No relevant information was found."

    return json.dumps(
        {
            "notice": notice,
            "results": results,
        },
        ensure_ascii=False,
    )
