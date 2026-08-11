"""Build the ephemeral NL2Skill agent configuration."""

from nexent.core.agents.agent_model import AgentConfig


NL2SKILL_NAME = "__skill_creator__"


def create_nl2skill_agent_config(
    system_prompt: str,
    model_name: str,
) -> AgentConfig:
    """Create one request-scoped skill creator without persistent state."""

    return AgentConfig(
        name=NL2SKILL_NAME,
        description="Ephemeral natural-language skill builder",
        prompt_templates=None,
        tools=[],
        max_steps=5,
        model_name=model_name,
        provide_run_summary=False,
        instructions=system_prompt,
        enable_planning=False,
    )
