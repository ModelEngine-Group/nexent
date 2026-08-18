"""Build the ephemeral NL2Agent configuration."""

from jinja2 import StrictUndefined, Template
from nexent.core.agents.agent_model import AgentConfig

from consts.const import LANGUAGE
from tool_collection.mcp.nl2agent_mcp_tools import (
    MAX_TOOL_RECOMMENDATIONS,
    NL2A_WRAPPER_NAME,
    SAVE_AGENT_DRAFT_FIELDS_NAME,
    SEARCH_INSTALLED_MCP_TOOLS_NAME,
    create_nl2agent_mcp_tool_configs,
)
from utils.prompt_template_utils import get_prompt_template

NL2AGENT_NAME = "__nl2agent_runtime__"


def build_nl2agent_system_prompt(
    language: str,
    tool_name: str = SEARCH_INSTALLED_MCP_TOOLS_NAME,
    wrapper_name: str = NL2A_WRAPPER_NAME,
    save_tool_name: str = SAVE_AGENT_DRAFT_FIELDS_NAME,
    max_results: int = MAX_TOOL_RECOMMENDATIONS,
) -> str:
    """Load and render the localized NL2Agent system prompt."""

    template_language = (
        LANGUAGE["EN"] if language == LANGUAGE["EN"] else LANGUAGE["ZH"]
    )
    template = get_prompt_template("nl2agent", template_language)["system_prompt"]
    return Template(template, undefined=StrictUndefined).render(
        tool_name=tool_name,
        wrapper_name=wrapper_name,
        save_tool_name=save_tool_name,
        max_results=max_results,
    )


def create_nl2agent_agent_config(language: str) -> AgentConfig:
    """Create the in-memory AgentConfig for one NL2Agent request."""

    return AgentConfig(
        name=NL2AGENT_NAME,
        description="Ephemeral natural-language agent builder",
        prompt_templates=None,
        tools=create_nl2agent_mcp_tool_configs(),
        max_steps=8,
        model_name="main_model",
        provide_run_summary=False,
        instructions=build_nl2agent_system_prompt(language),
        enable_planning=False,
    )
