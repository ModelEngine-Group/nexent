# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Resolve one child invocation without inheriting parent model or conversation state."""

from concurrent.futures import CancelledError
from copy import deepcopy

from nexent.core.agents.contracts.config import copy_invocation_config
from nexent.core.agents.contracts.output import RunResult
from nexent.core.agents.orchestration.execution import execute_adapter
from nexent.core.concurrency.cancellation import RunTerminated
from nexent.monitor import get_agent_monitoring_context
from nexent.monitor.agent_fact import AgentRunObservation


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
        "run_role": "subagent",
        "run_timing": None,
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
    info.run_role = "subagent"
    info.run_result = None
    metadata = get_agent_monitoring_context()
    observation = (
        AgentRunObservation.from_context(metadata) if metadata and metadata.monitoring_parent_run_id else None
    )
    try:
        run_scope = observation.measure(info.stop_event) if observation is not None else None
        result = execute_adapter(info, run_scope=run_scope)
        info.attempt_outcome = info.run_result.status if isinstance(info.run_result, RunResult) else (
            "stopped" if info.stop_event.is_set() else "completed")
        return result
    except (RunTerminated, CancelledError):
        info.attempt_outcome = "stopped"
        raise
    except Exception:
        info.attempt_outcome = "failed"
        raise
    finally:
        if observation is not None:
            observation.report_terminal(info.attempt_outcome)


def child_invocation_factory(parent):
    """Inject frozen child selection without a resource-to-factory dependency."""
    def create(config, scope):
        info = child_run_info(parent, config, scope)
        return lambda task, **kwargs: invoke_child(info, task)
    return create
