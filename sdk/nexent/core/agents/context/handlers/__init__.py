"""Context item handler implementations for all supported item types."""

from .system_prompt_handler import SystemPromptHandler
from .tool_handler import ToolHandler
from .skill_handler import SkillHandler
from .memory_handler import MemoryHandler
from .knowledge_base_handler import KnowledgeBaseHandler
from .managed_agent_handler import ManagedAgentHandler
from .external_agent_handler import ExternalAgentHandler
from .history_turn_handler import HistoryTurnHandler
from .tool_call_result_handler import ToolCallResultHandler

ALL_HANDLERS = [
    SystemPromptHandler,
    ToolHandler,
    SkillHandler,
    MemoryHandler,
    KnowledgeBaseHandler,
    ManagedAgentHandler,
    ExternalAgentHandler,
    HistoryTurnHandler,
    ToolCallResultHandler,
]


def register_all() -> None:
    """Register all built-in handlers with the ItemHandlerRegistry."""
    from ..item_handler_registry import ItemHandlerRegistry

    for handler_cls in ALL_HANDLERS:
        ItemHandlerRegistry.register(handler_cls())
