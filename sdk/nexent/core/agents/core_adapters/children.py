"""Resolve one child invocation without inheriting parent model or conversation state."""

from copy import deepcopy

from ..agent_model import copy_invocation_config
from .factory import AgentCoreFactory


def child_run_info(parent, config, scope):
    """Keep trusted request resources while selecting the child's frozen model binding."""
    config = copy_invocation_config(config)
    models = [model.model_copy(deep=True) for model in parent.model_config_list]
    binding = config.runtime_model_config
    if binding is not None:
        if binding.cite_name != config.model_name:
            raise ValueError("Child model binding alias mismatch")
        models = [model for model in models if model.cite_name != config.model_name]
        models.append(binding.model_copy(deep=True))
    return parent.model_copy(update={
        "agent_config": config, "model_config_list": models, "query": "",
        "stop_event": scope.stop_event, "cancellation_scope": scope,
        "user_context": deepcopy(parent.user_context), "runtime_metadata": deepcopy(parent.runtime_metadata),
        "history": None, "context_input": None, "minio_files": [], "workspace_run_id": None,
        "context_budget_snapshot": config.context_budget_snapshot,
        "capacity_snapshot": config.capacity_snapshot,
        "enable_planning": config.enable_planning,
        "thread_execution_id": None, "thread_future": None, "attempt_outcome": None, "run_result": None,
    })


def invoke_child(info, task):
    """Select the configured Core and close its resources even after partial preparation."""
    if not isinstance(task, str) or not task.strip():
        raise ValueError("Child task must be a non-empty string")
    info.query = task
    adapter = AgentCoreFactory.create(info)
    try:
        adapter.validate()
        adapter.prepare()
        return adapter.run()
    finally:
        adapter.close()
