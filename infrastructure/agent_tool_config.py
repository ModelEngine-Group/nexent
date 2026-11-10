# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Tool descriptions shared by the Agent compiler and Runtime materializer."""

import json

from nexent.core.agents.agent_model import ToolConfig
from nexent.core.agents.prompt import get_builtin_tool_descriptions
from nexent.core.tools.create_scheduled_task_tool import CreateScheduledTaskProposalTool
from nexent.core.tools.parallel_executor import ParallelExecutorTool


def build_parallel_executor_tool_config(default_timeout_seconds: int) -> ToolConfig:
    return ToolConfig(
        class_name=ParallelExecutorTool.__name__,
        name=ParallelExecutorTool.name,
        description=ParallelExecutorTool.description,
        description_zh=ParallelExecutorTool.description_zh,
        inputs=json.dumps(
            ParallelExecutorTool.inputs_for_timeout(default_timeout_seconds),
            ensure_ascii=False,
        ),
        output_type=ParallelExecutorTool.output_type,
        params={"default_timeout_seconds": default_timeout_seconds},
        source="local",
    )


_PLAN_TOOLS = (
    ("create_plan", "CreatePlanTool", '{"title": "string", "steps": "array"}'),
    ("update_plan_step", "UpdatePlanStepTool", '{"step_id": "string", "status": "string"}'),
)
PLAN_TOOL_NAMES = frozenset(name for name, _, _ in _PLAN_TOOLS)


def build_plan_tool_configs() -> list[ToolConfig]:
    """Construct the fixed planning tools without accepting remote configuration."""
    prose_en = get_builtin_tool_descriptions("en")
    prose_zh = get_builtin_tool_descriptions("zh")
    return [
        ToolConfig(
            class_name=class_name, name=name, description=prose_en[name], description_zh=prose_zh[name],
            inputs=inputs, output_type="object", params={}, source="builtin",
        )
        for name, class_name, inputs in _PLAN_TOOLS
    ]

AUTOMATION_PROPOSAL_TOOL = CreateScheduledTaskProposalTool.name


def build_automation_proposal_tool(callback=None) -> ToolConfig:
    return ToolConfig(
        class_name=CreateScheduledTaskProposalTool.__name__,
        name=AUTOMATION_PROPOSAL_TOOL,
        description=CreateScheduledTaskProposalTool.description,
        description_zh=CreateScheduledTaskProposalTool.description_zh,
        inputs=json.dumps(CreateScheduledTaskProposalTool.inputs, ensure_ascii=False),
        output_type=CreateScheduledTaskProposalTool.output_type,
        params={},
        source="builtin",
        usage="builtin",
        metadata={"create_proposal": callback} if callback is not None else None,
    )


STORE_MEMORY_TOOL = "store_memory"


def build_store_memory_tool(memory_metadata: dict | None) -> ToolConfig:
    return ToolConfig(
        class_name="StoreMemoryTool",
        name=STORE_MEMORY_TOOL,
        description=(
            "Store one model-selected and summarized short-term memory extracted only "
            "from the conversation between the user and the current agent. Eligible "
            "information is limited to process-level observations made during intermediate "
            "action steps: user preferences, task goals, action plans and latest progress, "
            "or reflections on user feedback and errors. Do not store whole conversations, "
            "transient calculations, unverified guesses, duplicates, secrets, or information "
            "the user asks to forget. Call this tool only during intermediate action steps, "
            "not when generating the final answer."
        ),
        inputs=json.dumps(
            {
                "content": {
                    "type": "string",
                    "description": (
                        "One concise, reusable short-term memory entry already judged, "
                        "summarized, and deduplicated by the model"
                    ),
                    "description_zh": (
                        "由模型判断、总结并去重后的一条简洁、可复用的短期记忆"
                    ),
                }
            },
            ensure_ascii=False,
        ),
        output_type="string",
        params={},
        source="local",
        usage=None,
        metadata=memory_metadata,
    )
