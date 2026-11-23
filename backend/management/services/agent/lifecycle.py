# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Bridge local execution ownership to the existing Redis state protocol."""

from infrastructure.redis.run_state import creator_runtime_state_service, runtime_state_service
from runtime.identity import reference_options
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
        self, conversation_id, agent_run_info, user_id, reservation_token=None, *, creator=False,
    ):
        super().register_agent_run(
            conversation_id, agent_run_info, user_id, reservation_token, creator=creator,
        )
        if creator:
            # The creator Redis lease already set the run state when it claimed ownership.
            return
        runtime_state_service.register_run(
            user_id=user_id, conversation_id=conversation_id, **reference_options(agent_run_info),
        )

    def unregister_agent_run(
        self, conversation_id, user_id, status="completed", agent_run_info=None
    ):
        reference_source = agent_run_info or self.get_agent_run_info(conversation_id, user_id)
        removed = super().unregister_agent_run(
            conversation_id, user_id, status, agent_run_info
        )
        if removed:
            attrs = agent_run_info.__dict__ if agent_run_info is not None else {}
            generation = attrs.get("_runtime_execution_generation") or attrs.get("_automation_runtime_generation")
            generation_kwargs = {"generation": generation} if generation is not None else {}
            state_service = (creator_runtime_state_service
                             if reference_source is not None and reference_source.__dict__.get('_creator_runtime')
                             else runtime_state_service)
            state_service.mark_run_finished(
                user_id=user_id, conversation_id=conversation_id, status=status, **generation_kwargs,
                **reference_options(reference_source),
            )
        return removed

    def stop_creator_run(self, conversation_id, user_id, expected_generation=None):
        info = self.get_agent_run_info(conversation_id, user_id)
        try:
            remote_signal = creator_runtime_state_service.cancel_creator_run(
                user_id, conversation_id, expected_generation,
            )
        except Exception:
            remote_signal = False
        if (info is not None and info.__dict__.get('_creator_runtime')
                and (expected_generation is None
                     or info.__dict__.get('_automation_runtime_generation') == expected_generation)):
            return super().stop_agent_run(conversation_id, user_id, expected_run_info=info) or remote_signal
        return remote_signal

    def stop_agent_run(self, conversation_id, user_id, expected_generation=None, *, run_ref=None):
        ref_options = {'run_ref': run_ref} if run_ref is not None else {}
        if expected_generation is not None:
            info = self.get_agent_run_info(conversation_id, user_id)
            remote_signal_set = runtime_state_service.set_cancel_signal(
                user_id, conversation_id, expected_generation=expected_generation,
                **ref_options,
            )
            internal = info.__dict__.get('_runtime_run_reference') if info is not None else None
            if info is not None and (info.__dict__.get("_automation_runtime_generation") == expected_generation
                                     or (internal is not None and internal.run_id == expected_generation)):
                return super().stop_agent_run(conversation_id, user_id, expected_run_info=info) or remote_signal_set
            return remote_signal_set
        remote_signal_set = runtime_state_service.set_cancel_signal(
            user_id=user_id, conversation_id=conversation_id, **ref_options,
        )
        return super().stop_agent_run(conversation_id, user_id) or remote_signal_set


agent_run_manager = AgentRunManager()
