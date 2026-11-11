# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Bridge local execution ownership to the existing Redis state protocol."""

from management.services.agent.run_state import runtime_state_service
from runtime.executions import (
    AgentRunAlreadyActiveError,
    AgentRunConcurrencyExceededError,
    LocalExecutionRegistry,
)

__all__ = [
    "AgentRunAlreadyActiveError",
    "AgentRunConcurrencyExceededError",
    "AgentRunManager",
    "agent_run_manager",
]


class AgentRunManager(LocalExecutionRegistry):
    """Preserve the legacy API while isolating local worker resources."""

    def register_agent_run(
        self, conversation_id, agent_run_info, user_id, reservation_token=None
    ):
        super().register_agent_run(
            conversation_id, agent_run_info, user_id, reservation_token
        )
        runtime_state_service.register_run(
            user_id=user_id, conversation_id=conversation_id
        )

    def unregister_agent_run(
        self, conversation_id, user_id, status="completed", agent_run_info=None
    ):
        removed = super().unregister_agent_run(
            conversation_id, user_id, status, agent_run_info
        )
        if removed:
            generation = agent_run_info.__dict__.get("_automation_runtime_generation") if agent_run_info is not None else None
            generation_kwargs = {"generation": generation} if generation is not None else {}
            runtime_state_service.mark_run_finished(
                user_id=user_id, conversation_id=conversation_id, status=status, **generation_kwargs
            )
        return removed

    def stop_agent_run(self, conversation_id, user_id, expected_generation=None):
        if expected_generation is not None:
            info = self.get_agent_run_info(conversation_id, user_id)
            remote_signal_set = runtime_state_service.set_cancel_signal(
                user_id, conversation_id, expected_generation=expected_generation,
            )
            if info is not None and info.__dict__.get("_automation_runtime_generation") == expected_generation:
                return super().stop_agent_run(conversation_id, user_id, expected_run_info=info) or remote_signal_set
            return remote_signal_set
        remote_signal_set = runtime_state_service.set_cancel_signal(
            user_id=user_id, conversation_id=conversation_id
        )
        return super().stop_agent_run(conversation_id, user_id) or remote_signal_set


agent_run_manager = AgentRunManager()
