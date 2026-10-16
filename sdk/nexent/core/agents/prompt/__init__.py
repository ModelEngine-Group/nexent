"""Public prompt assembly API with lazy Agent-specific imports."""

from importlib import import_module
from typing import Any

from ...prompts import load_prompt


_EXPORTS = {
    "AgentPromptBundle": (".bundle", "AgentPromptBundle"),
    "AgentPromptComposer": (".composer", "AgentPromptComposer"),
    "HumanInteractionPrompts": (".composer", "HumanInteractionPrompts"),
}


def __getattr__(name: str) -> Any:
    try:
        module_name, attribute = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(name) from exc
    value = getattr(import_module(module_name, __name__), attribute)
    globals()[name] = value
    return value


def get_builtin_tool_descriptions(language: str) -> dict[str, str]:
    """Return SDK-owned prose for built-in tool configuration."""
    return load_prompt(language, "agent/context_sections")["builtin_tools"]


__all__ = [
    "AgentPromptBundle",
    "AgentPromptComposer",
    "HumanInteractionPrompts",
    "get_builtin_tool_descriptions",
]
