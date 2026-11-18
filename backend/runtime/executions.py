# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import logging

from contracts.errors.exceptions import (
    AgentRunAlreadyActiveError as AgentRunAlreadyActiveError,
    AgentRunConcurrencyExceededError as AgentRunConcurrencyExceededError,
)
from infrastructure.local_execution_registry import LocalExecutionRegistry as LocalExecutionRegistry
from infrastructure.redis.run_state import runtime_state_service


logger = logging.getLogger("agent_run_manager")


class AgentRunManager(LocalExecutionRegistry):
    """Mirror local execution lifecycle to the shared Redis state protocol."""

    def register_agent_run(
        self, conversation_id, agent_run_info, user_id, reservation_token=None
    ):
        super().register_agent_run(
            conversation_id, agent_run_info, user_id, reservation_token
        )
        options = {}
        if isinstance(conversation_id, str) and conversation_id.startswith("debug-"):
            options["tenant_id"] = getattr(agent_run_info, "tenant_id", None)
        runtime_state_service.register_run(user_id=user_id, conversation_id=conversation_id, **options)

    def unregister_agent_run(
        self, conversation_id, user_id, status="completed", agent_run_info=None
    ):
        removed = super().unregister_agent_run(
            conversation_id, user_id, status, agent_run_info
        )
        if removed:
            runtime_state_service.mark_run_finished(
                user_id=user_id, conversation_id=conversation_id, status=status
            )
        return removed

    def stop_agent_run(self, conversation_id, user_id):
        remote_signal_set = runtime_state_service.set_cancel_signal(
            user_id=user_id, conversation_id=conversation_id
        )
        return super().stop_agent_run(conversation_id, user_id) or remote_signal_set


agent_run_manager = AgentRunManager()


def registered_stop_response(run_id: int | str, user_id: str, stopped: bool) -> dict:
    """Present the public stop result without exposing an internal registry key."""
    if stopped:
        message = f"successfully stopped agent run for user_id {user_id}, run_id {run_id}"
    else:
        message = f"no running agent or preprocess tasks found for user_id {user_id}, run_id {run_id}"
    logger.info(message)
    result = {"status": "success", "message": message}
    if not stopped:
        result["already_stopped"] = True
    return result


def stop_registered_run(run_id: int | str, user_id: str) -> dict:
    """Cancel Runtime's live run while preserving the legacy response shape."""
    return registered_stop_response(run_id, user_id, agent_run_manager.stop_agent_run(run_id, user_id))
