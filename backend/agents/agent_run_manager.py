import logging
import threading
import uuid
from typing import Dict, Union

from nexent.core.agents.agent_model import AgentRunInfo
from services.runtime_state_service import runtime_state_service

logger = logging.getLogger("agent_run_manager")


class AgentRunAlreadyActiveError(RuntimeError):
    """Raised when a conversation already has an active agent run."""


class AgentRunConcurrencyExceededError(RuntimeError):
    """Raised when one agent id has reached its admitted run limit."""


class AgentRunManager:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super(AgentRunManager, cls).__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if not self._initialized:
            # user_id:conversation_id -> agent_run_info
            self.agent_runs: Dict[str, AgentRunInfo] = {}
            self._reservations: Dict[str, str] = {}
            self._agent_capacity_counts: dict[str, int] = {}
            self._agent_capacity_tokens: dict[str, str] = {}
            self._initialized = True

    def _get_run_key(self, conversation_id: Union[int, str], user_id: str) -> str:
        """Generate unique key for agent run using user_id and conversation_id"""
        return f"{user_id}:{conversation_id}"

    def reserve_agent_run(self, conversation_id: Union[int, str], user_id: str) -> str:
        """Atomically reserve a conversation before asynchronous run preparation."""
        with self._lock:
            run_key = self._get_run_key(conversation_id, user_id)
            if run_key in self.agent_runs or run_key in self._reservations:
                raise AgentRunAlreadyActiveError(
                    f"An agent run is already active for conversation {conversation_id}"
                )
            token = uuid.uuid4().hex
            self._reservations[run_key] = token
            return token

    def reserve_agent_capacity(
        self,
        agent_id: int | str,
        max_concurrent_runs: int,
    ) -> str:
        """Atomically reserve one admitted run slot for an agent id."""
        if max_concurrent_runs <= 0:
            raise ValueError("max_concurrent_runs must be greater than zero")
        agent_key = str(agent_id)
        with self._lock:
            current = self._agent_capacity_counts.get(agent_key, 0)
            if current >= max_concurrent_runs:
                raise AgentRunConcurrencyExceededError(
                    f"Agent {agent_key} has reached its concurrent run limit"
                )
            token = uuid.uuid4().hex
            self._agent_capacity_counts[agent_key] = current + 1
            self._agent_capacity_tokens[token] = agent_key
            return token

    def release_agent_capacity(self, capacity_token: str) -> bool:
        """Release an agent admission slot exactly once."""
        with self._lock:
            agent_key = self._agent_capacity_tokens.pop(capacity_token, None)
            if agent_key is None:
                return False
            remaining = self._agent_capacity_counts[agent_key] - 1
            if remaining > 0:
                self._agent_capacity_counts[agent_key] = remaining
            else:
                del self._agent_capacity_counts[agent_key]
            return True

    def get_agent_capacity_count(self, agent_id: int | str) -> int:
        """Return the current admitted run count for one agent id."""
        with self._lock:
            return self._agent_capacity_counts.get(str(agent_id), 0)

    def release_agent_run_reservation(
        self,
        conversation_id: Union[int, str],
        user_id: str,
        reservation_token: str,
    ) -> bool:
        """Release a reservation only when the caller still owns it."""
        with self._lock:
            run_key = self._get_run_key(conversation_id, user_id)
            if self._reservations.get(run_key) != reservation_token:
                return False
            del self._reservations[run_key]
            return True

    def register_agent_run(
        self,
        conversation_id: Union[int, str],
        agent_run_info,
        user_id: str,
        reservation_token: str | None = None,
    ):
        """register agent run instance"""
        with self._lock:
            run_key = self._get_run_key(conversation_id, user_id)
            if run_key in self.agent_runs:
                raise AgentRunAlreadyActiveError(
                    f"An agent run is already active for conversation {conversation_id}"
                )
            if reservation_token is not None:
                if self._reservations.get(run_key) != reservation_token:
                    raise AgentRunAlreadyActiveError(
                        f"Agent run reservation is no longer valid for conversation {conversation_id}"
                    )
                del self._reservations[run_key]
            elif run_key in self._reservations:
                raise AgentRunAlreadyActiveError(
                    f"An agent run is already being prepared for conversation {conversation_id}"
                )
            self.agent_runs[run_key] = agent_run_info
            logger.info(
                f"register agent run instance, user_id: {user_id}, conversation_id: {conversation_id}"
            )
        runtime_state_service.register_run(
            user_id=user_id, conversation_id=conversation_id
        )

    def unregister_agent_run(
        self,
        conversation_id: Union[int, str],
        user_id: str,
        status: str = "completed",
        agent_run_info=None,
    ) -> bool:
        """unregister agent run instance"""
        removed = False
        with self._lock:
            run_key = self._get_run_key(conversation_id, user_id)
            if run_key in self.agent_runs:
                if (
                    agent_run_info is not None
                    and self.agent_runs[run_key] is not agent_run_info
                ):
                    logger.warning(
                        "ignored stale agent run unregister, user_id: %s, conversation_id: %s",
                        user_id,
                        conversation_id,
                    )
                    return False
                del self.agent_runs[run_key]
                removed = True
                logger.info(
                    f"unregister agent run instance, user_id: {user_id}, conversation_id: {conversation_id}"
                )
            else:
                logger.info(
                    f"no agent run instance found for user_id: {user_id}, conversation_id: {conversation_id}"
                )
        if removed:
            runtime_state_service.mark_run_finished(
                user_id=user_id, conversation_id=conversation_id, status=status
            )
        return removed

    def get_agent_run_info(self, conversation_id: Union[int, str], user_id: str):
        """get agent run instance"""
        run_key = self._get_run_key(conversation_id, user_id)
        return self.agent_runs.get(run_key)

    def get_active_run_count(self) -> int:
        """Return the number of registered live runs."""
        with self._lock:
            return len(self.agent_runs)

    def stop_agent_run(self, conversation_id: Union[int, str], user_id: str) -> bool:
        """stop agent run for specified conversation_id and user_id"""
        remote_signal_set = runtime_state_service.set_cancel_signal(
            user_id=user_id,
            conversation_id=conversation_id,
        )
        agent_run_info = self.get_agent_run_info(conversation_id, user_id)
        if agent_run_info is not None:
            agent_run_info.stop_event.set()
            cancellation_scope = getattr(agent_run_info, "cancellation_scope", None)
            if cancellation_scope is not None:
                cancellation_scope.cancel()
            thread_manager = getattr(agent_run_info, "thread_manager", None)
            execution_id = getattr(agent_run_info, "thread_execution_id", None)
            if thread_manager is not None and execution_id:
                thread_manager.cancel(
                    execution_id,
                    reason="agent run cancellation requested",
                    wait_timeout=0,
                    mark_stuck_on_timeout=False,
                )
            logger.info(
                f"agent run stopped, user_id: {user_id}, conversation_id: {conversation_id}"
            )
            return True
        return remote_signal_set


# create singleton instance
agent_run_manager = AgentRunManager()
