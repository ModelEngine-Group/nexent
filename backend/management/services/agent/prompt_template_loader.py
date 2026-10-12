"""Management provider for role- and language-specific Agent templates."""

from collections.abc import Mapping

from nexent.core.agents.prompt import AgentPromptBundle


def load_agent_prompt_bundle(
    *, is_manager: bool, language: str, template_override: Mapping | None = None,
) -> AgentPromptBundle:
    """Select a YAML template and delegate its contract validation to the SDK."""
    role = "manager" if is_manager else "managed"
    if language not in {"zh", "en"}:
        raise ValueError("unsupported Agent prompt language")
    return AgentPromptBundle.from_resource(
        role=role, language=language, template_override=template_override,
    )
