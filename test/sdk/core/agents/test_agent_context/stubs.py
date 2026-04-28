"""
stubs.py
────────
Pure stub classes that stand in for smolagents types, plus the factory
function that wires them into sys.modules.

No pytest imports. No agent_context imports. Zero side-effects on import.
Call register_smolagents_mocks() exactly once before loading agent_context.
"""

import sys
from types import ModuleType
from typing import Any, List, Optional
from unittest.mock import MagicMock
from dataclasses import dataclass


# Stub: smolagents.models

class _MessageRole:
    USER      = "user"
    ASSISTANT = "assistant"
    SYSTEM    = "system"


class _ChatMessage:
    def __init__(self, role: str, content: Any):
        self.role    = role
        self.content = content

    def __repr__(self):
        return f"ChatMessage(role={self.role!r}, content={self.content!r})"


# ──────────────────────────────────────────────────────────────
# Stub: smolagents.memory
# ──────────────────────────────────────────────────────────────

class _MemoryStep:
    """Base class for all step types; provides the to_messages interface."""

    def to_messages(self, summary_mode: bool = False) -> List[_ChatMessage]:
        return []


@dataclass
class _TaskStep(_MemoryStep):
    task: str = ""

    def to_messages(self, summary_mode: bool = False) -> List[_ChatMessage]:
        content = [{"type": "text", "text": self.task}]
        return [_ChatMessage(role=_MessageRole.USER, content=content)]


@dataclass
class _ActionStep(_MemoryStep):
    step_number:   Optional[int]  = None
    model_output:  Optional[str]  = None
    action_output: Optional[Any]  = None
    observations:  Optional[str]  = None
    tool_calls:    Optional[list] = None
    error:         Optional[str]  = None
    token_usage:   Optional[Any]  = None

    def to_messages(self, summary_mode: bool = False) -> List[_ChatMessage]:
        if self.model_output:
            return [_ChatMessage(
                role=_MessageRole.ASSISTANT,
                content=[{"type": "text", "text": self.model_output}],
            )]
        return []


@dataclass
class _SystemPromptStep(_MemoryStep):
    system_prompt: str = ""

    def to_messages(self, summary_mode: bool = False) -> List[_ChatMessage]:
        if summary_mode:
            return []
        return [_ChatMessage(
            role=_MessageRole.SYSTEM,
            content=[{"type": "text", "text": self.system_prompt}],
        )]


class _AgentMemory:
    def __init__(self, steps=None, system_prompt=None):
        self.steps:         List[_MemoryStep] = steps or []
        self.system_prompt: Optional[Any]     = system_prompt


# ──────────────────────────────────────────────────────────────
# sys.modules registration
# ──────────────────────────────────────────────────────────────

def build_smolagents_mock() -> ModuleType:
    """
    Construct the full smolagents mock module tree.
    Returns the top-level module; does NOT register it in sys.modules.
    """
    mock_smolagents        = ModuleType("smolagents")
    mock_smolagents.__path__ = []

    # smolagents.agents — only the names referenced by agent_context are needed
    agents_mod = ModuleType("smolagents.agents")
    for _name in [
        "CodeAgent", "populate_template", "handle_agent_output_types",
        "AgentError", "ActionOutput", "RunResult",
    ]:
        setattr(agents_mod, _name, MagicMock(name=f"smolagents.agents.{_name}"))
    setattr(mock_smolagents, "agents", agents_mod)

    # smolagents.memory
    memory_mod = ModuleType("smolagents.memory")
    memory_mod.TaskStep         = _TaskStep
    memory_mod.ActionStep       = _ActionStep
    memory_mod.MemoryStep       = _MemoryStep
    memory_mod.AgentMemory      = _AgentMemory
    memory_mod.ToolCall         = MagicMock(name="smolagents.memory.ToolCall")
    setattr(mock_smolagents, "memory", memory_mod)

    # smolagents.models
    models_mod = ModuleType("smolagents.models")
    models_mod.ChatMessage = _ChatMessage
    models_mod.MessageRole = _MessageRole
    setattr(mock_smolagents, "models", models_mod)

    return mock_smolagents


def register_smolagents_mocks() -> ModuleType:
    """
    Build and register the smolagents mock tree into sys.modules.
    Idempotent: subsequent calls return the already-registered module.
    Returns the top-level mock module.
    """
    if "smolagents" in sys.modules:
        return sys.modules["smolagents"]

    mock = build_smolagents_mock()
    sys.modules.update({
        "smolagents":        mock,
        "smolagents.memory": mock.memory,
        "smolagents.models": mock.models,
        "smolagents.agents": mock.agents,
    })
    return mock