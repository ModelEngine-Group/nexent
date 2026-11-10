# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Tool descriptions shared by the Agent compiler and Runtime materializer."""

import json

from nexent.core.agents.agent_model import ToolConfig
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
