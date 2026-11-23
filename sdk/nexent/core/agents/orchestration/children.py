# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Resolve one child invocation without inheriting parent model or conversation state."""

import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from nexent.core.agents.contracts.config import copy_invocation_config
from nexent.core.agents.orchestration.execution import execute_adapter


def child_run_info(parent, config, scope, *, parallel_mode=None):
    """Keep trusted request resources while selecting the child's frozen model binding."""
    config = copy_invocation_config(config)
    models = [model.model_copy(deep=True) for model in parent.model_config_list]
    binding = config.runtime_model_config
    if binding is not None:
        if binding.cite_name != config.model_name:
            raise ValueError("Child model binding alias mismatch")
        models = [model for model in models if model.cite_name != config.model_name]
        models.append(binding.model_copy(deep=True))
    updates = {
        "run_role": "subagent",
        "parallel_child_mode": parallel_mode,
        "published_child_files": [],
        "agent_config": config, "model_config_list": models, "query": "",
        "stop_event": scope.stop_event, "cancellation_scope": scope,
        "user_context": deepcopy(parent.user_context), "runtime_metadata": deepcopy(parent.runtime_metadata),
        "history": None, "context_input": None, "minio_files": [], "workspace_run_id": None,
        "context_budget_snapshot": config.context_budget_snapshot,
        "capacity_snapshot": config.capacity_snapshot,
        "enable_planning": config.enable_planning,
        "thread_execution_id": None, "thread_future": None, "attempt_outcome": None, "run_result": None,
    }
    if parallel_mode == "sandbox":
        workspace_id = uuid4().hex
        workspace = str(Path(parent.workspace_path).parent.resolve() / workspace_id)
        sandbox = parent.sandbox_config
        updates.update(
            workspace_path=workspace, workspace_run_id=workspace_id, minio_files=deepcopy(parent.minio_files),
            sandbox_config=replace(sandbox, failure_policy="error", output_dir=str(Path(workspace) / "outputs"),
                                   extra_kwargs={**sandbox.extra_kwargs, "workspace_path": workspace}),
        )
        for tool in config.tools:
            if tool.class_name in {"DownloadFromS3Tool", "UploadToS3Tool"}:
                tool.params = {**(tool.params or {}), "workspace_path": workspace}
                tool.metadata = {**(tool.metadata or {}), "run_id": workspace_id}
            elif tool.class_name in {"ReadFileTool", "ListDirectoryTool"}:
                tool.params = {**(tool.params or {}), "init_path": str(Path(workspace) / "outputs")}
    return parent.model_copy(update=updates)


def invoke_child(info, task):
    """Select the configured Core and close its resources even after partial preparation."""
    if not isinstance(task, str) or not task.strip():
        raise ValueError("Child task must be a non-empty string")
    info.query = task
    info.run_role = "subagent"
    answer = execute_adapter(info)
    if info.published_child_files:
        return json.dumps({"answer": answer, "artifacts": info.published_child_files}, ensure_ascii=False)
    return answer


def child_invocation_factory(parent, *, parallel_mode=None):
    """Inject frozen child selection without a resource-to-factory dependency."""
    def create(config, scope):
        mode = parallel_mode() if parallel_mode is not None else None
        info = child_run_info(parent, config, scope, parallel_mode=mode)
        return lambda task, **kwargs: invoke_child(info, task)
    return create
