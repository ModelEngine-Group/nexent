import logging
import threading
from typing import TYPE_CHECKING, Dict, Union

from nexent.core.agents.agent_model import AgentRunInfo
from services.runtime_state_service import runtime_state_service

if TYPE_CHECKING:
    from nexent.core.agents.context import ContextManager, ContextManagerConfig

logger = logging.getLogger("agent_run_manager")


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
            self._initialized = True

    def _get_run_key(self, conversation_id: Union[int, str], user_id: str) -> str:
        """Generate unique key for agent run using user_id and conversation_id"""
        return f"{user_id}:{conversation_id}"

    def register_agent_run(self, conversation_id: Union[int, str], agent_run_info, user_id: str):
        """register agent run instance"""
        with self._lock:
            run_key = self._get_run_key(conversation_id, user_id)
            self.agent_runs[run_key] = agent_run_info
            logger.info(
                f"register agent run instance, user_id: {user_id}, conversation_id: {conversation_id}")
        runtime_state_service.register_run(user_id=user_id, conversation_id=conversation_id)

    def unregister_agent_run(self, conversation_id: Union[int, str], user_id: str, status: str = "completed"):
        """unregister agent run instance"""
        with self._lock:
            run_key = self._get_run_key(conversation_id, user_id)
            if run_key in self.agent_runs:
                del self.agent_runs[run_key]
                logger.info(
                    f"unregister agent run instance, user_id: {user_id}, conversation_id: {conversation_id}")
            else:
                logger.info(
                    f"no agent run instance found for user_id: {user_id}, conversation_id: {conversation_id}")
        runtime_state_service.mark_run_finished(user_id=user_id, conversation_id=conversation_id, status=status)

    def get_agent_run_info(self, conversation_id: Union[int, str], user_id: str):
        """get agent run instance"""
        run_key = self._get_run_key(conversation_id, user_id)
        return self.agent_runs.get(run_key)

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

    def create_context_manager(
        self,
        conversation_id: Union[int, str],
        config: "ContextManagerConfig",
        max_steps: int
    ) -> "ContextManager":
        """Create a ContextManager isolated to one agent run."""
        from nexent.core.agents.context import ContextManager

        logger.info(
            "Created run-scoped ContextManager for conversation_id: %s",
            conversation_id,
        )
        return ContextManager(config=config, max_steps=max_steps)

    def clear_conversation_context_manager(self, conversation_id: Union[int, str]):
        """Compatibility no-op because ContextManagers are run-scoped."""
        logger.debug(
            "No cached ContextManager to clear for conversation_id: %s",
            conversation_id,
        )


# create singleton instance
agent_run_manager = AgentRunManager()
