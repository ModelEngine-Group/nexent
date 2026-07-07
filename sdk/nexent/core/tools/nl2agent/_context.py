"""Shared session context for NL2AGENT builtin tools.

Each NL2AGENT tool reads its session context (draft agent_id, user_id,
tenant_id, model_id, language) from this module. The context is injected at
agent build time via `ToolConfig.metadata` and set by `get_*_tool()` in each
tool module.

This mirrors the pattern in `read_skill_config_tool.py` where a module-level
global holds the tool instance.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class Nl2AgentContext:
    """Session context for an NL2AGENT tool.

    Attributes:
        agent_id: The running NL2AGENT default agent's id (the chat agent).
        draft_agent_id: The target draft agent being built. Tools that operate
            on the draft (nl2agent_apply_local_resources,
            nl2agent_finalize_agent, nl2agent_search_local_resources) read this
            field. Falls back to agent_id
            when not set (backward-compat).
        user_id: The user initiating the session.
        tenant_id: The tenant ID.
        model_id: The model ID used for LLM scoring.
        language: The language code ("zh" or "en").
    """
    agent_id: Optional[int] = None
    draft_agent_id: Optional[int] = None
    user_id: Optional[str] = None
    tenant_id: Optional[str] = None
    model_id: Optional[int] = None
    language: Optional[str] = None


# Module-level context singleton. Set by the `get_*_tool()` initializers.
_context: Optional[Nl2AgentContext] = None


def set_nl2agent_context(
    agent_id: Optional[int] = None,
    user_id: Optional[str] = None,
    tenant_id: Optional[str] = None,
    model_id: Optional[int] = None,
    language: Optional[str] = None,
    draft_agent_id: Optional[int] = None,
) -> Nl2AgentContext:
    """Set the global NL2AGENT session context. Idempotent; overwrites prior values."""
    global _context
    _context = Nl2AgentContext(
        agent_id=agent_id,
        draft_agent_id=draft_agent_id,
        user_id=user_id,
        tenant_id=tenant_id,
        model_id=model_id,
        language=language,
    )
    return _context


def get_nl2agent_context() -> Optional[Nl2AgentContext]:
    """Return the current NL2AGENT session context, or None if not set."""
    return _context
