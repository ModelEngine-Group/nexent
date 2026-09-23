"""Management provider for role- and language-specific Agent templates."""

from collections.abc import Mapping

from nexent.core.agents.prompt import AgentPromptBundle
from nexent.core.prompts import load_prompt


def load_agent_prompt_bundle(
    *, is_manager: bool, language: str, template_override: Mapping | None = None,
) -> AgentPromptBundle:
    """Select a YAML template and delegate its contract validation to the SDK."""
    role = "manager" if is_manager else "managed"
    if language not in {"zh", "en"}:
        raise ValueError("unsupported Agent prompt language")
    template = template_override if template_override is not None else load_prompt(
        language, "agent/agent_manager" if is_manager else "agent/agent_worker"
    )
    return AgentPromptBundle.from_mapping(role=role, language=language, template=template)
