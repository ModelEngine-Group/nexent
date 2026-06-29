import logging
import threading
from typing import TYPE_CHECKING, Any, Dict, Optional, Union

from nexent.core.agents.agent_model import AgentRunInfo, ContextIdentity

if TYPE_CHECKING:
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
            # ContextIdentity.canonical_key -> agent_run_info
            self.agent_runs: Dict[str, AgentRunInfo] = {}
            # ContextIdentity.canonical_key -> ContextManager (conversation-level lifetime)
            self._conversation_context_managers: Dict[str, Any] = {}
            # ContextIdentity.canonical_key -> active run count for safe cleanup
            self._conversation_run_counts: Dict[str, int] = {}
            self._initialized = True

    def _context_identity(
        self,
        conversation_id: Union[int, str],
        user_id: str,
        tenant_id: Optional[str] = None,
    ) -> ContextIdentity:
        """Resolve the context identity used for runtime state keying."""
        if not tenant_id:
            raise ValueError("tenant_id is required for ContextIdentity")
        return ContextIdentity(
            tenant_id=str(tenant_id),
            user_id=str(user_id),
            conversation_id=str(conversation_id),
        )

    def _get_run_key(
        self,
        conversation_id: Union[int, str],
        user_id: str,
        tenant_id: Optional[str] = None,
    ) -> str:
        """Generate unique key for agent run using full ContextIdentity."""
        return self._context_identity(conversation_id, user_id, tenant_id).canonical_key

    def register_agent_run(
        self,
        conversation_id: Union[int, str],
        agent_run_info,
        user_id: str,
        tenant_id: Optional[str] = None,
    ):
        """register agent run instance"""
        with self._lock:
            identity = self._context_identity(conversation_id, user_id, tenant_id)
            run_key = identity.canonical_key
            self.agent_runs[run_key] = agent_run_info
            conv_key = identity.canonical_key
            self._conversation_run_counts[conv_key] = self._conversation_run_counts.get(conv_key, 0) + 1
            logger.info(
                f"register agent run instance, identity: {identity.canonical_key}")

    def unregister_agent_run(
        self,
        conversation_id: Union[int, str],
        user_id: str,
        tenant_id: Optional[str] = None,
    ):
        """unregister agent run instance"""
        with self._lock:
            identity = self._context_identity(conversation_id, user_id, tenant_id)
            run_key = identity.canonical_key
            if run_key in self.agent_runs:
                del self.agent_runs[run_key]
                conv_key = identity.canonical_key
                self._conversation_run_counts[conv_key] = max(
                    0, self._conversation_run_counts.get(conv_key, 0) - 1
                )
                logger.info(
                    f"unregister agent run instance, identity: {identity.canonical_key}")
            else:
                logger.info(
                    f"no agent run instance found for identity: {identity.canonical_key}")

    def get_agent_run_info(
        self,
        conversation_id: Union[int, str],
        user_id: str,
        tenant_id: Optional[str] = None,
    ):
        """get agent run instance"""
        run_key = self._get_run_key(conversation_id, user_id, tenant_id)
        return self.agent_runs.get(run_key)

    def stop_agent_run(
        self,
        conversation_id: Union[int, str],
        user_id: str,
        tenant_id: Optional[str] = None,
    ) -> bool:
        """stop agent run for specified conversation_id and user_id"""
        agent_run_info = self.get_agent_run_info(conversation_id, user_id, tenant_id)
        if agent_run_info is not None:
            agent_run_info.stop_event.set()
            logger.info(
                f"agent run stopped, identity: {self._get_run_key(conversation_id, user_id, tenant_id)}")
            return True
        return False

    def get_or_create_context_manager(
        self,
        conversation_id: Union[int, str],
        config: "ContextManagerConfig",
        max_steps: int,
        user_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
    ) -> "ContextManager":
        """Get or create a conversation-level ContextManager instance."""
        from nexent.core.agents.agent_context import ContextManager

        if user_id is None:
            raise ValueError("user_id is required to create a ContextManager")
        identity = self._context_identity(conversation_id, user_id, tenant_id)
        conv_key = identity.canonical_key
        with self._lock:
            cm = self._conversation_context_managers.get(conv_key)
            if cm is None:
                cm = ContextManager(config=config, max_steps=max_steps)
                self._conversation_context_managers[conv_key] = cm
                logger.info(
                    f"Created new ContextManager for identity: {conv_key}")
            return cm

    def clear_conversation_context_manager(
        self,
        conversation_id: Union[int, str],
        user_id: str,
        tenant_id: Optional[str] = None,
    ):
        """Explicitly clear the ContextManager for a conversation."""
        identity = self._context_identity(conversation_id, user_id, tenant_id)
        conv_key = identity.canonical_key
        with self._lock:
            cm = self._conversation_context_managers.pop(conv_key, None)
            self._conversation_run_counts.pop(conv_key, None)
            if cm:
                logger.info(
                    f"Cleared ContextManager for identity: {conv_key}")


# create singleton instance
agent_run_manager = AgentRunManager()
