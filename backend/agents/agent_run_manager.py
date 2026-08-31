import logging
import threading
import uuid
from typing import Dict, Union

from nexent.core.agents.agent_model import AgentRunInfo
from services.runtime_state_service import runtime_state_service

logger = logging.getLogger("agent_run_manager")


class AgentRunAlreadyActiveError(RuntimeError):
    """Raised when a conversation already has an active agent run."""


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
                f"register agent run instance, user_id: {user_id}, conversation_id: {conversation_id}")
        runtime_state_service.register_run(user_id=user_id, conversation_id=conversation_id)

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
                if agent_run_info is not None and self.agent_runs[run_key] is not agent_run_info:
                    logger.warning(
                        "ignored stale agent run unregister, user_id: %s, conversation_id: %s",
                        user_id,
                        conversation_id,
                    )
                    return False
                del self.agent_runs[run_key]
                removed = True
                logger.info(
                    f"unregister agent run instance, user_id: {user_id}, conversation_id: {conversation_id}")
            else:
                logger.info(
                    f"no agent run instance found for user_id: {user_id}, conversation_id: {conversation_id}")
        if removed:
            runtime_state_service.mark_run_finished(user_id=user_id, conversation_id=conversation_id, status=status)
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
            logger.info(
                f"agent run stopped, user_id: {user_id}, conversation_id: {conversation_id}")
            return True
        return remote_signal_set

# create singleton instance
agent_run_manager = AgentRunManager()
