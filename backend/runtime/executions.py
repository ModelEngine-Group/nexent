# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import logging
import threading
import uuid
from typing import Dict, Union

from nexent.core.agents.contracts.run import AgentRunInfo

logger = logging.getLogger("agent_run_manager")


class AgentRunAlreadyActiveError(RuntimeError):
    """Raised when a conversation already has an active agent run."""


class AgentRunConcurrencyExceededError(RuntimeError):
    """Raised when one agent id has reached its admitted run limit."""


class LocalExecutionRegistry:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls.__dict__.get("_instance") is None:
            with cls._lock:
                if cls.__dict__.get("_instance") is None:
                    cls._instance = super(LocalExecutionRegistry, cls).__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if not self._initialized:
            # user_id:conversation_id -> agent_run_info
            self.agent_runs: Dict[str, AgentRunInfo] = {}
            self._reservations: Dict[str, str] = {}
            self._agent_capacity_counts: dict[str, int] = {}
            self._agent_capacity_tokens: dict[str, str] = {}
            self._coordinator = None
            self._distributed_leases = {}
            self._initialized = True

    def _get_run_key(self, conversation_id: Union[int, str], user_id: str) -> str:
        """Generate unique key for agent run using user_id and conversation_id"""
        return f"{user_id}:{conversation_id}"

    def configure_coordinator(self, coordinator):
        """Install deployment-owned coordination before admitting any business work."""
        with self._lock:
            if self.agent_runs or self._reservations:
                raise RuntimeError('Cannot change coordination with admitted Runtime work')
            if self._coordinator is not None and self._coordinator is not coordinator:
                raise RuntimeError('Runtime coordination is immutable after configuration')
            self._coordinator = coordinator

    def reserve_agent_run(self, conversation_id: Union[int, str], user_id: str, *,
                          tenant_id=None, execution_run_id=None, kind='CHAT', cancel=lambda: None,
                          creator=False) -> str:
        """Atomically reserve a conversation before asynchronous run preparation."""
        with self._lock:
            run_key = self._get_run_key(conversation_id, user_id)
            if run_key in self.agent_runs or run_key in self._reservations:
                raise AgentRunAlreadyActiveError(
                    f"An agent run is already active for conversation {conversation_id}"
                )
            token = uuid.uuid4().hex
            if self._coordinator is not None and not creator:
                from runtime.sandbox_coordination import SandboxRunBusy

                if not tenant_id or not execution_run_id:
                    raise RuntimeError('Distributed admission requires trusted tenant and execution identities')
                try:
                    lease = self._coordinator.reserve(tenant_id, user_id, conversation_id, execution_run_id,
                                                      kind=kind, cancel=cancel)
                except SandboxRunBusy as exc:
                    raise AgentRunAlreadyActiveError(str(exc)) from exc
                token = lease.token
                self._distributed_leases[run_key] = lease
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
            lease = self._distributed_leases.get(run_key)
            if lease is not None:
                self._coordinator.finish(lease)
                del self._distributed_leases[run_key]
            del self._reservations[run_key]
            return True

    def register_agent_run(
        self,
        conversation_id: Union[int, str],
        agent_run_info,
        user_id: str,
        reservation_token: str | None = None,
        *, creator=False,
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
            elif run_key in self._reservations:
                raise AgentRunAlreadyActiveError(
                    f"An agent run is already being prepared for conversation {conversation_id}"
                )
            lease = self._distributed_leases.get(run_key)
            if creator:
                if reservation_token is None or lease is not None:
                    raise AgentRunAlreadyActiveError('Creator execution requires its local reservation')
                agent_run_info.__dict__['_creator_runtime'] = True
            elif self._coordinator is not None:
                if lease is None:
                    raise AgentRunAlreadyActiveError('Distributed execution requires an admitted run lease')
                self._coordinator.activate(lease)
                agent_run_info.__dict__['_runtime_distributed_lease'] = lease
                agent_run_info.__dict__['_runtime_run_reference'] = self._coordinator.reference(lease)

                def cancel_registered():
                    agent_run_info.stop_event.set()
                    scope = getattr(agent_run_info, 'cancellation_scope', None)
                    if scope is not None:
                        scope.cancel()

                self._coordinator.bind_cancellation(lease, cancel_registered)
            if reservation_token is not None:
                del self._reservations[run_key]
            self.agent_runs[run_key] = agent_run_info
            logger.info(
                f"register agent run instance, user_id: {user_id}, conversation_id: {conversation_id}"
            )

    def unregister_agent_run(
        self,
        conversation_id: Union[int, str],
        user_id: str,
        status: str = "completed",
        agent_run_info=None,
    ) -> bool:
        """unregister agent run instance"""
        pending = None
        with self._lock:
            run_key = self._get_run_key(conversation_id, user_id)
            if run_key not in self.agent_runs:
                return False
            live = self.agent_runs[run_key]
            if agent_run_info is not None and live is not agent_run_info:
                return False
            future = getattr(live, 'thread_future', None) if self._coordinator is not None else None
            if future is not None and not future.done():
                pending = (future, live)
            else:
                lease = self._distributed_leases.get(run_key)
                if lease is not None:
                    self._coordinator.finish(lease)
                    del self._distributed_leases[run_key]
                del self.agent_runs[run_key]
                logger.info(
                    f"unregister agent run instance, user_id: {user_id}, conversation_id: {conversation_id}"
                )
        if pending is not None:
            future, live = pending
            # Future callbacks can run inline. Never attach one while holding
            # the registry lock or completion between done()/add would deadlock.
            future.add_done_callback(lambda _future: self.unregister_agent_run(
                conversation_id, user_id, status, live,
            ))
            return False
        return True

    def get_agent_run_info(self, conversation_id: Union[int, str], user_id: str):
        """get agent run instance"""
        run_key = self._get_run_key(conversation_id, user_id)
        return self.agent_runs.get(run_key)

    def get_active_run_count(self) -> int:
        """Return the number of registered live runs."""
        with self._lock:
            return len(self.agent_runs)

    def get_distributed_lease(self, conversation_id, user_id):
        with self._lock:
            return self._distributed_leases.get(self._get_run_key(conversation_id, user_id))

    def get_reserved_run_count(self):
        with self._lock:
            return len(self._reservations)

    def stop_agent_run(self, conversation_id: Union[int, str], user_id: str, expected_run_info=None) -> bool:
        """stop agent run for specified conversation_id and user_id"""
        agent_run_info = self.get_agent_run_info(conversation_id, user_id)
        if expected_run_info is not None and agent_run_info is not expected_run_info:
            return False
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
        return False
