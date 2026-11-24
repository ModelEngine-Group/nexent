# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Build the ephemeral NL2Agent configuration."""

import json

from contracts.constants.constants import LANGUAGE
from contracts.constants.environment import NEXENT_AGENT_CORE
from infrastructure.agent_core_policy import apply_agent_core_policy
from nexent.core.agents.contracts.config import AgentConfig, ToolConfig
from nexent.core.agents.context import ContextItemInput, ContextItemType
from nexent.core.agents.prompt.meta import compose_nl2agent_system
from nexent.core.tools.parallel_executor import ParallelExecutorTool
from infrastructure.nl2agent_tool_config import (
    MAX_BINDING_CANDIDATES,
    NL2A_WRAPPER_NAME,
    RECOMMEND_RESOURCES_NAME,
    SAVE_AGENT_DRAFT_FIELDS_NAME,
    SEARCH_INSTALLED_RESOURCES_NAME,
    SEARCH_UNINSTALLED_RESOURCES_NAME,
)

NL2AGENT_NAME = "nl2agent_main"


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

    template_language = LANGUAGE["EN"] if language == LANGUAGE["EN"] else LANGUAGE["ZH"]
    return compose_nl2agent_system(
        template_language,
        {
            "installed_tool_name": tool_name,
            "uninstalled_tool_name": uninstalled_tool_name,
            "recommend_tool_name": recommend_tool_name,
            "wrapper_name": wrapper_name,
            "save_tool_name": save_tool_name,
            "max_results": max_results,
            "target_core": NEXENT_AGENT_CORE,
        },
    )


def create_nl2agent_agent_config(language: str, tools: list[ToolConfig], snapshot: dict | None = None) -> AgentConfig:
    """Create the in-memory AgentConfig for one NL2Agent request."""

    system_prompt = build_nl2agent_system_prompt(language)
    tools = list(tools)
    tools.append(
        ToolConfig(
            class_name=ParallelExecutorTool.__name__,
            name=ParallelExecutorTool.name,
            description=ParallelExecutorTool.description,
            description_zh=ParallelExecutorTool.description_zh,
            inputs=json.dumps(ParallelExecutorTool.inputs, ensure_ascii=False),
            output_type=ParallelExecutorTool.output_type,
            params={},
            source="local",
        )
    )
    config = AgentConfig(
        response_mode="python_workflow",
        agent_id=snapshot["agent_id"] if snapshot is not None else None,
        version_no=snapshot["version_no"] if snapshot is not None else None,
        runtime_ref=(f"agent:{snapshot['agent_id']}:v{snapshot['version_no']}" if snapshot is not None else None),
        origin="SYSTEM",
        name=NL2AGENT_NAME,
        display_name="创建智能体",
        description=(
            snapshot["description"] if snapshot is not None and snapshot.get("description")
            else "Natural-language agent builder"
        ),
        prompt_templates=None,
        tools=tools,
        max_steps=int(snapshot["max_steps"]) if snapshot is not None else 8,
        model_name="main_model",
        provide_run_summary=False,
        automatic_memory_enabled=False,
        enable_protocol_repair_retry=snapshot.get("enable_protocol_repair_retry", True) if snapshot is not None else True,
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
    return apply_agent_core_policy(config, NEXENT_AGENT_CORE)
