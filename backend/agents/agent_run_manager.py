import logging
import os
import threading
from collections import OrderedDict
from typing import Dict, Union

from nexent.core.agents.agent_model import AgentRunInfo
from nexent.core.agents.agent_context import ContextManager, ContextManagerConfig

logger = logging.getLogger("agent_run_manager")

DEFAULT_CONTEXT_MANAGER_CACHE_MAX_SIZE = 128


def _get_context_manager_cache_max_size() -> int:
    raw_value = os.getenv(
        "NEXENT_CONTEXT_MANAGER_CACHE_MAX_SIZE",
        str(DEFAULT_CONTEXT_MANAGER_CACHE_MAX_SIZE),
    )
    try:
        return max(1, int(raw_value))
    except ValueError:
        logger.warning(
            "Invalid NEXENT_CONTEXT_MANAGER_CACHE_MAX_SIZE=%r; using default %d",
            raw_value,
            DEFAULT_CONTEXT_MANAGER_CACHE_MAX_SIZE,
        )
        return DEFAULT_CONTEXT_MANAGER_CACHE_MAX_SIZE


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
            self._conversation_context_managers: OrderedDict[
                str, ContextManager
            ] = OrderedDict()
            # conversation_id -> active run count for safe cleanup
            self._conversation_run_counts: Dict[str, int] = {}
            self._context_manager_cache_max_size = (
                _get_context_manager_cache_max_size()
            )
            self._initialized = True

    def _evict_idle_context_managers_locked(self):
        """Evict least-recently-used idle managers until the cache is bounded."""
        while (
            len(self._conversation_context_managers)
            > self._context_manager_cache_max_size
        ):
            idle_key = next(
                (
                    conv_key
                    for conv_key in self._conversation_context_managers
                    if self._conversation_run_counts.get(conv_key, 0) == 0
                ),
                None,
            )
            if idle_key is None:
                # Active conversations are never evicted. A later unregister
                # call will retry the eviction once one becomes idle.
                return
            self._conversation_context_managers.pop(idle_key, None)
            self._conversation_run_counts.pop(idle_key, None)
            logger.info(
                "Evicted idle ContextManager for conversation_id: %s "
                "(cache_size=%d, max_size=%d)",
                idle_key,
                len(self._conversation_context_managers),
                self._context_manager_cache_max_size,
            )

    def _get_run_key(self, conversation_id: Union[int, str], user_id: str) -> str:
        """Generate unique key for agent run using user_id and conversation_id"""
        return f"{user_id}:{conversation_id}"

    def register_agent_run(self, conversation_id: Union[int, str], agent_run_info, user_id: str):
        """register agent run instance"""
        with self._lock:
            run_key = self._get_run_key(conversation_id, user_id)
            is_new_run = run_key not in self.agent_runs
            self.agent_runs[run_key] = agent_run_info
            conv_key = str(conversation_id)
            if is_new_run:
                self._conversation_run_counts[conv_key] = (
                    self._conversation_run_counts.get(conv_key, 0) + 1
                )
            if conv_key in self._conversation_context_managers:
                self._conversation_context_managers.move_to_end(conv_key)
            logger.info(
                f"register agent run instance, user_id: {user_id}, conversation_id: {conversation_id}")

    def unregister_agent_run(self, conversation_id: Union[int, str], user_id: str):
        """unregister agent run instance"""
        with self._lock:
            run_key = self._get_run_key(conversation_id, user_id)
            if run_key in self.agent_runs:
                del self.agent_runs[run_key]
                conv_key = str(conversation_id)
                remaining_runs = max(
                    0, self._conversation_run_counts.get(conv_key, 0) - 1
                )
                if (
                    remaining_runs == 0
                    and conv_key not in self._conversation_context_managers
                ):
                    self._conversation_run_counts.pop(conv_key, None)
                else:
                    self._conversation_run_counts[conv_key] = remaining_runs
                self._evict_idle_context_managers_locked()
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
            else:
                self._conversation_context_managers.move_to_end(conv_key)
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
