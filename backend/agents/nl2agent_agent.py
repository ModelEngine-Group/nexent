"""Build the ephemeral NL2Agent configuration."""

import json

from jinja2 import StrictUndefined, Template
from nexent.core.agents.agent_model import AgentConfig, ToolConfig
from nexent.core.agents.context import ContextItemInput, ContextItemType
from nexent.core.tools.parallel_executor import ParallelExecutorTool

from consts.const import LANGUAGE
from tool_collection.mcp.nl2agent_mcp_tools import (
    MAX_BINDING_CANDIDATES,
    NL2A_WRAPPER_NAME,
    RECOMMEND_RESOURCES_NAME,
    SAVE_AGENT_DRAFT_FIELDS_NAME,
    SEARCH_INSTALLED_RESOURCES_NAME,
    SEARCH_UNINSTALLED_RESOURCES_NAME,
    create_nl2agent_mcp_tool_configs,
)
from utils.prompt_template_utils import get_prompt_template

NL2AGENT_NAME = "__nl2agent_runtime__"


def build_nl2agent_system_prompt(
    language: str,
    tool_name: str = SEARCH_INSTALLED_RESOURCES_NAME,
    uninstalled_tool_name: str = SEARCH_UNINSTALLED_RESOURCES_NAME,
    recommend_tool_name: str = RECOMMEND_RESOURCES_NAME,
    wrapper_name: str = NL2A_WRAPPER_NAME,
    save_tool_name: str = SAVE_AGENT_DRAFT_FIELDS_NAME,
    max_results: int = MAX_BINDING_CANDIDATES,
) -> str:
    """Load and render the localized NL2Agent system prompt."""

    template_language = (
        LANGUAGE["EN"] if language == LANGUAGE["EN"] else LANGUAGE["ZH"]
    )
    template = get_prompt_template("nl2agent", template_language)["system_prompt"]
    return Template(template, undefined=StrictUndefined).render(
        installed_tool_name=tool_name,
        uninstalled_tool_name=uninstalled_tool_name,
        recommend_tool_name=recommend_tool_name,
        wrapper_name=wrapper_name,
        save_tool_name=save_tool_name,
        max_results=max_results,
    )


def create_nl2agent_agent_config(language: str) -> AgentConfig:
    """Create the in-memory AgentConfig for one NL2Agent request."""

    system_prompt = build_nl2agent_system_prompt(language)
    tools = create_nl2agent_mcp_tool_configs()
    tools.append(
        ToolConfig(
            class_name=ParallelExecutorTool.__name__,
            name=ParallelExecutorTool.name,
            description=ParallelExecutorTool.description,
            inputs=json.dumps(ParallelExecutorTool.inputs, ensure_ascii=False),
            output_type=ParallelExecutorTool.output_type,
            params={},
            source="local",
        )
    )
    return AgentConfig(
        name=NL2AGENT_NAME,
        description="Ephemeral natural-language agent builder",
        prompt_templates=None,
        tools=tools,
        max_steps=8,
        model_name="main_model",
        provide_run_summary=False,
        context_items=[
            ContextItemInput(
                id="system:nl2agent_prompt",
                type=ContextItemType.SYSTEM,
                content={"text": system_prompt},
                source=("prompt:nl2agent",),
                priority=100,
                metadata={"authority": "platform", "layout_order": -1},
            )
        ],
        enable_planning=False,
    )
