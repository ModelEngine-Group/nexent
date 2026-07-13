import logging
import threading
import uuid
from typing import TYPE_CHECKING, Any, Dict, Union

from services.agent_runtime.config import get_deployment_agent_runtime_provider
from services.agent_runtime.models import ActiveRunHandle, RunControl, RunStatus
from services.runtime_state_service import runtime_state_service

if TYPE_CHECKING:
    from nexent.core.agents.agent_context import ContextManager, ContextManagerConfig
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
            # user_id:conversation_id -> agent_run_info
            self.agent_runs: Dict[str, "AgentRunInfo"] = {}
            # user_id:conversation_id or user_id:request:<request_id> -> active run handle
            self.active_run_handles: Dict[str, ActiveRunHandle] = {}
            # conversation_id -> ContextManager (conversation-level lifetime)
            self._conversation_context_managers: Dict[str, Any] = {}
            # conversation_id -> active run count for safe cleanup
            self._conversation_run_counts: Dict[str, int] = {}
            self._initialized = True

    def _get_run_key(
        self,
        conversation_id: Union[int, str, None],
        user_id: str,
        request_id: str | None = None,
    ) -> str:
        """Generate unique key for agent run using user_id and conversation_id"""
        if conversation_id is None and request_id:
            return f"{user_id}:request:{request_id}"
        return f"{user_id}:{conversation_id}"

    def _get_request_run_key(self, request_id: str, user_id: str) -> str:
        """Generate the internal request-scoped active run key."""
        return f"{user_id}:request:{request_id}"

    def register_agent_run(
        self,
        conversation_id: Union[int, str, None],
        agent_run_info,
        user_id: str,
        request_id: str | None = None,
        runtime_provider: str | None = None,
        event_sink: Any | None = None,
        run_control: RunControl | None = None,
    ):
        """register agent run instance"""
        request_id = request_id or str(uuid.uuid4())
        runtime_provider = runtime_provider or get_deployment_agent_runtime_provider()
        run_control = run_control or RunControl(
            request_id=request_id,
            user_id=user_id,
            conversation_id=conversation_id,
            legacy_stop_event=getattr(agent_run_info, "stop_event", None),
        )
        handle = ActiveRunHandle(
            request_id=request_id,
            user_id=user_id,
            conversation_id=conversation_id,
            runtime_provider=runtime_provider,
            run_control=run_control,
            event_sink=event_sink,
            legacy_agent_run_info=agent_run_info,
            status=RunStatus.RUNNING,
        )
        with self._lock:
            request_run_key = self._get_request_run_key(request_id, user_id)
            self.active_run_handles[request_run_key] = handle
            if conversation_id is not None:
                # Preserve the legacy conversation key for callers that stop by conversation.
                legacy_run_key = self._get_run_key(conversation_id, user_id)
                self.agent_runs[legacy_run_key] = agent_run_info
                self.active_run_handles[legacy_run_key] = handle
            else:
                self.agent_runs[request_run_key] = agent_run_info
            conv_key = str(conversation_id if conversation_id is not None else request_id)
            self._conversation_run_counts[conv_key] = self._conversation_run_counts.get(conv_key, 0) + 1
            logger.info(
                f"register agent run instance, user_id: {user_id}, conversation_id: {conversation_id}")
        if conversation_id is not None:
            runtime_state_service.register_run(user_id=user_id, conversation_id=conversation_id)

    def unregister_agent_run(
        self,
        conversation_id: Union[int, str, None],
        user_id: str,
        status: str = "completed",
        request_id: str | None = None,
    ):
        """unregister agent run instance"""
        with self._lock:
            run_key = self._get_run_key(conversation_id, user_id, request_id=request_id)
            run_keys = {run_key}
            if request_id:
                run_keys.add(self._get_request_run_key(request_id, user_id))
            if conversation_id is not None:
                run_keys.add(self._get_run_key(conversation_id, user_id))
            removed = False
            for key in run_keys:
                removed = key in self.agent_runs or key in self.active_run_handles or removed
                self.agent_runs.pop(key, None)
                self.active_run_handles.pop(key, None)
            if removed:
                conv_key = str(conversation_id if conversation_id is not None else request_id)
                self._conversation_run_counts[conv_key] = max(
                    0, self._conversation_run_counts.get(conv_key, 0) - 1
                )
                logger.info(
                    f"unregister agent run instance, user_id: {user_id}, conversation_id: {conversation_id}")
            else:
                logger.info(
                    f"no agent run instance found for user_id: {user_id}, conversation_id: {conversation_id}")
        if conversation_id is not None:
            runtime_state_service.mark_run_finished(user_id=user_id, conversation_id=conversation_id, status=status)

    def get_agent_run_info(
        self,
        conversation_id: Union[int, str, None],
        user_id: str,
        request_id: str | None = None,
    ):
        """get agent run instance"""
        run_key = self._get_run_key(conversation_id, user_id, request_id=request_id)
        return self.agent_runs.get(run_key)

    def get_active_run_handle(
        self,
        conversation_id: Union[int, str, None],
        user_id: str,
        request_id: str | None = None,
    ) -> ActiveRunHandle | None:
        """get active run handle"""
        run_key = (
            self._get_request_run_key(request_id, user_id)
            if request_id
            else self._get_run_key(conversation_id, user_id)
        )
        return self.active_run_handles.get(run_key)

    def stop_agent_run(
        self,
        conversation_id: Union[int, str, None],
        user_id: str,
        request_id: str | None = None,
    ) -> bool:
        """stop agent run for specified conversation_id and user_id"""
        remote_signal_set = False
        if conversation_id is not None:
            remote_signal_set = runtime_state_service.set_cancel_signal(
                user_id=user_id,
                conversation_id=conversation_id,
            ) is True
        handle = self.get_active_run_handle(conversation_id, user_id, request_id=request_id)
        if handle is not None:
            handle.run_control.cancel()
            handle.status = RunStatus.STOPPING
            logger.info(
                f"agent run stopped, user_id: {user_id}, conversation_id: {conversation_id}")
            return True
        agent_run_info = self.get_agent_run_info(conversation_id, user_id, request_id=request_id)
        if agent_run_info is not None:
            agent_run_info.stop_event.set()
            logger.info(
                f"agent run stopped, user_id: {user_id}, conversation_id: {conversation_id}")
            return True
        return remote_signal_set

    def get_or_create_context_manager(
        self,
        conversation_id: Union[int, str],
        config: "ContextManagerConfig",
        max_steps: int
    ) -> "ContextManager":
        """Get or create a conversation-level ContextManager instance."""
        from nexent.core.agents.agent_context import ContextManager

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
