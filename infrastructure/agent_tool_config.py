# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Tool descriptions shared by the Agent compiler and Runtime materializer."""

import json

from nexent.core.agents.agent_model import ToolConfig
from nexent.core.agents.prompt import get_builtin_tool_descriptions
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
