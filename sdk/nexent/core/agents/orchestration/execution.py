# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Common run context helpers and Adapter lifetime; no engine loop."""
import json
import logging
from copy import deepcopy
from typing import Any, Dict

from nexent.core.agents.contracts.run import AgentRunInfo
from nexent.core.concurrency import ThreadManager
from nexent.core.concurrency.helpers import get_fallback_thread_manager, shutdown_fallback_thread_manager
from nexent.core.utils.observer import ProcessType


logger = logging.getLogger("run_agent")

def _get_default_agent_thread_manager() -> ThreadManager:
    """Return a bounded fallback for direct SDK callers.

    Backend services must inject their process-local manager. The fallback keeps
    the public SDK call compatible and can be closed explicitly with
    ``shutdown_default_agent_thread_manager``.
    """
    return get_fallback_thread_manager()


async def shutdown_default_agent_thread_manager(timeout: float = 15.0):
    """Close the direct-SDK fallback manager when an embedding process exits."""
    return await shutdown_fallback_thread_manager(timeout=timeout)


def build_run_additional_args(agent_run_info: AgentRunInfo) -> Dict[str, Any]:
    """Build isolated variables for one agent run, including empty metadata."""

    return {"metadata": deepcopy(agent_run_info.runtime_metadata)}


def _get_authorized_context_items(agent_run_info: AgentRunInfo):
    """Return the run snapshot, falling back for direct SDK callers."""
    context_input = getattr(agent_run_info, "context_input", None)
    if context_input is not None:
        return tuple(context_input.items)
    return getattr(agent_run_info.agent_config, "context_items", None)


def _get_authorized_history(agent_run_info: AgentRunInfo):
    """Return the run snapshot, falling back for direct SDK callers."""
    context_input = getattr(agent_run_info, "context_input", None)
    if context_input is not None:
        # Historical runs are ContextItems. AgentMemory is reserved for this run.
        return []
    return agent_run_info.history


def _emit_uncertainty_reserve_warning(agent_run_info: AgentRunInfo) -> None:
    snapshot = getattr(agent_run_info, "context_budget_snapshot", None)
    if snapshot is None:
        return
    warnings = snapshot.warnings
    if "uncertainty_reserve_active" not in warnings:
        return

    payload = {
        "code": "uncertainty_reserve_active",
        "message": (
            "W2 applied the unified 10% uncertainty reserve because selected "
            "model capability behavior is not fully verified."
        ),
        "budget_fingerprint": snapshot.fingerprint,
        "w1_fingerprint": snapshot.w1_fingerprint,
        "uncertainty_reserve_tokens": snapshot.uncertainty_reserve_tokens,
        "effective_input_limit_tokens": snapshot.effective_input_limit_tokens,
    }
    logger.warning(
        "W2 uncertainty reserve active: budget_fingerprint=%s w1_fingerprint=%s "
        "uncertainty_reserve_tokens=%s effective_input_limit_tokens=%s",
        payload["budget_fingerprint"],
        payload["w1_fingerprint"],
        payload["uncertainty_reserve_tokens"],
        payload["effective_input_limit_tokens"],
    )
    try:
        agent_run_info.observer.add_message(
            "",
            ProcessType.OTHER,
            json.dumps(payload, ensure_ascii=False),
        )
    except Exception:
        logger.debug("Failed to emit W2 uncertainty reserve observer warning", exc_info=True)


def execute_adapter(info):
    """Release an Adapter even when validation or preparation raises."""
    from nexent.core.agents.factory import AgentCoreFactory
    adapter = AgentCoreFactory.create(info)
    try:
        adapter.validate()
        adapter.prepare()
        return adapter.run()
    finally:
        adapter.close()
