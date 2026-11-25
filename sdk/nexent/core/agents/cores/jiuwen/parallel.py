# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Conservative admission policy for Jiuwen's native tool scheduler."""

from itertools import groupby

from nexent.core.agents.sandbox.config import SandboxLevel
from nexent.core.model_service.profiles.resolved_profile import ResolvedModelProfile


READ_ONLY_CLASSES = frozenset({
    "ReadFileTool", "ListDirectoryTool", "KnowledgeBaseSearchTool",
})
# These system tools are injected during preparation. An eligible child keeps
# them when called alone but must not acquire them in a parallel batch.
SERIAL_SYSTEM_CLASSES = frozenset({
    "DownloadFromS3Tool", "UploadToS3Tool",
})


def is_read_only_tool(config):
    return config.source in {"local", "builtin"} and config.class_name in READ_ONLY_CLASSES


def is_parallel_child(config, models):
    """Only native leaf children with known resource effects can overlap."""
    if (config.agent_core != "jiuwen" or config.response_mode != "chat"
            or config.worker_agents or config.external_a2a_agents):
        return False
    if any(not (
        is_read_only_tool(tool)
        or (tool.source == "builtin" and tool.class_name in SERIAL_SYSTEM_CLASSES)
        or (tool.source in {"local", "builtin"} and tool.class_name == "ParallelExecutorTool"
            and tool.name == "parallel_executor")
    ) for tool in config.tools):
        return False
    bound = config.runtime_model_config or next(
        (model for model in models if model.cite_name == config.model_name), None,
    )
    profile = bound.resolved_profile if bound is not None else None
    return isinstance(profile, ResolvedModelProfile) and profile.capabilities.tools.status == "supported"


def child_parallel_mode(config, run):
    """Preserve Python when the deployed Docker policy can provide an owned workspace and kernel."""
    if not is_parallel_child(config, run.model_config_list):
        return None
    if run.sandbox_config is not None and run.sandbox_config.level == SandboxLevel.DOCKER and run.workspace_path:
        return "sandbox"
    if run.sandbox_config is None or run.sandbox_config.level == SandboxLevel.LOCAL:
        return "read_only"
    return None


def concurrent_children(calls, parallel_tools, children):
    """Identify individual child calls that share a native scheduler batch."""
    result = {}
    for safe, group in groupby(calls, key=lambda call: call.name in parallel_tools):
        if safe:
            batch = list(group)
            if len(batch) > 1:
                result.update({call.provider_call_id: children[call.name] for call in batch if call.name in children})
    return result
