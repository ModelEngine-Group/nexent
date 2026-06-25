import logging
import threading
from typing import Dict, Union

from nexent.core.agents.agent_model import AgentRunInfo
from nexent.core.agents.agent_context import ContextManager, ContextManagerConfig

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
            # conversation_id -> ContextManager (conversation-level lifetime)
            self._conversation_context_managers: Dict[str, ContextManager] = {}
            # conversation_id -> active run count for safe cleanup
            self._conversation_run_counts: Dict[str, int] = {}
            self._initialized = True

    def _get_run_key(self, conversation_id: Union[int, str], user_id: str) -> str:
        """Generate unique key for agent run using user_id and conversation_id"""
        return f"{user_id}:{conversation_id}"

    def register_agent_run(self, conversation_id: Union[int, str], agent_run_info, user_id: str):
        """register agent run instance"""
        with self._lock:
            run_key = self._get_run_key(conversation_id, user_id)
            self.agent_runs[run_key] = agent_run_info
            conv_key = str(conversation_id)
            self._conversation_run_counts[conv_key] = self._conversation_run_counts.get(conv_key, 0) + 1
            logger.info(
                f"register agent run instance, user_id: {user_id}, conversation_id: {conversation_id}")

    def unregister_agent_run(self, conversation_id: Union[int, str], user_id: str):
        """unregister agent run instance"""
        with self._lock:
            run_key = self._get_run_key(conversation_id, user_id)
            if run_key in self.agent_runs:
                del self.agent_runs[run_key]
                conv_key = str(conversation_id)
                self._conversation_run_counts[conv_key] = max(
                    0, self._conversation_run_counts.get(conv_key, 0) - 1
                )
                logger.info(
                    f"unregister agent run instance, user_id: {user_id}, conversation_id: {conversation_id}")
            else:
                logger.info(
                    f"no agent run instance found for user_id: {user_id}, conversation_id: {conversation_id}")

    def get_agent_run_info(self, conversation_id: Union[int, str], user_id: str):
        """get agent run instance"""
        run_key = self._get_run_key(conversation_id, user_id)
        return self.agent_runs.get(run_key)

    def stop_agent_run(self, conversation_id: Union[int, str], user_id: str) -> bool:
        """stop agent run for specified conversation_id and user_id"""
        agent_run_info = self.get_agent_run_info(conversation_id, user_id)
        if agent_run_info is not None:
            agent_run_info.stop_event.set()
            logger.info(
                f"agent run stopped, user_id: {user_id}, conversation_id: {conversation_id}")
            return True
        return False

    def get_or_create_context_manager(
        self,
        conversation_id: Union[int, str],
        config: ContextManagerConfig,
        max_steps: int
    ) -> ContextManager:
        """Get or create a conversation-level ContextManager instance."""
        conv_key = str(conversation_id)
        with self._lock:
            cm = self._conversation_context_managers.get(conv_key)
            if cm is None:
                cm = ContextManager(config=config, max_steps=max_steps)
                self._conversation_context_managers[conv_key] = cm
                logger.info(
                    f"Created new ContextManager for conversation_id: {conv_key}")
            return cm

    def clear_conversation_context_manager(self, conversation_id: Union[int, str]):
        """Explicitly clear the ContextManager for a conversation."""
        conv_key = str(conversation_id)
        with self._lock:
            cm = self._conversation_context_managers.pop(conv_key, None)
            self._conversation_run_counts.pop(conv_key, None)
            if cm:
                logger.info(
                    f"Cleared ContextManager for conversation_id: {conv_key}")


# create singleton instance
agent_run_manager = AgentRunManager()
