import logging
import threading
from typing import Dict

from nexent.core.agents.agent_model import AgentRunInfo

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
            # conversation_id -> agent_run_info
            self.agent_runs: Dict[int, AgentRunInfo] = {}
            self._initialized = True

    def register_agent_run(self, conversation_id: int, agent_run_info):
        """register agent run instance"""
        with self._lock:
            self.agent_runs[conversation_id] = agent_run_info
            logger.info(
                f"register agent run instance, conversation_id: {conversation_id}")

    def unregister_agent_run(self, conversation_id: int):
        """unregister agent run instance"""
        with self._lock:
            if conversation_id in self.agent_runs:
                del self.agent_runs[conversation_id]
                logger.info(
                    f"unregister agent run instance, conversation_id: {conversation_id}")
            else:
                logger.info(
                    f"no agent run instance found for conversation_id: {conversation_id}")

    def get_agent_run_info(self, conversation_id: int):
        """get agent run instance"""
        return self.agent_runs.get(conversation_id)

    def stop_agent_run(self, conversation_id: int) -> bool:
        """stop agent run for specified conversation_id"""
        agent_run_info = self.get_agent_run_info(conversation_id)
        if agent_run_info is not None:
            agent_run_info.stop_event.set()
            logger.info(
                f"agent run stopped, conversation_id: {conversation_id}")
            return True
        return False


# create singleton instance
agent_run_manager = AgentRunManager()
